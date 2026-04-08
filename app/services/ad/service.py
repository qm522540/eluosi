"""广告业务逻辑"""

import csv
import io
from datetime import date
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.ad import AdCampaign, AdGroup, AdKeyword, AdStat
from app.models.notification import Notification
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


def _keyword_to_dict(k: AdKeyword) -> dict:
    return {
        "id": k.id,
        "ad_group_id": k.ad_group_id,
        "keyword": k.keyword,
        "match_type": k.match_type,
        "bid": float(k.bid) if k.bid else None,
        "is_negative": k.is_negative,
        "status": k.status,
    }


# ==================== 广告活动 创建/删除 ====================

def create_campaign(db: Session, tenant_id: int, data: dict) -> dict:
    """创建广告活动"""
    try:
        campaign = AdCampaign(
            tenant_id=tenant_id,
            shop_id=data["shop_id"],
            platform=data["platform"],
            platform_campaign_id=f"manual-{int(date.today().strftime('%Y%m%d'))}-{data['name'][:20]}",
            name=data["name"],
            ad_type=data["ad_type"],
            daily_budget=data.get("daily_budget"),
            total_budget=data.get("total_budget"),
            status=data.get("status", "draft"),
            start_date=data.get("start_date"),
            end_date=data.get("end_date"),
        )
        db.add(campaign)
        db.commit()
        db.refresh(campaign)
        logger.info(f"广告活动创建成功: id={campaign.id}, name={campaign.name}")
        return {"code": ErrorCode.SUCCESS, "data": _campaign_to_dict(campaign)}
    except Exception as e:
        db.rollback()
        logger.error(f"创建广告活动失败: {e}")
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "创建广告活动失败"}


def delete_campaign(db: Session, campaign_id: int, tenant_id: int) -> dict:
    """删除广告活动（级联删除关联的广告组、关键词、统计）"""
    try:
        campaign = db.query(AdCampaign).filter(
            AdCampaign.id == campaign_id,
            AdCampaign.tenant_id == tenant_id,
        ).first()
        if not campaign:
            return {"code": ErrorCode.AD_CAMPAIGN_NOT_FOUND, "msg": "广告活动不存在"}

        # 删除关联数据
        group_ids = [g.id for g in db.query(AdGroup.id).filter(
            AdGroup.campaign_id == campaign_id, AdGroup.tenant_id == tenant_id
        ).all()]
        if group_ids:
            db.query(AdKeyword).filter(AdKeyword.ad_group_id.in_(group_ids)).delete(synchronize_session=False)
        db.query(AdGroup).filter(AdGroup.campaign_id == campaign_id, AdGroup.tenant_id == tenant_id).delete(synchronize_session=False)
        db.query(AdStat).filter(AdStat.campaign_id == campaign_id, AdStat.tenant_id == tenant_id).delete(synchronize_session=False)
        db.delete(campaign)
        db.commit()

        logger.info(f"广告活动删除成功: campaign_id={campaign_id}")
        return {"code": ErrorCode.SUCCESS, "data": None}
    except Exception as e:
        db.rollback()
        logger.error(f"删除广告活动失败 campaign_id={campaign_id}: {e}")
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "删除广告活动失败"}


# ==================== 广告组 CRUD ====================

def list_ad_groups(db: Session, tenant_id: int, campaign_id: int) -> dict:
    """获取广告活动下的所有广告组"""
    try:
        campaign = db.query(AdCampaign).filter(
            AdCampaign.id == campaign_id, AdCampaign.tenant_id == tenant_id
        ).first()
        if not campaign:
            return {"code": ErrorCode.AD_CAMPAIGN_NOT_FOUND, "msg": "广告活动不存在"}

        groups = db.query(AdGroup).filter(
            AdGroup.campaign_id == campaign_id, AdGroup.tenant_id == tenant_id
        ).order_by(AdGroup.created_at.desc()).all()

        items = []
        for g in groups:
            gd = _adgroup_to_dict(g)
            # 附带关键词数量
            gd["keyword_count"] = db.query(AdKeyword).filter(
                AdKeyword.ad_group_id == g.id, AdKeyword.tenant_id == tenant_id
            ).count()
            items.append(gd)

        return {"code": ErrorCode.SUCCESS, "data": items}
    except Exception as e:
        logger.error(f"获取广告组列表失败: {e}")
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "获取广告组列表失败"}


