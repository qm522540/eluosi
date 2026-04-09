"""广告业务逻辑"""

import csv
import io
from datetime import date, datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func, case, desc

from app.models.ad import AdCampaign, AdGroup, AdKeyword, AdStat, AdAutomationRule
from app.models.notification import Notification
from app.utils.errors import ErrorCode
from app.utils.logger import logger


def list_campaigns(db: Session, tenant_id: int, shop_id: int = None,
                   platform: str = None, status: str = None,
                   page: int = 1, page_size: int = 20) -> dict:
    """获取广告活动列表（含近期统计：费用/展现/CTR）"""
    try:
        query = db.query(AdCampaign).filter(AdCampaign.tenant_id == tenant_id)
        if shop_id:
            query = query.filter(AdCampaign.shop_id == shop_id)
        if platform:
            query = query.filter(AdCampaign.platform == platform)
        if status:
            query = query.filter(AdCampaign.status == status)
        else:
            # 默认不显示已归档的活动
            query = query.filter(AdCampaign.status != "archived")

        total = query.count()
        # active排最前，其余按创建时间倒序
        status_order = case(
            (AdCampaign.status == "active", 0),
            (AdCampaign.status == "draft", 1),
            (AdCampaign.status == "paused", 2),
            (AdCampaign.status == "archived", 3),
            else_=4,
        )
        campaigns = query.order_by(status_order, AdCampaign.created_at.desc()).offset(
            (page - 1) * page_size
        ).limit(page_size).all()

        # 批量查询这些活动的累计统计数据
        campaign_ids = [c.id for c in campaigns]
        stats_map = {}
        if campaign_ids:
            stats_rows = db.query(
                AdStat.campaign_id,
                func.sum(AdStat.impressions).label("impressions"),
                func.sum(AdStat.clicks).label("clicks"),
                func.sum(AdStat.spend).label("spend"),
                func.sum(AdStat.orders).label("orders"),
                func.sum(AdStat.revenue).label("revenue"),
            ).filter(
                AdStat.campaign_id.in_(campaign_ids),
            ).group_by(AdStat.campaign_id).all()

            for row in stats_rows:
                imp = int(row.impressions or 0)
                clk = int(row.clicks or 0)
                spend = float(row.spend or 0)
                revenue = float(row.revenue or 0)
                stats_map[row.campaign_id] = {
                    "impressions": imp,
                    "clicks": clk,
                    "spend": round(spend, 2),
                    "orders": int(row.orders or 0),
                    "revenue": round(revenue, 2),
                    "ctr": round(clk / imp * 100, 2) if imp > 0 else 0,
                    "cpc": round(spend / clk, 2) if clk > 0 else 0,
                    "roas": round(revenue / spend, 2) if spend > 0 else 0,
                }

        items = []
        for c in campaigns:
            item = _campaign_to_dict(c)
            stats = stats_map.get(c.id, {})
            item["impressions"] = stats.get("impressions", 0)
            item["clicks"] = stats.get("clicks", 0)
            item["spend"] = stats.get("spend", 0)
            item["orders"] = stats.get("orders", 0)
            item["revenue"] = stats.get("revenue", 0)
            item["ctr"] = stats.get("ctr", 0)
            item["cpc"] = stats.get("cpc", 0)
            item["roas"] = stats.get("roas", 0)
            items.append(item)

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
        "daily_budget": float(c.daily_budget) if c.daily_budget is not None else None,
        "total_budget": float(c.total_budget) if c.total_budget is not None else None,
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


# ==================== 数据分析增强 ====================

