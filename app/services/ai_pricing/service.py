"""AI智能调价服务层"""

from datetime import datetime, timedelta
from typing import Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.models.ai_pricing import AiPricingConfig, AiPricingSuggestion
from app.models.ad import AdCampaign, AdStat
from app.models.shop import Shop
from app.utils.errors import ErrorCode

import logging

logger = logging.getLogger(__name__)


# ==================== 配置管理 ====================

def get_configs(db: Session, tenant_id: int, shop_id: int) -> dict:
    """获取店铺调价配置列表"""
    shop = db.query(Shop).filter(Shop.id == shop_id, Shop.tenant_id == tenant_id).first()
    if not shop:
        return {"code": ErrorCode.SHOP_NOT_FOUND, "msg": "店铺不存在"}

    configs = db.query(AiPricingConfig).filter(
        AiPricingConfig.tenant_id == tenant_id,
        AiPricingConfig.shop_id == shop_id,
    ).order_by(AiPricingConfig.id).all()

    return {"code": 0, "data": [_config_to_dict(c) for c in configs]}


def update_config(db: Session, tenant_id: int, config_id: int, data: dict) -> dict:
    """更新调价配置"""
    config = db.query(AiPricingConfig).filter(
        AiPricingConfig.id == config_id,
        AiPricingConfig.tenant_id == tenant_id,
    ).first()
    if not config:
        return {"code": ErrorCode.NOT_FOUND, "msg": "配置不存在"}

    # 交叉校验
    target_roas = data.get("target_roas", float(config.target_roas))
    min_roas = data.get("min_roas", float(config.min_roas))
    if min_roas >= target_roas:
        return {"code": ErrorCode.PARAM_ERROR, "msg": "min_roas必须小于target_roas"}

    min_bid = data.get("min_bid", float(config.min_bid))
    max_bid = data.get("max_bid", float(config.max_bid))
    if min_bid >= max_bid:
        return {"code": ErrorCode.PARAM_ERROR, "msg": "min_bid必须小于max_bid"}

    # 转换bool→int
    if "auto_execute" in data and data["auto_execute"] is not None:
        data["auto_execute"] = 1 if data["auto_execute"] else 0
    if "is_active" in data and data["is_active"] is not None:
        data["is_active"] = 1 if data["is_active"] else 0

    for key, value in data.items():
        if value is not None and hasattr(config, key):
            setattr(config, key, value)
    db.commit()
    db.refresh(config)

    return {"code": 0, "data": _config_to_dict(config)}


# ==================== AI分析 ====================

def analyze_shop(db: Session, tenant_id: int, shop_id: int,
                 category_name: Optional[str] = None,
                 campaign_ids: Optional[List[int]] = None) -> dict:
    """对店铺执行AI调价分析，生成建议"""
    shop = db.query(Shop).filter(Shop.id == shop_id, Shop.tenant_id == tenant_id).first()
    if not shop:
        return {"code": ErrorCode.SHOP_NOT_FOUND, "msg": "店铺不存在"}

    # 获取配置
    config_query = db.query(AiPricingConfig).filter(
        AiPricingConfig.tenant_id == tenant_id,
        AiPricingConfig.shop_id == shop_id,
        AiPricingConfig.is_active == 1,
    )
    if category_name:
        config_query = config_query.filter(AiPricingConfig.category_name == category_name)
    configs = config_query.all()

    if not configs:
        # 没有配置时使用通用默认参数
        configs = [_default_config(tenant_id, shop_id)]

    # 获取活跃活动
    campaign_query = db.query(AdCampaign).filter(
        AdCampaign.tenant_id == tenant_id,
        AdCampaign.shop_id == shop_id,
        AdCampaign.status == "active",
    )
    if campaign_ids:
        campaign_query = campaign_query.filter(AdCampaign.id.in_(campaign_ids))
    campaigns = campaign_query.all()

    if not campaigns:
        return {"code": 0, "data": {"analyzed_count": 0, "suggestion_count": 0, "suggestions": []}}

    # 使用第一个匹配的配置（后续可按品类匹配）
    config = configs[0]
    suggestions = []

    for campaign in campaigns:
        campaign_suggestions = _analyze_campaign(db, tenant_id, shop, campaign, config)
        suggestions.extend(campaign_suggestions)

    # 批量保存建议
    saved = []
    for s in suggestions:
        suggestion = AiPricingSuggestion(**s)
        db.add(suggestion)
        db.flush()
        saved.append(_suggestion_to_dict(suggestion))
    db.commit()

    return {
        "code": 0,
        "data": {
            "analyzed_count": len(campaigns),
            "suggestion_count": len(saved),
            "suggestions": saved,
        }
    }