def create_ad_group(db: Session, tenant_id: int, data: dict) -> dict:
    """创建广告组"""
    try:
        campaign = db.query(AdCampaign).filter(
            AdCampaign.id == data["campaign_id"], AdCampaign.tenant_id == tenant_id
        ).first()
        if not campaign:
            return {"code": ErrorCode.AD_CAMPAIGN_NOT_FOUND, "msg": "广告活动不存在"}

        group = AdGroup(
            tenant_id=tenant_id,
            campaign_id=data["campaign_id"],
            name=data["name"],
            bid=data.get("bid"),
            listing_id=data.get("listing_id"),
            status=data.get("status", "active"),
        )
        db.add(group)
        db.commit()
        db.refresh(group)
        logger.info(f"广告组创建成功: id={group.id}")
        return {"code": ErrorCode.SUCCESS, "data": _adgroup_to_dict(group)}
    except Exception as e:
        db.rollback()
        logger.error(f"创建广告组失败: {e}")
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "创建广告组失败"}


def update_ad_group(db: Session, group_id: int, tenant_id: int, data: dict) -> dict:
    """更新广告组"""
    try:
        group = db.query(AdGroup).filter(
            AdGroup.id == group_id, AdGroup.tenant_id == tenant_id
        ).first()
        if not group:
            return {"code": ErrorCode.AD_GROUP_NOT_FOUND, "msg": "广告组不存在"}

        for key, value in data.items():
            if value is not None:
                setattr(group, key, value)
        db.commit()
        db.refresh(group)
        return {"code": ErrorCode.SUCCESS, "data": _adgroup_to_dict(group)}
    except Exception as e:
        db.rollback()
        logger.error(f"更新广告组失败 group_id={group_id}: {e}")
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "更新广告组失败"}


def delete_ad_group(db: Session, group_id: int, tenant_id: int) -> dict:
    """删除广告组（级联删除关键词）"""
    try:
        group = db.query(AdGroup).filter(
            AdGroup.id == group_id, AdGroup.tenant_id == tenant_id
        ).first()
        if not group:
            return {"code": ErrorCode.AD_GROUP_NOT_FOUND, "msg": "广告组不存在"}

        db.query(AdKeyword).filter(
            AdKeyword.ad_group_id == group_id, AdKeyword.tenant_id == tenant_id
        ).delete(synchronize_session=False)
        db.delete(group)
        db.commit()
        logger.info(f"广告组删除成功: group_id={group_id}")
        return {"code": ErrorCode.SUCCESS, "data": None}
    except Exception as e:
        db.rollback()
        logger.error(f"删除广告组失败 group_id={group_id}: {e}")
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "删除广告组失败"}


# ==================== 关键词 CRUD ====================

def list_keywords(db: Session, tenant_id: int, ad_group_id: int) -> dict:
    """获取广告组下的所有关键词"""
    try:
        group = db.query(AdGroup).filter(
            AdGroup.id == ad_group_id, AdGroup.tenant_id == tenant_id
        ).first()
        if not group:
            return {"code": ErrorCode.AD_GROUP_NOT_FOUND, "msg": "广告组不存在"}

        keywords = db.query(AdKeyword).filter(
            AdKeyword.ad_group_id == ad_group_id, AdKeyword.tenant_id == tenant_id
        ).order_by(AdKeyword.created_at.desc()).all()

        return {"code": ErrorCode.SUCCESS, "data": [_keyword_to_dict(k) for k in keywords]}
    except Exception as e:
        logger.error(f"获取关键词列表失败: {e}")
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "获取关键词列表失败"}


