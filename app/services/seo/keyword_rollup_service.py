"""店级关键词聚合服务（organic scope，按词跨商品汇总 + 下钻到商品）

与 service.py 的 candidates 不同：
- candidates 是 (product_id, keyword) 二维粒度
- rollup 是 keyword 一维粒度 + 点开下钻恢复 product 分项

数据源：product_search_queries（WB Jam / Ozon Premium 订阅的自然搜索词）
合规：规则 1 tenant_id / 规则 4 shop_id 全带；规则 2 用 timezone-aware datetime
"""

import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session


_NOT_READY_HINT = {
    "wb":     "WB 数据来源 POST /api/v2/search-report/product/search-texts，需 Jam 订阅开通后由 ozon_product_queries 同类定时任务拉取入库。",
    "ozon":   "Ozon 数据来源 POST /v1/analytics/product-queries/details，需 Premium 订阅；凌晨 02:30 自动同步。",
    "yandex": "Yandex Market 暂不支持商品级搜索词洞察。",
}

# 判断候选行是否来自 self scope 的 SQL 片段（self 才有真数据，category 继承的数字是假的）
_HAS_SELF_CLAUSE = """(
    JSON_CONTAINS(c.sources, JSON_OBJECT('type','organic','scope','self'))
 OR JSON_CONTAINS(c.sources, JSON_OBJECT('type','paid','scope','self'))
)"""


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


# =============================================================================
# 按商品看 Tab 的关键词聚合视图（走 seo_keyword_candidates 候选池表）
# 与 compute_keyword_rollup (走 product_search_queries) 的区别：
# - rollup：真实自然搜索原始数据（最直接）
# - candidates_rollup：引擎加工后的候选池（含付费+自然+类目扩散推断+反哺评分）
# 口径：两者都只对 sources 含 self 的行 SUM，避免继承数字被重复求和
# =============================================================================