def _analyze_campaign(db: Session, tenant_id: int, shop, campaign, config) -> list:
    """分析单个活动，返回建议列表"""
    from datetime import date

    today = date.today()
    # 获取近7天统计数据
    stats = db.query(AdStat).filter(
        AdStat.tenant_id == tenant_id,
        AdStat.campaign_id == campaign.id,
        AdStat.stat_date >= today - timedelta(days=7),
        AdStat.stat_date <= today,
    ).all()

    if not stats:
        return []

    # 汇总指标
    total_spend = sum(float(s.spend) for s in stats)
    total_revenue = sum(float(s.revenue) for s in stats)
    total_clicks = sum(s.clicks for s in stats)
    current_roas = round(total_revenue / total_spend, 2) if total_spend > 0 else 0

    # 今日花费
    today_stats = [s for s in stats if s.stat_date == today]
    today_spend = sum(float(s.spend) for s in today_stats)

    # 当前出价（取daily_budget近似，实际应从平台API获取）
    current_bid = float(campaign.daily_budget) if campaign.daily_budget else 100.0

    target_roas = float(config.target_roas)
    min_roas = float(config.min_roas)
    max_adjust = float(config.max_adjust_pct)
    max_bid = float(config.max_bid)
    min_bid = float(config.min_bid)
    daily_limit = float(config.daily_budget_limit)

    if daily_limit <= 0:
        return []

    suggestions = []
    budget_usage_pct = round(today_spend / daily_limit * 100)

    # 决策逻辑
    if current_roas >= target_roas and today_spend < daily_limit * 0.7:
        # ROAS优秀且预算充足 → 加价抢量
        adjust_pct = min(max_adjust, (current_roas / target_roas - 1) * 50)
        adjust_pct = round(min(adjust_pct, max_adjust), 2)
        suggested_bid = round(current_bid * (1 + adjust_pct / 100), 2)
        suggested_bid = min(suggested_bid, max_bid)
        reason = f"当前ROAS {current_roas}高于目标{target_roas}，且日预算使用率仅{budget_usage_pct}%，建议加价抢量"
        expected_roas = round(current_roas * 0.85, 2)  # 加价后ROAS预计下降
    elif current_roas < min_roas:
        # ROAS过低 → 降价止损
        adjust_pct = -min(max_adjust, (1 - current_roas / min_roas) * 50)
        adjust_pct = round(max(-max_adjust, adjust_pct), 2)
        suggested_bid = round(current_bid * (1 + adjust_pct / 100), 2)
        suggested_bid = max(suggested_bid, min_bid)
        reason = f"当前ROAS {current_roas}低于最低阈值{min_roas}，建议降价止损"
        expected_roas = round(current_roas * 1.2, 2)
    elif today_spend >= daily_limit * 0.9:
        # 接近预算上限 → 降价控成本
        adjust_pct = -round(min(max_adjust * 0.5, 15), 2)
        suggested_bid = round(current_bid * (1 + adjust_pct / 100), 2)
        suggested_bid = max(suggested_bid, min_bid)
        reason = f"今日花费{today_spend}已达预算{daily_limit}的{budget_usage_pct}%，建议降价控制成本"
        expected_roas = round(current_roas * 1.1, 2)
    else:
        # 无需调整
        return []

    actual_adjust_pct = round((suggested_bid - current_bid) / current_bid * 100, 2) if current_bid > 0 else 0

    suggestions.append({
        "tenant_id": tenant_id,
        "shop_id": shop.id,
        "campaign_id": campaign.id,
        "product_id": campaign.platform_campaign_id,
        "product_name": campaign.name,
        "current_bid": current_bid,
        "suggested_bid": suggested_bid,
        "adjust_pct": actual_adjust_pct,
        "reason": reason,
        "current_roas": current_roas,
        "expected_roas": expected_roas,
        "current_spend": today_spend,
        "daily_budget": daily_limit,
        "ai_model": "deepseek",
        "status": "pending",
        "auto_executed": 0,
        "expires_at": datetime.now() + timedelta(hours=2),
    })

    return suggestions


# ==================== 建议管理 ====================

def get_suggestions(db: Session, tenant_id: int, shop_id: int,
                    status: str = "pending", page: int = 1, page_size: int = 20) -> dict:
    """获取待确认建议列表"""
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

    return {
        "code": 0,
        "data": {
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": [_suggestion_to_dict(s) for s in items],
        }
    }