def create_keyword(db: Session, tenant_id: int, data: dict) -> dict:
    """创建关键词"""
    try:
        group = db.query(AdGroup).filter(
            AdGroup.id == data["ad_group_id"], AdGroup.tenant_id == tenant_id
        ).first()
        if not group:
            return {"code": ErrorCode.AD_GROUP_NOT_FOUND, "msg": "广告组不存在"}

        kw = AdKeyword(
            tenant_id=tenant_id,
            ad_group_id=data["ad_group_id"],
            keyword=data["keyword"],
            match_type=data.get("match_type", "broad"),
            bid=data.get("bid"),
            is_negative=data.get("is_negative", 0),
            status=data.get("status", "active"),
        )
        db.add(kw)
        db.commit()
        db.refresh(kw)
        return {"code": ErrorCode.SUCCESS, "data": _keyword_to_dict(kw)}
    except Exception as e:
        db.rollback()
        logger.error(f"创建关键词失败: {e}")
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "创建关键词失败"}


def batch_create_keywords(db: Session, tenant_id: int, data: dict) -> dict:
    """批量创建关键词"""
    try:
        group = db.query(AdGroup).filter(
            AdGroup.id == data["ad_group_id"], AdGroup.tenant_id == tenant_id
        ).first()
        if not group:
            return {"code": ErrorCode.AD_GROUP_NOT_FOUND, "msg": "广告组不存在"}

        created = []
        for kw_text in data["keywords"]:
            kw_text = kw_text.strip()
            if not kw_text:
                continue
            kw = AdKeyword(
                tenant_id=tenant_id,
                ad_group_id=data["ad_group_id"],
                keyword=kw_text,
                match_type=data.get("match_type", "broad"),
                bid=data.get("bid"),
                is_negative=data.get("is_negative", 0),
                status="active",
            )
            db.add(kw)
            created.append(kw)

        db.commit()
        for kw in created:
            db.refresh(kw)
        return {"code": ErrorCode.SUCCESS, "data": [_keyword_to_dict(k) for k in created]}
    except Exception as e:
        db.rollback()
        logger.error(f"批量创建关键词失败: {e}")
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "批量创建关键词失败"}


def update_keyword(db: Session, keyword_id: int, tenant_id: int, data: dict) -> dict:
    """更新关键词"""
    try:
        kw = db.query(AdKeyword).filter(
            AdKeyword.id == keyword_id, AdKeyword.tenant_id == tenant_id
        ).first()
        if not kw:
            return {"code": ErrorCode.AD_KEYWORD_NOT_FOUND, "msg": "关键词不存在"}

        for key, value in data.items():
            if value is not None:
                setattr(kw, key, value)
        db.commit()
        db.refresh(kw)
        return {"code": ErrorCode.SUCCESS, "data": _keyword_to_dict(kw)}
    except Exception as e:
        db.rollback()
        logger.error(f"更新关键词失败 keyword_id={keyword_id}: {e}")
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "更新关键词失败"}


def delete_keyword(db: Session, keyword_id: int, tenant_id: int) -> dict:
    """删除关键词"""
    try:
        kw = db.query(AdKeyword).filter(
            AdKeyword.id == keyword_id, AdKeyword.tenant_id == tenant_id
        ).first()
        if not kw:
            return {"code": ErrorCode.AD_KEYWORD_NOT_FOUND, "msg": "关键词不存在"}

        db.delete(kw)
        db.commit()
        return {"code": ErrorCode.SUCCESS, "data": None}
    except Exception as e:
        db.rollback()
        logger.error(f"删除关键词失败 keyword_id={keyword_id}: {e}")
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "删除关键词失败"}


# ==================== 出价优化 ====================

