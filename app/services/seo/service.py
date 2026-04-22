"""SEO 候选词池引擎：多源融合（付费 + 自然搜索）

源接入状态：
- 源 A  paid self     本商品付费词    依赖 ad_keywords + ad_stats（WB/Ozon 当前都缺数据）
- 源 A' paid category 同类目付费聚合  同上
- 源 B  organic self  本商品自然搜索词 依赖 product_search_queries（Ozon Premium 通后有数据）
- 源 B' organic category 同类目自然词  同上
- 源 C  Wordstat 搜索引擎趋势         三期 Yandex OAuth 通后接

核心函数：
- analyze_paid_to_organic: 刷引擎，扫近 N 天 → upsert 候选池
- list_candidates:          分页查询候选 + 统计 4 格汇总
- adopt_candidate:          用户点"加入标题"
- ignore_candidates:        批量忽略（数组入参）
"""

import json
import math
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import text, bindparam
from sqlalchemy.orm import Session

from app.utils.errors import ErrorCode


# ==================== 引擎：刷候选池 ====================

def analyze_paid_to_organic(
    db: Session, tenant_id: int, shop,
    days: int = 30, roas_threshold: float = 2.0, min_orders: int = 1,
) -> dict:
    """付费词反哺引擎：两维度聚合 → 候选词池 upsert。

    scope='self' 本商品自己的付费词（Source A）
    scope='category' 同 local_category_id 其他商品 ≥3 个共享的词（Source C1-a）

    规则 1：所有 SQL 带 tenant_id；upsert SET tenant_id。
    规则 4：shop 由路由层 get_owned_shop 校验属当前租户。
    """
    today = datetime.now(timezone.utc).date()
    since = today - timedelta(days=days)

    candidates = {}  # (product_id, keyword_lower) -> dict

    # ===== Step A: 商品维 =====
    # P0-1 修 2026-04-19：原 GROUP BY 含 pl.variant_attrs (JSON) 在 sql_mode=
    # ONLY_FULL_GROUP_BY 下兼容风险（部分 MySQL 版本报 3908）。改 GROUP BY
    # 到 (keyword, product_id) 主键层，其他 SELECT 字段用 ANY_VALUE 包裹。
    self_sql = text("""
        SELECT
            kw.keyword AS keyword,
            p.id AS product_id,
            ANY_VALUE(p.local_category_id) AS cat_id,
            ANY_VALUE(COALESCE(pl.title_ru, '')) AS title,
            ANY_VALUE(COALESCE(CAST(pl.variant_attrs AS CHAR), '')) AS attrs,
            SUM(s.impressions) AS imps,
            SUM(s.clicks) AS clicks,
            SUM(s.orders) AS orders,
            SUM(s.spend) AS spend,
            SUM(s.revenue) AS revenue
        FROM ad_keywords kw
        JOIN ad_groups g ON g.id = kw.ad_group_id AND g.tenant_id = kw.tenant_id
        JOIN ad_campaigns c ON c.id = g.campaign_id AND c.tenant_id = kw.tenant_id
        JOIN platform_listings pl ON pl.id = g.listing_id AND pl.tenant_id = kw.tenant_id
        JOIN products p ON p.id = pl.product_id AND p.tenant_id = kw.tenant_id
        LEFT JOIN ad_stats s ON s.keyword_id = kw.id
                             AND s.tenant_id = kw.tenant_id
                             AND s.stat_date >= :since
        WHERE kw.tenant_id = :tid
          AND c.shop_id = :sid
          AND kw.is_negative = 0
          AND (p.status != 'deleted' OR p.status IS NULL)
        GROUP BY kw.keyword, p.id
        HAVING SUM(s.orders) >= :min_orders
           AND SUM(s.spend) > 0
           AND (SUM(s.revenue) / SUM(s.spend)) >= :roas_th
    """)
    self_rows = db.execute(self_sql, {
        "tid": tenant_id, "sid": shop.id, "since": since,
        "min_orders": min_orders, "roas_th": float(roas_threshold),
    }).fetchall()

    for r in self_rows:
        kw = (r.keyword or "").strip().lower()
        if not kw:
            continue
        key = (r.product_id, kw)
        roas = (float(r.revenue) / float(r.spend)) if r.spend else 0.0
        cand = candidates.setdefault(key, _new_candidate(r.product_id, kw))
        cand["sources"].append({"type": "paid", "scope": "self"})
        cand["paid_roas"] = round(roas, 2)
        cand["paid_orders"] = int(r.orders or 0)
        cand["paid_spend"] = round(float(r.spend or 0), 2)
        cand["paid_revenue"] = round(float(r.revenue or 0), 2)
        cand["_title"] = r.title or ""
        cand["_attrs"] = r.attrs or ""
        cand["_cat_id"] = r.cat_id

    # ===== Step B: 类目维聚合 —— 哪些 (cat, keyword) 在 ≥3 个商品上都有转化 =====
    cat_sql = text("""
        SELECT
            kw.keyword AS keyword,
            p.local_category_id AS cat_id,
            COUNT(DISTINCT p.id) AS shared_products,
            SUM(s.orders) AS orders,
            SUM(s.spend) AS spend,
            SUM(s.revenue) AS revenue
        FROM ad_keywords kw
        JOIN ad_groups g ON g.id = kw.ad_group_id AND g.tenant_id = kw.tenant_id
        JOIN ad_campaigns c ON c.id = g.campaign_id AND c.tenant_id = kw.tenant_id
        JOIN platform_listings pl ON pl.id = g.listing_id AND pl.tenant_id = kw.tenant_id
        JOIN products p ON p.id = pl.product_id AND p.tenant_id = kw.tenant_id
        LEFT JOIN ad_stats s ON s.keyword_id = kw.id
                             AND s.tenant_id = kw.tenant_id
                             AND s.stat_date >= :since
        WHERE kw.tenant_id = :tid
          AND c.shop_id = :sid
          AND kw.is_negative = 0
          AND p.local_category_id IS NOT NULL
          AND (p.status != 'deleted' OR p.status IS NULL)
        GROUP BY kw.keyword, p.local_category_id
        HAVING COUNT(DISTINCT p.id) >= 3
           AND SUM(s.orders) >= :min_orders
           AND SUM(s.spend) > 0
           AND (SUM(s.revenue) / SUM(s.spend)) >= :roas_th
    """)
    cat_rows = db.execute(cat_sql, {
        "tid": tenant_id, "sid": shop.id, "since": since,
        "min_orders": min_orders, "roas_th": float(roas_threshold),
    }).fetchall()

    cat_kw_map = {}  # cat_id -> [(kw_lower, orders, spend, revenue), ...]
    for r in cat_rows:
        kw = (r.keyword or "").strip().lower()
        if not kw:
            continue
        cat_kw_map.setdefault(r.cat_id, []).append(
            (kw, int(r.orders or 0), float(r.spend or 0), float(r.revenue or 0))
        )

    # ===== Step C: 把类目维词扩散到同类目所有商品 =====
    # P0-2 修 2026-04-19：同商品可能有多个 platform_listings（variant 变体 /
    # 已归档），不过滤 + 不聚合会出笛卡尔积。后续 Step D dict 去重时 _title/
    # _attrs 被随机覆盖，覆盖判断不稳。修法：过滤死 listings + GROUP BY p.id
    # + ANY_VALUE 取 title/attrs 其一（同商品的 variants title 基本一致）。
    if cat_kw_map:
        prod_sql = text("""
            SELECT
                p.id AS product_id,
                ANY_VALUE(p.local_category_id) AS cat_id,
                ANY_VALUE(COALESCE(pl.title_ru, '')) AS title,
                ANY_VALUE(COALESCE(CAST(pl.variant_attrs AS CHAR), '')) AS attrs
            FROM products p
            JOIN platform_listings pl ON pl.product_id = p.id
                                       AND pl.tenant_id = p.tenant_id
            WHERE p.tenant_id = :tid
              AND pl.shop_id = :sid
              AND pl.status NOT IN ('deleted', 'archived')
              AND p.local_category_id IN :cat_ids
              AND (p.status != 'deleted' OR p.status IS NULL)
            GROUP BY p.id
        """).bindparams(bindparam("cat_ids", expanding=True))

        prod_rows = db.execute(prod_sql, {
            "tid": tenant_id, "sid": shop.id,
            "cat_ids": list(cat_kw_map.keys()),
        }).fetchall()

        for pr in prod_rows:
            for kw, orders, spend, revenue in cat_kw_map.get(pr.cat_id, []):
                key = (pr.product_id, kw)
                cand = candidates.setdefault(key, _new_candidate(pr.product_id, kw))
                already_cat = any(
                    s["type"] == "paid" and s["scope"] == "category"
                    for s in cand["sources"]
                )
                if not already_cat:
                    cand["sources"].append({"type": "paid", "scope": "category"})
                # 类目指标不覆盖更强的商品维信号，仅在 self 未命中时填
                if cand.get("paid_roas") is None:
                    roas = (revenue / spend) if spend else 0.0
                    cand["paid_roas"] = round(roas, 2)
                    cand["paid_orders"] = orders
                    cand["paid_spend"] = round(spend, 2)
                    cand["paid_revenue"] = round(revenue, 2)
                cand["_title"] = pr.title or ""
                cand["_attrs"] = pr.attrs or ""
                cand["_cat_id"] = pr.cat_id

    # ===== Step E: 自然搜索词 (源 B self) 从 product_search_queries 聚合 =====
    # 门槛：近 N 天 frequency ≥ 5 或 orders ≥ 1。降低 scale 过滤 —— 这是 SEO 机会词
    # 的直接信号（用户实际搜到你商品），比 ROAS 门槛更直接。
    organic_self_sql = text("""
        SELECT
            q.query_text AS keyword,
            q.product_id AS product_id,
            ANY_VALUE(p.local_category_id) AS cat_id,
            ANY_VALUE(COALESCE(pl.title_ru, '')) AS title,
            ANY_VALUE(COALESCE(CAST(pl.variant_attrs AS CHAR), '')) AS attrs,
            SUM(q.frequency) AS frequency,
            SUM(q.impressions) AS impressions,
            SUM(q.add_to_cart) AS add_to_cart,
            SUM(q.orders) AS orders,
            SUM(q.revenue) AS revenue
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
          AND (p.status != 'deleted' OR p.status IS NULL)
        GROUP BY q.query_text, q.product_id
        HAVING SUM(q.frequency) >= 5 OR SUM(q.orders) >= 1
    """)
    org_self_rows = db.execute(organic_self_sql, {
        "tid": tenant_id, "sid": shop.id, "since": since,
    }).fetchall()

    for r in org_self_rows:
        kw = (r.keyword or "").strip().lower()
        if not kw or not r.product_id:
            continue
        key = (r.product_id, kw)
        cand = candidates.setdefault(key, _new_candidate(r.product_id, kw))
        already = any(
            s["type"] == "organic" and s["scope"] == "self" for s in cand["sources"]
        )
        if not already:
            cand["sources"].append({"type": "organic", "scope": "self"})
        cand["organic_impressions"] = int(r.impressions or 0) or int(r.frequency or 0)
        cand["organic_add_to_cart"] = int(r.add_to_cart or 0)
        cand["organic_orders"] = int(r.orders or 0)
        # 若 paid 未填，用 organic title/attrs 做覆盖判断兜底
        if not cand.get("_title"):
            cand["_title"] = r.title or ""
            cand["_attrs"] = r.attrs or ""
            cand["_cat_id"] = r.cat_id

    # ===== Step F: 自然搜索词 (源 B' category) 同类目 ≥2 商品共享 =====
    organic_cat_sql = text("""
        SELECT
            q.query_text AS keyword,
            p.local_category_id AS cat_id,
            COUNT(DISTINCT p.id) AS shared_products,
            SUM(q.frequency) AS frequency,
            SUM(q.impressions) AS impressions,
            SUM(q.add_to_cart) AS add_to_cart,
            SUM(q.orders) AS orders,
            SUM(q.revenue) AS revenue
        FROM product_search_queries q
        JOIN products p ON p.id = q.product_id AND p.tenant_id = q.tenant_id
        WHERE q.tenant_id = :tid
          AND q.shop_id = :sid
          AND q.stat_date >= :since
          AND q.product_id IS NOT NULL
          AND p.local_category_id IS NOT NULL
          AND (p.status != 'deleted' OR p.status IS NULL)
        GROUP BY q.query_text, p.local_category_id
        HAVING COUNT(DISTINCT p.id) >= 2
           AND (SUM(q.frequency) >= 10 OR SUM(q.orders) >= 1)
    """)
    org_cat_rows = db.execute(organic_cat_sql, {
        "tid": tenant_id, "sid": shop.id, "since": since,
    }).fetchall()

    org_cat_kw_map = {}
    for r in org_cat_rows:
        kw = (r.keyword or "").strip().lower()
        if not kw:
            continue
        org_cat_kw_map.setdefault(r.cat_id, []).append(
            (kw, int(r.frequency or 0), int(r.impressions or 0),
             int(r.add_to_cart or 0), int(r.orders or 0))
        )

    # 把 organic 类目词扩散到同类目全部商品
    if org_cat_kw_map:
        prod_cat_sql = text("""
            SELECT
                p.id AS product_id,
                ANY_VALUE(p.local_category_id) AS cat_id,
                ANY_VALUE(COALESCE(pl.title_ru, '')) AS title,
                ANY_VALUE(COALESCE(CAST(pl.variant_attrs AS CHAR), '')) AS attrs
            FROM products p
            JOIN platform_listings pl ON pl.product_id = p.id
                                       AND pl.tenant_id = p.tenant_id
            WHERE p.tenant_id = :tid
              AND pl.shop_id = :sid
              AND pl.status NOT IN ('deleted', 'archived')
              AND p.local_category_id IN :cat_ids
              AND (p.status != 'deleted' OR p.status IS NULL)
            GROUP BY p.id
        """).bindparams(bindparam("cat_ids", expanding=True))
        prod_cat_rows = db.execute(prod_cat_sql, {
            "tid": tenant_id, "sid": shop.id,
            "cat_ids": list(org_cat_kw_map.keys()),
        }).fetchall()

        for pr in prod_cat_rows:
            for kw, freq, imp, atc, orders in org_cat_kw_map.get(pr.cat_id, []):
                key = (pr.product_id, kw)
                cand = candidates.setdefault(key, _new_candidate(pr.product_id, kw))
                already = any(
                    s["type"] == "organic" and s["scope"] == "category"
                    for s in cand["sources"]
                )
                if not already:
                    cand["sources"].append({"type": "organic", "scope": "category"})
                # 类目指标不覆盖更强的 self 信号，仅在 self 未命中时填
                if cand.get("organic_orders") is None:
                    cand["organic_impressions"] = imp or freq
                    cand["organic_add_to_cart"] = atc
                    cand["organic_orders"] = orders
                if not cand.get("_title"):
                    cand["_title"] = pr.title or ""
                    cand["_attrs"] = pr.attrs or ""
                    cand["_cat_id"] = pr.cat_id

    # ===== Step D: 覆盖判断 + 算分 + 过滤已覆盖 =====
    finalized = []
    for (pid, kw), cand in candidates.items():
        title_lower = (cand.pop("_title", "") or "").lower()
        attrs_lower = (cand.pop("_attrs", "") or "").lower()
        cand.pop("_cat_id", None)
        in_title = 1 if kw in title_lower else 0
        in_attrs = 1 if kw in attrs_lower else 0
        if in_title and in_attrs:
            continue  # 已完全覆盖，不是反哺候选
        cand["in_title"] = in_title
        cand["in_attrs"] = in_attrs
        cand["score"] = _compute_score(cand)
        finalized.append(cand)

    written = _upsert_candidates(db, tenant_id, shop.id, finalized)

    return {
        "code": ErrorCode.SUCCESS,
        "data": {
            "shop_id": shop.id,
            "analyzed_pairs": len(candidates),
            "candidates": len(finalized),
            "written": written,
            "roas_threshold": float(roas_threshold),
            "days": days,
        },
    }