def compute_candidates_rollup(
    db: Session,
    tenant_id: int,
    shop,
    *,
    source: str = "all",
    status: str = "pending",
    keyword: str = "",
    hide_covered: bool = True,
    sort: str = "score_desc",
    limit: int = 200,
) -> dict:
    """按商品看 Tab 的关键词聚合主视图

    聚合维度：LOWER(keyword)；对 self scope 的行 SUM 真数据，非 self 只算推荐覆盖。
    """
    filters = [
        "c.tenant_id = :tid", "c.shop_id = :sid",
        "c.status = :status",
    ]
    params = {"tid": tenant_id, "sid": shop.id, "status": status, "lim": limit}

    if keyword and keyword.strip():
        filters.append("LOWER(c.keyword) LIKE :kw")
        params["kw"] = f"%{keyword.strip().lower()}%"

    # hide_covered: 过滤掉"已在标题或属性里"的候选（无改进空间）
    if hide_covered:
        filters.append("(c.in_title = 0 AND c.in_attrs = 0)")

    # source filter: 支持逗号分隔多选,如 "paid_self,organic_self"; "all" 或空表示不过滤
    source_clauses = {
        "paid_self":        "JSON_CONTAINS(c.sources, JSON_OBJECT('type','paid','scope','self'))",
        "paid_category":    "JSON_CONTAINS(c.sources, JSON_OBJECT('type','paid','scope','category'))",
        "organic_self":     "JSON_CONTAINS(c.sources, JSON_OBJECT('type','organic','scope','self'))",
        "organic_category": "JSON_CONTAINS(c.sources, JSON_OBJECT('type','organic','scope','category'))",
        "with_orders":      f"({_HAS_SELF_CLAUSE} AND (COALESCE(c.paid_orders,0) + COALESCE(c.organic_orders,0)) > 0)",
    }
    source_list = [s.strip() for s in (source or "").split(",") if s.strip()]
    source_list = [s for s in source_list if s in source_clauses]
    if source_list:
        or_clause = " OR ".join(source_clauses[s] for s in source_list)
        filters.append(f"({or_clause})")

    where_clause = " AND ".join(filters)

    sort_map = {
        "score_desc":   "max_score DESC, total_orders DESC",
        "orders_desc":  "total_orders DESC, max_score DESC",
        "impr_desc":    "total_impr DESC",
        "products_desc":"product_count DESC, total_orders DESC",
    }
    order_by = sort_map.get(sort, sort_map["score_desc"])

    sql = text(f"""
        SELECT c.keyword,
               COUNT(DISTINCT c.product_id) AS product_count,
               COUNT(DISTINCT CASE WHEN {_HAS_SELF_CLAUSE} THEN c.product_id END) AS self_product_count,
               SUM(CASE WHEN {_HAS_SELF_CLAUSE}
                        THEN COALESCE(c.paid_orders,0) + COALESCE(c.organic_orders,0) ELSE 0 END) AS total_orders,
               SUM(CASE WHEN {_HAS_SELF_CLAUSE}
                        THEN COALESCE(c.organic_impressions,0) ELSE 0 END) AS total_impr,
               SUM(CASE WHEN {_HAS_SELF_CLAUSE}
                        THEN COALESCE(c.organic_add_to_cart,0) ELSE 0 END) AS total_cart,
               ROUND(MAX(c.score), 1) AS max_score,
               MAX(CASE WHEN JSON_CONTAINS(c.sources, JSON_OBJECT('type','paid','scope','self'))
                         OR JSON_CONTAINS(c.sources, JSON_OBJECT('type','paid','scope','category'))
                        THEN 1 ELSE 0 END) AS has_paid,
               MAX(CASE WHEN JSON_CONTAINS(c.sources, JSON_OBJECT('type','organic','scope','self'))
                         OR JSON_CONTAINS(c.sources, JSON_OBJECT('type','organic','scope','category'))
                        THEN 1 ELSE 0 END) AS has_organic
        FROM seo_keyword_candidates c
        WHERE {where_clause}
        GROUP BY c.keyword
        ORDER BY {order_by}
        LIMIT :lim
    """)

    rows = db.execute(sql, params).fetchall()

    items = [{
        "keyword":            r.keyword,
        "product_count":      int(r.product_count or 0),
        "self_product_count": int(r.self_product_count or 0),
        "total_orders":       int(r.total_orders or 0),
        "total_impressions":  int(r.total_impr or 0),
        "total_add_to_cart":  int(r.total_cart or 0),
        "max_score":          float(r.max_score or 0),
        "has_paid":           bool(r.has_paid),
        "has_organic":        bool(r.has_organic),
    } for r in rows]

    summary = {
        "kw_count":          len(items),
        "total_impressions": sum(it["total_impressions"] for it in items),
        "total_orders":      sum(it["total_orders"] for it in items),
        "with_self_kw":      sum(1 for it in items if it["self_product_count"] > 0),
    }

    return {
        "code": 0,
        "data": {"items": items, "total": len(items), "summary": summary},
    }


