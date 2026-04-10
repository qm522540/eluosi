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
from app.schemas.ai_pricing import PricingConfigUpdate, AnalyzeRequest, ToggleAutoRequest, CampaignPricingConfigUpdate, PromoCalendarCreate
from app.models.ai_pricing import AiPricingConfig, AiPricingSuggestion
from app.models.ad import AdCampaign
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


# ==================== 模板管理 ====================

@router.get("/templates")
def get_pricing_templates(
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """获取所有可用策略模板列表（供前端下拉选择）"""
    from app.services.ai.config_resolver import get_all_templates
    templates = get_all_templates(db, tenant_id)
    return success(templates)


@router.put("/campaigns/{campaign_id}/config")
def update_campaign_pricing_config(
    campaign_id: int,
    req: CampaignPricingConfigUpdate,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """给广告活动绑定模板或设置覆盖参数"""
    from app.models.ad import AdCampaign

    campaign = db.query(AdCampaign).filter(
        AdCampaign.id == campaign_id,
        AdCampaign.tenant_id == tenant_id,
    ).first()
    if not campaign:
        return error(ErrorCode.NOT_FOUND, "广告活动不存在")

    # 校验模板存在性
    data = req.model_dump(exclude_none=True)
    if "pricing_config_id" in data and data["pricing_config_id"] is not None:
        config = db.query(AiPricingConfig).filter(
            AiPricingConfig.id == data["pricing_config_id"],
            AiPricingConfig.tenant_id == tenant_id,
        ).first()
        if not config:
            return error(ErrorCode.NOT_FOUND, "策略模板不存在")

    for key, value in data.items():
        if hasattr(campaign, key):
            setattr(campaign, key, value)

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"更新活动配置失败 campaign_id={campaign_id}: {e}")
        return error(ErrorCode.UNKNOWN_ERROR, "更新配置失败")

    return success({
        "campaign_id": campaign_id,
        "pricing_config_id": campaign.pricing_config_id,
        "custom_max_bid": float(campaign.custom_max_bid) if campaign.custom_max_bid else None,
        "custom_daily_budget": float(campaign.custom_daily_budget) if campaign.custom_daily_budget else None,
        "custom_target_roas": float(campaign.custom_target_roas) if campaign.custom_target_roas else None,
    }, msg="配置已更新")


# ==================== 大促管理 ====================

@router.get("/promo-calendars")
def get_promo_calendars(
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """获取大促日历列表"""
    from app.models.promo_calendar import PromoCalendar
    promos = db.query(PromoCalendar).filter(
        PromoCalendar.tenant_id == tenant_id,
    ).order_by(PromoCalendar.promo_date).all()

    return success([{
        "id": p.id,
        "promo_name": p.promo_name,
        "promo_date": p.promo_date.isoformat(),
        "pre_heat_days": p.pre_heat_days,
        "recovery_days": p.recovery_days,
        "pre_heat_multiplier": float(p.pre_heat_multiplier),
        "peak_multiplier": float(p.peak_multiplier),
        "recovery_day1_multiplier": float(p.recovery_day1_multiplier),
        "recovery_day2_multiplier": float(p.recovery_day2_multiplier),
        "recovery_day3_multiplier": float(p.recovery_day3_multiplier),
        "is_active": bool(p.is_active),
    } for p in promos])


@router.post("/promo-calendars")
def create_promo_calendar(
    req: PromoCalendarCreate,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """新增大促日期"""
    from app.models.promo_calendar import PromoCalendar
    try:
        promo = PromoCalendar(
            tenant_id=tenant_id,
            **req.model_dump(),
        )
        db.add(promo)
        db.commit()
        return success({"id": promo.id}, msg="大促日期已添加")
    except Exception as e:
        db.rollback()
        logger.error(f"创建大促日期失败: {e}")
        return error(ErrorCode.PARAM_ERROR, f"创建失败: {str(e)[:100]}")


@router.get("/promo-status")
def get_promo_status(
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """获取当前大促状态"""
    from app.services.ai.promo_detector import detect_promo_context
    ctx = detect_promo_context(db, tenant_id)
    return success({
        "is_promo_period": ctx.is_promo_period,
        "promo_phase": ctx.promo_phase,
        "promo_name": ctx.promo_name,
        "bid_multiplier": ctx.bid_multiplier,
        "strategy_hint": ctx.strategy_hint,
        "days_to_promo": ctx.days_to_promo,
    })


# ==================== 数据初始化 ====================

@router.get("/data-status/{shop_id}")
def get_data_status(
    shop_id: int,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """查询店铺数据初始化状态（前端进入AI调价时调用）"""
    # 先校验shop归属
    shop = db.query(Shop).filter(Shop.id == shop_id, Shop.tenant_id == tenant_id).first()
    if not shop:
        return error(ErrorCode.SHOP_NOT_FOUND, "店铺不存在")
    from app.services.data.ozon_stats_collector import check_shop_init_status
    result = check_shop_init_status(db, shop_id)
    return success(result)


@router.post("/data-init/{shop_id}")
async def trigger_data_init(
    shop_id: int,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """触发店铺首次3个月数据拉取（后台异步执行，立即返回）"""
    # 先校验shop归属
    shop = db.query(Shop).filter(Shop.id == shop_id, Shop.tenant_id == tenant_id).first()
    if not shop:
        return error(ErrorCode.SHOP_NOT_FOUND, "店铺不存在")

    from app.services.data.ozon_stats_collector import check_shop_init_status

    status = check_shop_init_status(db, shop_id)
    if status.get("initialized"):
        return success(status, msg="数据已初始化，无需重复拉取")

    # 提交Celery后台任务，不阻塞HTTP请求
    try:
        from app.tasks.ai_pricing_task import async_init_shop_data
        async_init_shop_data.delay(shop_id)
        return success({"initialized": False, "message": "数据初始化已在后台启动，约需1-3分钟"})
    except Exception as e:
        logger.error(f"提交数据初始化任务失败 shop_id={shop_id}: {e}")
        return error(ErrorCode.UNKNOWN_ERROR, "提交初始化任务失败")


# ==================== WB建议模式 ====================

@router.post("/wb/analyze/{shop_id}")
async def wb_manual_analyze(
    shop_id: int,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """手动触发WB店铺AI分析（建议模式）"""
    from app.services.ad.wb_pricing import run_wb_ai_analysis
    result = await run_wb_ai_analysis(db, tenant_id, shop_id)
    if result.get("code", 0) != 0:
        return error(result["code"], result["msg"])
    return success(result["data"])


@router.get("/wb/suggestions/{shop_id}")
def get_wb_suggestions(
    shop_id: int,
    status: str = Query("pending"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """获取WB待确认建议列表（含WB后台直链）"""
    # 过期处理
    _expire_old_suggestions(db, tenant_id, shop_id)

    query = db.query(AiPricingSuggestion, AdCampaign).filter(
        AiPricingSuggestion.tenant_id == tenant_id,
        AiPricingSuggestion.shop_id == shop_id,
        AiPricingSuggestion.status == status,
    ).join(AdCampaign, AiPricingSuggestion.campaign_id == AdCampaign.id).filter(
        AdCampaign.platform == "wb",
        AdCampaign.tenant_id == tenant_id,
    )

    total = query.count()
    rows = query.order_by(AiPricingSuggestion.created_at.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()

    result_items = []
    for s, campaign in rows:
        d = _suggestion_to_dict(s)
        d["campaign_name"] = campaign.name if campaign else None
        d["platform_campaign_id"] = campaign.platform_campaign_id if campaign else None
        d["wb_backend_url"] = (
            f"https://cmp.wildberries.ru/campaigns/list/active/edit/{campaign.platform_campaign_id}"
            if campaign else None
        )
        result_items.append(d)

    return success({
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": result_items,
    })


@router.post("/wb/suggestions/{suggestion_id}/reject")
def wb_suggestion_reject(
    suggestion_id: int,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """拒绝WB建议"""
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
    return success({"id": suggestion.id, "status": "rejected"}, msg="建议已忽略")


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
    campaign_ids = req.campaign_ids if req else None

    result = await run_ai_analysis(
        db, tenant_id, shop_id,
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
        "template_name": config.template_name,
        "template_type": getattr(config, 'template_type', 'default') or 'default',
        "description": getattr(config, 'description', '') or '',
        "target_roas": float(config.target_roas),
        "min_roas": float(config.min_roas),
        "gross_margin": float(config.gross_margin),
        "daily_budget_limit": float(config.daily_budget_limit),
        "no_budget_limit": bool(getattr(config, 'no_budget_limit', 0)),
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
        "decision_basis": getattr(s, "decision_basis", "today_only"),
        "history_avg_roas": float(s.history_avg_roas) if getattr(s, "history_avg_roas", None) else None,
        "data_days": getattr(s, "data_days", 0),
        "time_slot": getattr(s, "time_slot", None),
        "moscow_hour": getattr(s, "moscow_hour", None),
        "template_name": getattr(s, "template_name", None),
        "data_source": getattr(s, "data_source", "today_only"),
        "campaign_data_days": getattr(s, "campaign_data_days", 0),
        "is_new_campaign": bool(getattr(s, "is_new_campaign", 0)),
        "shop_avg_roas": float(s.shop_avg_roas) if getattr(s, "shop_avg_roas", None) else None,
        "product_stage": getattr(s, "product_stage", "unknown"),
        "stage_optimize_target": getattr(s, "stage_optimize_target", None),
        "promo_phase": getattr(s, "promo_phase", None),
        "promo_multiplier": float(s.promo_multiplier) if getattr(s, "promo_multiplier", None) else 1.0,
    }
