"""评价管理路由 (Review Hub)

前缀: /api/v1/reviews
平台: WB Feedbacks API + Ozon Review API (Premium 订阅)
设计参考: app/services/reviews/__init__.py

合规自查:
- 规则 1 (多租户): 路径含 shop_id 走 get_owned_shop 守卫 + service 层 AND tenant_id
- 规则 4 (单店作用域): 所有手动触发型 (sync/generate/send) 必须按 shop_id 过滤
"""

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_tenant_id, get_owned_shop, get_current_user
from app.schemas.review import (
    GenerateReplyRequest, SendReplyRequest,
    ReviewSettingsUpdate, ReviewSyncRequest,
)
from app.services.reviews import service as reviews_service
from app.utils.response import success, error

router = APIRouter()


# ==================== 1. 列表 ====================

@router.get("")
def list_reviews(
    shop_id: int = Query(..., description="店铺 ID (必填, 按店隔离)"),
    status: str = Query(None, description="unread/read/replied/auto_replied/ignored"),
    rating: int = Query(None, ge=1, le=5),
    sentiment: str = Query(None, description="positive/neutral/negative/unknown"),
    keyword: str = Query(None, max_length=100, description="搜俄文/中文模糊"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
    shop=Depends(get_owned_shop),    # 守卫 shop_id 归属
):
    """评价分页列表"""
    result = reviews_service.list_reviews(
        db, tenant_id=tenant_id, shop_id=shop.id,
        status=status, rating=rating, sentiment=sentiment, keyword=keyword,
        page=page, page_size=page_size,
    )
    return success(result)


# ==================== 2. 红点角标 ====================

@router.get("/unread-count")
def unread_count(
    shop_id: int = Query(None, description="None=本租户全店聚合"),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """未读评价数 (顶部菜单 Badge 用)"""
    cnt = reviews_service.get_unread_count(
        db, tenant_id=tenant_id, shop_id=shop_id,
    )
    return success({"unread_count": cnt})


# ==================== 3. 手动同步 ====================

@router.post("/{shop_id}/sync")
async def sync_reviews(
    shop_id: int,
    req: ReviewSyncRequest = Body(default_factory=ReviewSyncRequest),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
    shop=Depends(get_owned_shop),
):
    """手动触发拉取评价 + UPSERT + AI 翻译

    平台限制:
    - WB: Feedbacks API rate limit 1 req/s (跟 seller token 共享池)
    - Ozon: 需 Premium 订阅, 失败时透传 SubscriptionRequiredError
    """
    if shop.platform not in ("wb", "ozon"):
        return error(10002, f"评价模块暂不支持 {shop.platform} 平台")
    try:
        result = await reviews_service.sync_reviews(
            db, tenant_id=tenant_id, shop_id=shop.id,
            only_unanswered=req.only_unanswered,
            max_pages=req.max_pages,
        )
        return success(result)
    except Exception as e:
        return error(1, f"同步失败: {str(e)[:300]}")


# ==================== 4. 标已读 ====================

@router.patch("/{review_id}/mark-read")
def mark_read(
    review_id: int,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """标已读 (业务层 unread→read; Ozon 平台同步留 Phase 2)"""
    result = reviews_service.mark_read(
        db, tenant_id=tenant_id, review_id=review_id,
    )
    if not result.get("ok"):
        return error(40004, result.get("msg") or "操作失败")
    return success(result)


# ==================== 5. 生成 AI 回复草稿 ====================

@router.post("/{review_id}/generate-reply")
async def generate_reply(
    review_id: int,
    req: GenerateReplyRequest = Body(default_factory=GenerateReplyRequest),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
    user=Depends(get_current_user),
):
    """生成俄语回复草稿 + 中文翻译

    重新生成时传新的 custom_hint, generated_count 自增, 多版草稿留痕.
    """
    result = await reviews_service.generate_reply(
        db, tenant_id=tenant_id, review_id=review_id,
        custom_hint=req.custom_hint or "",
        user_id=user["user_id"],
    )
    if not result.get("ok"):
        return error(1, result.get("msg") or "生成失败")
    return success({
        "reply_id": result["reply_id"],
        "draft_ru": result["draft_ru"],
        "draft_zh": result["draft_zh"],
        "generated_count": result["generated_count"],
    })


# ==================== 6. 真实发送回复 ====================

@router.post("/{review_id}/send-reply")
async def send_reply(
    review_id: int,
    req: SendReplyRequest = Body(...),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
    user=Depends(get_current_user),
):
    """真实发送回复到平台

    用户在 UI 编辑过 final_content_ru 时透传; 没编辑用 draft 原版.
    """
    result = await reviews_service.send_reply(
        db, tenant_id=tenant_id, reply_id=req.reply_id,
        final_content_ru=req.final_content_ru,
        user_id=user["user_id"],
    )
    if not result.get("ok"):
        return error(1, result.get("msg") or "发送失败")
    return success(result)


# ==================== 7. 取店铺级设置 ====================

@router.get("/settings/{shop_id}")
def get_settings(
    shop_id: int,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
    shop=Depends(get_owned_shop),
):
    """店铺级评价配置 (不存在自动返默认)"""
    result = reviews_service.get_settings(
        db, tenant_id=tenant_id, shop_id=shop.id,
    )
    return success(result)


# ==================== 8. 更新店铺级设置 ====================

@router.patch("/settings/{shop_id}")
def update_settings(
    shop_id: int,
    req: ReviewSettingsUpdate = Body(...),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
    shop=Depends(get_owned_shop),
):
    """更新店铺级评价配置 (自动回复开关 / 语气 / 签名 / 自定义 prompt)"""
    try:
        result = reviews_service.update_settings(
            db, tenant_id=tenant_id, shop_id=shop.id,
            auto_reply_enabled=req.auto_reply_enabled,
            auto_reply_rating_floor=req.auto_reply_rating_floor,
            reply_tone=req.reply_tone,
            brand_signature=req.brand_signature,
            custom_prompt_extra=req.custom_prompt_extra,
        )
        return success(result)
    except ValueError as e:
        return error(10002, str(e))