def list_candidates_rollup_products(
    db: Session,
    tenant_id: int,
    shop,
    *,
    keyword: str,
    status: str = "pending",
    limit: int = 100,
) -> dict:
    """单关键词下钻到候选商品明细（含 self + category 全量，自带 self 标记）"""
    if not keyword or not keyword.strip():
        return {"code": 10002, "msg": "keyword 不能为空"}

    sql = text(f"""
        SELECT c.id AS candidate_id,
               c.shop_id,
               c.product_id,
               c.keyword,
               c.status,
               c.score,
               c.in_title,
               c.in_attrs,
               c.sources,
               c.paid_orders, c.paid_revenue, c.paid_roas,
               c.organic_orders, c.organic_impressions, c.organic_add_to_cart,
               {_HAS_SELF_CLAUSE} AS has_self,
               COALESCE(pl.title_ru, p.name_ru, p.name_zh, '') AS title,
               p.image_url,
               p.local_category_id AS cat_id,
               pl.platform_sku_id,
               pl.rating,
               pl.review_count
        FROM seo_keyword_candidates c
        JOIN products p ON p.id = c.product_id AND p.tenant_id = c.tenant_id
        LEFT JOIN platform_listings pl ON pl.product_id = p.id
                                       AND pl.tenant_id = p.tenant_id
                                       AND pl.shop_id = c.shop_id
                                       AND pl.status NOT IN ('deleted', 'archived')
        WHERE c.tenant_id = :tid
          AND c.shop_id = :sid
          AND LOWER(c.keyword) = LOWER(:kw)
          AND c.status = :status
        ORDER BY has_self DESC, c.score DESC, (COALESCE(c.paid_orders,0) + COALESCE(c.organic_orders,0)) DESC
        LIMIT :lim
    """)

    rows = db.execute(sql, {
        "tid": tenant_id, "sid": shop.id,
        "kw": keyword.strip(), "status": status, "lim": limit,
    }).fetchall()

    # 一次查询该词 × 各类目的 evidence，按 cat_id 分组挂到每一行
    evidence_by_cat = _fetch_category_evidence(
        db=db, tenant_id=tenant_id, shop_id=shop.id,
        keyword=keyword.strip(), days=30,
    )

    items = []
    for r in rows:
        has_self = bool(r.has_self)
        cat_id = int(r.cat_id) if r.cat_id is not None else None
        items.append({
            "candidate_id":    int(r.candidate_id),
            "shop_id":         int(r.shop_id),
            "product_id":      int(r.product_id),
            "title":           r.title or "",
            "image_url":       r.image_url or "",
            "platform_sku_id": r.platform_sku_id or "",
            "rating":          float(r.rating) if r.rating is not None else None,
            "review_count":    int(r.review_count or 0),
            "status":          r.status,
            "score":           float(r.score or 0),
            "in_title":        bool(r.in_title),
            "in_attrs":        bool(r.in_attrs),
            "sources":         r.sources if isinstance(r.sources, list) else (json.loads(r.sources) if r.sources else []),
            "has_self":        has_self,
            "cat_id":          cat_id,
            # 仅 self 行显示真实数字, category-only 行字段置 null 让前端知道"无实证"
            "paid_orders":     (int(r.paid_orders or 0) if has_self else None),
            "paid_revenue":    (round(float(r.paid_revenue or 0), 2) if has_self else None),
            "paid_roas":       (round(float(r.paid_roas or 0), 2) if has_self else None),
            "organic_orders":  (int(r.organic_orders or 0) if has_self else None),
            "organic_impressions": (int(r.organic_impressions or 0) if has_self else None),
            "organic_add_to_cart": (int(r.organic_add_to_cart or 0) if has_self else None),
            # category evidence：给前端展示推断理由（"类目里 N 款真实搜中 · X 订单"）
            # 仅对 has_self=false 行有意义，has_self 行 evidence 留着也无妨
            "category_evidence": evidence_by_cat.get(cat_id) if cat_id is not None else None,
        })

    return {
        "code": 0,
        "data": {"keyword": keyword.strip(), "items": items, "total": len(items)},
    }