def optimize_bids(db: Session, tenant_id: int, data: dict) -> dict:
    """基于ROAS的出价优化建议

    策略：
    - ROAS > 目标值 → 可适当加价以获取更多流量
    - ROAS < 目标值 → 应降低出价控制成本
    - 无数据的广告组不做调整
    """
    try:
        campaign_id = data["campaign_id"]
        target_roas = data.get("target_roas", 2.0)
        max_increase = data.get("max_bid_increase", 30) / 100
        max_decrease = data.get("max_bid_decrease", 30) / 100

        campaign = db.query(AdCampaign).filter(
            AdCampaign.id == campaign_id, AdCampaign.tenant_id == tenant_id
        ).first()
        if not campaign:
            return {"code": ErrorCode.AD_CAMPAIGN_NOT_FOUND, "msg": "广告活动不存在"}

        groups = db.query(AdGroup).filter(
            AdGroup.campaign_id == campaign_id,
            AdGroup.tenant_id == tenant_id,
            AdGroup.status == "active",
        ).all()

        suggestions = []
        today = date.today()
        from datetime import timedelta
        start = today - timedelta(days=7)

        for group in groups:
            if not group.bid or float(group.bid) <= 0:
                continue

            current_bid = float(group.bid)

            # 近7天统计
            stats = db.query(
                func.sum(AdStat.spend).label("spend"),
                func.sum(AdStat.revenue).label("revenue"),
                func.sum(AdStat.clicks).label("clicks"),
                func.sum(AdStat.impressions).label("impressions"),
            ).filter(
                AdStat.campaign_id == campaign_id,
                AdStat.ad_group_id == group.id,
                AdStat.stat_date >= start,
                AdStat.stat_date <= today,
            ).first()

            spend = float(stats.spend or 0)
            revenue = float(stats.revenue or 0)
            clicks = int(stats.clicks or 0)

            if spend <= 0 or clicks <= 0:
                continue

            actual_roas = revenue / spend if spend > 0 else 0
            ratio = actual_roas / target_roas if target_roas > 0 else 1

            if ratio > 1:
                # 表现好，加价
                adjustment = min((ratio - 1) * 0.5, max_increase)
                new_bid = round(current_bid * (1 + adjustment), 2)
                action = "increase"
            else:
                # 表现差，降价
                adjustment = min((1 - ratio) * 0.5, max_decrease)
                new_bid = round(current_bid * (1 - adjustment), 2)
                new_bid = max(new_bid, 0.01)
                action = "decrease"

            suggestions.append({
                "group_id": group.id,
                "group_name": group.name,
                "current_bid": current_bid,
                "suggested_bid": new_bid,
                "action": action,
                "change_percent": round(abs(new_bid - current_bid) / current_bid * 100, 1),
                "actual_roas": round(actual_roas, 2),
                "spend_7d": round(spend, 2),
                "revenue_7d": round(revenue, 2),
                "clicks_7d": clicks,
            })

        return {"code": ErrorCode.SUCCESS, "data": {
            "campaign_id": campaign_id,
            "campaign_name": campaign.name,
            "target_roas": target_roas,
            "suggestions": suggestions,
        }}
    except Exception as e:
        logger.error(f"出价优化失败: {e}")
        return {"code": ErrorCode.AD_OPTIMIZE_FAILED, "msg": "出价优化失败"}


def apply_bid_suggestions(db: Session, tenant_id: int, suggestions: list) -> dict:
    """应用出价建议 — 批量更新广告组出价"""
    try:
        updated = 0
        for item in suggestions:
            group = db.query(AdGroup).filter(
                AdGroup.id == item["group_id"], AdGroup.tenant_id == tenant_id
            ).first()
            if group:
                group.bid = item["suggested_bid"]
                updated += 1

        db.commit()
        logger.info(f"批量更新出价成功: {updated}个广告组")
        return {"code": ErrorCode.SUCCESS, "data": {"updated": updated}}
    except Exception as e:
        db.rollback()
        logger.error(f"批量更新出价失败: {e}")
        return {"code": ErrorCode.AD_OPTIMIZE_FAILED, "msg": "应用出价建议失败"}


# ==================== 数据导出 ====================