def approve_suggestion(db: Session, tenant_id: int, suggestion_id: int) -> dict:
    """确认执行建议"""
    suggestion = db.query(AiPricingSuggestion).filter(
        AiPricingSuggestion.id == suggestion_id,
        AiPricingSuggestion.tenant_id == tenant_id,
    ).first()
    if not suggestion:
        return {"code": ErrorCode.NOT_FOUND, "msg": "建议记录不存在"}

    if suggestion.status != "pending":
        return {"code": ErrorCode.PARAM_ERROR, "msg": f"当前状态为{suggestion.status}，仅pending可执行"}

    # 检查是否过期
    if suggestion.expires_at and suggestion.expires_at < datetime.now():
        suggestion.status = "expired"
        db.commit()
        return {"code": ErrorCode.PARAM_ERROR, "msg": "建议已过期"}

    # 标记为approved，实际API调用由调用方执行
    suggestion.status = "executed"
    suggestion.executed_at = datetime.now()
    db.commit()
    db.refresh(suggestion)

    return {
        "code": 0,
        "data": {
            "id": suggestion.id,
            "status": suggestion.status,
            "executed_at": suggestion.executed_at.isoformat() if suggestion.executed_at else None,
            "product_id": suggestion.product_id,
            "old_bid": float(suggestion.current_bid),
            "new_bid": float(suggestion.suggested_bid),
        }
    }


def reject_suggestion(db: Session, tenant_id: int, suggestion_id: int) -> dict:
    """拒绝建议"""
    suggestion = db.query(AiPricingSuggestion).filter(
        AiPricingSuggestion.id == suggestion_id,
        AiPricingSuggestion.tenant_id == tenant_id,
    ).first()
    if not suggestion:
        return {"code": ErrorCode.NOT_FOUND, "msg": "建议记录不存在"}

    if suggestion.status != "pending":
        return {"code": ErrorCode.PARAM_ERROR, "msg": f"当前状态为{suggestion.status}，仅pending可拒绝"}

    suggestion.status = "rejected"
    db.commit()

    return {"code": 0, "data": {"id": suggestion.id, "status": "rejected"}}


def toggle_auto_execute(db: Session, tenant_id: int, shop_id: int,
                        auto_execute: bool, category_name: Optional[str] = None) -> dict:
    """切换自动/建议模式"""
    query = db.query(AiPricingConfig).filter(
        AiPricingConfig.tenant_id == tenant_id,
        AiPricingConfig.shop_id == shop_id,
    )
    if category_name:
        query = query.filter(AiPricingConfig.category_name == category_name)

    configs = query.all()
    if not configs:
        return {"code": ErrorCode.NOT_FOUND, "msg": "未找到调价配置"}

    value = 1 if auto_execute else 0
    for config in configs:
        config.auto_execute = value
    db.commit()

    return {
        "code": 0,
        "data": {
            "shop_id": shop_id,
            "updated_count": len(configs),
            "auto_execute": auto_execute,
        }
    }


def get_history(db: Session, tenant_id: int, shop_id: int,
                status: Optional[str] = None,
                start_date: Optional[str] = None, end_date: Optional[str] = None,
                page: int = 1, page_size: int = 20) -> dict:
    """获取调价历史记录"""
    query = db.query(AiPricingSuggestion).filter(
        AiPricingSuggestion.tenant_id == tenant_id,
        AiPricingSuggestion.shop_id == shop_id,
        AiPricingSuggestion.status != "pending",
    )
    if status:
        query = query.filter(AiPricingSuggestion.status == status)
    if start_date:
        query = query.filter(AiPricingSuggestion.created_at >= start_date)
    if end_date:
        query = query.filter(AiPricingSuggestion.created_at <= end_date + " 23:59:59")

    total = query.count()
    items = query.order_by(AiPricingSuggestion.created_at.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()

    return {
        "code": 0,
        "data": {
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": [_suggestion_to_dict(s) for s in items],
        }
    }


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


def _default_config(tenant_id: int, shop_id: int):
    """返回默认配置对象（不持久化）"""
    config = AiPricingConfig()
    config.tenant_id = tenant_id
    config.shop_id = shop_id
    config.category_name = "通用默认"
    config.target_roas = 2.00
    config.min_roas = 1.20
    config.gross_margin = 0.45
    config.daily_budget_limit = 1500.00
    config.max_bid = 180.00
    config.min_bid = 3.00
    config.max_adjust_pct = 30.00
    config.auto_execute = 0
    config.is_active = 1
    return config


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