def _fetch_category_evidence(
    db: Session, tenant_id: int, shop_id: int, keyword: str, days: int = 30,
) -> dict:
    """查该 (shop, keyword) 在 product_search_queries 里按 local_category_id 分组的证据。

    返回 {cat_id: {cat_id, cat_name, cat_name_ru, products_verified, total_orders, total_frequency, total_impressions}}
    用于前端「推荐理由」Tag 展示 — 解答"为什么这些 0 曝光商品出现在推荐里"。
    """
    today = datetime.now(timezone.utc).date()
    since = today - timedelta(days=days)
    rows = db.execute(text("""
        SELECT p.local_category_id AS cat_id,
               COUNT(DISTINCT p.id)          AS products_verified,
               COALESCE(SUM(q.orders), 0)      AS total_orders,
               COALESCE(SUM(q.frequency), 0)   AS total_frequency,
               COALESCE(SUM(q.impressions), 0) AS total_impressions,
               COALESCE(SUM(q.add_to_cart), 0) AS total_add_to_cart
        FROM product_search_queries q
        JOIN products p ON p.id = q.product_id AND p.tenant_id = q.tenant_id
        WHERE q.tenant_id = :tid AND q.shop_id = :sid
          AND LOWER(q.query_text) = LOWER(:kw)
          AND q.stat_date >= :since
          AND p.local_category_id IS NOT NULL
        GROUP BY p.local_category_id
    """), {"tid": tenant_id, "sid": shop_id, "kw": keyword, "since": since}).fetchall()

    if not rows:
        return {}

    cat_ids = [r.cat_id for r in rows]
    # 取类目名（中文 + 俄文）便于前端直接显示
    name_rows = db.execute(
        text("SELECT id, name, name_ru FROM local_categories "
             "WHERE tenant_id = :tid AND id IN :ids")
        .bindparams(bindparam("ids", expanding=True)),
        {"tid": tenant_id, "ids": cat_ids},
    ).fetchall()
    name_map = {n.id: (n.name, n.name_ru) for n in name_rows}

    out = {}
    for r in rows:
        nm_cn, nm_ru = name_map.get(r.cat_id, (None, None))
        out[r.cat_id] = {
            "cat_id":            int(r.cat_id),
            "cat_name":          nm_cn or "",
            "cat_name_ru":       nm_ru or "",
            "products_verified": int(r.products_verified or 0),
            "total_orders":      int(r.total_orders or 0),
            "total_frequency":   int(r.total_frequency or 0),
            "total_impressions": int(r.total_impressions or 0),
            "total_add_to_cart": int(r.total_add_to_cart or 0),
        }
    return out


def list_category_evidence_top_products(
    db: Session, tenant_id: int, shop,
    *, keyword: str, category_id: int, limit: int = 5,
) -> dict:
    """弹窗展示：该类目下对该关键词真实搜中的 Top N 商品"""
    if not keyword or not keyword.strip() or not category_id:
        return {"code": 10002, "msg": "keyword / category_id 不能为空"}

    rows = db.execute(text("""
        SELECT p.id AS product_id,
               ANY_VALUE(COALESCE(pl.title_ru, p.name_ru, p.name_zh, '')) AS title,
               ANY_VALUE(p.image_url)          AS image_url,
               ANY_VALUE(pl.platform_sku_id)   AS platform_sku_id,
               SUM(q.frequency)                AS total_frequency,
               SUM(q.impressions)              AS total_impressions,
               SUM(q.add_to_cart)              AS total_add_to_cart,
               SUM(q.orders)                   AS total_orders
        FROM product_search_queries q
        JOIN products p ON p.id = q.product_id AND p.tenant_id = q.tenant_id
        LEFT JOIN platform_listings pl ON pl.product_id = p.id
                                       AND pl.tenant_id = p.tenant_id
                                       AND pl.shop_id = q.shop_id
                                       AND pl.status NOT IN ('deleted', 'archived')
        WHERE q.tenant_id = :tid AND q.shop_id = :sid
          AND LOWER(q.query_text) = LOWER(:kw)
          AND q.stat_date >= CURDATE() - INTERVAL 30 DAY
          AND p.local_category_id = :cat_id
        GROUP BY p.id
        ORDER BY SUM(q.impressions) DESC, SUM(q.orders) DESC
        LIMIT :lim
    """), {
        "tid": tenant_id, "sid": shop.id, "kw": keyword.strip(),
        "cat_id": category_id, "lim": limit,
    }).fetchall()

    items = [{
        "product_id":        int(r.product_id),
        "title":             r.title or "",
        "image_url":         r.image_url or "",
        "platform_sku_id":   r.platform_sku_id or "",
        "total_frequency":   int(r.total_frequency or 0),
        "total_impressions": int(r.total_impressions or 0),
        "total_add_to_cart": int(r.total_add_to_cart or 0),
        "total_orders":      int(r.total_orders or 0),
    } for r in rows]
    return {"code": 0, "data": {"keyword": keyword.strip(), "category_id": category_id, "items": items}}