def export_stats_csv(db: Session, tenant_id: int, start_date: date, end_date: date,
                     shop_id: int = None, platform: str = None) -> str:
    """导出广告统计数据为CSV字符串"""
    try:
        query = db.query(
            AdStat.stat_date,
            AdStat.platform,
            AdCampaign.name.label("campaign_name"),
            AdStat.impressions,
            AdStat.clicks,
            AdStat.spend,
            AdStat.orders,
            AdStat.revenue,
        ).join(
            AdCampaign, AdStat.campaign_id == AdCampaign.id
        ).filter(
            AdStat.tenant_id == tenant_id,
            AdStat.stat_date >= start_date,
            AdStat.stat_date <= end_date,
        )
        if shop_id:
            query = query.filter(AdCampaign.shop_id == shop_id)
        if platform:
            query = query.filter(AdStat.platform == platform)

        rows = query.order_by(AdStat.stat_date.desc()).all()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["日期", "平台", "活动名称", "展示", "点击", "花费(₽)", "订单", "收入(₽)", "CTR%", "CPC", "ACOS%", "ROAS"])

        for row in rows:
            impressions = int(row.impressions or 0)
            clicks = int(row.clicks or 0)
            spend = float(row.spend or 0)
            revenue = float(row.revenue or 0)
            ctr = round(clicks / impressions * 100, 2) if impressions > 0 else 0
            cpc = round(spend / clicks, 2) if clicks > 0 else 0
            acos = round(spend / revenue * 100, 2) if revenue > 0 else 0
            roas = round(revenue / spend, 2) if spend > 0 else 0

            platform_labels = {"wb": "Wildberries", "ozon": "Ozon", "yandex": "Yandex"}
            writer.writerow([
                row.stat_date.isoformat(),
                platform_labels.get(row.platform, row.platform),
                row.campaign_name,
                impressions, clicks, round(spend, 2),
                int(row.orders or 0), round(revenue, 2),
                ctr, cpc, acos, roas,
            ])

        return output.getvalue()
    except Exception as e:
        logger.error(f"导出统计数据失败: {e}")
        return ""


# ==================== ROI告警 ====================

def get_roi_alerts(db: Session, tenant_id: int, is_read: int = None,
                   page: int = 1, page_size: int = 20) -> dict:
    """获取ROI告警通知列表"""
    try:
        query = db.query(Notification).filter(
            Notification.tenant_id == tenant_id,
            Notification.notification_type == "roi_alert",
        )
        if is_read is not None:
            query = query.filter(Notification.is_read == is_read)

        total = query.count()
        items = query.order_by(Notification.created_at.desc()).offset(
            (page - 1) * page_size
        ).limit(page_size).all()

        return {"code": ErrorCode.SUCCESS, "data": {
            "items": [{
                "id": n.id,
                "title": n.title,
                "content": n.content,
                "is_read": n.is_read,
                "sent_at": n.sent_at.isoformat() if n.sent_at else None,
                "created_at": n.created_at.isoformat() if n.created_at else None,
            } for n in items],
            "total": total,
            "page": page,
            "page_size": page_size,
        }}
    except Exception as e:
        logger.error(f"获取ROI告警列表失败: {e}")
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "获取ROI告警列表失败"}


# ==================== 告警阈值配置 ====================

# 默认告警阈值（内存存储，也可存入数据库）
_alert_config = {
    "acos_warning": 30.0,
    "acos_critical": 50.0,
    "roas_warning": 2.0,
    "budget_usage_threshold": 0.8,
    "roas_critical_with_budget": 1.5,
}


def get_alert_config(tenant_id: int) -> dict:
    """获取告警阈值配置"""
    return {"code": ErrorCode.SUCCESS, "data": dict(_alert_config)}


def update_alert_config(tenant_id: int, data: dict) -> dict:
    """更新告警阈值配置"""
    try:
        for key, value in data.items():
            if value is not None and key in _alert_config:
                _alert_config[key] = value
        logger.info(f"告警阈值配置已更新: {_alert_config}")
        return {"code": ErrorCode.SUCCESS, "data": dict(_alert_config)}
    except Exception as e:
        logger.error(f"更新告警阈值配置失败: {e}")
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "更新告警阈值配置失败"}