def _new_candidate(product_id: int, keyword: str) -> dict:
    return {
        "product_id": product_id,
        "keyword": keyword[:200],
        "sources": [],
        "paid_roas": None,
        "paid_orders": None,
        "paid_spend": None,
        "paid_revenue": None,
        "organic_impressions": None,
        "organic_add_to_cart": None,
        "organic_orders": None,
        "wordstat_volume": None,
        "in_title": 0,
        "in_attrs": 0,
        "score": 0,
    }


def _compute_score(cand: dict) -> float:
    """综合得分：来源数×2 + ROAS + log10(付费订单+1)×2 + log10(自然曝光+1) +
       log10(自然订单+1)×2，上限 100"""
    src_count = len(cand.get("sources") or [])
    roas = float(cand.get("paid_roas") or 0)
    paid_orders = int(cand.get("paid_orders") or 0)
    org_imp = int(cand.get("organic_impressions") or 0)
    org_orders = int(cand.get("organic_orders") or 0)
    score = (
        src_count * 2
        + roas
        + math.log10(paid_orders + 1) * 2
        + math.log10(org_imp + 1)
        + math.log10(org_orders + 1) * 2
    )
    return round(min(score, 100.0), 2)


def _upsert_candidates(db: Session, tenant_id: int, shop_id: int, rows: list) -> int:
    """批量 upsert 到 seo_keyword_candidates。

    规则 1 纵深：ON DUPLICATE KEY UPDATE 含 SET tenant_id（CLAUDE.md 明文）。
    status 字段不在 UPDATE 里 —— 保留用户已 adopted/ignored 的处理状态。
    """
    if not rows:
        return 0
    sql = text("""
        INSERT INTO seo_keyword_candidates
          (tenant_id, shop_id, product_id, keyword, sources, score,
           paid_roas, paid_orders, paid_spend, paid_revenue,
           organic_impressions, organic_add_to_cart, organic_orders,
           in_title, in_attrs, status, created_at, updated_at)
        VALUES
          (:tid, :sid, :pid, :kw, :srcs, :score,
           :roas, :orders, :spend, :rev,
           :o_imp, :o_atc, :o_orders,
           :in_t, :in_a, 'pending', :now, :now)
        ON DUPLICATE KEY UPDATE
          tenant_id = VALUES(tenant_id),
          sources = VALUES(sources),
          score = VALUES(score),
          paid_roas = VALUES(paid_roas),
          paid_orders = VALUES(paid_orders),
          paid_spend = VALUES(paid_spend),
          paid_revenue = VALUES(paid_revenue),
          organic_impressions = VALUES(organic_impressions),
          organic_add_to_cart = VALUES(organic_add_to_cart),
          organic_orders = VALUES(organic_orders),
          in_title = VALUES(in_title),
          in_attrs = VALUES(in_attrs),
          updated_at = VALUES(updated_at)
    """)
    now_utc = datetime.now(timezone.utc)
    count = 0
    for r in rows:
        db.execute(sql, {
            "tid": tenant_id, "sid": shop_id,
            "pid": r["product_id"], "kw": r["keyword"],
            "srcs": json.dumps(r["sources"], ensure_ascii=False),
            "score": r["score"],
            "roas": r.get("paid_roas"),
            "orders": r.get("paid_orders"),
            "spend": r.get("paid_spend"),
            "rev": r.get("paid_revenue"),
            "o_imp": r.get("organic_impressions"),
            "o_atc": r.get("organic_add_to_cart"),
            "o_orders": r.get("organic_orders"),
            "in_t": r["in_title"], "in_a": r["in_attrs"],
            "now": now_utc,
        })
        count += 1
    db.commit()
    return count