def get_platform_comparison(db: Session, tenant_id: int, start_date: date,
                            end_date: date, shop_id: int = None) -> dict:
    """多平台对比分析"""
    try:
        query = db.query(
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
            campaign_ids = db.query(AdCampaign.id).filter(
                AdCampaign.shop_id == shop_id, AdCampaign.tenant_id == tenant_id
            ).subquery()
            query = query.filter(AdStat.campaign_id.in_(campaign_ids))

        rows = query.group_by(AdStat.platform).all()

        platforms = []
        for row in rows:
            imp = int(row.impressions or 0)
            clk = int(row.clicks or 0)
            spend = float(row.spend or 0)
            orders = int(row.orders or 0)
            revenue = float(row.revenue or 0)
            platforms.append({
                "platform": row.platform,
                "impressions": imp,
                "clicks": clk,
                "spend": round(spend, 2),
                "orders": orders,
                "revenue": round(revenue, 2),
                "ctr": round(clk / imp * 100, 2) if imp > 0 else 0,
                "cpc": round(spend / clk, 2) if clk > 0 else 0,
                "acos": round(spend / revenue * 100, 2) if revenue > 0 else 0,
                "roas": round(revenue / spend, 2) if spend > 0 else 0,
                "conversion_rate": round(orders / clk * 100, 2) if clk > 0 else 0,
            })

        return {"code": ErrorCode.SUCCESS, "data": platforms}
    except Exception as e:
        logger.error(f"平台对比分析失败: {e}")
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "平台对比分析失败"}


def get_campaign_ranking(db: Session, tenant_id: int, start_date: date,
                         end_date: date, sort_by: str = "spend",
                         limit: int = 10, shop_id: int = None,
                         platform: str = None) -> dict:
    """广告活动TOP排名"""
    try:
        query = db.query(
            AdStat.campaign_id,
            AdCampaign.name,
            AdCampaign.platform,
            AdCampaign.status,
            func.sum(AdStat.impressions).label("impressions"),
            func.sum(AdStat.clicks).label("clicks"),
            func.sum(AdStat.spend).label("spend"),
            func.sum(AdStat.orders).label("orders"),
            func.sum(AdStat.revenue).label("revenue"),
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

        query = query.group_by(AdStat.campaign_id, AdCampaign.name,
                               AdCampaign.platform, AdCampaign.status)

        sort_col = {
            "spend": func.sum(AdStat.spend),
            "revenue": func.sum(AdStat.revenue),
            "clicks": func.sum(AdStat.clicks),
            "impressions": func.sum(AdStat.impressions),
            "orders": func.sum(AdStat.orders),
        }.get(sort_by, func.sum(AdStat.spend))

        rows = query.order_by(desc(sort_col)).limit(limit).all()

        items = []
        for row in rows:
            imp = int(row.impressions or 0)
            clk = int(row.clicks or 0)
            spend = float(row.spend or 0)
            orders = int(row.orders or 0)
            revenue = float(row.revenue or 0)
            items.append({
                "campaign_id": row.campaign_id,
                "name": row.name,
                "platform": row.platform,
                "status": row.status,
                "impressions": imp,
                "clicks": clk,
                "spend": round(spend, 2),
                "orders": orders,
                "revenue": round(revenue, 2),
                "ctr": round(clk / imp * 100, 2) if imp > 0 else 0,
                "acos": round(spend / revenue * 100, 2) if revenue > 0 else 0,
                "roas": round(revenue / spend, 2) if spend > 0 else 0,
            })

        return {"code": ErrorCode.SUCCESS, "data": items}
    except Exception as e:
        logger.error(f"活动排名分析失败: {e}")
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "活动排名分析失败"}


