"""店铺克隆扫描引擎 — _run_scan 核心

详细规范: docs/api/store_clone.md §4.1

流程:
1. factory.get_provider 拿 B 店 Provider
2. since = task.last_check_at or (task.created_at - 7 days)
3. provider.list_products 分页拉
4. 对每个 snapshot: 查重 → 类目映射 → 价格规则 → 创建草稿 product+listing →
   下载图片 → 暂存 source 原文 (AI 延后)
5. AI 改写批处理 (sem=5 + 失败 fallback)
6. 写 clone_logs (含 skipped_skus 明细)
7. 更新 task.last_*

强制约定 (规范 §11):
- providers 走 *Client 不绕路
- AI 改写复用 SEO 接口 (optimize_title / generate_description), 不重复实现
"""

import asyncio
import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.models.clone import CloneTask, ClonePendingProduct, CloneLog
from app.models.product import Product, PlatformListing
from app.models.shop import Shop
from app.models.category import CategoryPlatformMapping
from app.utils.logger import setup_logger
from app.utils.moscow_time import utc_now_naive

from .providers import get_provider, ProductSnapshot

logger = setup_logger("clone.scan_engine")

DEFAULT_FIRST_SCAN_WINDOW_DAYS = 7
LIST_PAGE_SIZE = 100
AI_REWRITE_SEMAPHORE = 5


# ==================== 类目映射 ====================

def _resolve_target_category(
    db: Session, tenant_id: int,
    source_platform: str, source_cat_id: str,
    target_platform: str, strategy: str,
) -> tuple[Optional[str], str]:
    """跨平台/同平台类目映射

    Returns: (target_platform_category_id, mapping_status)
        mapping_status: 'ok' / 'missing'
    """
    # 同平台直接复用
    if source_platform == target_platform:
        return source_cat_id, "ok"

    if not source_cat_id:
        return None, "missing"

    # 跨平台 use_local_map / reject_if_missing 都走 028 反查
    # 步骤 1: source_cat_id → local_category_id
    src_mapping = db.query(CategoryPlatformMapping).filter(
        CategoryPlatformMapping.tenant_id == tenant_id,
        CategoryPlatformMapping.platform == source_platform,
        CategoryPlatformMapping.platform_category_id == source_cat_id,
    ).first()
    if not src_mapping:
        return None, "missing"

    # 步骤 2: local_category_id → target_platform_category_id
    tgt_mapping = db.query(CategoryPlatformMapping).filter(
        CategoryPlatformMapping.tenant_id == tenant_id,
        CategoryPlatformMapping.local_category_id == src_mapping.local_category_id,
        CategoryPlatformMapping.platform == target_platform,
    ).first()
    if not tgt_mapping:
        return None, "missing"

    return str(tgt_mapping.platform_category_id), "ok"


# ==================== 价格规则 ====================

def _apply_price_rule(source_price: Decimal, mode: str,
                      adjust_pct: Optional[Decimal]) -> Decimal:
    """同价 / 涨跌 % 规则"""
    if mode == "same" or not adjust_pct:
        return source_price
    factor = Decimal("1") + Decimal(str(adjust_pct)) / Decimal("100")
    return (source_price * factor).quantize(Decimal("0.01"))


# ==================== 草稿创建 ====================

def _create_drafts(
    db: Session, task: CloneTask, snap: ProductSnapshot,
    target_cat_id: str,
) -> tuple[Optional[int], Optional[int], Optional[str]]:
    """新建占位 products + platform_listings 草稿 (规范 §3.3 状态机)

    Returns: (product_id, listing_id, error_msg) — 失败返 (None, None, "...")

    用 savepoint 包裹: 单 SKU 失败只回滚自己, 不污染同页其他草稿
    (避免历史教训: ORM 字段缺失时 product 已 flush 但 listing 抛错,
     外层 commit 把孤儿 product 一并写库)。
    """
    sp = db.begin_nested()
    try:
        sku_placeholder = f"clone-pending-{task.id}-{snap.source_sku_id}"
        product = Product(
            tenant_id=task.tenant_id,
            shop_id=task.target_shop_id,
            sku=sku_placeholder,
            name_zh=(snap.title_ru or "")[:200],
            name_ru=snap.title_ru or "",
            brand=None,
            local_category_id=None,  # scan_engine 不强行回填; 用户在映射管理统一处理
            status="inactive",
            created_at=utc_now_naive(),
        )
        db.add(product)
        db.flush()

        # 推断 target_platform
        target_shop = db.query(Shop).filter(Shop.id == task.target_shop_id).first()
        target_platform = target_shop.platform if target_shop else snap.source_platform

        # platform_product_id / platform_sku_id 在草稿期都用占位串
        # publish 成功后由 publish_engine 回填真实 offer_id
        draft_token = uuid.uuid4().hex[:8]
        listing = PlatformListing(
            tenant_id=task.tenant_id,
            shop_id=task.target_shop_id,
            product_id=product.id,
            platform=target_platform,
            platform_sku_id=f"clone-draft-{draft_token}",
            platform_product_id=f"clone-draft-{draft_token}",
            title_ru=snap.title_ru,
            description_ru=snap.description_ru,
            platform_category_id=target_cat_id or None,
            status="inactive",
            publish_status="draft",
            clone_task_id=task.id,
            created_at=utc_now_naive(),
        )
        db.add(listing)
        db.flush()
        sp.commit()
        return product.id, listing.id, None
    except Exception as e:
        sp.rollback()
        msg = str(e)[:200]
        logger.error(f"_create_drafts 失败 task={task.id} sku={snap.source_sku_id}: {e}")
        return None, None, msg


