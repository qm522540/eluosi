"""店级关键词聚合服务（organic scope，按词跨商品汇总 + 下钻到商品）

与 service.py 的 candidates 不同：
- candidates 是 (product_id, keyword) 二维粒度
- rollup 是 keyword 一维粒度 + 点开下钻恢复 product 分项

数据源：product_search_queries（WB Jam / Ozon Premium 订阅的自然搜索词）
合规：规则 1 tenant_id / 规则 4 shop_id 全带；规则 2 用 timezone-aware datetime
"""

import json
from datetime import datetime, timedelta, timezone
from typing import List

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session


_NOT_READY_HINT = {
    "wb":     "WB 数据来源 POST /api/v2/search-report/product/search-texts，需 Jam 订阅开通后由 ozon_product_queries 同类定时任务拉取入库。",
    "ozon":   "Ozon 数据来源 POST /v1/analytics/product-queries/details，需 Premium 订阅；凌晨 02:30 自动同步。",
    "yandex": "Yandex Market 暂不支持商品级搜索词洞察。",
}

# candidates 表空态专用 hint（SEO Optimize「按商品看」Tab 的聚合视图）
# 与 _NOT_READY_HINT 区别：这里按"源数据存在性"分诊，精准引导用户
# 引擎依赖：源 A=ad_keywords（不是 ad_stats，关键词级数据才能反哺）/ 源 B=product_search_queries
# 真实场景（2026-04-24 Pt.Gril）：店铺所有活动是 Trafareti CPC（自动广告无关键词），
# ad_keywords=0 → 引擎源 A 永远空；同时 Premium 未配 → 源 B 也空 → 候选池永远生不出
_CANDIDATES_NO_SOURCE_HINT = {
    "wb":     "WB 候选池暂无数据。可能原因：① 该店广告活动是「自动广告」类型（无关键词级数据，候选池引擎依赖关键词）；② 无 active 广告活动；③ Jam 订阅刚开通或同步未完成，每日 MSK 04:00 自动拉取。请先在 WB 后台检查广告类型与订阅状态。",
    "ozon":   "Ozon 候选池暂无数据。可能原因：① 该店广告活动是 Trafareti CPC 等「自动广告」类型（无关键词级数据，候选池引擎依赖关键词）；② 无 active 广告活动；③ Premium 订阅刚开通或同步未完成，每日 MSK 02:30 自动拉取。请先在 Ozon 后台检查广告类型与订阅状态。",
    "yandex": "Yandex Market 暂不支持候选词反哺功能。",
}
_CANDIDATES_ENGINE_NOT_RUN_HINT = {
    "wb":     "WB 已有广告关键词或搜索词数据但候选池尚未生成。候选池引擎按需触发，请联系管理员手动跑一次 analyze_paid_to_organic，或在「按商品单商品」模式下点「刷新候选池」。",
    "ozon":   "Ozon 已有广告关键词或搜索词数据但候选池尚未生成。候选池引擎按需触发，请联系管理员手动跑一次 analyze_paid_to_organic，或在「按商品单商品」模式下点「刷新候选池」。",
    "yandex": "Yandex Market 暂不支持候选词反哺功能。",
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
    shop_ids: list = None,
) -> dict:
    """按 query_text 跨商品聚合（支持多店合并：shop_ids 优先于单店 shop）

    HAVING 用和 service.py organic_self_sql 一致的门槛（frequency ≥ 5 或 orders ≥ 1），
    保证和"按商品看"Tab 里出现的自然搜索词是同一个候选池。
    """
    since = _since_date(days)

    # 多店模式：shop_ids 非空 → 用 IN 聚合；否则退化为单店 shop.id
    if shop_ids:
        sids = list({int(x) for x in shop_ids if x})
    else:
        sids = [shop.id]

    has_data = db.execute(text("""
        SELECT COUNT(*) FROM product_search_queries
        WHERE tenant_id = :tid AND shop_id IN :sids AND stat_date >= :since
    """).bindparams(bindparam("sids", expanding=True)),
        {"tid": tenant_id, "sids": sids, "since": since}).scalar() or 0

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
          AND q.shop_id IN :sids
          AND q.stat_date >= :since
          AND q.product_id IS NOT NULL
          AND (p.status != 'deleted' OR p.status IS NULL)
          {kw_clause}
        GROUP BY q.query_text
        HAVING (SUM(q.frequency) >= 5 OR SUM(q.orders) >= 1)
          {having_min_orders}
        ORDER BY {order_by}
        LIMIT :lim
    """).bindparams(bindparam("sids", expanding=True))

    params = {
        "tid": tenant_id, "sids": sids,
        "since": since, "lim": limit,
    }
    if kw_like:
        params["kw"] = kw_like
    if min_orders > 0:
        params["min_orders"] = min_orders

    rows = db.execute(sql, params).fetchall()

    import math
    def _calc_score(orders, impressions, add_to_cart, product_count):
        # 与候选池 score 同思路：log(订单+1)*2 + log(曝光+1) + log(自然订单+1)*2 + 来源数*2
        # 店铺 TOP 没"来源数"概念，用 product_count（多商品命中视为"多源信号"）做替代
        # ROAS 项 Ozon 没付费数据，跳过
        score = (
            math.log10(orders + 1) * 4
            + math.log10(impressions + 1) * 1
            + math.log10(add_to_cart + 1) * 2
            + min(product_count, 10) * 0.3  # 多商品命中加分但封顶 10
        )
        return round(score, 1)

    items = [{
        "keyword":       r.keyword,
        "frequency":     int(r.frequency or 0),
        "impressions":   int(r.impressions or 0),
        "add_to_cart":   int(r.add_to_cart or 0),
        "orders":        int(r.orders or 0),
        "revenue":       round(float(r.revenue or 0), 2),
        "product_count": int(r.product_count or 0),
        "score":         _calc_score(int(r.orders or 0), int(r.impressions or 0),
                                     int(r.add_to_cart or 0), int(r.product_count or 0)),
        "candidate_row_count": 0,
    } for r in rows]

    # 全店汇总：套相同 WHERE + HAVING（含 keyword/min_orders 过滤），但不带 ORDER BY + LIMIT。
    # 修复 UX bug：之前 summary 基于 items 求和，切排序后取出的 200 词集合变化导致
    # "总订单/总收入"漂移（用户截图 9→5 / 3360→1919），违反"切排序词集不应变"直觉。
    summary_sql = text(f"""
        SELECT COUNT(*) AS kw_count,
               COALESCE(SUM(impressions), 0) AS total_impressions,
               COALESCE(SUM(orders), 0)      AS total_orders,
               COALESCE(SUM(revenue), 0)     AS total_revenue
        FROM (
            SELECT
                SUM(q.frequency)    AS frequency,
                SUM(q.impressions)  AS impressions,
                SUM(q.orders)       AS orders,
                SUM(q.revenue)      AS revenue
            FROM product_search_queries q
            JOIN products p ON p.id = q.product_id AND p.tenant_id = q.tenant_id
            WHERE q.tenant_id = :tid
              AND q.shop_id IN :sids
              AND q.stat_date >= :since
              AND q.product_id IS NOT NULL
              AND (p.status != 'deleted' OR p.status IS NULL)
              {kw_clause}
            GROUP BY q.query_text
            HAVING (SUM(q.frequency) >= 5 OR SUM(q.orders) >= 1)
              {having_min_orders}
        ) t
    """).bindparams(bindparam("sids", expanding=True))
    sum_params = {"tid": tenant_id, "sids": sids, "since": since}
    if kw_like:
        sum_params["kw"] = kw_like
    if min_orders > 0:
        sum_params["min_orders"] = min_orders
    sum_row = db.execute(summary_sql, sum_params).fetchone()

    # 旁路查询：每个 keyword 在 seo_keyword_candidates 表出现多少行
    # 用于前端"口径差异说明"：按商品看里同一词可能展示 N 次（含类目推断），
    # 帮用户理解为什么按商品看"看起来订单多"而 rollup"看起来订单少"
    if items:
        kw_list = [it["keyword"] for it in items]
        cand_rows = db.execute(text("""
            SELECT LOWER(keyword) AS kw_lower, COUNT(*) AS cnt
            FROM seo_keyword_candidates
            WHERE tenant_id = :tid AND shop_id IN :sids
              AND LOWER(keyword) IN :kws
            GROUP BY LOWER(keyword)
        """).bindparams(bindparam("kws", expanding=True),
                        bindparam("sids", expanding=True)), {
            "tid": tenant_id, "sids": sids,
            "kws": [kw.lower() for kw in kw_list],
        }).fetchall()
        cand_map = {r.kw_lower: int(r.cnt) for r in cand_rows}
        for it in items:
            it["candidate_row_count"] = cand_map.get(it["keyword"].lower(), 0)

        # 跨店覆盖：每个词在当前 tenant 下出现在哪些 shop（不限 sids，全店扫一遍）
        # cross_shop_count = 该词在多少家店出现过
        # cross_shop_shop_ids = 哪些店（前端可对比当前 sids，差额标记"+N 跨店"）
        cross_rows = db.execute(text("""
            SELECT LOWER(q.query_text) AS kw_lower,
                   q.shop_id AS shop_id,
                   SUM(q.orders) AS orders
            FROM product_search_queries q
            WHERE q.tenant_id = :tid
              AND q.stat_date >= :since
              AND q.product_id IS NOT NULL
              AND LOWER(q.query_text) IN :kws
            GROUP BY LOWER(q.query_text), q.shop_id
        """).bindparams(bindparam("kws", expanding=True)), {
            "tid": tenant_id, "since": since,
            "kws": [kw.lower() for kw in kw_list],
        }).fetchall()
        cross_map = {}
        for r in cross_rows:
            cross_map.setdefault(r.kw_lower, []).append({
                "shop_id": int(r.shop_id),
                "orders": int(r.orders or 0),
            })
        sids_set = set(sids)
        for it in items:
            shops_for_kw = cross_map.get(it["keyword"].lower(), [])
            other_shops = [s for s in shops_for_kw if s["shop_id"] not in sids_set]
            it["cross_shop_count"] = len(other_shops)
            it["cross_shop_shops"] = other_shops[:5]  # 防止前端过载，只返前 5 家

    summary = {
        "kw_count":         int(sum_row.kw_count or 0),
        "total_impressions": int(sum_row.total_impressions or 0),
        "total_orders":     int(sum_row.total_orders or 0),
        "total_revenue":    round(float(sum_row.total_revenue or 0), 2),
        "shown_count":      len(items),
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
    shop_ids: list = None,
) -> dict:
    """单关键词下钻：该词在各商品的贡献分项（支持多店）

    精确匹配 LOWER(query_text)，保证和店级行 SUM 能对上。
    返回字段含 in_title / in_attrs 标识标题/属性是否已含该词。
    """
    if not keyword or not keyword.strip():
        return {"code": 10002, "msg": "keyword 不能为空"}

    since = _since_date(days)

    if shop_ids:
        sids = list({int(x) for x in shop_ids if x})
    else:
        sids = [shop.id]

    kw_lower = keyword.strip().lower()

    sql = text("""
        SELECT
            q.product_id,
            q.shop_id                      AS shop_id,
            ANY_VALUE(COALESCE(pl.title_ru, p.name_ru, p.name_zh, '')) AS title,
            ANY_VALUE(p.image_url)         AS image_url,
            ANY_VALUE(pl.platform_sku_id)  AS platform_sku_id,
            ANY_VALUE(p.sku)               AS product_sku,
            MAX(CASE WHEN LOWER(COALESCE(pl.title_ru, p.name_ru, p.name_zh, ''))
                          LIKE CONCAT('%', :kw_lower, '%') THEN 1 ELSE 0 END) AS in_title,
            MAX(CASE WHEN LOWER(COALESCE(CAST(pl.variant_attrs AS CHAR), ''))
                          LIKE CONCAT('%', :kw_lower, '%') THEN 1 ELSE 0 END) AS in_attrs,
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
          AND q.shop_id IN :sids
          AND q.stat_date >= :since
          AND q.product_id IS NOT NULL
          AND LOWER(q.query_text) = :kw_lower
          AND (p.status != 'deleted' OR p.status IS NULL)
        GROUP BY q.product_id, q.shop_id
        ORDER BY SUM(q.revenue) DESC, SUM(q.orders) DESC, SUM(q.impressions) DESC
        LIMIT :lim
    """).bindparams(bindparam("sids", expanding=True))

    rows = db.execute(sql, {
        "tid": tenant_id, "sids": sids, "since": since,
        "kw_lower": kw_lower, "lim": limit,
    }).fetchall()

    items = [{
        "product_id":      int(r.product_id),
        "shop_id":         int(r.shop_id),
        "title":           r.title or "",
        "image_url":       r.image_url or "",
        "platform_sku_id": r.platform_sku_id or "",
        "product_sku":     r.product_sku or "",
        "in_title":        bool(r.in_title),
        "in_attrs":        bool(r.in_attrs),
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
    # 空态快速判定：候选池表整体无数据 → 返 not_ready + 平台 hint
    # 与 compute_keyword_rollup 对齐 data_status 契约，让前端能给出"数据在同步中"而非
    # "当前条件下无候选词"的误导性空态（后者让用户以为功能坏了）
    pool_count = db.execute(text(
        "SELECT COUNT(*) FROM seo_keyword_candidates "
        "WHERE tenant_id = :tid AND shop_id = :sid"
    ), {"tid": tenant_id, "sid": shop.id}).scalar() or 0
    if pool_count == 0:
        # 分诊源数据：源 A=ad_keywords(引擎 self_sql 强依赖，自动广告类型该表 0 行)
        # 源 B=product_search_queries(订阅同步)
        # 全空 → 业务侧无源数据；有源但池空 → 引擎漏跑
        ad_kw_count = db.execute(text(
            "SELECT 1 FROM ad_keywords kw "
            "JOIN ad_groups g ON g.id = kw.ad_group_id AND g.tenant_id = kw.tenant_id "
            "JOIN ad_campaigns c ON c.id = g.campaign_id AND c.tenant_id = kw.tenant_id "
            "WHERE c.shop_id = :sid AND c.tenant_id = :tid LIMIT 1"
        ), {"tid": tenant_id, "sid": shop.id}).scalar() or 0
        psq_count = db.execute(text(
            "SELECT 1 FROM product_search_queries "
            "WHERE tenant_id = :tid AND shop_id = :sid LIMIT 1"
        ), {"tid": tenant_id, "sid": shop.id}).scalar() or 0
        if ad_kw_count == 0 and psq_count == 0:
            reason = "no_source"
            hint = _CANDIDATES_NO_SOURCE_HINT.get(shop.platform, "候选池暂无数据")
        else:
            reason = "engine_not_run"
            hint = _CANDIDATES_ENGINE_NOT_RUN_HINT.get(shop.platform, "候选池引擎未运行")
        return {
            "code": 0,
            "data": {
                "items": [], "total": 0,
                "summary": {
                    "kw_count": 0, "total_impressions": 0,
                    "total_orders": 0, "with_self_kw": 0,
                },
                "data_status": "not_ready",
                "not_ready_reason": reason,
                "hint": hint,
            },
        }

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
        # cross_shop_self: 引擎 Step G 写入。entry 含 source_shop_id 等业务字段,
        # JSON_CONTAINS 只能匹配子对象 → 用 JSON_SEARCH 找 type 是否含 'cross_shop'
        "cross_shop_self":  "JSON_SEARCH(c.sources, 'one', 'cross_shop', NULL, '$[*].type') IS NOT NULL",
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
                        THEN 1 ELSE 0 END) AS has_organic,
               MAX(CASE WHEN JSON_SEARCH(c.sources, 'one', 'cross_shop', NULL, '$[*].type') IS NOT NULL
                        THEN 1 ELSE 0 END) AS has_cross_shop
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
        "has_cross_shop":     bool(r.has_cross_shop),
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
               p.sku AS product_sku,
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
        LIMIT :lim
    """)
    # 注：ORDER BY 移到 Python 层，因为要把 cross_shop 插入 self 和 category 中间

    rows = db.execute(sql, {
        "tid": tenant_id, "sid": shop.id,
        "kw": keyword.strip(), "status": status, "lim": limit,
    }).fetchall()

    # 一次查询该词 × 各类目的 evidence，按 cat_id 分组挂到每一行
    evidence_by_cat = _fetch_category_evidence(
        db=db, tenant_id=tenant_id, shop_id=shop.id,
        keyword=keyword.strip(), days=30,
    )
    # 跨店同款证据：对本店之外的其他 shop 里相同 p.sku 的 listing 查 product_search_queries
    # 目的：WB 店铺里 0 曝光的 SK-E0001 若在 OZON 店里有 228 曝光 → 本店应感知此机会
    product_skus = list({r.product_sku for r in rows if r.product_sku})
    cross_shop_by_sku = _fetch_cross_shop_evidence(
        db=db, tenant_id=tenant_id, current_shop_id=shop.id,
        product_skus=product_skus, keyword=keyword.strip(), days=30,
    )

    items = []
    for r in rows:
        has_self = bool(r.has_self)
        cat_id = int(r.cat_id) if r.cat_id is not None else None
        product_sku = r.product_sku or ""
        cross = cross_shop_by_sku.get(product_sku) if product_sku else None
        has_cross_shop = bool(cross and cross.get("total_impressions", 0) > 0)
        items.append({
            "candidate_id":    int(r.candidate_id),
            "shop_id":         int(r.shop_id),
            "product_id":      int(r.product_id),
            "product_sku":     product_sku,
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
            "has_cross_shop":  has_cross_shop,
            "cat_id":          cat_id,
            # 仅 self 行显示真实数字, category-only 行字段置 null 让前端知道"无实证"
            "paid_orders":     (int(r.paid_orders or 0) if has_self else None),
            "paid_revenue":    (round(float(r.paid_revenue or 0), 2) if has_self else None),
            "paid_roas":       (round(float(r.paid_roas or 0), 2) if has_self else None),
            "organic_orders":  (int(r.organic_orders or 0) if has_self else None),
            "organic_impressions": (int(r.organic_impressions or 0) if has_self else None),
            "organic_add_to_cart": (int(r.organic_add_to_cart or 0) if has_self else None),
            # category evidence：给前端展示推断理由（"类目里 N 款真实搜中 · X 订单"）
            "category_evidence": evidence_by_cat.get(cat_id) if cat_id is not None else None,
            # cross_shop evidence：同 product.sku 在其他 shop 里真实搜中的汇总
            # 业务语义"这款商品在别的店已证实吃到这词流量，你店同款加进标题也会受益"
            "cross_shop_evidence": cross,
        })

    # 排序：has_self > has_cross_shop > category > _other；同层按 score DESC + orders DESC
    def _rank(it):
        if it["has_self"]:         return 0
        if it["has_cross_shop"]:   return 1  # 跨店同款优先级高于类目推断
        if it.get("category_evidence"): return 2
        return 3
    items.sort(key=lambda it: (
        _rank(it),
        -float(it.get("score") or 0),
        -(int(it.get("paid_orders") or 0) + int(it.get("organic_orders") or 0)),
    ))

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


