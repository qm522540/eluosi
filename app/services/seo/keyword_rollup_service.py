"""店级关键词聚合服务（organic scope，按词跨商品汇总 + 下钻到商品）

与 service.py 的 candidates 不同：
- candidates 是 (product_id, keyword) 二维粒度
- rollup 是 keyword 一维粒度 + 点开下钻恢复 product 分项

数据源：product_search_queries（WB Jam / Ozon Premium 订阅的自然搜索词）
合规：规则 1 tenant_id / 规则 4 shop_id 全带；规则 2 用 timezone-aware datetime
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session


_NOT_READY_HINT = {
    "wb":     "WB 数据来源 POST /api/v2/search-report/product/search-texts，需 Jam 订阅开通后由 ozon_product_queries 同类定时任务拉取入库。",
    "ozon":   "Ozon 数据来源 POST /v1/analytics/product-queries/details，需 Premium 订阅；凌晨 02:30 自动同步。",
    "yandex": "Yandex Market 暂不支持商品级搜索词洞察。",
}


def _since_date(days: int) -> str:
    return (datetime.now(timezone.utc).date() - timedelta(days=days)).isoformat()


def compute_keyword_rollup(
    db: Session,
    tenant_id: int,
    shop,
    *,
    days: int = 30,
    sort: str = "revenue_desc",
    keyword: str = "",
    min_orders: int = 0,
    limit: int = 100,
) -> dict:
    """按 query_text 跨商品聚合

    HAVING 用和 service.py organic_self_sql 一致的门槛（frequency ≥ 5 或 orders ≥ 1），
    保证和"按商品看"Tab 里出现的自然搜索词是同一个候选池。
    """
    since = _since_date(days)

    has_data = db.execute(text("""
        SELECT COUNT(*) FROM product_search_queries
        WHERE tenant_id = :tid AND shop_id = :sid AND stat_date >= :since
    """), {"tid": tenant_id, "sid": shop.id, "since": since}).scalar() or 0

    if not has_data:
        return {
            "code": 0,
            "data": {
                "items": [], "total": 0,
                "days": days,
                "data_status": "not_ready",
                "hint": _NOT_READY_HINT.get(shop.platform, "暂无搜索词数据"),
            },
        }

    sort_map = {
        "revenue_desc":     "revenue DESC, orders DESC",
        "orders_desc":      "orders DESC, revenue DESC",
        "impressions_desc": "impressions DESC",
        "cart_desc":        "add_to_cart DESC",
    }
    order_by = sort_map.get(sort, sort_map["revenue_desc"])

    kw_like = None
    if keyword and keyword.strip():
        kw_like = f"%{keyword.strip().lower()}%"

    kw_clause = "AND LOWER(q.query_text) LIKE :kw" if kw_like else ""
    having_min_orders = "AND SUM(q.orders) >= :min_orders" if min_orders > 0 else ""

    sql = text(f"""
        SELECT
            q.query_text AS keyword,
            SUM(q.frequency)    AS frequency,
            SUM(q.impressions)  AS impressions,
            SUM(q.add_to_cart)  AS add_to_cart,
            SUM(q.orders)       AS orders,
            SUM(q.revenue)      AS revenue,
            COUNT(DISTINCT q.product_id) AS product_count
        FROM product_search_queries q
        JOIN products p ON p.id = q.product_id AND p.tenant_id = q.tenant_id
        WHERE q.tenant_id = :tid
          AND q.shop_id = :sid
          AND q.stat_date >= :since
          AND q.product_id IS NOT NULL
          AND (p.status != 'deleted' OR p.status IS NULL)
          {kw_clause}
        GROUP BY q.query_text
        HAVING (SUM(q.frequency) >= 5 OR SUM(q.orders) >= 1)
          {having_min_orders}
        ORDER BY {order_by}
        LIMIT :lim
    """)

    params = {
        "tid": tenant_id, "sid": shop.id,
        "since": since, "lim": limit,
    }
    if kw_like:
        params["kw"] = kw_like
    if min_orders > 0:
        params["min_orders"] = min_orders

    rows = db.execute(sql, params).fetchall()

    items = [{
        "keyword":       r.keyword,
        "frequency":     int(r.frequency or 0),
        "impressions":   int(r.impressions or 0),
        "add_to_cart":   int(r.add_to_cart or 0),
        "orders":        int(r.orders or 0),
        "revenue":       round(float(r.revenue or 0), 2),
        "product_count": int(r.product_count or 0),
        "candidate_row_count": 0,
    } for r in rows]

    # 旁路查询：每个 keyword 在 seo_keyword_candidates 表出现多少行
    # 用于前端"口径差异说明"：按商品看里同一词可能展示 N 次（含类目推断），
    # 帮用户理解为什么按商品看"看起来订单多"而 rollup"看起来订单少"
    if items:
        kw_list = [it["keyword"] for it in items]
        cand_rows = db.execute(text("""
            SELECT LOWER(keyword) AS kw_lower, COUNT(*) AS cnt
            FROM seo_keyword_candidates
            WHERE tenant_id = :tid AND shop_id = :sid
              AND LOWER(keyword) IN :kws
            GROUP BY LOWER(keyword)
        """).bindparams(bindparam("kws", expanding=True)), {
            "tid": tenant_id, "sid": shop.id,
            "kws": [kw.lower() for kw in kw_list],
        }).fetchall()
        cand_map = {r.kw_lower: int(r.cnt) for r in cand_rows}
        for it in items:
            it["candidate_row_count"] = cand_map.get(it["keyword"].lower(), 0)

    summary = {
        "kw_count":         len(items),
        "total_impressions": sum(it["impressions"] for it in items),
        "total_orders":     sum(it["orders"] for it in items),
        "total_revenue":    round(sum(it["revenue"] for it in items), 2),
    }

    return {
        "code": 0,
        "data": {
            "items": items,
            "total": len(items),
            "days": days,
            "data_status": "ready",
            "summary": summary,
        },
    }


def list_rollup_products(
    db: Session,
    tenant_id: int,
    shop,
    *,
    keyword: str,
    days: int = 30,
    limit: int = 20,
) -> dict:
    """单关键词下钻：该词在各商品的贡献分项

    精确匹配 LOWER(query_text)，保证和店级行 SUM 能对上。
    """
    if not keyword or not keyword.strip():
        return {"code": 10002, "msg": "keyword 不能为空"}

    since = _since_date(days)

    sql = text("""
        SELECT
            q.product_id,
            ANY_VALUE(COALESCE(pl.title_ru, p.name_ru, p.name_zh, '')) AS title,
            ANY_VALUE(p.image_url)         AS image_url,
            ANY_VALUE(pl.platform_sku_id)  AS platform_sku_id,
            ANY_VALUE(pl.rating)           AS rating,
            ANY_VALUE(pl.review_count)     AS review_count,
            SUM(q.frequency)   AS frequency,
            SUM(q.impressions) AS impressions,
            SUM(q.add_to_cart) AS add_to_cart,
            SUM(q.orders)      AS orders,
            SUM(q.revenue)     AS revenue
        FROM product_search_queries q
        JOIN products p ON p.id = q.product_id AND p.tenant_id = q.tenant_id
        LEFT JOIN platform_listings pl ON pl.product_id = p.id
                                       AND pl.tenant_id = p.tenant_id
                                       AND pl.shop_id = q.shop_id
                                       AND pl.status NOT IN ('deleted', 'archived')
        WHERE q.tenant_id = :tid
          AND q.shop_id = :sid
          AND q.stat_date >= :since
          AND q.product_id IS NOT NULL
          AND LOWER(q.query_text) = LOWER(:kw)
          AND (p.status != 'deleted' OR p.status IS NULL)
        GROUP BY q.product_id
        ORDER BY SUM(q.revenue) DESC, SUM(q.orders) DESC, SUM(q.impressions) DESC
        LIMIT :lim
    """)

    rows = db.execute(sql, {
        "tid": tenant_id, "sid": shop.id, "since": since,
        "kw": keyword.strip(), "lim": limit,
    }).fetchall()

    items = [{
        "product_id":      int(r.product_id),
        "title":           r.title or "",
        "image_url":       r.image_url or "",
        "platform_sku_id": r.platform_sku_id or "",
        "rating":          float(r.rating) if r.rating is not None else None,
        "review_count":    int(r.review_count or 0),
        "frequency":       int(r.frequency or 0),
        "impressions":     int(r.impressions or 0),
        "add_to_cart":     int(r.add_to_cart or 0),
        "orders":          int(r.orders or 0),
        "revenue":         round(float(r.revenue or 0), 2),
    } for r in rows]

    return {
        "code": 0,
        "data": {
            "keyword": keyword.strip(),
            "items":   items,
            "total":   len(items),
            "days":    days,
        },
    }
