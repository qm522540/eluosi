"""财务业务逻辑"""

from datetime import date, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.finance import FinanceCost, FinanceRevenue, FinanceRoiSnapshot
from app.models.ad import AdCampaign
from app.models.shop import Shop
from app.models.product import Product
from app.utils.errors import ErrorCode
from app.utils.logger import logger
from app.utils.moscow_time import moscow_today


def get_revenue_list(db: Session, tenant_id: int, start_date: date, end_date: date,
                     shop_id: int = None, page: int = 1, page_size: int = 20) -> dict:
    """获取收入明细"""
    try:
        query = db.query(FinanceRevenue).filter(
            FinanceRevenue.tenant_id == tenant_id,
            FinanceRevenue.revenue_date >= start_date,
            FinanceRevenue.revenue_date <= end_date,
        )
        if shop_id:
            query = query.filter(FinanceRevenue.shop_id == shop_id)

        total = query.count()
        items = query.order_by(FinanceRevenue.revenue_date.desc()).offset(
            (page - 1) * page_size
        ).limit(page_size).all()

        return {
            "code": ErrorCode.SUCCESS,
            "data": {
                "items": [_revenue_to_dict(r) for r in items],
                "total": total,
                "page": page,
                "page_size": page_size,
                "pages": (total + page_size - 1) // page_size,
            },
        }
    except Exception as e:
        logger.error(f"获取收入明细失败 tenant_id={tenant_id}: {e}")
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "获取收入明细失败"}


def get_cost_list(db: Session, tenant_id: int, start_date: date, end_date: date,
                  shop_id: int = None, cost_type: str = None,
                  page: int = 1, page_size: int = 20) -> dict:
    """获取费用明细"""
    try:
        query = db.query(FinanceCost).filter(
            FinanceCost.tenant_id == tenant_id,
            FinanceCost.cost_date >= start_date,
            FinanceCost.cost_date <= end_date,
        )
        if shop_id:
            query = query.filter(FinanceCost.shop_id == shop_id)
        if cost_type:
            query = query.filter(FinanceCost.cost_type == cost_type)

        total = query.count()
        items = query.order_by(FinanceCost.cost_date.desc()).offset(
            (page - 1) * page_size
        ).limit(page_size).all()

        return {
            "code": ErrorCode.SUCCESS,
            "data": {
                "items": [_cost_to_dict(c) for c in items],
                "total": total,
                "page": page,
                "page_size": page_size,
                "pages": (total + page_size - 1) // page_size,
            },
        }
    except Exception as e:
        logger.error(f"获取费用明细失败 tenant_id={tenant_id}: {e}")
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "获取费用明细失败"}


def create_cost(db: Session, tenant_id: int, data: dict) -> dict:
    """手动录入费用"""
    try:
        cost = FinanceCost(tenant_id=tenant_id, **data)
        db.add(cost)
        db.commit()
        db.refresh(cost)

        logger.info(f"费用录入成功: cost_id={cost.id} type={cost.cost_type}")
        return {"code": ErrorCode.SUCCESS, "data": _cost_to_dict(cost)}
    except Exception as e:
        db.rollback()
        logger.error(f"录入费用失败 tenant_id={tenant_id}: {e}")
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "录入费用失败"}


def get_roi_snapshots(db: Session, tenant_id: int, start_date: date, end_date: date,
                      shop_id: int = None, period: str = "daily") -> dict:
    """获取ROI快照列表（趋势图数据）"""
    try:
        query = db.query(FinanceRoiSnapshot).filter(
            FinanceRoiSnapshot.tenant_id == tenant_id,
            FinanceRoiSnapshot.snapshot_date >= start_date,
            FinanceRoiSnapshot.snapshot_date <= end_date,
            FinanceRoiSnapshot.period == period,
        )
        if shop_id:
            query = query.filter(FinanceRoiSnapshot.shop_id == shop_id)

        snapshots = query.order_by(FinanceRoiSnapshot.snapshot_date.asc()).all()

        items = [{
            "shop_id": s.shop_id,
            "snapshot_date": s.snapshot_date.isoformat(),
            "period": s.period,
            "total_revenue": float(s.total_revenue),
            "total_cost": float(s.total_cost),
            "ad_spend": float(s.ad_spend),
            "gross_profit": float(s.gross_profit),
            "roi": float(s.roi) if s.roi else None,
            "roas": float(s.roas) if s.roas else None,
        } for s in snapshots]

        return {"code": ErrorCode.SUCCESS, "data": items}
    except Exception as e:
        logger.error(f"获取ROI快照失败 tenant_id={tenant_id}: {e}")
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "获取ROI快照失败"}