# ==================== 图片处理 ====================
#
# 草稿期不下载图片到 OSS, 只暂存 B 店原图 URL。
# OSS 下载延后到 _publish_pending(publish_engine) 执行。
#
# 原因:
# - 串行下图 25 秒/SKU × 385 件 = 2.5h, 同步触发 scan-now 必撞 nginx 60s timeout
# - 被拒的商品下载也是浪费 OSS 流量
# - review 阶段用 B 店原图预览完全可用 (审核期内 B 店改图/删图是小概率)
#
# proposed_payload.images_oss 字段语义:
#   草稿期 = B 店原图 URL 列表
#   publish 后 = OSS URL 列表 (publish_engine 在 dispatch 前下载并写回)


# ==================== AI 改写批处理 ====================

async def _ai_rewrite_one(
    db: Session, tenant_id: int, listing_id: int,
    target_platform: str,
    title_mode: str, desc_mode: str,
    proposed: dict,
):
    """单条 AI 改写, sem 外层控制并发"""
    from app.services.product.service import optimize_title, generate_description

    if title_mode == "ai_rewrite":
        try:
            r = await optimize_title(db, listing_id, tenant_id)
            if r and r.get("code") == 0:
                new_title = (r.get("data") or {}).get("new_title")
                if new_title:
                    proposed["title_ru"] = new_title
            else:
                proposed["_ai_rewrite_failed_title"] = True
                logger.warning(f"AI 标题改写失败 listing={listing_id}: {r.get('msg') if r else 'none'}")
        except Exception as e:
            proposed["_ai_rewrite_failed_title"] = True
            proposed["_ai_rewrite_error"] = str(e)[:200]
            logger.error(f"AI 标题改写异常 listing={listing_id}: {e}")

    if desc_mode == "ai_rewrite":
        try:
            r = await generate_description(db, listing_id, tenant_id, target_platform)
            if r and r.get("code") == 0:
                new_desc = (r.get("data") or {}).get("description")
                if new_desc:
                    proposed["description_ru"] = new_desc
            else:
                proposed["_ai_rewrite_failed_desc"] = True
                logger.warning(f"AI 描述改写失败 listing={listing_id}: {r.get('msg') if r else 'none'}")
        except Exception as e:
            proposed["_ai_rewrite_failed_desc"] = True
            proposed["_ai_rewrite_error"] = str(e)[:200]
            logger.error(f"AI 描述改写异常 listing={listing_id}: {e}")


# ==================== 主入口 ====================