# ==================== 查询：候选清单 ====================

def list_candidates(
    db: Session, tenant_id: int, shop,
    source_filter: str = "all", status: str = "pending",
    keyword: str = "", page: int = 1, size: int = 20,
    product_id: Optional[int] = None,
    hide_covered: bool = False,
) -> dict:
    """分页拉候选清单 + 4 格汇总。

    source_filter:
      - all            全部
      - paid_self      只来自商品维付费
      - paid_category  只来自类目维付费
      - organic_self   只来自自然搜索（本商品）
      - organic_category 只来自自然搜索（同类目）
      - with_orders    只看带真实订单的（强证据，paid_orders OR organic_orders > 0)

    product_id: 可选，只返回指定商品的候选（Health → Optimize 闭环用）
    hide_covered: True 时隐藏 in_title=1 的行（已在标题，改无意义）
    """
    page = max(1, int(page))
    size = min(max(1, int(size)), 100)
    offset = (page - 1) * size

    where_parts = ["c.tenant_id = :tid", "c.shop_id = :sid"]
    params = {"tid": tenant_id, "sid": shop.id}
    if product_id:
        where_parts.append("c.product_id = :pid")
        params["pid"] = int(product_id)
    if status and status != "all":
        where_parts.append("c.status = :st")
        params["st"] = status
    if keyword and keyword.strip():
        where_parts.append("c.keyword LIKE :kw_like")
        params["kw_like"] = f"%{keyword.strip().lower()}%"
    if source_filter == "paid_self":
        where_parts.append("JSON_CONTAINS(c.sources, JSON_OBJECT('type','paid','scope','self'))")
    elif source_filter == "paid_category":
        where_parts.append("JSON_CONTAINS(c.sources, JSON_OBJECT('type','paid','scope','category'))")
    elif source_filter == "organic_self":
        where_parts.append("JSON_CONTAINS(c.sources, JSON_OBJECT('type','organic','scope','self'))")
    elif source_filter == "organic_category":
        where_parts.append("JSON_CONTAINS(c.sources, JSON_OBJECT('type','organic','scope','category'))")
    elif source_filter == "with_orders":
        where_parts.append("(COALESCE(c.paid_orders,0) > 0 OR COALESCE(c.organic_orders,0) > 0)")
    if hide_covered:
        where_parts.append("c.in_title = 0")
    where_sql = " AND ".join(where_parts)

    # P0-3 修 2026-04-19：totals / items 的 LEFT JOIN platform_listings 无
    # listing status 过滤，同商品多 listings 时：
    # - totals.COUNT(*) 被笛卡尔积放大 → 前端 4 格数字偏高（严重数据错）
    # - items 一个 candidate 因多 listings 重复出现在分页
    # 修法：LEFT JOIN 加 pl.status 过滤 + COUNT(DISTINCT c.id) + GROUP BY c.id
    # + 其他 JOIN 字段用 ANY_VALUE 包裹。

    # 4 格 totals（不分页）
    totals_sql = text(f"""
        SELECT
            COUNT(DISTINCT c.id) AS total,
            SUM(CASE WHEN COALESCE(c.paid_orders,0) > 0
                       OR COALESCE(c.organic_orders,0) > 0
                     THEN 1 ELSE 0 END) AS with_conversion,
            SUM(CASE WHEN c.in_title = 0 AND c.in_attrs = 0 THEN 1 ELSE 0 END) AS gap,
            COUNT(DISTINCT c.product_id) AS products
        FROM seo_keyword_candidates c
        WHERE {where_sql}
    """)
    totals_row = db.execute(totals_sql, params).fetchone()

    # 分页 items，JOIN products 取商品名、类目 + listings 取标题 & 图片
    items_sql = text(f"""
        SELECT
            c.id, c.keyword, c.product_id, c.sources, c.score,
            c.paid_roas, c.paid_orders, c.paid_spend, c.paid_revenue,
            c.organic_impressions, c.organic_add_to_cart, c.organic_orders,
            c.wordstat_volume, c.in_title, c.in_attrs, c.status,
            c.adopted_at, c.adopted_by, c.updated_at,
            ANY_VALUE(p.name_zh) AS product_name,
            ANY_VALUE(p.sku) AS product_code,
            ANY_VALUE(p.local_category_id) AS cat_id,
            ANY_VALUE(pl.title_ru) AS current_title,
            ANY_VALUE(pl.oss_images) AS images
        FROM seo_keyword_candidates c
        JOIN products p ON p.id = c.product_id AND p.tenant_id = c.tenant_id
        LEFT JOIN platform_listings pl ON pl.product_id = p.id
                                       AND pl.shop_id = c.shop_id
                                       AND pl.tenant_id = c.tenant_id
                                       AND pl.status NOT IN ('deleted', 'archived')
        WHERE {where_sql}
        GROUP BY c.id
        ORDER BY (COALESCE(c.paid_orders,0) + COALESCE(c.organic_orders,0)) DESC,
                 c.score DESC,
                 COALESCE(c.organic_impressions,0) DESC
        LIMIT :offset, :size
    """)
    params2 = dict(params, offset=offset, size=size)
    rows = db.execute(items_sql, params2).fetchall()

    items = []
    for r in rows:
        src_raw = r.sources
        if isinstance(src_raw, str):
            try:
                src_raw = json.loads(src_raw)
            except Exception:
                src_raw = []
        images = r.images
        if isinstance(images, str):
            try:
                images = json.loads(images)
            except Exception:
                images = None
        first_image = None
        if isinstance(images, list) and images:
            first_image = images[0] if isinstance(images[0], str) else images[0].get("url")
        items.append({
            "id": r.id,
            "keyword": r.keyword,
            "product_id": r.product_id,
            "product_name": r.product_name,
            "product_code": r.product_code,
            "current_title": r.current_title,
            "category_id": r.cat_id,
            "image_url": first_image,
            "sources": src_raw or [],
            "score": float(r.score or 0),
            "paid_roas": float(r.paid_roas) if r.paid_roas is not None else None,
            "paid_orders": r.paid_orders,
            "paid_spend": float(r.paid_spend) if r.paid_spend is not None else None,
            "paid_revenue": float(r.paid_revenue) if r.paid_revenue is not None else None,
            "organic_impressions": r.organic_impressions,
            "organic_add_to_cart": r.organic_add_to_cart,
            "organic_orders": r.organic_orders,
            "wordstat_volume": r.wordstat_volume,
            "in_title": bool(r.in_title),
            "in_attrs": bool(r.in_attrs),
            "status": r.status,
            "adopted_at": r.adopted_at.isoformat() if r.adopted_at else None,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        })

    return {
        "code": ErrorCode.SUCCESS,
        "data": {
            "totals": {
                "total": int(totals_row.total or 0),
                "with_conversion": int(totals_row.with_conversion or 0),
                "gap": int(totals_row.gap or 0),
                "products": int(totals_row.products or 0),
            },
            "items": items,
            "page": page,
            "size": size,
        },
    }


