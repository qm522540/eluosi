"""SEO Before/After ROI 报表 — 改标题效果对比

业务问题：用户改了 N 个商品的标题后，到底有没有效果？多少曝光提升？多少订单提升？

逻辑：
- 找所有 approval_status='applied' 的 SeoGeneratedContent（用户确认"我已改到平台"）
- applied_at 作为切割点
  - Before 窗口: applied_at - window_days ~ applied_at - 1 天（闭区间）
  - After  窗口: applied_at ~ applied_at + window_days - 1 天
- 从 product_search_queries 按 platform_sku_id + 日期窗口聚合 曝光/订单/营收
- 计算 delta% = (after - before) / before × 100，before=0 时 delta=null 标记 new

状态分类：
- observing: applied_at 距今 < window_days，observation 不完整
- completed: observation 已满 window_days

空态：0 条 applied 时返 total_applied=0，前端渲染引导"去 Report 标记已用积累数据"。

规则 1 tenant_id / 规则 4 shop_id：所有 SQL 三层过滤。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session


def _delta_pct(after: float, before: float) -> Optional[float]:
    """计算环比百分比。before=0 时返 None（前端显示为"新增/零基线"）。"""
    if before <= 0:
        return None
    return round((after - before) / before * 100, 1)


def compute_roi_report(
    db: Session,
    tenant_id: int,
    shop,  # Shop ORM 对象
    window_days: int = 14,
) -> dict:
    """计算店铺所有 applied 记录的 Before/After ROI 对比。

    Returns:
        {"code": 0, "data": {window_days, totals, items, empty_hint}}
    """
    shop_id = shop.id
    platform = shop.platform
    now_utc = datetime.now(timezone.utc)
    today = now_utc.date()

    # ---------- SQL 1: 拉所有 applied 记录 + 商品信息 ----------
    applied_sql = text("""
        SELECT
            g.id AS gid,
            g.listing_id,
            g.original_text,
            g.generated_text,
            g.keywords_used,
            g.ai_model,
            g.approved_by,
            g.applied_at,
            g.created_at,
            ANY_VALUE(pl.product_id) AS product_id,
            ANY_VALUE(pl.platform_sku_id) AS platform_sku_id,
            ANY_VALUE(pl.title_ru) AS current_title,
            ANY_VALUE(p.name_zh) AS product_name,
            ANY_VALUE(p.image_url) AS image_url
        FROM seo_generated_contents g
        JOIN platform_listings pl ON pl.id = g.listing_id
                                   AND pl.tenant_id = g.tenant_id
                                   AND pl.shop_id = :sid
        LEFT JOIN products p ON p.id = pl.product_id
                              AND p.tenant_id = pl.tenant_id
                              AND p.shop_id = pl.shop_id
        WHERE g.tenant_id = :tid
          AND g.content_type = 'title'
          AND g.approval_status = 'applied'
          AND g.applied_at IS NOT NULL
        GROUP BY g.id
        ORDER BY g.applied_at DESC
    """)
    applied_rows = db.execute(applied_sql, {"tid": tenant_id, "sid": shop_id}).fetchall()

    if not applied_rows:
        return {"code": 0, "data": {
            "window_days": window_days,
            "platform": platform,
            "totals": {
                "total_applied": 0, "completed": 0, "observing": 0,
                "sum_impressions_before": 0, "sum_impressions_after": 0,
                "sum_orders_before": 0, "sum_orders_after": 0,
                "avg_impressions_delta_pct": None,
            },
            "items": [],
            "empty_hint": "暂无已应用的 AI 标题记录。去「SEO 管理 → 效果报表 → AI 生成历史」页面，改完商品标题后点「标记已用」按钮来建立 ROI 观察基线。",
        }}

    # ---------- SQL 2: 对每个 applied 记录查 Before/After 窗口数据 ----------
    sku_ids = [r.platform_sku_id for r in applied_rows if r.platform_sku_id]
    # 去重保序
    sku_ids = list(dict.fromkeys(sku_ids))

    if not sku_ids:
        # 有 applied 但无 platform_sku_id（listing 已删？），直接返空基线
        sku_stats = {}
    else:
        # 一次性拉所有相关 SKU 的全量 product_search_queries 按日期 + 曝光/订单/营收
        stats_sql = text("""
            SELECT
                platform_sku_id,
                stat_date,
                SUM(impressions) AS imp,
                SUM(orders) AS ords,
                SUM(revenue) AS rev
            FROM product_search_queries
            WHERE tenant_id = :tid
              AND shop_id = :sid
              AND platform_sku_id IN :skus
            GROUP BY platform_sku_id, stat_date
        """).bindparams(bindparam("skus", expanding=True))
        stats_rows = db.execute(stats_sql, {
            "tid": tenant_id, "sid": shop_id, "skus": sku_ids,
        }).fetchall()

        # 按 sku_id 分组 { sku_id: [(date, imp, ord, rev), ...] }
        sku_stats: dict[str, list[tuple]] = {}
        for sr in stats_rows:
            sku_stats.setdefault(sr.platform_sku_id, []).append(
                (sr.stat_date, int(sr.imp or 0), int(sr.ords or 0), float(sr.rev or 0))
            )

    # ---------- Python 层：逐条 applied 切 Before/After 窗口 ----------
    items = []
    totals = {
        "total_applied": len(applied_rows),
        "completed": 0,
        "observing": 0,
        "sum_impressions_before": 0,
        "sum_impressions_after": 0,
        "sum_orders_before": 0,
        "sum_orders_after": 0,
    }
    delta_pcts_for_avg = []

    for r in applied_rows:
        applied_dt = r.applied_at
        # 兼容 DB 层可能返 naive datetime（MySQL DATETIME 无 tz）
        if applied_dt.tzinfo is None:
            applied_dt = applied_dt.replace(tzinfo=timezone.utc)
        applied_date = applied_dt.date()
        applied_days_ago = (today - applied_date).days

        before_start = applied_date - timedelta(days=window_days)
        before_end = applied_date - timedelta(days=1)
        after_start = applied_date
        after_end = min(applied_date + timedelta(days=window_days - 1), today)
        after_days_elapsed = max(0, (after_end - after_start).days + 1)

        # 聚合 Before / After
        before_imp = before_ord = 0
        before_rev = 0.0
        after_imp = after_ord = 0
        after_rev = 0.0

        stats = sku_stats.get(r.platform_sku_id, []) if r.platform_sku_id else []
        for (d, imp, ords, rev) in stats:
            if before_start <= d <= before_end:
                before_imp += imp; before_ord += ords; before_rev += rev
            elif after_start <= d <= after_end:
                after_imp += imp; after_ord += ords; after_rev += rev

        status = "completed" if applied_days_ago >= window_days else "observing"
        if status == "completed":
            totals["completed"] += 1
        else:
            totals["observing"] += 1

        totals["sum_impressions_before"] += before_imp
        totals["sum_impressions_after"] += after_imp
        totals["sum_orders_before"] += before_ord
        totals["sum_orders_after"] += after_ord

        imp_pct = _delta_pct(after_imp, before_imp)
        ord_pct = _delta_pct(after_ord, before_ord)
        rev_pct = _delta_pct(after_rev, before_rev)
        if imp_pct is not None:
            delta_pcts_for_avg.append(imp_pct)

        title_changed = bool(r.current_title and r.generated_text
                             and r.current_title.strip() == r.generated_text.strip())

        items.append({
            "generated_id": int(r.gid),
            "product_id": int(r.product_id) if r.product_id else None,
            "product_name": r.product_name or "",
            "image_url": r.image_url,
            "platform_sku_id": r.platform_sku_id,
            "original_title": r.original_text or "",
            "generated_title": r.generated_text or "",
            "current_title": r.current_title or "",
            "title_changed_to_generated": title_changed,
            "ai_model": r.ai_model,
            "applied_at": applied_dt.isoformat(),
            "applied_days_ago": applied_days_ago,
            "after_days_elapsed": after_days_elapsed,
            "status": status,
            "before": {
                "start": before_start.isoformat(), "end": before_end.isoformat(),
                "impressions": before_imp, "orders": before_ord, "revenue": round(before_rev, 2),
            },
            "after": {
                "start": after_start.isoformat(), "end": after_end.isoformat(),
                "impressions": after_imp, "orders": after_ord, "revenue": round(after_rev, 2),
                "days_elapsed": after_days_elapsed,
            },
            "delta": {
                "impressions_pct": imp_pct,
                "orders_pct": ord_pct,
                "revenue_pct": rev_pct,
            },
        })

    avg_imp_pct = round(sum(delta_pcts_for_avg) / len(delta_pcts_for_avg), 1) if delta_pcts_for_avg else None
    totals["avg_impressions_delta_pct"] = avg_imp_pct

    return {"code": 0, "data": {
        "window_days": window_days,
        "platform": platform,
        "totals": totals,
        "items": items,
        "empty_hint": None,
    }}
