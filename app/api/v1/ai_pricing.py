"""AI智能调价路由

8个接口：
- 配置管理: GET configs, PUT config
- AI分析: POST analyze
- 建议管理: GET suggestions, POST approve, POST reject
- 模式切换: POST toggle-auto
- 历史记录: GET history
"""

import asyncio
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_current_user, get_tenant_id
from app.schemas.ai_pricing import PricingConfigUpdate, AnalyzeRequest, ToggleAutoRequest
from app.models.ai_pricing import AiPricingConfig, AiPricingSuggestion
from app.models.shop import Shop
from app.services.ad.ai_pricing import (
    approve_suggestion as do_approve,
    run_ai_analysis,
)
from app.utils.response import success, error
from app.utils.errors import ErrorCode
from app.utils.logger import setup_logger

logger = setup_logger("api.ai_pricing")

router = APIRouter()


# ==================== 配置管理 ====================

@router.get("/configs/{shop_id}")
def config_list(
    shop_id: int,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """获取店铺调价配置"""
    try:
        shop = db.query(Shop).filter(Shop.id == shop_id, Shop.tenant_id == tenant_id).first()
        if not shop:
            return error(ErrorCode.SHOP_NOT_FOUND, "店铺不存在")

        configs = db.query(AiPricingConfig).filter(
            AiPricingConfig.tenant_id == tenant_id,
            AiPricingConfig.shop_id == shop_id,
        ).order_by(AiPricingConfig.id).all()

        return success([_config_to_dict(c) for c in configs])
    except Exception as e:
        logger.error(f"获取调价配置失败 shop_id={shop_id}: {e}")
        return error(ErrorCode.UNKNOWN_ERROR, "获取配置失败")


@router.put("/configs/{config_id}")
def config_update(
    config_id: int,
    req: PricingConfigUpdate,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """更新调价配置"""
    config = db.query(AiPricingConfig).filter(
        AiPricingConfig.id == config_id,
        AiPricingConfig.tenant_id == tenant_id,
    ).first()
    if not config:
        return error(ErrorCode.NOT_FOUND, "配置不存在")

    data = req.model_dump(exclude_none=True)

    # 交叉校验
    target_roas = data.get("target_roas", float(config.target_roas))
    min_roas = data.get("min_roas", float(config.min_roas))
    if min_roas >= target_roas:
        return error(ErrorCode.PARAM_ERROR, "min_roas必须小于target_roas")

    min_bid = data.get("min_bid", float(config.min_bid))
    max_bid = data.get("max_bid", float(config.max_bid))
    if min_bid >= max_bid:
        return error(ErrorCode.PARAM_ERROR, "min_bid必须小于max_bid")

    # 转换bool→int
    if "auto_execute" in data and data["auto_execute"] is not None:
        data["auto_execute"] = 1 if data["auto_execute"] else 0
    if "is_active" in data and data["is_active"] is not None:
        data["is_active"] = 1 if data["is_active"] else 0

    try:
        for key, value in data.items():
            if value is not None and hasattr(config, key):
                setattr(config, key, value)
        db.commit()
        db.refresh(config)
        return success(_config_to_dict(config), msg="配置更新成功")
    except Exception as e:
        db.rollback()
        logger.error(f"更新配置失败 config_id={config_id}: {e}")
        return error(ErrorCode.UNKNOWN_ERROR, "更新配置失败")


# ==================== AI分析 ====================

@router.post("/analyze/{shop_id}")
async def analyze(
    shop_id: int,
    req: AnalyzeRequest = None,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """手动触发AI分析（调DeepSeek）"""
    category_name = req.category_name if req else None
    campaign_ids = req.campaign_ids if req else None

    result = await run_ai_analysis(
        db, tenant_id, shop_id,
        category_name=category_name,
        campaign_ids=campaign_ids,
    )

    if result.get("code", 0) != 0:
        return error(result["code"], result["msg"])
    return success(result["data"])


# ==================== 建议管理 ====================

@router.get("/suggestions/{shop_id}")
def suggestion_list(
    shop_id: int,
    status: str = Query("pending", description="状态: pending/approved/rejected/executed/expired"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """获取建议列表"""
    # 先将过期建议标记
    _expire_old_suggestions(db, tenant_id, shop_id)

    query = db.query(AiPricingSuggestion).filter(
        AiPricingSuggestion.tenant_id == tenant_id,
        AiPricingSuggestion.shop_id == shop_id,
    )
    if status:
        query = query.filter(AiPricingSuggestion.status == status)

    total = query.count()
    items = query.order_by(AiPricingSuggestion.created_at.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()

    return success({
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [_suggestion_to_dict(s) for s in items],
    })


@router.post("/suggestions/{suggestion_id}/approve")
async def suggestion_approve(
    suggestion_id: int,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """确认执行建议（调Ozon API修改出价）"""
    result = await do_approve(db, tenant_id, suggestion_id)
    if result.get("code", 0) != 0:
        return error(result["code"], result["msg"])
    return success(result["data"], msg="建议已执行")


@router.post("/suggestions/{suggestion_id}/reject")
def suggestion_reject(
    suggestion_id: int,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """拒绝建议"""
    suggestion = db.query(AiPricingSuggestion).filter(
        AiPricingSuggestion.id == suggestion_id,
        AiPricingSuggestion.tenant_id == tenant_id,
    ).first()
    if not suggestion:
        return error(ErrorCode.NOT_FOUND, "建议记录不存在")

    if suggestion.status != "pending":
        return error(ErrorCode.PARAM_ERROR, f"当前状态为{suggestion.status}，仅pending可拒绝")

    suggestion.status = "rejected"
    db.commit()

    return success({"id": suggestion.id, "status": "rejected"}, msg="建议已拒绝")


# ==================== 模式切换 ====================

@router.post("/toggle-auto/{shop_id}")
def toggle_auto(
    shop_id: int,
    req: ToggleAutoRequest,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """切换自动/建议模式"""
    query = db.query(AiPricingConfig).filter(
        AiPricingConfig.tenant_id == tenant_id,
        AiPricingConfig.shop_id == shop_id,
    )
    if req.category_name:
        query = query.filter(AiPricingConfig.category_name == req.category_name)

    configs = query.all()
    if not configs:
        return error(ErrorCode.NOT_FOUND, "未找到调价配置")

    value = 1 if req.auto_execute else 0
    for config in configs:
        config.auto_execute = value
    db.commit()

    mode_text = "自动执行" if req.auto_execute else "手动确认"
    return success({
        "shop_id": shop_id,
        "updated_count": len(configs),
        "auto_execute": req.auto_execute,
    }, msg=f"已切换为{mode_text}模式")


# ==================== 历史记录 ====================

@router.get("/history/{shop_id}")
def history_list(
    shop_id: int,
    status: str = Query(None, description="状态: executed/rejected/expired"),
    start_date: str = Query(None, description="起始日期 YYYY-MM-DD"),
    end_date: str = Query(None, description="结束日期 YYYY-MM-DD"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """调价历史记录"""
    query = db.query(AiPricingSuggestion).filter(
        AiPricingSuggestion.tenant_id == tenant_id,
        AiPricingSuggestion.shop_id == shop_id,
        AiPricingSuggestion.status != "pending",
    )
    if status:
        query = query.filter(AiPricingSuggestion.status == status)
    if start_date:
        try:
            dt_start = datetime.strptime(start_date, "%Y-%m-%d")
            query = query.filter(AiPricingSuggestion.created_at >= dt_start)
        except ValueError:
            return error(ErrorCode.PARAM_ERROR, "start_date格式错误，应为YYYY-MM-DD")
    if end_date:
        try:
            dt_end = datetime.strptime(end_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
            query = query.filter(AiPricingSuggestion.created_at <= dt_end)
        except ValueError:
            return error(ErrorCode.PARAM_ERROR, "end_date格式错误，应为YYYY-MM-DD")

    total = query.count()
    items = query.order_by(AiPricingSuggestion.created_at.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()

    return success({
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [_suggestion_to_dict(s) for s in items],
    })


# ==================== 内部工具函数 ====================

def _expire_old_suggestions(db: Session, tenant_id: int, shop_id: int):
    """将过期的pending建议标记为expired"""
    now = datetime.now()
    db.query(AiPricingSuggestion).filter(
        AiPricingSuggestion.tenant_id == tenant_id,
        AiPricingSuggestion.shop_id == shop_id,
        AiPricingSuggestion.status == "pending",
        AiPricingSuggestion.expires_at < now,
    ).update({"status": "expired"})
    db.commit()


def _config_to_dict(config: AiPricingConfig) -> dict:
    return {
        "id": config.id,
        "shop_id": config.shop_id,
        "category_name": config.category_name,
        "target_roas": float(config.target_roas),
        "min_roas": float(config.min_roas),
        "gross_margin": float(config.gross_margin),
        "daily_budget_limit": float(config.daily_budget_limit),
        "max_bid": float(config.max_bid),
        "min_bid": float(config.min_bid),
        "max_adjust_pct": float(config.max_adjust_pct),
        "auto_execute": bool(config.auto_execute),
        "is_active": bool(config.is_active),
        "created_at": config.created_at.isoformat() if config.created_at else None,
        "updated_at": config.updated_at.isoformat() if config.updated_at else None,
    }


def _suggestion_to_dict(s: AiPricingSuggestion) -> dict:
    return {
        "id": s.id,
        "campaign_id": s.campaign_id,
        "product_id": s.product_id,
        "product_name": s.product_name,
        "image_url": s.image_url,
        "current_bid": float(s.current_bid),
        "suggested_bid": float(s.suggested_bid),
        "adjust_pct": float(s.adjust_pct),
        "reason": s.reason,
        "current_roas": float(s.current_roas) if s.current_roas else None,
        "expected_roas": float(s.expected_roas) if s.expected_roas else None,
        "current_spend": float(s.current_spend) if s.current_spend else None,
        "daily_budget": float(s.daily_budget) if s.daily_budget else None,
        "ai_model": s.ai_model,
        "status": s.status,
        "auto_executed": bool(s.auto_executed),
        "executed_at": s.executed_at.isoformat() if s.executed_at else None,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "expires_at": s.expires_at.isoformat() if s.expires_at else None,
    }