def get_product_roi(db: Session, tenant_id: int, start_date: date,
                    end_date: date, shop_id: int = None,
                    platform: str = None) -> dict:
    """商品级ROI分析（通过广告组关联的listing_id）"""
    try:
        query = db.query(
            AdGroup.listing_id,
            AdGroup.name.label("group_name"),
            AdCampaign.platform,
            func.sum(AdStat.impressions).label("impressions"),
            func.sum(AdStat.clicks).label("clicks"),
            func.sum(AdStat.spend).label("spend"),
            func.sum(AdStat.orders).label("orders"),
            func.sum(AdStat.revenue).label("revenue"),
        ).join(
            AdCampaign, AdStat.campaign_id == AdCampaign.id
        ).outerjoin(
            AdGroup, (AdStat.ad_group_id == AdGroup.id)
        ).filter(
            AdStat.tenant_id == tenant_id,
            AdStat.stat_date >= start_date,
            AdStat.stat_date <= end_date,
        )
        if shop_id:
            query = query.filter(AdCampaign.shop_id == shop_id)
        if platform:
            query = query.filter(AdStat.platform == platform)

        rows = query.group_by(
            AdGroup.listing_id, AdGroup.name, AdCampaign.platform
        ).order_by(desc(func.sum(AdStat.spend))).limit(50).all()

        items = []
        for row in rows:
            spend = float(row.spend or 0)
            revenue = float(row.revenue or 0)
            clk = int(row.clicks or 0)
            orders = int(row.orders or 0)
            items.append({
                "listing_id": row.listing_id,
                "group_name": row.group_name or f"商品-{row.listing_id}",
                "platform": row.platform,
                "impressions": int(row.impressions or 0),
                "clicks": clk,
                "spend": round(spend, 2),
                "orders": orders,
                "revenue": round(revenue, 2),
                "roas": round(revenue / spend, 2) if spend > 0 else 0,
                "acos": round(spend / revenue * 100, 2) if revenue > 0 else 0,
                "cpa": round(spend / orders, 2) if orders > 0 else 0,
            })

        return {"code": ErrorCode.SUCCESS, "data": items}
    except Exception as e:
        logger.error(f"商品ROI分析失败: {e}")
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "商品ROI分析失败"}


# ==================== 自动化规则引擎 ====================

def list_automation_rules(db: Session, tenant_id: int, rule_type: str = None,
                          enabled: int = None) -> dict:
    """获取自动化规则列表"""
    try:
        query = db.query(AdAutomationRule).filter(
            AdAutomationRule.tenant_id == tenant_id
        )
        if rule_type:
            query = query.filter(AdAutomationRule.rule_type == rule_type)
        if enabled is not None:
            query = query.filter(AdAutomationRule.enabled == enabled)

        rules = query.order_by(AdAutomationRule.created_at.desc()).all()
        return {"code": ErrorCode.SUCCESS, "data": [_rule_to_dict(r) for r in rules]}
    except Exception as e:
        logger.error(f"获取自动化规则列表失败: {e}")
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "获取自动化规则列表失败"}


def create_automation_rule(db: Session, tenant_id: int, data: dict) -> dict:
    """创建自动化规则"""
    try:
        rule = AdAutomationRule(
            tenant_id=tenant_id,
            name=data["name"],
            rule_type=data["rule_type"],
            conditions=data.get("conditions"),
            actions=data.get("actions"),
            platform=data.get("platform"),
            campaign_id=data.get("campaign_id"),
            shop_id=data.get("shop_id"),
            enabled=data.get("enabled", 1),
        )
        db.add(rule)
        db.commit()
        db.refresh(rule)
        logger.info(f"自动化规则创建成功: id={rule.id}, name={rule.name}")
        return {"code": ErrorCode.SUCCESS, "data": _rule_to_dict(rule)}
    except Exception as e:
        db.rollback()
        logger.error(f"创建自动化规则失败: {e}")
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "创建自动化规则失败"}


def update_automation_rule(db: Session, rule_id: int, tenant_id: int, data: dict) -> dict:
    """更新自动化规则"""
    try:
        rule = db.query(AdAutomationRule).filter(
            AdAutomationRule.id == rule_id, AdAutomationRule.tenant_id == tenant_id
        ).first()
        if not rule:
            return {"code": ErrorCode.AD_RULE_NOT_FOUND, "msg": "自动化规则不存在"}

        for key, value in data.items():
            if value is not None:
                setattr(rule, key, value)
        db.commit()
        db.refresh(rule)
        return {"code": ErrorCode.SUCCESS, "data": _rule_to_dict(rule)}
    except Exception as e:
        db.rollback()
        logger.error(f"更新自动化规则失败: {e}")
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "更新自动化规则失败"}