# ==================== 跨商品爆款词发现 ====================

def list_champion_keywords(
    db: Session, tenant_id: int, shop,
    limit: int = 10,
    min_products: int = 2,
) -> dict:
    """跨商品爆款词：同一关键词在多个商品的候选池里都带过订单。

    业务价值：改一个词，全店多个商品受益。用户首屏能看到"该批量改哪个词"。

    筛选条件：
    - 带订单（paid_orders OR organic_orders > 0）—— 强证据
    - 当前商品标题/属性都没这个词（in_title=0 AND in_attrs=0）—— 真正的反哺机会
    - status = pending
    - 至少涉及 min_products 个商品（默认 2）

    排序：覆盖商品数 DESC, 总订单 DESC。
    """
    limit = min(max(1, int(limit)), 30)
    min_products = max(2, int(min_products))

    # 注意：seo_keyword_candidates 表里"类目扩散"推断商品会继承源词 orders/impressions 数字,
    # 直接 SUM 会把同一份真数据重复求和 (如 38 商品 × 2 单 → 76 单的假象).
    # 修法：只对 sources 含 {scope:'self'} 的行求真数据；推荐覆盖数另记.
    rows = db.execute(text("""
        SELECT c.keyword,
               COUNT(DISTINCT c.product_id) AS product_count,
               COUNT(DISTINCT CASE
                   WHEN JSON_CONTAINS(c.sources, JSON_OBJECT('type','organic','scope','self'))
                     OR JSON_CONTAINS(c.sources, JSON_OBJECT('type','paid','scope','self'))
                   THEN c.product_id
               END) AS self_product_count,
               SUM(CASE
                   WHEN JSON_CONTAINS(c.sources, JSON_OBJECT('type','organic','scope','self'))
                     OR JSON_CONTAINS(c.sources, JSON_OBJECT('type','paid','scope','self'))
                   THEN COALESCE(c.paid_orders,0) + COALESCE(c.organic_orders,0)
                   ELSE 0
               END) AS total_orders,
               SUM(CASE
                   WHEN JSON_CONTAINS(c.sources, JSON_OBJECT('type','organic','scope','self'))
                   THEN COALESCE(c.organic_impressions,0)
                   ELSE 0
               END) AS total_impr,
               ROUND(MAX(c.score), 1) AS max_score,
               SUBSTRING_INDEX(
                   GROUP_CONCAT(DISTINCT p.name_zh ORDER BY p.id SEPARATOR '|'),
                   '|', 3
               ) AS top_product_names
        FROM seo_keyword_candidates c
        JOIN products p ON p.id = c.product_id AND p.tenant_id = c.tenant_id
        WHERE c.tenant_id = :tid
          AND c.shop_id = :sid
          AND (COALESCE(c.paid_orders,0) > 0 OR COALESCE(c.organic_orders,0) > 0)
          AND c.in_title = 0 AND c.in_attrs = 0
          AND c.status = 'pending'
        GROUP BY c.keyword
        HAVING product_count >= :minp AND self_product_count >= 1
        ORDER BY total_orders DESC, product_count DESC
        LIMIT :lim
    """), {
        "tid": tenant_id, "sid": shop.id,
        "minp": min_products, "lim": limit,
    }).fetchall()

    items = [
        {
            "keyword": r.keyword,
            "product_count": int(r.product_count or 0),
            "self_product_count": int(r.self_product_count or 0),
            "total_orders": int(r.total_orders or 0),
            "total_impressions": int(r.total_impr or 0),
            "max_score": float(r.max_score or 0),
            "top_product_names": (r.top_product_names or "").split("|")[:3],
        }
        for r in rows
    ]

    return {"code": ErrorCode.SUCCESS, "data": {"items": items}}