def _fetch_cross_shop_evidence(
    db: Session, tenant_id: int, current_shop_id: int,
    product_skus: List[str], keyword: str, days: int = 30,
) -> dict:
    """对一批 products.sku，查它们在 current_shop 之外的其他 shop 的 product_search_queries 真实搜中汇总。

    业务意图：同款商品跨店 SEO 共享 — A 店 WB-Shario 的 SK-E0001 搜中 189 曝光时，
    B 店 OZON-Shario 的 SK-E0001 若 0 曝光应感知"同款已证明可行"这一信号。

    返回 {product_sku: {other_shops_count, total_impressions, total_orders, total_add_to_cart, total_frequency, top_shops}}
    top_shops: 前 3 个有证据的 shop [{shop_id, shop_name, platform, platform_sku_id, impressions, orders}]
    """
    if not product_skus:
        return {}

    rows = db.execute(
        text(f"""
            SELECT p.sku                       AS product_sku,
                   q.shop_id                   AS shop_id,
                   s.name                      AS shop_name,
                   s.platform                  AS platform,
                   ANY_VALUE(pl.platform_sku_id) AS platform_sku_id,
                   SUM(q.frequency)            AS total_frequency,
                   SUM(q.impressions)          AS total_impressions,
                   SUM(q.add_to_cart)          AS total_add_to_cart,
                   SUM(q.orders)               AS total_orders
            FROM product_search_queries q
            JOIN products p ON p.id = q.product_id AND p.tenant_id = q.tenant_id
            JOIN shops    s ON s.id = q.shop_id   AND s.tenant_id = q.tenant_id
            LEFT JOIN platform_listings pl ON pl.product_id = p.id
                                           AND pl.tenant_id = p.tenant_id
                                           AND pl.shop_id = q.shop_id
                                           AND pl.status NOT IN ('deleted', 'archived')
            WHERE q.tenant_id = :tid
              AND q.shop_id != :current_sid
              AND p.sku IN :skus
              AND LOWER(q.query_text) = LOWER(:kw)
              AND q.stat_date >= :since
            GROUP BY p.sku, q.shop_id, s.name, s.platform
            ORDER BY SUM(q.impressions) DESC
        """).bindparams(bindparam("skus", expanding=True)),
        {
            "tid": tenant_id, "current_sid": current_shop_id,
            "skus": product_skus, "kw": keyword,
            "since": datetime.now(timezone.utc).date() - timedelta(days=days),
        },
    ).fetchall()

    out: dict = {}
    for r in rows:
        sku = r.product_sku
        if not sku:
            continue
        bucket = out.setdefault(sku, {
            "product_sku": sku,
            "other_shops_count": 0,
            "total_impressions": 0,
            "total_orders":      0,
            "total_add_to_cart": 0,
            "total_frequency":   0,
            "top_shops":         [],
        })
        bucket["other_shops_count"] += 1
        bucket["total_impressions"] += int(r.total_impressions or 0)
        bucket["total_orders"]      += int(r.total_orders or 0)
        bucket["total_add_to_cart"] += int(r.total_add_to_cart or 0)
        bucket["total_frequency"]   += int(r.total_frequency or 0)
        if len(bucket["top_shops"]) < 3:
            bucket["top_shops"].append({
                "shop_id":         int(r.shop_id),
                "shop_name":       r.shop_name or "",
                "platform":        r.platform or "",
                "platform_sku_id": r.platform_sku_id or "",
                "impressions":     int(r.total_impressions or 0),
                "orders":          int(r.total_orders or 0),
                "add_to_cart":     int(r.total_add_to_cart or 0),
            })
    return out


