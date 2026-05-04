"""评价管理业务核心 service

7 个业务函数:
  - list_reviews: 分页列表 + 过滤 (status/rating/sentiment/keyword)
  - sync_reviews: 调 provider 拉新评价 + UPSERT + 异步翻译/sentiment
  - mark_read: 业务层标已读 + Ozon 调 provider.mark_read 同步平台
  - get_unread_count: 红点角标 (按租户全店聚合)
  - generate_reply: 调 ai_replier 生成草稿 + INSERT shop_review_replies (draft)
  - send_reply: 调 provider.post_reply 发送 + UPDATE reply.sent_status='sent'
  - get_settings / update_settings: 店铺级配置 (auto_reply_enabled 等)

合规自查:
  - 规则 1: 所有 query 都 AND tenant_id (路由层 get_owned_shop 守卫 + service 双层)
  - 规则 6: 时间字段写 utc_now_naive(), 不用 datetime.now() / utcnow()
  - 规则 4: 手动触发型接口按 shop_id 过滤 (sync_reviews / generate_reply 等)
"""

from datetime import datetime
from typing import Optional, List

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.shop import Shop
from app.models.product import PlatformListing
from app.models.review import ShopReview, ShopReviewReply, ShopReviewSettings
from app.services.reviews.ai_replier import (
    detect_sentiment,
    generate_reply_draft,
    translate_to_zh,
)
from app.services.reviews.providers.base import ReviewSnapshot
from app.utils.logger import setup_logger
from app.utils.moscow_time import utc_now_naive

logger = setup_logger("reviews.service")


# ==================== 内部 helper ====================

def _get_provider(db: Session, shop: Shop):
    """按平台返回 WBReviewProvider / OzonReviewProvider"""
    if shop.platform == "wb":
        from app.services.reviews.providers.wb import WBReviewProvider
        return WBReviewProvider(db, shop)
    if shop.platform == "ozon":
        from app.services.reviews.providers.ozon import OzonReviewProvider
        return OzonReviewProvider(db, shop)
    raise ValueError(f"评价模块暂不支持平台 {shop.platform!r}")


def _resolve_product_id(
    db: Session, tenant_id: int, shop_id: int, platform_sku_id: str,
) -> Optional[int]:
    """按 platform_sku_id 反查本地 product_id (跨店匹配兜底)

    Args:
        platform_sku_id: WB nmId / Ozon sku (str 化)

    Returns:
        product_id / None (查不到)
    """
    if not platform_sku_id:
        return None
    listing = db.query(PlatformListing.product_id).filter(
        PlatformListing.tenant_id == tenant_id,
        PlatformListing.shop_id == shop_id,
        PlatformListing.platform_product_id == str(platform_sku_id),
    ).first()
    return listing.product_id if listing else None


