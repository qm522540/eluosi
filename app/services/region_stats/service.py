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


def _get_shop_avg_margin(db: Session, tenant_id: int, shop_id: int) -> tuple:
    """取店铺级平均净毛利率。
    优先顺序：该店铺所有 products.net_margin 平均 → ai_pricing_configs.default_config.gross_margin
    → 兜底 0.30。返回 (avg_margin, source)。
    """
    row = db.execute(text("""
        SELECT AVG(net_margin) avg_m, COUNT(net_margin) n
        FROM products
        WHERE tenant_id=:tid AND shop_id=:sid
          AND status!='deleted' AND net_margin IS NOT NULL
    """), {"tid": tenant_id, "sid": shop_id}).fetchone()
    if row and row.avg_m is not None and (row.n or 0) > 0:
        return float(row.avg_m), f"按店铺 {row.n} 款商品 net_margin 平均"

    row = db.execute(text("""
        SELECT default_config FROM ai_pricing_configs
        WHERE tenant_id=:tid AND shop_id=:sid
    """), {"tid": tenant_id, "sid": shop_id}).fetchone()
    if row and row.default_config:
        import json
        try:
            cfg = row.default_config if isinstance(row.default_config, dict) else json.loads(row.default_config)
            gm = cfg.get("gross_margin")
            if gm:
                return float(gm), "按店铺 AI 调价默认配置 gross_margin"
        except Exception:
            pass

    return 0.30, "默认兜底 30%（店铺未配置毛利率）"


def _suggest_region_action(return_rate: float, net_profit_est: float,
                           revenue_pct: float, orders: int) -> tuple:
    """按退货率 + 净贡献 + 订单规模给出屏蔽建议。
    返回 (suggestion, reason)，suggestion ∈ {'block','watch','keep'}。
    """
    if orders < 3:
        return "keep", "订单过少，数据不足不做判断"
    if return_rate >= 15:
        return "block", f"退货率 {return_rate:.1f}% 过高，不建议投广告"
    if net_profit_est < 0:
        return "block", f"扣除退货损失后净利润为负（估算 ₽{net_profit_est:.0f}）"
    if return_rate >= 8:
        return "watch", f"退货率 {return_rate:.1f}% 偏高，建议观察"
    if revenue_pct < 1 and orders < 10:
        return "watch", f"销售占比 {revenue_pct:.1f}% 偏低，规模不值得重点投放"
    return "keep", "表现正常"


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

    # 店铺平均毛利率（用于净贡献估算）
    avg_margin, margin_source = _get_shop_avg_margin(db, tenant_id, shop_id)

    allowed = {"revenue", "orders", "avg_price", "returns", "net_profit_est"}
    sort_col = sort_by if sort_by in allowed else "revenue"
    # net_profit_est 需 Python 侧排序（SQL 层无法直接表达退货损失+毛利）
    if sort_col in {"revenue", "orders", "returns"}:
        order_expr = f"SUM({sort_col}) DESC"
    elif sort_col == "avg_price":
        order_expr = "ROUND(SUM(revenue)/NULLIF(SUM(orders),0),2) DESC"
    else:
        order_expr = "SUM(revenue) DESC"

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
        return_rate = round(ret_val / ord_val * 100, 1) if ord_val > 0 else 0
        # 净贡献 = 销售额 × 毛利率 − 退货损失（退货按全损算，简化）
        gross_profit = rev_val * avg_margin
        return_loss = rev_val * return_rate / 100
        net_profit_est = round(gross_profit - return_loss, 2)
        revenue_pct = round(rev_val / total_revenue * 100, 1) if total_revenue > 0 else 0
        suggestion, suggestion_reason = _suggest_region_action(
            return_rate, net_profit_est, revenue_pct, ord_val)
        items.append({
            "region_name": r.region_name,
            "region_name_zh": _RU_REGIONS_ZH.get(r.region_name, ""),
            "orders": ord_val,
            "revenue": rev_val,
            "avg_price": round(rev_val / ord_val, 2) if ord_val > 0 else 0,
            "returns": ret_val,
            "return_rate": return_rate,
            "orders_pct": round(ord_val / total_orders * 100, 1) if total_orders > 0 else 0,
            "revenue_pct": revenue_pct,
            "net_profit_est": net_profit_est,
            "suggestion": suggestion,
            "suggestion_reason": suggestion_reason,
        })

    if sort_col == "net_profit_est":
        items.sort(key=lambda x: x["net_profit_est"], reverse=True)

    # 全店净贡献估算
    total_gross = total_revenue * avg_margin
    total_returns = sum(_f(r.ret) for r in rows)  # 退货件数总和
    total_return_loss = sum(
        _f(r.rev) * (_f(r.ret) / _f(r.ord) if _f(r.ord) > 0 else 0)
        for r in rows
    )
    total_net_profit = round(total_gross - total_return_loss, 2)

    return {"code": 0, "data": {
        "date_from": date_from, "date_to": date_to,
        "totals": {
            "regions": int(totals_row.regions or 0),
            "orders": total_orders,
            "revenue": total_revenue,
            "avg_price": round(total_revenue / total_orders, 2) if total_orders > 0 else 0,
            "avg_margin_pct": round(avg_margin * 100, 1),
            "margin_source": margin_source,
            "net_profit_est": total_net_profit,
        },
        "items": items,
    }}