def list_cross_shop_top_products(
    db: Session, tenant_id: int, shop,
    *, keyword: str, product_sku: str, limit: int = 10,
) -> dict:
    """弹窗展示：该 products.sku 在当前 shop 之外的其他 shop 里真实搜中的全部 listing 明细"""
    if not keyword or not keyword.strip() or not product_sku:
        return {"code": 10002, "msg": "keyword / product_sku 不能为空"}

    rows = db.execute(text("""
        SELECT q.shop_id,
               s.name     AS shop_name,
               s.platform AS platform,
               ANY_VALUE(COALESCE(pl.title_ru, p.name_ru, p.name_zh, '')) AS title,
               ANY_VALUE(p.image_url)          AS image_url,
               ANY_VALUE(pl.platform_sku_id)   AS platform_sku_id,
               SUM(q.frequency)                AS total_frequency,
               SUM(q.impressions)              AS total_impressions,
               SUM(q.add_to_cart)              AS total_add_to_cart,
               SUM(q.orders)                   AS total_orders
        FROM product_search_queries q
        JOIN products p ON p.id = q.product_id AND p.tenant_id = q.tenant_id
        JOIN shops    s ON s.id = q.shop_id   AND s.tenant_id = q.tenant_id
        LEFT JOIN platform_listings pl ON pl.product_id = p.id
                                       AND pl.tenant_id = p.tenant_id
                                       AND pl.shop_id = q.shop_id
                                       AND pl.status NOT IN ('deleted', 'archived')
        WHERE q.tenant_id = :tid
          AND q.shop_id != :current_sid
          AND p.sku = :sku
          AND LOWER(q.query_text) = LOWER(:kw)
          AND q.stat_date >= CURDATE() - INTERVAL 30 DAY
        GROUP BY q.shop_id, s.name, s.platform
        ORDER BY SUM(q.impressions) DESC, SUM(q.orders) DESC
        LIMIT :lim
    """), {
        "tid": tenant_id, "current_sid": shop.id, "sku": product_sku,
        "kw": keyword.strip(), "lim": limit,
    }).fetchall()

    items = [{
        "shop_id":         int(r.shop_id),
        "shop_name":       r.shop_name or "",
        "platform":        r.platform or "",
        "title":           r.title or "",
        "image_url":       r.image_url or "",
        "platform_sku_id": r.platform_sku_id or "",
        "total_frequency":   int(r.total_frequency or 0),
        "total_impressions": int(r.total_impressions or 0),
        "total_add_to_cart": int(r.total_add_to_cart or 0),
        "total_orders":      int(r.total_orders or 0),
    } for r in rows]
    return {"code": 0, "data": {
        "keyword": keyword.strip(), "product_sku": product_sku, "items": items,
    }}


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