def get_finance_summary(db: Session, tenant_id: int, start_date: date, end_date: date,
                        shop_id: int = None) -> dict:
    """获取财务汇总（收入/成本/利润/ROI）"""
    try:
        # 汇总收入
        rev_query = db.query(
            func.sum(FinanceRevenue.revenue).label("revenue"),
            func.sum(FinanceRevenue.net_revenue).label("net_revenue"),
            func.sum(FinanceRevenue.orders_count).label("orders"),
            func.sum(FinanceRevenue.returns_count).label("returns"),
        ).filter(
            FinanceRevenue.tenant_id == tenant_id,
            FinanceRevenue.revenue_date >= start_date,
            FinanceRevenue.revenue_date <= end_date,
        )
        if shop_id:
            rev_query = rev_query.filter(FinanceRevenue.shop_id == shop_id)
        rev = rev_query.one()

        # 汇总成本（按类型）
        cost_query = db.query(
            FinanceCost.cost_type,
            func.sum(FinanceCost.amount).label("amount"),
        ).filter(
            FinanceCost.tenant_id == tenant_id,
            FinanceCost.cost_date >= start_date,
            FinanceCost.cost_date <= end_date,
        )
        if shop_id:
            cost_query = cost_query.filter(FinanceCost.shop_id == shop_id)
        cost_rows = cost_query.group_by(FinanceCost.cost_type).all()

        cost_breakdown = {}
        total_cost = 0
        for row in cost_rows:
            amount = float(row.amount or 0)
            cost_breakdown[row.cost_type] = round(amount, 2)
            total_cost += amount

        total_revenue = float(rev.revenue or 0)
        net_revenue = float(rev.net_revenue or 0)
        gross_profit = net_revenue - total_cost

        summary = {
            "total_revenue": round(total_revenue, 2),
            "net_revenue": round(net_revenue, 2),
            "total_orders": int(rev.orders or 0),
            "total_returns": int(rev.returns or 0),
            "total_cost": round(total_cost, 2),
            "cost_breakdown": cost_breakdown,
            "gross_profit": round(gross_profit, 2),
            "roi": round(gross_profit / total_cost * 100, 2) if total_cost > 0 else None,
            "roas": round(total_revenue / cost_breakdown.get("ad_spend", 0), 4) if cost_breakdown.get("ad_spend", 0) > 0 else None,
        }

        return {"code": ErrorCode.SUCCESS, "data": summary}
    except Exception as e:
        logger.error(f"获取财务汇总失败 tenant_id={tenant_id}: {e}")
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "获取财务汇总失败"}


def get_dashboard_overview(db: Session, tenant_id: int) -> dict:
    """首页大盘统计数据"""
    try:
        today = moscow_today()

        # 店铺数量
        shop_count = db.query(Shop).filter(
            Shop.tenant_id == tenant_id,
            Shop.status == "active",
        ).count()

        # 商品数量
        product_count = db.query(Product).filter(
            Product.tenant_id == tenant_id,
            Product.status == "active",
        ).count()

        # 活跃广告活动数
        active_campaigns = db.query(AdCampaign).filter(
            AdCampaign.tenant_id == tenant_id,
            AdCampaign.status == "active",
        ).count()

        # 今日收入
        rev_row = db.query(
            func.sum(FinanceRevenue.net_revenue).label("net_revenue"),
        ).filter(
            FinanceRevenue.tenant_id == tenant_id,
            FinanceRevenue.revenue_date == today,
        ).one()
        today_revenue = float(rev_row.net_revenue or 0)

        # 今日广告花费
        cost_row = db.query(
            func.sum(FinanceCost.amount).label("amount"),
        ).filter(
            FinanceCost.tenant_id == tenant_id,
            FinanceCost.cost_date == today,
            FinanceCost.cost_type == "ad_spend",
        ).one()
        today_spend = float(cost_row.amount or 0)

        today_roi = None
        if today_spend > 0:
            today_roi = round(today_revenue / today_spend, 4)

        overview = {
            "shop_count": shop_count,
            "product_count": product_count,
            "active_campaigns": active_campaigns,
            "today_revenue": round(today_revenue, 2),
            "today_spend": round(today_spend, 2),
            "today_roi": today_roi,
        }

        return {"code": ErrorCode.SUCCESS, "data": overview}
    except Exception as e:
        logger.error(f"获取大盘数据失败 tenant_id={tenant_id}: {e}")
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "获取大盘数据失败"}


# ==================== 辅助函数 ====================

def _revenue_to_dict(r: FinanceRevenue) -> dict:
    return {
        "id": r.id,
        "shop_id": r.shop_id,
        "listing_id": r.listing_id,
        "revenue_date": r.revenue_date.isoformat(),
        "orders_count": r.orders_count,
        "revenue": float(r.revenue),
        "returns_count": r.returns_count,
        "returns_amount": float(r.returns_amount),
        "net_revenue": float(r.net_revenue),
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


def _cost_to_dict(c: FinanceCost) -> dict:
    return {
        "id": c.id,
        "shop_id": c.shop_id,
        "listing_id": c.listing_id,
        "cost_date": c.cost_date.isoformat(),
        "cost_type": c.cost_type,
        "amount": float(c.amount),
        "currency": c.currency,
        "notes": c.notes,
        "created_at": c.created_at.isoformat() if c.created_at else None,
    }
