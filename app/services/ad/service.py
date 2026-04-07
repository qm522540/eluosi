"""广告业务逻辑"""

from datetime import date
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.ad import AdCampaign, AdGroup, AdKeyword, AdStat
from app.utils.errors import ErrorCode
from app.utils.logger import logger


def list_campaigns(db: Session, tenant_id: int, shop_id: int = None,
                   platform: str = None, status: str = None,
                   page: int = 1, page_size: int = 20) -> dict:
    """获取广告活动列表"""
    try:
        query = db.query(AdCampaign).filter(AdCampaign.tenant_id == tenant_id)
        if shop_id:
            query = query.filter(AdCampaign.shop_id == shop_id)
        if platform:
            query = query.filter(AdCampaign.platform == platform)
        if status:
            query = query.filter(AdCampaign.status == status)

        total = query.count()
        campaigns = query.order_by(AdCampaign.created_at.desc()).offset(
            (page - 1) * page_size
        ).limit(page_size).all()

        items = [_campaign_to_dict(c) for c in campaigns]
        return {
            "code": ErrorCode.SUCCESS,
            "data": {
                "items": items,
                "total": total,
                "page": page,
                "page_size": page_size,
                "pages": (total + page_size - 1) // page_size,
            },
        }
    except Exception as e:
        logger.error(f"获取广告活动列表失败 tenant_id={tenant_id}: {e}")
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "获取广告活动列表失败"}


def get_campaign(db: Session, campaign_id: int, tenant_id: int) -> dict:
    """获取广告活动详情（含广告组和关键词）"""
    try:
        campaign = db.query(AdCampaign).filter(
            AdCampaign.id == campaign_id,
            AdCampaign.tenant_id == tenant_id,
        ).first()

        if not campaign:
            return {"code": ErrorCode.AD_CAMPAIGN_NOT_FOUND, "msg": "广告活动不存在"}

        detail = _campaign_to_dict(campaign)

        # 获取广告组
        groups = db.query(AdGroup).filter(
            AdGroup.campaign_id == campaign_id,
            AdGroup.tenant_id == tenant_id,
        ).all()
        detail["ad_groups"] = [_adgroup_to_dict(g) for g in groups]

        return {"code": ErrorCode.SUCCESS, "data": detail}
    except Exception as e:
        logger.error(f"获取广告活动详情失败 campaign_id={campaign_id}: {e}")
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "获取广告活动详情失败"}


def update_campaign(db: Session, campaign_id: int, tenant_id: int, data: dict) -> dict:
    """更新广告活动（调整预算/状态）"""
    try:
        campaign = db.query(AdCampaign).filter(
            AdCampaign.id == campaign_id,
            AdCampaign.tenant_id == tenant_id,
        ).first()

        if not campaign:
            return {"code": ErrorCode.AD_CAMPAIGN_NOT_FOUND, "msg": "广告活动不存在"}

        for key, value in data.items():
            if value is not None:
                setattr(campaign, key, value)

        db.commit()
        db.refresh(campaign)

        logger.info(f"广告活动更新成功: campaign_id={campaign.id}")
        return {"code": ErrorCode.SUCCESS, "data": _campaign_to_dict(campaign)}
    except Exception as e:
        db.rollback()
        logger.error(f"更新广告活动失败 campaign_id={campaign_id}: {e}")
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "更新广告活动失败"}


def get_ad_stats(db: Session, tenant_id: int, start_date: date, end_date: date,
                 shop_id: int = None, campaign_id: int = None,
                 platform: str = None) -> dict:
    """查询广告统计数据（按天汇总）"""
    try:
        query = db.query(
            AdStat.stat_date,
            AdStat.platform,
            func.sum(AdStat.impressions).label("impressions"),
            func.sum(AdStat.clicks).label("clicks"),
            func.sum(AdStat.spend).label("spend"),
            func.sum(AdStat.orders).label("orders"),
            func.sum(AdStat.revenue).label("revenue"),
        ).filter(
            AdStat.tenant_id == tenant_id,
            AdStat.stat_date >= start_date,
            AdStat.stat_date <= end_date,
        )
        if shop_id:
            # 通过campaign表关联shop_id
            campaign_ids = db.query(AdCampaign.id).filter(
                AdCampaign.shop_id == shop_id,
                AdCampaign.tenant_id == tenant_id,
            ).subquery()
            query = query.filter(AdStat.campaign_id.in_(campaign_ids))
        if campaign_id:
            query = query.filter(AdStat.campaign_id == campaign_id)
        if platform:
            query = query.filter(AdStat.platform == platform)

        rows = query.group_by(AdStat.stat_date, AdStat.platform).order_by(
            AdStat.stat_date.desc()
        ).all()

        items = []
        for row in rows:
            impressions = int(row.impressions or 0)
            clicks = int(row.clicks or 0)
            spend = float(row.spend or 0)
            orders = int(row.orders or 0)
            revenue = float(row.revenue or 0)
            items.append({
                "stat_date": row.stat_date.isoformat(),
                "platform": row.platform,
                "impressions": impressions,
                "clicks": clicks,
                "spend": round(spend, 2),
                "orders": orders,
                "revenue": round(revenue, 2),
                "ctr": round(clicks / impressions * 100, 4) if impressions > 0 else None,
                "cpc": round(spend / clicks, 2) if clicks > 0 else None,
                "acos": round(spend / revenue * 100, 4) if revenue > 0 else None,
                "roas": round(revenue / spend, 4) if spend > 0 else None,
            })

        return {"code": ErrorCode.SUCCESS, "data": items}
    except Exception as e:
        logger.error(f"查询广告统计失败 tenant_id={tenant_id}: {e}")
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "查询广告统计失败"}


