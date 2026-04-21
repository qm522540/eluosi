"""SEO 关键词表现追踪 — 核心词日趋势 + 环比下滑预警

回答用户的核心问题："哪些核心词正在带曝光带订单？哪些在掉？该重点改哪个商品？"

功能：
- 按 query_text 聚合 product_search_queries，对比"最近 N 天"vs"上 N 天"
- 曝光/订单/加购/营收 4 维度的绝对值 + 环比变化%
- 下滑预警：曝光掉 ≥30% 标 drop，从 ≥50 掉到 0 标 vanish
- 新词识别：prev=0 且 cur>0 标 new
- 涉及商品列表：点词回查"哪些商品靠它带流量"

数据源：
- WB   POST /api/v2/search-report/product/search-texts（需 Jam 订阅）
- Ozon POST /v1/analytics/product-queries/details   （需 Premium 订阅）
- 两平台 median_position 暂不可用（Ozon API 不返），position 维度走 data_insufficient 兜底

规则合规：
- 规则 1 tenant_id：所有 SQL WHERE 都带
- 规则 2 datetime.now(timezone.utc)：今日锚定
- 规则 4 shop_id：所有 WHERE 带（API 层 get_owned_shop 守卫）
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session


# ==================== 趋势分类 ====================

def _classify_trend(imp_cur: int, imp_prev: int) -> tuple[str, Optional[float]]:
    """返回 (trend, delta_pct)。

    trend: new / up / stable / down / vanish / idle
    delta_pct: None 代表上期为 0 无法计算环比
    """
    if imp_prev == 0 and imp_cur == 0:
        return "idle", None
    if imp_prev == 0 and imp_cur > 0:
        return "new", None
    if imp_cur == 0 and imp_prev > 0:
        return "vanish", -100.0
    delta = (imp_cur - imp_prev) / imp_prev * 100
    if delta >= 20:
        return "up", round(delta, 1)
    if delta <= -20:
        return "down", round(delta, 1)
    return "stable", round(delta, 1)


def _compute_alert(imp_cur: int, imp_prev: int, ord_cur: int, ord_prev: int) -> Optional[str]:
    """预警规则（宽进严出，只在明显异常时报）:
    - vanish: 上期曝光 ≥ 50 且本期 0
    - drop:   上期曝光 ≥ 20 且本期 / 上期 ≤ 0.7
    - orders_drop: 上期订单 ≥ 2 且本期 0
    - 其他无预警
    """
    if imp_prev >= 50 and imp_cur == 0:
        return "vanish"
    if imp_prev >= 20 and imp_cur / imp_prev <= 0.7:
        return "drop"
    if ord_prev >= 2 and ord_cur == 0:
        return "orders_drop"
    return None


# ==================== 主入口 ====================

def compute_keyword_tracking(
    db: Session,
    tenant_id: int,
    shop,  # Shop ORM 对象（API 层 get_owned_shop 已守卫）
    date_range: int = 7,
    sort: str = "impressions_desc",
    keyword: str = "",
    min_impressions: int = 0,
    alert_only: bool = False,
    page: int = 1,
    size: int = 20,
) -> dict:
    """计算店铺核心词追踪数据。

    date_range: 本期长度（天），默认 7。上期同长度紧邻其前。
    返回:
        {"code": 0, "data": {data_status, period, totals, items, page, size, total}}
    """
    shop_id = shop.id
    platform = shop.platform

    # ---------- 日期段计算（基于 UTC today，不依赖数据分布）----------
    today = datetime.now(timezone.utc).date()
    cur_end = today
    cur_start = today - timedelta(days=date_range - 1)
    prev_end = cur_start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=date_range - 1)

    period = {
        "cur_start": cur_start.isoformat(),
        "cur_end": cur_end.isoformat(),
        "prev_start": prev_start.isoformat(),
        "prev_end": prev_end.isoformat(),
        "days": date_range,
    }

    # ---------- 数据就绪度检查：若两期全无数据，返 not_ready ----------
    check_sql = text("""
        SELECT COUNT(*) AS n, MIN(stat_date) AS min_d, MAX(stat_date) AS max_d
        FROM product_search_queries
        WHERE tenant_id = :tid
          AND shop_id = :sid
          AND stat_date BETWEEN :prev_start AND :cur_end
    """)
    check = db.execute(check_sql, {
        "tid": tenant_id, "sid": shop_id,
        "prev_start": prev_start, "cur_end": cur_end,
    }).fetchone()
    total_rows = int(check.n or 0)

    if total_rows == 0:
        hint_by_platform = {
            "wb": "WB 数据来源 POST /api/v2/search-report/product/search-texts，需 Jam 订阅。",
            "ozon": "Ozon 数据来源 POST /v1/analytics/product-queries/details，需 Premium 订阅。",
            "yandex": "Yandex Market 暂不支持商品级搜索词洞察。",
        }
        return {"code": 0, "data": {
            "data_status": "not_ready",
            "platform": platform,
            "period": period,
            "hint": hint_by_platform.get(platform, "本平台暂无搜索词数据"),
            "totals": {"total_queries": 0, "drop_alert_count": 0, "new_count": 0, "sum_impressions_cur": 0, "sum_orders_cur": 0},
            "items": [],
            "page": page, "size": size, "total": 0,
        }}

    # ---------- 聚合 SQL ----------
    agg_sql = text("""
        SELECT
            query_text,
            SUM(CASE WHEN stat_date BETWEEN :cur_start AND :cur_end THEN impressions ELSE 0 END) AS imp_cur,
            SUM(CASE WHEN stat_date BETWEEN :prev_start AND :prev_end THEN impressions ELSE 0 END) AS imp_prev,
            SUM(CASE WHEN stat_date BETWEEN :cur_start AND :cur_end THEN clicks ELSE 0 END) AS clk_cur,
            SUM(CASE WHEN stat_date BETWEEN :prev_start AND :prev_end THEN clicks ELSE 0 END) AS clk_prev,
            SUM(CASE WHEN stat_date BETWEEN :cur_start AND :cur_end THEN add_to_cart ELSE 0 END) AS cart_cur,
            SUM(CASE WHEN stat_date BETWEEN :prev_start AND :prev_end THEN add_to_cart ELSE 0 END) AS cart_prev,
            SUM(CASE WHEN stat_date BETWEEN :cur_start AND :cur_end THEN orders ELSE 0 END) AS ord_cur,
            SUM(CASE WHEN stat_date BETWEEN :prev_start AND :prev_end THEN orders ELSE 0 END) AS ord_prev,
            SUM(CASE WHEN stat_date BETWEEN :cur_start AND :cur_end THEN revenue ELSE 0 END) AS rev_cur,
            SUM(CASE WHEN stat_date BETWEEN :prev_start AND :prev_end THEN revenue ELSE 0 END) AS rev_prev,
            COUNT(DISTINCT platform_sku_id) AS skus_involved,
            AVG(CASE WHEN stat_date BETWEEN :cur_start AND :cur_end AND median_position IS NOT NULL THEN median_position END) AS avg_pos_cur
        FROM product_search_queries
        WHERE tenant_id = :tid
          AND shop_id = :sid
          AND stat_date BETWEEN :prev_start AND :cur_end
          AND (:kw = '' OR query_text LIKE :kw_like)
        GROUP BY query_text
    """)
    params = {
        "tid": tenant_id, "sid": shop_id,
        "cur_start": cur_start, "cur_end": cur_end,
        "prev_start": prev_start, "prev_end": prev_end,
        "kw": keyword, "kw_like": f"%{keyword}%" if keyword else "",
    }
    rows = db.execute(agg_sql, params).fetchall()

    # ---------- Python 层：趋势/预警计算 + 过滤 ----------
    items = []
    totals = {
        "total_queries": 0,
        "drop_alert_count": 0,
        "new_count": 0,
        "sum_impressions_cur": 0,
        "sum_orders_cur": 0,
    }
    has_position_any = False

    for r in rows:
        imp_cur = int(r.imp_cur or 0)
        imp_prev = int(r.imp_prev or 0)
        ord_cur = int(r.ord_cur or 0)
        ord_prev = int(r.ord_prev or 0)

        if imp_cur < min_impressions and imp_prev < min_impressions:
            continue

        trend, delta_pct = _classify_trend(imp_cur, imp_prev)
        alert = _compute_alert(imp_cur, imp_prev, ord_cur, ord_prev)

        if alert_only and not alert:
            continue

        avg_pos = float(r.avg_pos_cur) if r.avg_pos_cur is not None else None
        if avg_pos is not None:
            has_position_any = True

        items.append({
            "query_text": r.query_text,
            "impressions_cur": imp_cur,
            "impressions_prev": imp_prev,
            "clicks_cur": int(r.clk_cur or 0),
            "clicks_prev": int(r.clk_prev or 0),
            "cart_cur": int(r.cart_cur or 0),
            "cart_prev": int(r.cart_prev or 0),
            "orders_cur": ord_cur,
            "orders_prev": ord_prev,
            "revenue_cur": float(r.rev_cur or 0),
            "revenue_prev": float(r.rev_prev or 0),
            "impressions_delta_pct": delta_pct,
            "trend": trend,
            "alert": alert,
            "skus_involved": int(r.skus_involved or 0),
            "avg_position": round(avg_pos, 2) if avg_pos is not None else None,
        })

        totals["total_queries"] += 1
        totals["sum_impressions_cur"] += imp_cur
        totals["sum_orders_cur"] += ord_cur
        if alert:
            totals["drop_alert_count"] += 1
        if trend == "new":
            totals["new_count"] += 1

    # ---------- 排序 ----------
    if sort == "impressions_desc":
        items.sort(key=lambda x: -x["impressions_cur"])
    elif sort == "orders_desc":
        items.sort(key=lambda x: (-x["orders_cur"], -x["impressions_cur"]))
    elif sort == "drop_desc":
        # 最大跌幅优先（alert 优先 + delta 升序）
        rank = {"vanish": 0, "drop": 1, "orders_drop": 2, None: 3}
        items.sort(key=lambda x: (rank.get(x["alert"], 99),
                                  x["impressions_delta_pct"] if x["impressions_delta_pct"] is not None else 0))
    elif sort == "new_desc":
        items.sort(key=lambda x: (0 if x["trend"] == "new" else 1, -x["impressions_cur"]))
    else:  # impressions_desc fallback
        items.sort(key=lambda x: -x["impressions_cur"])

    # ---------- 分页 ----------
    total_count = len(items)
    offset = (page - 1) * size
    page_items = items[offset:offset + size]

    return {"code": 0, "data": {
        "data_status": "ready",
        "platform": platform,
        "period": period,
        "has_position_data": has_position_any,
        "position_hint": None if has_position_any else "当前平台 API 不返回商品搜索排名字段，position 维度已豁免",
        "totals": totals,
        "items": page_items,
        "page": page, "size": size, "total": total_count,
    }}


# ==================== 单词详情（涉及商品下钻）====================

def list_query_top_skus(
    db: Session,
    tenant_id: int,
    shop,
    query_text: str,
    date_range: int = 7,
    limit: int = 10,
) -> dict:
    """给定一个核心词，返回带该词曝光/订单最多的 Top N 商品。

    用途：用户点某个词后展开抽屉，看"这词靠哪几个商品撑起来"。
    """
    shop_id = shop.id
    today = datetime.now(timezone.utc).date()
    cur_end = today
    cur_start = today - timedelta(days=date_range - 1)

    sql = text("""
        SELECT
            psq.platform_sku_id,
            psq.product_id,
            ANY_VALUE(p.name_zh) AS name_zh,
            ANY_VALUE(p.image_url) AS image_url,
            ANY_VALUE(pl.title_ru) AS title_ru,
            SUM(psq.impressions) AS imp,
            SUM(psq.clicks) AS clk,
            SUM(psq.add_to_cart) AS cart,
            SUM(psq.orders) AS ords,
            SUM(psq.revenue) AS rev,
            AVG(psq.median_position) AS avg_pos
        FROM product_search_queries psq
        LEFT JOIN products p
            ON p.id = psq.product_id
           AND p.tenant_id = psq.tenant_id
        LEFT JOIN platform_listings pl
            ON pl.product_id = psq.product_id
           AND pl.tenant_id = psq.tenant_id
           AND pl.shop_id = psq.shop_id
           AND pl.status NOT IN ('deleted', 'archived')
        WHERE psq.tenant_id = :tid
          AND psq.shop_id = :sid
          AND psq.query_text = :q
          AND psq.stat_date BETWEEN :cur_start AND :cur_end
        GROUP BY psq.platform_sku_id, psq.product_id
        ORDER BY imp DESC
        LIMIT :lim
    """)
    rows = db.execute(sql, {
        "tid": tenant_id, "sid": shop_id, "q": query_text,
        "cur_start": cur_start, "cur_end": cur_end,
        "lim": limit,
    }).fetchall()

    items = [{
        "platform_sku_id": r.platform_sku_id,
        "product_id": int(r.product_id) if r.product_id else None,
        "product_name": r.name_zh or "",
        "image_url": r.image_url,
        "title_ru": r.title_ru or "",
        "impressions": int(r.imp or 0),
        "clicks": int(r.clk or 0),
        "cart": int(r.cart or 0),
        "orders": int(r.ords or 0),
        "revenue": float(r.rev or 0),
        "avg_position": round(float(r.avg_pos), 2) if r.avg_pos is not None else None,
    } for r in rows]

    return {"code": 0, "data": {
        "query_text": query_text,
        "period": {"start": cur_start.isoformat(), "end": cur_end.isoformat(), "days": date_range},
        "items": items,
        "total": len(items),
    }}