def delete_automation_rule(db: Session, rule_id: int, tenant_id: int) -> dict:
    """删除自动化规则"""
    try:
        rule = db.query(AdAutomationRule).filter(
            AdAutomationRule.id == rule_id, AdAutomationRule.tenant_id == tenant_id
        ).first()
        if not rule:
            return {"code": ErrorCode.AD_RULE_NOT_FOUND, "msg": "自动化规则不存在"}

        db.delete(rule)
        db.commit()
        logger.info(f"自动化规则删除成功: rule_id={rule_id}")
        return {"code": ErrorCode.SUCCESS, "data": None}
    except Exception as e:
        db.rollback()
        logger.error(f"删除自动化规则失败: {e}")
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "删除自动化规则失败"}


def execute_automation_rules(db: Session, tenant_id: int) -> dict:
    """执行所有启用的自动化规则"""
    try:
        rules = db.query(AdAutomationRule).filter(
            AdAutomationRule.tenant_id == tenant_id,
            AdAutomationRule.enabled == 1,
        ).all()

        results = []
        today = date.today()
        week_ago = today - timedelta(days=7)

        for rule in rules:
            try:
                triggered = _execute_single_rule(db, tenant_id, rule, week_ago, today)
                results.append({
                    "rule_id": rule.id,
                    "name": rule.name,
                    "triggered": triggered,
                })
            except Exception as e:
                logger.warning(f"规则 {rule.id} 执行失败: {e}")
                results.append({
                    "rule_id": rule.id,
                    "name": rule.name,
                    "triggered": False,
                    "error": str(e),
                })

        return {"code": ErrorCode.SUCCESS, "data": {
            "rules_checked": len(rules),
            "results": results,
        }}
    except Exception as e:
        logger.error(f"执行自动化规则失败: {e}")
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "执行自动化规则失败"}