def region_detail(db: Session, tenant_id: int, shop_id: int, region_name: str,
                  date_from=None, date_to=None, limit: int = 10) -> dict:
    """返回某地区 TOP N SKU 的销售明细，用于"决策是否关闭该地区配送"。
    WB：直接调 region-sale API 按 regionName 过滤 + nmID 聚合（不存表，避免膨胀）。
    """
    from app.models.shop import Shop
    date_from, date_to = _default_dates(date_from, date_to)
    shop = db.query(Shop).filter(
        Shop.id == shop_id, Shop.tenant_id == tenant_id
    ).first()
    if not shop:
        return {"code": ErrorCode.SHOP_NOT_FOUND, "msg": "店铺不存在"}
    if shop.platform != "wb":
        return {"code": 0, "data": {
            "region_name": region_name,
            "region_name_zh": _RU_REGIONS_ZH.get(region_name, ""),
            "date_from": date_from, "date_to": date_to,
            "items": [], "platform": shop.platform,
            "note": f"{shop.platform.upper()} 暂不支持 SKU 粒度的地区销售",
        }}

    import asyncio
    from app.services.platform.wb import WBClient
    async def _fetch():
        c = WBClient(shop_id=shop.id, api_key=shop.api_key)
        try:
            return await c.fetch_region_sales_by_sku(date_from, date_to, region_name)
        finally:
            await c.close()
    loop = asyncio.new_event_loop()
    try:
        rows = loop.run_until_complete(_fetch())
    finally:
        loop.close()

    # 按销售额降序
    rows.sort(key=lambda x: x["revenue"], reverse=True)
    rows = rows[:limit]

    # 反查商品中文名
    nm_ids = [r["nm_id"] for r in rows]
    name_map = {}
    if nm_ids:
        from app.models.product import Product, PlatformListing
        pl_rows = db.query(
            PlatformListing.platform_product_id, PlatformListing.product_id,
        ).filter(
            PlatformListing.tenant_id == tenant_id,
            PlatformListing.shop_id == shop_id,
            PlatformListing.platform == "wb",
            PlatformListing.platform_product_id.in_([str(n) for n in nm_ids]),
        ).all()
        prod_ids = [r.product_id for r in pl_rows]
        pid_to_nm = {r.product_id: r.platform_product_id for r in pl_rows}
        if prod_ids:
            prods = db.query(
                Product.id, Product.name_zh, Product.sku, Product.image_url,
            ).filter(Product.id.in_(prod_ids)).all()
            for p in prods:
                nm = pid_to_nm.get(p.id)
                if nm:
                    name_map[str(nm)] = {
                        "name_zh": p.name_zh, "sku_local": p.sku,
                        "image_url": p.image_url,
                    }

    total_rev = sum(r["revenue"] for r in rows) or 1
    items = []
    for r in rows:
        info = name_map.get(str(r["nm_id"]), {}) or {}
        items.append({
            "nm_id": r["nm_id"],
            "sa": r["sa"],
            "name_zh": info.get("name_zh") or "",
            "image_url": info.get("image_url"),
            "orders": r["orders"],
            "revenue": r["revenue"],
            "revenue_pct_in_region": round(r["revenue"] / total_rev * 100, 1),
        })

    return {"code": 0, "data": {
        "region_name": region_name,
        "region_name_zh": _RU_REGIONS_ZH.get(region_name, ""),
        "date_from": date_from, "date_to": date_to,
        "platform": "wb",
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