async def _run_scan(
    db: Session, task_id: int, tenant_id: int,
    selected_skus: Optional[set] = None,
) -> dict:
    """扫描入口 — 同步触发 (scan-now) + Celery beat 共用

    Args:
        selected_skus: None = 全量立项 (兼容旧逻辑); set = 只立项指定的 source_sku_id

    Returns: {code, data: {found, new, skip_*, duration_ms, log_id}, msg?}
    """
    t0 = utc_now_naive()

    task = db.query(CloneTask).filter(
        CloneTask.id == task_id, CloneTask.tenant_id == tenant_id,
    ).first()
    if not task:
        from app.utils.errors import ErrorCode
        return {"code": ErrorCode.CLONE_TASK_NOT_FOUND, "msg": "克隆任务不存在"}

    source_shop = db.query(Shop).filter(Shop.id == task.source_shop_id).first()
    target_shop = db.query(Shop).filter(Shop.id == task.target_shop_id).first()
    if not source_shop or not target_shop:
        from app.utils.errors import ErrorCode
        return {"code": ErrorCode.CLONE_TASK_SOURCE_INVALID, "msg": "源/目标店铺已不存在"}

    target_platform = target_shop.platform
    source_platform = source_shop.platform

    # 计数器
    found = new = 0
    skip_published = skip_rejected = skip_pending = skip_category_missing = 0
    skip_a_shop_sku_exists = 0  # 11.1: A 店本地 SKU 已存在跳过
    skipped_skus: list[dict] = []
    ai_rewrite_targets: list[tuple[ClonePendingProduct, int, str, dict]] = []

    # 11.1 真 BUG 修复: 预拉 A 店所有真实 sku 集合 (排除占位 'clone-*')
    # 用于跨店去重 — 老板老板手工录的本地 sku, A 店已有就跳过
    a_existing_skus = set()
    rows = db.query(Product.sku).filter(
        Product.shop_id == task.target_shop_id,
        Product.tenant_id == tenant_id,
        Product.status != 'deleted',
        Product.sku.isnot(None),
    ).all()
    for (s,) in rows:
        if s and not s.startswith(('clone-pending-', 'clone-draft-')):
            a_existing_skus.add(s)
    logger.info(f"task={task_id} A 店预拉 {len(a_existing_skus)} 个真实 sku 用于跨店去重")

    # 拿 provider (规则: factory dispatch + *Client 不绕路)
    try:
        provider = get_provider(db, source_shop)
    except Exception as e:
        logger.error(f"get_provider 失败 task={task_id}: {e}")
        from app.utils.errors import ErrorCode
        task.last_error_msg = str(e)[:500]
        db.commit()
        return {"code": ErrorCode.CLONE_SOURCE_API_FAILED, "msg": str(e)[:200]}

    # 分页 list_products
    cursor: Optional[str] = None
    while True:
        try:
            snapshots, cursor = await provider.list_products(cursor=cursor, limit=LIST_PAGE_SIZE)
        except NotImplementedError as e:
            logger.warning(f"Provider 未实现 task={task_id}: {e}")
            from app.utils.errors import ErrorCode
            task.last_error_msg = str(e)[:500]
            db.commit()
            return {"code": ErrorCode.CLONE_SOURCE_API_FAILED, "msg": str(e)[:200]}
        except Exception as e:
            logger.error(f"list_products 失败 task={task_id}: {e}")
            from app.utils.errors import ErrorCode
            task.last_error_msg = str(e)[:500]
            db.commit()
            return {"code": ErrorCode.CLONE_SOURCE_API_FAILED, "msg": str(e)[:200]}

        if not snapshots:
            break

        for snap in snapshots:
            found += 1
            # 11.2: 用户在 preview 后没勾的 sku 直接跳过, 不立项也不计 skip
            if selected_skus is not None and snap.source_sku_id not in selected_skus:
                continue
            # a. 查重 (UNIQUE 约束 + 显式查避免 INSERT 抛异常)
            existing = db.query(ClonePendingProduct).filter(
                ClonePendingProduct.task_id == task_id,
                ClonePendingProduct.source_sku_id == snap.source_sku_id,
            ).first()
            if existing:
                if existing.status == "published":
                    skip_published += 1
                    skipped_skus.append({"sku": snap.source_sku_id, "reason": "published"})
                elif existing.status == "rejected":
                    skip_rejected += 1
                    skipped_skus.append({"sku": snap.source_sku_id, "reason": "rejected"})
                else:
                    skip_pending += 1
                    skipped_skus.append({"sku": snap.source_sku_id, "reason": "in_queue"})
                continue

            # a2. 11.1: 跨店本地 SKU 去重 — 反查 B 店 listing → product.sku, 看 A 店是否已有同 sku
            #     场景: 老板手工在 A 店建过该 sku, 不该重复立项 pending
            #     B 店 sku 不规则/为空时此层跳过, 走原 (task_id, source_sku_id) UNIQUE 兜底
            b_listing = db.query(PlatformListing).filter(
                PlatformListing.shop_id == task.source_shop_id,
                PlatformListing.tenant_id == tenant_id,
                PlatformListing.platform_sku_id == snap.source_sku_id,
                PlatformListing.status != 'deleted',
            ).first()
            b_local_sku = None
            if b_listing and b_listing.product_id:
                b_product = db.query(Product).filter(
                    Product.id == b_listing.product_id,
                    Product.tenant_id == tenant_id,
                ).first()
                if b_product and b_product.sku and not b_product.sku.startswith(('clone-pending-', 'clone-draft-')):
                    b_local_sku = b_product.sku
            if b_local_sku and b_local_sku in a_existing_skus:
                skip_a_shop_sku_exists += 1
                skipped_skus.append({
                    "sku": snap.source_sku_id, "reason": "a_shop_sku_exists",
                    "detail": f"A 店已有本地 sku={b_local_sku}",
                })
                continue

            # b. 类目映射
            target_cat_id, mapping_status = _resolve_target_category(
                db, tenant_id,
                source_platform, snap.platform_category_id,
                target_platform, task.category_strategy,
            )
            if mapping_status == "missing" and task.category_strategy in ("use_local_map", "reject_if_missing"):
                skip_category_missing += 1
                skipped_skus.append({
                    "sku": snap.source_sku_id, "reason": "category_missing",
                    "detail": f"{source_platform} cat={snap.platform_category_id} 未映射到 {target_platform}",
                })
                continue

            # c. 价格规则
            target_price = _apply_price_rule(
                snap.price_rub, task.price_mode, task.price_adjust_pct,
            )

            # d/e. 创建草稿 product + listing
            draft_product_id, draft_listing_id, draft_err = _create_drafts(
                db, task, snap, target_cat_id or "",
            )
            if not draft_listing_id:
                skipped_skus.append({
                    "sku": snap.source_sku_id, "reason": "draft_create_failed",
                    "detail": draft_err or "",
                })
                continue

            # f. 草稿期不下载图片到 OSS, 只暂存 B 店原图 URL
            #    OSS 下载延后到 publish_engine._publish_pending 执行
            oss_urls = list(snap.images or [])

            # g. proposed_payload 骨架 (AI 改写延后)
            proposed = {
                "title_ru": snap.title_ru,
                "description_ru": snap.description_ru,
                "price_rub": float(target_price),
                "stock": task.default_stock,
                "images_oss": oss_urls,
                "platform_category_id": target_cat_id or "",
                "platform_category_name": snap.platform_category_name,
                "type_id": snap.type_id,  # Ozon /v3/product/import 必填
                "attributes": snap.attributes,
            }

            # h. INSERT pending
            try:
                pending = ClonePendingProduct(
                    tenant_id=tenant_id,
                    task_id=task.id,
                    source_shop_id=task.source_shop_id,
                    source_platform=snap.source_platform,
                    source_sku_id=snap.source_sku_id,
                    source_snapshot={
                        "platform": snap.source_platform,
                        "sku_id": snap.source_sku_id,
                        "title_ru": snap.title_ru,
                        "description_ru": snap.description_ru,
                        "price_rub": float(snap.price_rub),
                        "stock": snap.stock,
                        "images": snap.images,
                        "platform_category_id": snap.platform_category_id,
                        "platform_category_name": snap.platform_category_name,
                        "type_id": snap.type_id,  # Ozon /v3/product/import 必填
                        "attributes": snap.attributes,
                    },
                    proposed_payload=proposed,
                    draft_listing_id=draft_listing_id,
                    status="pending",
                    category_mapping_status=mapping_status,
                    detected_at=utc_now_naive(),
                )
                db.add(pending)
                db.flush()
                new += 1

                # i. 收集 AI 候选
                if task.title_mode == "ai_rewrite" or task.desc_mode == "ai_rewrite":
                    ai_rewrite_targets.append((pending, draft_listing_id, target_platform, proposed))
            except Exception as e:
                logger.error(
                    f"INSERT pending 失败 task={task.id} sku={snap.source_sku_id}: {e}"
                )
                skipped_skus.append({"sku": snap.source_sku_id, "reason": "insert_failed",
                                     "detail": str(e)[:120]})

        db.commit()
        if not cursor:
            break

    # 5. AI 改写批处理 (sem=5, 失败 fallback 不阻断)
    ai_rewrite_total = len(ai_rewrite_targets)
    ai_rewrite_failed = 0
    if ai_rewrite_targets:
        sem = asyncio.Semaphore(AI_REWRITE_SEMAPHORE)

        async def _wrap(p, lid, plat, prop):
            async with sem:
                await _ai_rewrite_one(
                    db, tenant_id, lid, plat,
                    task.title_mode, task.desc_mode, prop,
                )

        await asyncio.gather(
            *(_wrap(p, lid, plat, prop) for (p, lid, plat, prop) in ai_rewrite_targets),
            return_exceptions=True,
        )

        # 把改写后的 proposed 同步回 DB + listing
        for (pending, lid, _plat, prop) in ai_rewrite_targets:
            if prop.get("_ai_rewrite_failed_title") or prop.get("_ai_rewrite_failed_desc"):
                ai_rewrite_failed += 1
            pending.proposed_payload = prop
            listing = db.query(PlatformListing).filter(PlatformListing.id == lid).first()
            if listing:
                if "title_ru" in prop:
                    listing.title_ru = prop["title_ru"]
                if "description_ru" in prop:
                    listing.description_ru = prop["description_ru"]
        db.commit()

    # 6. 写日志 + 7. 更新 task
    duration_ms = int((utc_now_naive() - t0).total_seconds() * 1000)
    detail = {
        "found": found, "new": new,
        "skip_published": skip_published,
        "skip_rejected": skip_rejected,
        "skip_pending": skip_pending,
        "skip_category_missing": skip_category_missing,
        "skip_a_shop_sku_exists": skip_a_shop_sku_exists,  # 11.1
        "ai_rewrite_total": ai_rewrite_total,
        "ai_rewrite_failed": ai_rewrite_failed,
        "skipped_skus": skipped_skus[:200],  # 截断防 JSON 过大
    }
    log = CloneLog(
        tenant_id=tenant_id, task_id=task.id,
        log_type="scan",
        status="success" if new > 0 or found == 0 else (
            "partial" if skip_category_missing > 0 else "success"
        ),
        rows_affected=new,
        duration_ms=duration_ms,
        detail=detail,
    )
    db.add(log)

    task.last_check_at = utc_now_naive()
    task.last_found_count = found
    task.last_publish_count = new
    task.last_skip_count = (
        skip_published + skip_rejected + skip_category_missing
        + skip_pending + skip_a_shop_sku_exists
    )
    task.last_error_msg = None
    db.commit()
    db.refresh(log)

    return {"code": 0, "data": {
        "found": found, "new": new,
        "skip_published": skip_published,
        "skip_rejected": skip_rejected,
        "skip_pending": skip_pending,
        "skip_category_missing": skip_category_missing,
        "skip_a_shop_sku_exists": skip_a_shop_sku_exists,  # 11.1
        "ai_rewrite_total": ai_rewrite_total,
        "ai_rewrite_failed": ai_rewrite_failed,
        "duration_ms": duration_ms,
        "log_id": log.id,
    }}