def _execute_single_rule(db: Session, tenant_id: int, rule: AdAutomationRule,
                         start_date: date, end_date: date) -> bool:
    """执行单条规则，返回是否触发了动作"""
    conditions = rule.conditions or {}
    actions = rule.actions or {}

    # 构建活动查询范围
    query = db.query(AdCampaign).filter(
        AdCampaign.tenant_id == tenant_id,
        AdCampaign.status == "active",
    )
    if rule.platform:
        query = query.filter(AdCampaign.platform == rule.platform)
    if rule.campaign_id:
        query = query.filter(AdCampaign.id == rule.campaign_id)
    if rule.shop_id:
        query = query.filter(AdCampaign.shop_id == rule.shop_id)

    campaigns = query.all()
    triggered = False

    for campaign in campaigns:
        # 获取近期统计
        stats = db.query(
            func.sum(AdStat.spend).label("spend"),
            func.sum(AdStat.revenue).label("revenue"),
            func.sum(AdStat.clicks).label("clicks"),
            func.sum(AdStat.orders).label("orders"),
        ).filter(
            AdStat.campaign_id == campaign.id,
            AdStat.stat_date >= start_date,
            AdStat.stat_date <= end_date,
        ).first()

        spend = float(stats.spend or 0)
        revenue = float(stats.revenue or 0)
        roas = revenue / spend if spend > 0 else 0

        if rule.rule_type == "pause_low_roi":
            min_roas = conditions.get("min_roas", 1.0)
            min_spend = conditions.get("min_spend", 100)
            if spend >= min_spend and roas < min_roas:
                campaign.status = "paused"
                triggered = True
                logger.info(f"规则[{rule.name}] 暂停活动 {campaign.id}，ROAS={roas:.2f}<{min_roas}")

        elif rule.rule_type == "auto_bid":
            # 分时调价模式：根据当前时段调整出价比例
            peak_hours = conditions.get("peak_hours", [19, 20, 21])
            peak_pct = conditions.get("peak_pct", 30)
            sub_peak_hours = conditions.get("sub_peak_hours", [22])
            sub_peak_pct = conditions.get("sub_peak_pct", 20)
            off_peak_hours = conditions.get("off_peak_hours", [2, 3, 4, 5, 6])
            off_peak_pct = conditions.get("off_peak_pct", -50)

            # 确定当前时段的调价比例（莫斯科时间）
            from pytz import timezone as pytz_tz
            moscow_hour = datetime.now(pytz_tz("Europe/Moscow")).hour

            if moscow_hour in peak_hours:
                adjust_pct = peak_pct
            elif moscow_hour in sub_peak_hours:
                adjust_pct = sub_peak_pct
            elif moscow_hour in off_peak_hours:
                adjust_pct = off_peak_pct
            else:
                adjust_pct = 0  # 平峰：原价

            # 获取或初始化原始出价记录
            original_bids = (actions.get("original_bids") or {}).get(str(campaign.id), {})

            groups = db.query(AdGroup).filter(
                AdGroup.campaign_id == campaign.id,
                AdGroup.tenant_id == tenant_id,
                AdGroup.status == "active",
            ).all()
            for group in groups:
                if not group.bid or float(group.bid) <= 0:
                    continue
                gid = str(group.id)
                # 首次运行：记录原始出价
                if gid not in original_bids:
                    original_bids[gid] = float(group.bid)
                base_bid = original_bids[gid]
                new_bid = round(base_bid * (1 + adjust_pct / 100), 2)
                new_bid = max(new_bid, 0.01)
                if abs(float(group.bid) - new_bid) > 0.001:
                    group.bid = new_bid
                    triggered = True

            # 保存原始出价到 actions
            if not actions.get("original_bids"):
                actions["original_bids"] = {}
            actions["original_bids"][str(campaign.id)] = original_bids
            rule.actions = actions

        elif rule.rule_type == "budget_cap":
            daily_limit = conditions.get("max_daily_spend", 0)
            # 检查今天的花费
            today_spend_row = db.query(
                func.sum(AdStat.spend).label("spend")
            ).filter(
                AdStat.campaign_id == campaign.id,
                AdStat.stat_date == end_date,
            ).first()
            today_spend = float(today_spend_row.spend or 0) if today_spend_row else 0
            if daily_limit > 0 and today_spend >= daily_limit:
                campaign.status = "paused"
                triggered = True
                logger.info(f"规则[{rule.name}] 预算到达上限，暂停活动 {campaign.id}")

        elif rule.rule_type == "schedule":
            active_hours = conditions.get("active_hours", [])
            current_hour = datetime.now().hour
            should_be_active = current_hour in active_hours if active_hours else True
            if should_be_active and campaign.status == "paused":
                campaign.status = "active"
                triggered = True
            elif not should_be_active and campaign.status == "active":
                campaign.status = "paused"
                triggered = True

    if triggered:
        rule.last_triggered_at = datetime.utcnow()
        rule.trigger_count += 1
        db.commit()

    return triggered