# ==================== 用户处理：adopt / ignore ====================

def adopt_candidate(
    db: Session, tenant_id: int, shop_id: int,
    candidate_id: int, user_id: Optional[int] = None,
) -> dict:
    """标记"加入标题"。只改候选池状态，不改 products.title（三期再做）。"""
    row = db.execute(text("""
        SELECT id, status FROM seo_keyword_candidates
        WHERE id = :cid AND tenant_id = :tid AND shop_id = :sid
    """), {"cid": candidate_id, "tid": tenant_id, "sid": shop_id}).fetchone()
    if not row:
        return {"code": ErrorCode.SEO_CANDIDATE_NOT_FOUND, "msg": "候选词不存在"}
    if row.status not in ("pending", "ignored"):
        return {"code": ErrorCode.SEO_CANDIDATE_INVALID_STATUS,
                "msg": f"当前状态 {row.status} 不允许 adopt"}

    now_utc = datetime.now(timezone.utc)
    db.execute(text("""
        UPDATE seo_keyword_candidates
        SET status = 'adopted', adopted_at = :now, adopted_by = :uid, updated_at = :now
        WHERE id = :cid AND tenant_id = :tid AND shop_id = :sid
    """), {"cid": candidate_id, "tid": tenant_id, "sid": shop_id,
           "now": now_utc, "uid": user_id})
    db.commit()
    return {"code": ErrorCode.SUCCESS, "data": {"id": candidate_id, "status": "adopted"}}


def ignore_candidates(
    db: Session, tenant_id: int, shop_id: int, ids: list,
) -> dict:
    """批量忽略（幂等）。已 adopted 的跳过。"""
    if not ids:
        return {"code": ErrorCode.SUCCESS, "data": {"updated": 0}}
    sql = text("""
        UPDATE seo_keyword_candidates
        SET status = 'ignored', updated_at = :now
        WHERE id IN :ids AND tenant_id = :tid AND shop_id = :sid
          AND status = 'pending'
    """).bindparams(bindparam("ids", expanding=True))
    res = db.execute(sql, {
        "ids": list(ids), "tid": tenant_id, "sid": shop_id,
        "now": datetime.now(timezone.utc),
    })
    db.commit()
    return {"code": ErrorCode.SUCCESS,
            "data": {"updated": res.rowcount}}