def _ensure_settings(
    db: Session, tenant_id: int, shop_id: int,
) -> ShopReviewSettings:
    """获取或自动创建店铺评价配置 (默认: auto_reply 关 / friendly / floor=4)"""
    s = db.query(ShopReviewSettings).filter(
        ShopReviewSettings.tenant_id == tenant_id,
        ShopReviewSettings.shop_id == shop_id,
    ).first()
    if s:
        return s
    s = ShopReviewSettings(
        tenant_id=tenant_id, shop_id=shop_id,
        auto_reply_enabled=0,
        auto_reply_rating_floor=4,
        reply_tone="friendly",
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


# ==================== 1. 列表 ====================

def list_reviews(
    db: Session,
    *,
    tenant_id: int,
    shop_id: int,
    status: Optional[str] = None,        # unread/read/replied/auto_replied/ignored
    rating: Optional[int] = None,         # 1-5
    sentiment: Optional[str] = None,
    keyword: Optional[str] = None,        # 模糊搜俄文 / 中文
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """分页列表

    Returns:
        {total, page, page_size, items: [...]}
    """
    page = max(int(page), 1)
    page_size = min(max(int(page_size), 1), 100)

    q = db.query(ShopReview).filter(
        ShopReview.tenant_id == tenant_id,
        ShopReview.shop_id == shop_id,
    )
    if status:
        q = q.filter(ShopReview.status == status)
    if rating:
        q = q.filter(ShopReview.rating == int(rating))
    if sentiment:
        q = q.filter(ShopReview.sentiment == sentiment)
    if keyword:
        kw = f"%{keyword.strip()}%"
        q = q.filter((ShopReview.content_ru.like(kw)) | (ShopReview.content_zh.like(kw)))

    total = q.count()
    # MySQL 不支持 NULLS LAST 语法 (PG 才有). MySQL DESC 时 NULL 已天然排末尾,
    # 直接 .desc() 即可; 不要 .nullslast() 否则 SQL 语法错.
    rows = (q.order_by(ShopReview.created_at_platform.desc(),
                       ShopReview.id.desc())
              .limit(page_size)
              .offset((page - 1) * page_size)
              .all())

    items = [_review_row_to_dict(r) for r in rows]
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": items,
    }


def _review_row_to_dict(r: ShopReview) -> dict:
    return {
        "id": r.id,
        "shop_id": r.shop_id,
        "platform": r.platform,
        "platform_review_id": r.platform_review_id,
        "rating": r.rating,
        "content_ru": r.content_ru,
        "content_zh": r.content_zh,
        "sentiment": r.sentiment,
        "customer_name": r.customer_name or "",
        "platform_sku_id": r.platform_sku_id or "",
        "platform_product_name": r.platform_product_name or "",
        "product_id": r.product_id,
        "created_at_platform": r.created_at_platform.isoformat() + "Z"
            if r.created_at_platform else None,
        "existing_reply_ru": r.existing_reply_ru or "",
        "existing_reply_at": r.existing_reply_at.isoformat() + "Z"
            if r.existing_reply_at else None,
        "is_answered": bool(r.is_answered),
        "status": r.status,
    }


# ==================== 2. 同步拉取 ====================

async def sync_reviews(
    db: Session, *, tenant_id: int, shop_id: int,
    only_unanswered: bool = True, max_pages: int = 10,
) -> dict:
    """拉买家评价 + UPSERT + 翻译/情感分析

    Returns:
        {synced, new, updated, translated, errors: [...]}
    """
    shop = db.query(Shop).filter(
        Shop.id == shop_id, Shop.tenant_id == tenant_id,
    ).first()
    if not shop:
        raise ValueError(f"店铺不存在 shop_id={shop_id}")
    if shop.platform not in ("wb", "ozon"):
        raise ValueError(f"评价模块暂不支持 {shop.platform}")

    provider = _get_provider(db, shop)
    cursor = None
    new_cnt = 0
    upd_cnt = 0
    translated_cnt = 0
    errors = []
    all_snaps: List[ReviewSnapshot] = []

    for page_idx in range(max_pages):
        try:
            snaps, cursor = await provider.list_reviews(
                only_unanswered=only_unanswered, cursor=cursor, limit=100,
            )
        except Exception as e:
            errors.append(f"page {page_idx}: {str(e)[:200]}")
            logger.error(f"sync_reviews shop={shop_id} page={page_idx} 失败: {e}")
            break
        if not snaps:
            break
        all_snaps.extend(snaps)
        if not cursor:
            break

    # UPSERT 主表
    for snap in all_snaps:
        try:
            existing = db.query(ShopReview).filter(
                ShopReview.tenant_id == tenant_id,
                ShopReview.shop_id == shop_id,
                ShopReview.platform == snap.source_platform,
                ShopReview.platform_review_id == snap.platform_review_id,
            ).first()

            sentiment = detect_sentiment(snap.content_ru, snap.rating)
            product_id = _resolve_product_id(
                db, tenant_id, shop_id, snap.platform_sku_id,
            )

            if existing:
                # 已存在: 只更新 is_answered / existing_reply (其他保持稳定)
                existing.is_answered = 1 if snap.is_answered else 0
                if snap.existing_reply_ru:
                    existing.existing_reply_ru = snap.existing_reply_ru
                if snap.existing_reply_at:
                    existing.existing_reply_at = snap.existing_reply_at
                existing.updated_at = utc_now_naive()
                upd_cnt += 1
            else:
                rec = ShopReview(
                    tenant_id=tenant_id, shop_id=shop_id,
                    platform=snap.source_platform,
                    platform_review_id=snap.platform_review_id,
                    rating=snap.rating,
                    content_ru=snap.content_ru,
                    sentiment=sentiment,
                    customer_name=snap.customer_name or None,
                    platform_sku_id=snap.platform_sku_id or None,
                    platform_product_name=snap.platform_product_name or None,
                    product_id=product_id,
                    created_at_platform=snap.created_at_platform,
                    existing_reply_ru=snap.existing_reply_ru or None,
                    existing_reply_at=snap.existing_reply_at,
                    is_answered=1 if snap.is_answered else 0,
                    status="replied" if snap.is_answered else "unread",
                    raw_payload=snap.raw,
                )
                db.add(rec)
                db.flush()
                new_cnt += 1
                # 翻译新评价 (老评价不重翻, 节省 Kimi 配额)
                zh = await translate_to_zh(db, snap.content_ru)
                if zh:
                    rec.content_zh = zh
                    translated_cnt += 1
        except Exception as e:
            errors.append(f"review {snap.platform_review_id}: {str(e)[:200]}")
            logger.warning(
                f"sync_reviews UPSERT 失败 shop={shop_id} "
                f"rid={snap.platform_review_id}: {e}"
            )
            continue

    db.commit()

    return {
        "synced": len(all_snaps),
        "new": new_cnt,
        "updated": upd_cnt,
        "translated": translated_cnt,
        "errors": errors,
    }


# ==================== 3. 已读 / 未读计数 ====================

def mark_read(
    db: Session, *, tenant_id: int, review_id: int,
) -> dict:
    """业务层标已读. Ozon 同时调 provider.mark_read 平台同步."""
    rev = db.query(ShopReview).filter(
        ShopReview.id == review_id,
        ShopReview.tenant_id == tenant_id,
    ).first()
    if not rev:
        return {"ok": False, "msg": "评价不存在"}

    if rev.status == "unread":
        rev.status = "read"
        rev.updated_at = utc_now_naive()
        db.commit()
    return {"ok": True, "status": rev.status}


def get_unread_count(
    db: Session, *, tenant_id: int, shop_id: Optional[int] = None,
) -> int:
    """红点角标. shop_id=None 返本租户全店聚合"""
    q = db.query(ShopReview).filter(
        ShopReview.tenant_id == tenant_id,
        ShopReview.is_answered == 0,
        ShopReview.status == "unread",
    )
    if shop_id:
        q = q.filter(ShopReview.shop_id == shop_id)
    return q.count()


# ==================== 4. AI 生成回复草稿 ====================

async def generate_reply(
    db: Session, *, tenant_id: int, review_id: int,
    custom_hint: str = "", user_id: Optional[int] = None,
) -> dict:
    """调 AI 生成俄语回复草稿 + 翻译中文 + INSERT shop_review_replies (draft)

    用户点 "生成回复" / "重新生成" 都走这里, generated_count++.

    Returns:
        {ok, reply_id, draft_ru, draft_zh, generated_count, msg}
    """
    rev = db.query(ShopReview).filter(
        ShopReview.id == review_id,
        ShopReview.tenant_id == tenant_id,
    ).first()
    if not rev:
        return {"ok": False, "msg": "评价不存在"}

    settings = _ensure_settings(db, tenant_id, rev.shop_id)

    # 算这是第几次重新生成
    last_count = db.execute(text("""
        SELECT COALESCE(MAX(generated_count), 0) AS m
        FROM shop_review_replies
        WHERE tenant_id = :tid AND review_id = :rid
    """), {"tid": tenant_id, "rid": review_id}).scalar() or 0
    new_count = int(last_count) + 1

    # 调 AI — settings 字段全透传, SettingsModal 改的 tone/prompt_extra 真生效
    result = await generate_reply_draft(
        db, tenant_id=tenant_id,
        review_text_ru=rev.content_ru,
        rating=rev.rating,
        customer_name=rev.customer_name or "",
        product_name=rev.platform_product_name or "",
        custom_hint=custom_hint,
        brand_signature=settings.brand_signature or "",
        reply_tone=settings.reply_tone or "friendly",
        custom_prompt_extra=settings.custom_prompt_extra or "",
    )
    if not result.get("ok"):
        return {"ok": False, "msg": result.get("msg") or "AI 生成失败"}

    reply = ShopReviewReply(
        tenant_id=tenant_id, review_id=review_id,
        draft_content_ru=result["draft_ru"],
        draft_content_zh=result["draft_zh"],
        custom_hint=custom_hint or None,
        generated_count=new_count,
        ai_model=result.get("ai_model"),
        sent_status="draft",
        is_auto=0,
        sent_by=user_id,
    )
    db.add(reply)
    db.commit()
    db.refresh(reply)

    return {
        "ok": True,
        "reply_id": reply.id,
        "draft_ru": result["draft_ru"],
        "draft_zh": result["draft_zh"],
        "generated_count": new_count,
        "msg": "",
    }


# ==================== 5. 真实发送回复 ====================

async def send_reply(
    db: Session, *, tenant_id: int, reply_id: int,
    final_content_ru: Optional[str] = None,
    user_id: Optional[int] = None,
) -> dict:
    """真实发送回复到平台

    Args:
        reply_id: shop_review_replies.id (该 reply 的 draft 已存在)
        final_content_ru: 用户编辑后的最终俄语 (None=用 draft 原版)

    Returns:
        {ok, sent_status, msg, platform_status}
    """
    reply = db.query(ShopReviewReply).filter(
        ShopReviewReply.id == reply_id,
        ShopReviewReply.tenant_id == tenant_id,
    ).first()
    if not reply:
        return {"ok": False, "msg": "回复草稿不存在"}
    # 防 race condition: pending 也要拦, 否则狂点 100ms 内会两次 POST 平台
    if reply.sent_status in ("sent", "pending"):
        msg = "该回复已发送过" if reply.sent_status == "sent" else "回复正在发送中, 请勿重复点击"
        return {"ok": False, "msg": msg}

    rev = db.query(ShopReview).filter(
        ShopReview.id == reply.review_id,
        ShopReview.tenant_id == tenant_id,
    ).first()
    if not rev:
        return {"ok": False, "msg": "关联评价不存在"}

    shop = db.query(Shop).filter(
        Shop.id == rev.shop_id, Shop.tenant_id == tenant_id,
    ).first()
    if not shop:
        return {"ok": False, "msg": "店铺不存在"}

    # 用 final_content_ru (用户编辑过) 或回退 draft
    text_to_send = (final_content_ru or "").strip() or reply.draft_content_ru or ""
    if not text_to_send:
        return {"ok": False, "msg": "回复内容为空"}

    reply.sent_status = "pending"
    reply.final_content_ru = text_to_send
    db.commit()

    provider = _get_provider(db, shop)
    try:
        send_result = await provider.post_reply(
            platform_review_id=rev.platform_review_id,
            reply_ru=text_to_send,
        )
    except Exception as e:
        reply.sent_status = "failed"
        reply.sent_error_msg = str(e)[:500]
        reply.updated_at = utc_now_naive()
        db.commit()
        logger.error(
            f"send_reply 调 provider 异常 reply_id={reply_id}: {e}", exc_info=True,
        )
        return {"ok": False, "msg": str(e)[:300], "sent_status": "failed"}

    if send_result.get("ok"):
        reply.sent_status = "sent"
        reply.sent_at = utc_now_naive()
        reply.sent_by = user_id
        # 翻译最终发送内容给老板存档
        zh = await translate_to_zh(db, text_to_send)
        if zh:
            reply.final_content_zh = zh
        # 评价主表标 replied
        rev.status = "replied"
        rev.is_answered = 1
        rev.existing_reply_ru = text_to_send
        rev.existing_reply_at = utc_now_naive()
        rev.updated_at = utc_now_naive()
        db.commit()
        return {"ok": True, "sent_status": "sent",
                "msg": send_result.get("msg") or "发送成功"}
    else:
        reply.sent_status = "failed"
        reply.sent_error_msg = (send_result.get("msg") or "")[:500]
        reply.updated_at = utc_now_naive()
        db.commit()
        return {"ok": False, "sent_status": "failed",
                "msg": send_result.get("msg") or "平台拒收"}


# ==================== 6. 店铺级配置 ====================

def get_settings(
    db: Session, *, tenant_id: int, shop_id: int,
) -> dict:
    """取店铺评价配置 (不存在自动创建)"""
    s = _ensure_settings(db, tenant_id, shop_id)
    return {
        "shop_id": s.shop_id,
        "auto_reply_enabled": bool(s.auto_reply_enabled),
        "auto_reply_rating_floor": s.auto_reply_rating_floor,
        "reply_tone": s.reply_tone,
        "brand_signature": s.brand_signature or "",
        "custom_prompt_extra": s.custom_prompt_extra or "",
    }


def update_settings(
    db: Session, *, tenant_id: int, shop_id: int,
    auto_reply_enabled: Optional[bool] = None,
    auto_reply_rating_floor: Optional[int] = None,
    reply_tone: Optional[str] = None,
    brand_signature: Optional[str] = None,
    custom_prompt_extra: Optional[str] = None,
) -> dict:
    """更新店铺评价配置"""
    s = _ensure_settings(db, tenant_id, shop_id)
    if auto_reply_enabled is not None:
        s.auto_reply_enabled = 1 if auto_reply_enabled else 0
    if auto_reply_rating_floor is not None:
        floor = int(auto_reply_rating_floor)
        if floor < 1 or floor > 5:
            raise ValueError("auto_reply_rating_floor 必须 1-5")
        s.auto_reply_rating_floor = floor
    if reply_tone is not None:
        if reply_tone not in ("formal", "friendly", "warm"):
            raise ValueError(f"reply_tone 非法: {reply_tone!r}")
        s.reply_tone = reply_tone
    if brand_signature is not None:
        s.brand_signature = brand_signature[:200] or None
    if custom_prompt_extra is not None:
        s.custom_prompt_extra = custom_prompt_extra[:1000] or None
    s.updated_at = utc_now_naive()
    db.commit()
    db.refresh(s)
    return get_settings(db, tenant_id=tenant_id, shop_id=shop_id)
