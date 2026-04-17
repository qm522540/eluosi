"""地区销售分析查询"""

from datetime import date, timedelta
from typing import Optional
from decimal import Decimal
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.utils.errors import ErrorCode


def _default_dates(date_from, date_to):
    if not date_to:
        date_to = (date.today() - timedelta(days=1)).isoformat()
    if not date_from:
        date_from = (date.fromisoformat(date_to) - timedelta(days=6)).isoformat()
    return date_from, date_to


def _f(v):
    return float(v) if v is not None else 0


# 俄罗斯主要地区中文名缓存
_RU_REGIONS_ZH = {
    "Москва": "莫斯科", "Московская область": "莫斯科州",
    "Санкт-Петербург": "圣彼得堡", "Ленинградская область": "列宁格勒州",
    "Краснодарский край": "克拉斯诺达尔边疆区", "Свердловская область": "斯维尔德洛夫斯克州",
    "Новосибирская область": "新西伯利亚州", "Ростовская область": "罗斯托夫州",
    "Татарстан": "鞑靼斯坦", "Нижегородская область": "下诺夫哥罗德州",
    "Челябинская область": "车里雅宾斯克州", "Самарская область": "萨马拉州",
    "Башкортостан": "巴什科尔托斯坦", "Красноярский край": "克拉斯诺亚尔斯克边疆区",
    "Пермский край": "彼尔姆边疆区", "Воронежская область": "沃罗涅日州",
    "Волгоградская область": "伏尔加格勒州", "Тюменская область": "秋明州",
    "Омская область": "鄂木斯克州", "Саратовская область": "萨拉托夫州",
    "Иркутская область": "伊尔库茨克州", "Хабаровский край": "哈巴罗夫斯克边疆区",
    "Приморский край": "滨海边疆区", "Беларусь": "白俄罗斯", "Казахстан": "哈萨克斯坦",
    "Кыргызстан": "吉尔吉斯斯坦", "Узбекистан": "乌兹别克斯坦", "Армения": "亚美尼亚",
    "Брестская область": "布列斯特州", "Минская область": "明斯克州",
}


def ranking(db: Session, tenant_id: int, shop_id: int,
            date_from=None, date_to=None, sort_by="revenue", limit=50) -> dict:
    date_from, date_to = _default_dates(date_from, date_to)
    params = {"tid": tenant_id, "sid": shop_id, "df": date_from, "dt": date_to}

    totals_row = db.execute(text("""
        SELECT COUNT(DISTINCT region_name) regions, SUM(orders) ord, SUM(revenue) rev
        FROM region_daily_stats WHERE tenant_id=:tid AND shop_id=:sid AND stat_date BETWEEN :df AND :dt
    """), params).fetchone()
    total_orders = int(totals_row.ord or 0)
    total_revenue = _f(totals_row.rev)

    allowed = {"revenue", "orders", "avg_price", "returns"}
    sort_col = sort_by if sort_by in allowed else "revenue"
    if sort_col == "avg_price":
        order_expr = "ROUND(SUM(revenue)/NULLIF(SUM(orders),0),2) DESC"
    else:
        order_expr = f"SUM({sort_col}) DESC"

    rows = db.execute(text(f"""
        SELECT region_name, SUM(orders) ord, SUM(revenue) rev, SUM(returns) ret
        FROM region_daily_stats
        WHERE tenant_id=:tid AND shop_id=:sid AND stat_date BETWEEN :df AND :dt
        GROUP BY region_name ORDER BY {order_expr} LIMIT :lim
    """), {**params, "lim": min(limit, 200)}).fetchall()

    items = []
    for r in rows:
        ord_val = int(r.ord or 0)
        rev_val = _f(r.rev)
        ret_val = int(r.ret or 0)
        items.append({
            "region_name": r.region_name,
            "region_name_zh": _RU_REGIONS_ZH.get(r.region_name, ""),
            "orders": ord_val,
            "revenue": rev_val,
            "avg_price": round(rev_val / ord_val, 2) if ord_val > 0 else 0,
            "returns": ret_val,
            "return_rate": round(ret_val / ord_val * 100, 1) if ord_val > 0 else 0,
            "orders_pct": round(ord_val / total_orders * 100, 1) if total_orders > 0 else 0,
            "revenue_pct": round(rev_val / total_revenue * 100, 1) if total_revenue > 0 else 0,
        })

    return {"code": 0, "data": {
        "date_from": date_from, "date_to": date_to,
        "totals": {
            "regions": int(totals_row.regions or 0),
            "orders": total_orders,
            "revenue": total_revenue,
            "avg_price": round(total_revenue / total_orders, 2) if total_orders > 0 else 0,
        },
        "items": items,
    }}


def trend(db: Session, tenant_id: int, shop_id: int,
          date_from=None, date_to=None, top=5, metric="orders") -> dict:
    date_from, date_to = _default_dates(date_from, date_to)
    col = metric if metric in {"orders", "revenue"} else "orders"
    params = {"tid": tenant_id, "sid": shop_id, "df": date_from, "dt": date_to, "top": min(top, 20)}

    top_regions = [r.region_name for r in db.execute(text(f"""
        SELECT region_name FROM region_daily_stats
        WHERE tenant_id=:tid AND shop_id=:sid AND stat_date BETWEEN :df AND :dt
        GROUP BY region_name ORDER BY SUM({col}) DESC LIMIT :top
    """), params).fetchall()]

    if not top_regions:
        return {"code": 0, "data": {"dates": [], "series": []}}

    d = date.fromisoformat(date_from)
    d_end = date.fromisoformat(date_to)
    dates = []
    while d <= d_end:
        dates.append(d.isoformat())
        d += timedelta(days=1)

    series = []
    for rn in top_regions:
        rows = db.execute(text(f"""
            SELECT stat_date, SUM({col}) val FROM region_daily_stats
            WHERE tenant_id=:tid AND shop_id=:sid AND region_name=:rn AND stat_date BETWEEN :df AND :dt
            GROUP BY stat_date
        """), {"tid": tenant_id, "sid": shop_id, "rn": rn, "df": date_from, "dt": date_to}).fetchall()
        day_map = {r.stat_date.isoformat() if isinstance(r.stat_date, date) else str(r.stat_date): _f(r.val) for r in rows}
        series.append({"region_name": rn, "values": [day_map.get(d, 0) for d in dates]})

    return {"code": 0, "data": {"dates": dates, "series": series}}


def sync_status(db: Session, tenant_id: int, shop_id: int) -> dict:
    from app.models.shop import Shop
    shop = db.query(Shop).filter(Shop.id == shop_id, Shop.tenant_id == tenant_id).first()
    if not shop:
        return {"code": ErrorCode.SHOP_NOT_FOUND, "msg": "店铺不存在"}
    r = db.execute(text("""
        SELECT MIN(stat_date) earliest, MAX(stat_date) latest,
               COUNT(DISTINCT stat_date) total_days,
               COUNT(DISTINCT region_name) total_regions, COUNT(*) total_records
        FROM region_daily_stats WHERE tenant_id=:tid AND shop_id=:sid
    """), {"tid": tenant_id, "sid": shop_id}).fetchone()
    return {"code": 0, "data": {
        "shop_id": shop_id, "platform": shop.platform,
        "last_sync_date": r.latest.isoformat() if r.latest else None,
        "total_days": int(r.total_days or 0),
        "earliest_date": r.earliest.isoformat() if r.earliest else None,
        "latest_date": r.latest.isoformat() if r.latest else None,
        "total_regions": int(r.total_regions or 0),
        "total_records": int(r.total_records or 0),
    }}