# ==================== 11.2 干跑预览 ====================

async def _scan_preview(db: Session, task_id: int, tenant_id: int) -> dict:
    """干跑扫描 — 拉 B 店全量, 过滤后返候选清单, 不写库

    跟 _run_scan 共享同样的过滤逻辑 (同 task 去重 + 跨店 sku 去重 + 类目映射),
    但跳过 _create_drafts / INSERT pending / AI 改写 — 让用户预览后再确认.

    Returns: {code, data: {
        found, skip_*, candidates: [...], skipped_skus_sample: [...], duration_ms
    }}
    """
    t0 = utc_now_naive()

    task = db.query(CloneTask).filter(
        CloneTask.id == task_id, CloneTask.tenant_id == tenant_id,
    ).first()
    if not task:
        from app.utils.errors import ErrorCode
        return {"code": ErrorCode.CLONE_TASK_NOT_FOUND, "msg": "克隆任务不存在"}

    source_shop = db.query(Shop).filter(Shop.id == task.source_shop_id).first()
    target_shop = db.query(Shop).filter(Shop.id == task.target_shop_id).first()
    if not source_shop or not target_shop:
        from app.utils.errors import ErrorCode
        return {"code": ErrorCode.CLONE_TASK_SOURCE_INVALID, "msg": "源/目标店铺已不存在"}

    target_platform = target_shop.platform
    source_platform = source_shop.platform

    found = 0
    skip_published = skip_rejected = skip_pending = skip_category_missing = 0
    skip_a_shop_sku_exists = 0
    skipped_skus: list[dict] = []
    candidates: list[dict] = []

    # 预拉 A 店真实 sku 集合
    a_existing_skus = set()
    rows = db.query(Product.sku).filter(
        Product.shop_id == task.target_shop_id,
        Product.tenant_id == tenant_id,
        Product.status != 'deleted',
        Product.sku.isnot(None),
    ).all()
    for (s,) in rows:
        if s and not s.startswith(('clone-pending-', 'clone-draft-')):
            a_existing_skus.add(s)

    try:
        provider = get_provider(db, source_shop)
    except Exception as e:
        logger.error(f"_scan_preview get_provider 失败 task={task_id}: {e}")
        from app.utils.errors import ErrorCode
        return {"code": ErrorCode.CLONE_SOURCE_API_FAILED, "msg": str(e)[:200]}

    cursor: Optional[str] = None
    while True:
        try:
            snapshots, cursor = await provider.list_products(cursor=cursor, limit=LIST_PAGE_SIZE)
        except NotImplementedError as e:
            from app.utils.errors import ErrorCode
            return {"code": ErrorCode.CLONE_SOURCE_API_FAILED, "msg": str(e)[:200]}
        except Exception as e:
            logger.error(f"_scan_preview list_products 失败 task={task_id}: {e}")
            from app.utils.errors import ErrorCode
            return {"code": ErrorCode.CLONE_SOURCE_API_FAILED, "msg": str(e)[:200]}

        if not snapshots:
            break

        for snap in snapshots:
            found += 1

            # 1. 同 task 去重
            existing = db.query(ClonePendingProduct).filter(
                ClonePendingProduct.task_id == task_id,
                ClonePendingProduct.source_sku_id == snap.source_sku_id,
            ).first()
            if existing:
                if existing.status == "published":
                    skip_published += 1
                    skipped_skus.append({"sku": snap.source_sku_id, "reason": "published"})
                elif existing.status == "rejected":
                    skip_rejected += 1
                    skipped_skus.append({"sku": snap.source_sku_id, "reason": "rejected"})
                else:
                    skip_pending += 1
                    skipped_skus.append({"sku": snap.source_sku_id, "reason": "in_queue"})
                continue

            # 2. 跨店本地 sku 去重 (11.1)
            b_listing = db.query(PlatformListing).filter(
                PlatformListing.shop_id == task.source_shop_id,
                PlatformListing.tenant_id == tenant_id,
                PlatformListing.platform_sku_id == snap.source_sku_id,
                PlatformListing.status != 'deleted',
            ).first()
            b_local_sku = None
            if b_listing and b_listing.product_id:
                b_product = db.query(Product).filter(
                    Product.id == b_listing.product_id,
                    Product.tenant_id == tenant_id,
                ).first()
                if b_product and b_product.sku and not b_product.sku.startswith(('clone-pending-', 'clone-draft-')):
                    b_local_sku = b_product.sku
            if b_local_sku and b_local_sku in a_existing_skus:
                skip_a_shop_sku_exists += 1
                skipped_skus.append({
                    "sku": snap.source_sku_id, "reason": "a_shop_sku_exists",
                    "detail": f"A 店已有本地 sku={b_local_sku}",
                })
                continue

            # 3. 类目映射
            target_cat_id, mapping_status = _resolve_target_category(
                db, tenant_id,
                source_platform, snap.platform_category_id,
                target_platform, task.category_strategy,
            )
            if mapping_status == "missing" and task.category_strategy in ("use_local_map", "reject_if_missing"):
                skip_category_missing += 1
                skipped_skus.append({
                    "sku": snap.source_sku_id, "reason": "category_missing",
                    "detail": f"{source_platform} cat={snap.platform_category_id} 未映射到 {target_platform}",
                })
                continue

            # 4. 价格规则
            target_price = _apply_price_rule(
                snap.price_rub, task.price_mode, task.price_adjust_pct,
            )

            # 5. 收集候选 (不写库)
            candidates.append({
                "source_sku_id": snap.source_sku_id,
                "title_ru": snap.title_ru,
                "description_ru": (snap.description_ru or "")[:300],
                "price_b": float(snap.price_rub),
                "price_a_proposed": float(target_price),
                "stock": snap.stock,
                "images": list(snap.images or [])[:5],  # 缩略图最多 5 张
                "category_status": mapping_status,
                "target_category_id": target_cat_id,
                "type_id": snap.type_id,
                "source_platform": snap.source_platform,
                "local_sku_b": b_local_sku,
            })

        if not cursor:
            break

    duration_ms = int((utc_now_naive() - t0).total_seconds() * 1000)
    return {"code": 0, "data": {
        "found": found,
        "skip_published": skip_published,
        "skip_rejected": skip_rejected,
        "skip_pending": skip_pending,
        "skip_category_missing": skip_category_missing,
        "skip_a_shop_sku_exists": skip_a_shop_sku_exists,
        "candidates": candidates,
        "skipped_skus_sample": skipped_skus[:50],
        "duration_ms": duration_ms,
    }}