def _rule_to_dict(r: AdAutomationRule) -> dict:
    return {
        "id": r.id,
        "tenant_id": r.tenant_id,
        "name": r.name,
        "rule_type": r.rule_type,
        "conditions": r.conditions,
        "actions": r.actions,
        "platform": r.platform,
        "campaign_id": r.campaign_id,
        "shop_id": r.shop_id,
        "enabled": r.enabled,
        "last_triggered_at": r.last_triggered_at.isoformat() if r.last_triggered_at else None,
        "trigger_count": r.trigger_count,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


# ==================== 预算管理 ====================

def get_budget_overview(db: Session, tenant_id: int, shop_id: int = None,
                        platform: str = None) -> dict:
    """预算消耗概览"""
    try:
        today = date.today()
        month_start = today.replace(day=1)

        # 查询活跃活动
        camp_query = db.query(AdCampaign).filter(
            AdCampaign.tenant_id == tenant_id,
            AdCampaign.status.in_(["active", "paused"]),
        )
        if shop_id:
            camp_query = camp_query.filter(AdCampaign.shop_id == shop_id)
        if platform:
            camp_query = camp_query.filter(AdCampaign.platform == platform)
        campaigns = camp_query.all()

        if not campaigns:
            return {"code": ErrorCode.SUCCESS, "data": {
                "campaigns": [],
                "summary": {"total_daily_budget": 0, "total_monthly_budget": 0,
                             "today_spend": 0, "month_spend": 0, "budget_usage_pct": 0},
            }}

        campaign_ids = [c.id for c in campaigns]
        campaign_map = {c.id: c for c in campaigns}

        # 今日花费
        today_stats = db.query(
            AdStat.campaign_id,
            func.sum(AdStat.spend).label("spend"),
        ).filter(
            AdStat.campaign_id.in_(campaign_ids),
            AdStat.stat_date == today,
        ).group_by(AdStat.campaign_id).all()
        today_spend_map = {row.campaign_id: float(row.spend or 0) for row in today_stats}

        # 本月花费
        month_stats = db.query(
            AdStat.campaign_id,
            func.sum(AdStat.spend).label("spend"),
        ).filter(
            AdStat.campaign_id.in_(campaign_ids),
            AdStat.stat_date >= month_start,
            AdStat.stat_date <= today,
        ).group_by(AdStat.campaign_id).all()
        month_spend_map = {row.campaign_id: float(row.spend or 0) for row in month_stats}

        # 近7天平均日消耗
        week_ago = today - timedelta(days=7)
        week_stats = db.query(
            AdStat.campaign_id,
            func.sum(AdStat.spend).label("spend"),
        ).filter(
            AdStat.campaign_id.in_(campaign_ids),
            AdStat.stat_date >= week_ago,
            AdStat.stat_date <= today,
        ).group_by(AdStat.campaign_id).all()
        week_spend_map = {row.campaign_id: float(row.spend or 0) for row in week_stats}

        items = []
        total_daily_budget = 0
        total_today_spend = 0
        total_month_spend = 0

        for c in campaigns:
            daily_budget = float(c.daily_budget) if c.daily_budget else 0
            total_budget = float(c.total_budget) if c.total_budget else 0
            today_sp = today_spend_map.get(c.id, 0)
            month_sp = month_spend_map.get(c.id, 0)
            week_sp = week_spend_map.get(c.id, 0)
            avg_daily = round(week_sp / 7, 2) if week_sp > 0 else 0

            budget_usage_pct = round(today_sp / daily_budget * 100, 1) if daily_budget > 0 else 0
            days_remaining = None
            if avg_daily > 0 and total_budget > 0:
                remaining = total_budget - month_sp
                days_remaining = max(0, int(remaining / avg_daily))

            items.append({
                "campaign_id": c.id,
                "name": c.name,
                "platform": c.platform,
                "status": c.status,
                "daily_budget": daily_budget,
                "total_budget": total_budget,
                "today_spend": round(today_sp, 2),
                "month_spend": round(month_sp, 2),
                "avg_daily_spend": avg_daily,
                "budget_usage_pct": budget_usage_pct,
                "days_remaining": days_remaining,
            })

            total_daily_budget += daily_budget
            total_today_spend += today_sp
            total_month_spend += month_sp

        # 预警：超过80%日预算的活动
        alerts = []
        for item in items:
            if item["daily_budget"] > 0 and item["budget_usage_pct"] >= 80:
                level = "critical" if item["budget_usage_pct"] >= 100 else "warning"
                alerts.append({
                    "campaign_id": item["campaign_id"],
                    "name": item["name"],
                    "level": level,
                    "message": f"日预算已使用{item['budget_usage_pct']}%",
                    "today_spend": item["today_spend"],
                    "daily_budget": item["daily_budget"],
                })

        total_budget_usage = round(total_today_spend / total_daily_budget * 100, 1) if total_daily_budget > 0 else 0

        return {"code": ErrorCode.SUCCESS, "data": {
            "campaigns": sorted(items, key=lambda x: x["today_spend"], reverse=True),
            "alerts": alerts,
            "summary": {
                "total_daily_budget": round(total_daily_budget, 2),
                "total_today_spend": round(total_today_spend, 2),
                "total_month_spend": round(total_month_spend, 2),
                "budget_usage_pct": total_budget_usage,
                "active_campaigns": len([c for c in campaigns if c.status == "active"]),
                "total_campaigns": len(campaigns),
            },
        }}
    except Exception as e:
        logger.error(f"获取预算概览失败: {e}")
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "获取预算概览失败"}


