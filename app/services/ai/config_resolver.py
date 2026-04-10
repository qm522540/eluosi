"""调价配置解析器

优先级：单活动覆盖参数 > 活动绑定模板 > 默认标准模板
"""

from sqlalchemy.orm import Session

from app.models.ad import AdCampaign
from app.models.ai_pricing import AiPricingConfig
from app.utils.logger import setup_logger

logger = setup_logger("ai.config_resolver")


def get_effective_config(db: Session, tenant_id: int, campaign: AdCampaign) -> dict:
    """获取某个广告活动的最终生效配置

    合并模板配置和单活动覆盖参数
    """
    # 1. 确定基础模板
    config = None
    if getattr(campaign, 'pricing_config_id', None):
        config = db.query(AiPricingConfig).filter(
            AiPricingConfig.id == campaign.pricing_config_id,
            AiPricingConfig.tenant_id == tenant_id,
        ).first()

    if not config:
        config = _get_default_config(db, tenant_id)

    if not config:
        logger.warning("找不到配置模板，使用硬编码默认值")
        return _hardcoded_defaults()

    # 2. 单活动覆盖参数（优先级最高）
    result = {
        "config_id": config.id,
        "template_name": config.template_name,
        "template_type": config.template_type or "default",
        "description": getattr(config, 'description', None) or "",
        "target_roas": float(getattr(campaign, 'custom_target_roas', None) or config.target_roas),
        "min_roas": float(config.min_roas),
        "gross_margin": float(config.gross_margin),
        "daily_budget_limit": float(getattr(campaign, 'custom_daily_budget', None) or config.daily_budget_limit),
        "no_budget_limit": bool(getattr(config, 'no_budget_limit', 0)),
        "max_bid": float(getattr(campaign, 'custom_max_bid', None) or config.max_bid),
        "min_bid": float(config.min_bid),
        "max_adjust_pct": float(config.max_adjust_pct),
        "auto_execute": bool(config.auto_execute),
    }

    logger.info(
        f"campaign_id={campaign.id} 使用模板={result['template_name']} "
        f"target_roas={result['target_roas']} max_bid={result['max_bid']}"
    )
    return result


def _get_default_config(db: Session, tenant_id: int):
    """获取默认标准模板"""
    return db.query(AiPricingConfig).filter(
        AiPricingConfig.tenant_id == tenant_id,
        AiPricingConfig.template_type == "default",
        AiPricingConfig.is_active == 1,
    ).first()


def _hardcoded_defaults() -> dict:
    """兜底默认值"""
    return {
        "config_id": None,
        "template_name": "系统默认",
        "template_type": "default",
        "description": "硬编码兜底默认值",
        "target_roas": 3.0,
        "min_roas": 1.8,
        "gross_margin": 0.50,
        "daily_budget_limit": 2000.0,
        "no_budget_limit": False,
        "max_bid": 180.0,
        "min_bid": 3.0,
        "max_adjust_pct": 30.0,
        "auto_execute": False,
    }


def get_all_templates(db: Session, tenant_id: int) -> list:
    """获取所有可用模板列表（供前端下拉选择）"""
    configs = db.query(AiPricingConfig).filter(
        AiPricingConfig.tenant_id == tenant_id,
        AiPricingConfig.is_active == 1,
    ).order_by(AiPricingConfig.id).all()

    return [
        {
            "id": c.id,
            "template_name": c.template_name,
            "template_type": c.template_type or "default",
            "target_roas": float(c.target_roas),
            "min_roas": float(c.min_roas),
            "gross_margin": float(c.gross_margin),
            "daily_budget_limit": float(c.daily_budget_limit),
            "no_budget_limit": bool(getattr(c, 'no_budget_limit', 0)),
            "max_bid": float(c.max_bid),
            "min_bid": float(c.min_bid),
            "max_adjust_pct": float(c.max_adjust_pct),
            "description": getattr(c, 'description', None) or "",
            "auto_execute": bool(c.auto_execute),
        }
        for c in configs
    ]