def get_ad_summary(db: Session, tenant_id: int, start_date: date, end_date: date,
                   shop_id: int = None, platform: str = None) -> dict:
    """获取广告汇总数据（给Dashboard用）"""
    try:
        query = db.query(
            func.sum(AdStat.impressions).label("impressions"),
            func.sum(AdStat.clicks).label("clicks"),
            func.sum(AdStat.spend).label("spend"),
            func.sum(AdStat.orders).label("orders"),
            func.sum(AdStat.revenue).label("revenue"),
        ).filter(
            AdStat.tenant_id == tenant_id,
            AdStat.stat_date >= start_date,
            AdStat.stat_date <= end_date,
        )
        if shop_id:
            campaign_ids = db.query(AdCampaign.id).filter(
                AdCampaign.shop_id == shop_id,
                AdCampaign.tenant_id == tenant_id,
            ).subquery()
            query = query.filter(AdStat.campaign_id.in_(campaign_ids))
        if platform:
            query = query.filter(AdStat.platform == platform)

        row = query.one()
        impressions = int(row.impressions or 0)
        clicks = int(row.clicks or 0)
        spend = float(row.spend or 0)
        orders = int(row.orders or 0)
        revenue = float(row.revenue or 0)

        summary = {
            "total_impressions": impressions,
            "total_clicks": clicks,
            "total_spend": round(spend, 2),
            "total_orders": orders,
            "total_revenue": round(revenue, 2),
            "avg_ctr": round(clicks / impressions * 100, 4) if impressions > 0 else None,
            "avg_cpc": round(spend / clicks, 2) if clicks > 0 else None,
            "overall_acos": round(spend / revenue * 100, 4) if revenue > 0 else None,
            "overall_roas": round(revenue / spend, 4) if spend > 0 else None,
        }

        return {"code": ErrorCode.SUCCESS, "data": summary}
    except Exception as e:
        logger.error(f"获取广告汇总失败 tenant_id={tenant_id}: {e}")
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "获取广告汇总失败"}


def get_campaign_count(db: Session, tenant_id: int, status: str = "active") -> int:
    """获取广告活动数量"""
    try:
        return db.query(AdCampaign).filter(
            AdCampaign.tenant_id == tenant_id,
            AdCampaign.status == status,
        ).count()
    except Exception as e:
        logger.error(f"获取广告活动数量失败: {e}")
        return 0


# ==================== 辅助函数 ====================

def _campaign_to_dict(c: AdCampaign) -> dict:
    return {
        "id": c.id,
        "tenant_id": c.tenant_id,
        "shop_id": c.shop_id,
        "platform": c.platform,
        "platform_campaign_id": c.platform_campaign_id,
        "name": c.name,
        "ad_type": c.ad_type,
        "daily_budget": float(c.daily_budget) if c.daily_budget else None,
        "total_budget": float(c.total_budget) if c.total_budget else None,
        "status": c.status,
        "start_date": c.start_date.isoformat() if c.start_date else None,
        "end_date": c.end_date.isoformat() if c.end_date else None,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    }


def _adgroup_to_dict(g: AdGroup) -> dict:
    return {
        "id": g.id,
        "campaign_id": g.campaign_id,
        "platform_group_id": g.platform_group_id,
        "listing_id": g.listing_id,
        "name": g.name,
        "bid": float(g.bid) if g.bid else None,
        "status": g.status,
    }