def get_budget_suggestions(db: Session, tenant_id: int, shop_id: int = None,
                           platform: str = None) -> dict:
    """预算分配优化建议"""
    try:
        today = date.today()
        week_ago = today - timedelta(days=7)

        camp_query = db.query(AdCampaign).filter(
            AdCampaign.tenant_id == tenant_id,
            AdCampaign.status == "active",
        )
        if shop_id:
            camp_query = camp_query.filter(AdCampaign.shop_id == shop_id)
        if platform:
            camp_query = camp_query.filter(AdCampaign.platform == platform)
        campaigns = camp_query.all()

        if not campaigns:
            return {"code": ErrorCode.SUCCESS, "data": []}

        campaign_ids = [c.id for c in campaigns]
        campaign_map = {c.id: c for c in campaigns}

        # 近7天统计
        stats = db.query(
            AdStat.campaign_id,
            func.sum(AdStat.spend).label("spend"),
            func.sum(AdStat.revenue).label("revenue"),
            func.sum(AdStat.orders).label("orders"),
        ).filter(
            AdStat.campaign_id.in_(campaign_ids),
            AdStat.stat_date >= week_ago,
            AdStat.stat_date <= today,
        ).group_by(AdStat.campaign_id).all()

        suggestions = []
        for row in stats:
            c = campaign_map.get(row.campaign_id)
            if not c:
                continue
            spend = float(row.spend or 0)
            revenue = float(row.revenue or 0)
            roas = revenue / spend if spend > 0 else 0
            daily_budget = float(c.daily_budget) if c.daily_budget else 0
            avg_daily = round(spend / 7, 2)

            suggestion = {
                "campaign_id": c.id,
                "name": c.name,
                "platform": c.platform,
                "current_daily_budget": daily_budget,
                "avg_daily_spend": avg_daily,
                "roas_7d": round(roas, 2),
                "revenue_7d": round(revenue, 2),
                "spend_7d": round(spend, 2),
            }

            # 高ROAS活动建议加预算
            if roas >= 3.0 and daily_budget > 0:
                suggested = round(daily_budget * 1.3, 2)
                suggestion["action"] = "increase"
                suggestion["suggested_budget"] = suggested
                suggestion["reason"] = f"ROAS {roas:.1f}x 表现优秀，建议增加30%预算获取更多流量"
            # 低ROAS活动建议降预算
            elif roas < 1.0 and spend > 200:
                suggested = round(max(daily_budget * 0.5, 100), 2)
                suggestion["action"] = "decrease"
                suggestion["suggested_budget"] = suggested
                suggestion["reason"] = f"ROAS {roas:.1f}x 亏损，建议降低预算或优化后再投"
            # 预算使用率很低
            elif daily_budget > 0 and avg_daily < daily_budget * 0.3:
                suggestion["action"] = "decrease"
                suggestion["suggested_budget"] = round(max(avg_daily * 1.5, 100), 2)
                suggestion["reason"] = f"实际消耗仅为预算的{avg_daily/daily_budget*100:.0f}%，建议降低预算"
            else:
                suggestion["action"] = "keep"
                suggestion["suggested_budget"] = daily_budget
                suggestion["reason"] = "当前预算分配合理"

            suggestions.append(suggestion)

        suggestions.sort(key=lambda x: x["roas_7d"], reverse=True)
        return {"code": ErrorCode.SUCCESS, "data": suggestions}
    except Exception as e:
        logger.error(f"获取预算建议失败: {e}")
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "获取预算建议失败"}
