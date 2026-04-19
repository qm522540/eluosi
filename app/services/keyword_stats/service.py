"""关键词统计业务逻辑

数据来源：keyword_daily_stats 表（Celery 每日增量 + 手动回填）
查询接口：summary / sku-detail / trend / negative-suggestions / sync-status
"""

from datetime import date, timedelta, datetime, timezone
from typing import Optional
from decimal import Decimal
from sqlalchemy.orm import Session
from sqlalchemy import text, func

from app.models.keyword_stat import KeywordDailyStat
from app.services.keyword_stats.rules import get_rules, classify
from app.utils.errors import ErrorCode
from app.utils.logger import logger


def _default_dates(date_from: Optional[str], date_to: Optional[str]):
    if not date_to:
        date_to = (date.today() - timedelta(days=1)).isoformat()
    if not date_from:
        date_from = (date.fromisoformat(date_to) - timedelta(days=6)).isoformat()
    return date_from, date_to


def _float(v):
    if isinstance(v, Decimal):
        return float(v)
    return float(v) if v is not None else 0


_VALID_EFF = {"new", "star", "potential", "waste", "normal"}


def summary(
    db: Session, tenant_id: int, shop_id: int,
    date_from: str = None, date_to: str = None,
    campaign_id: int = None, keyword: str = None,
    sort_by: str = "spend", sort_order: str = "desc",
    page: int = 1, size: int = 50,
    efficiency: str = None,
) -> dict:
    """§3.1 关键词汇总列表

    实现说明：
    - efficiency 是 SQL 后派生字段（先聚合 → classify），无法下推到 SQL WHERE
    - 因此 server-side filter 走"先全量聚合 → Python 算 efficiency → filter → 切片分页"
    - 单店铺 distinct keyword 量级在 2-5k，全量聚合性能可接受（< 100ms）
    """
    date_from, date_to = _default_dates(date_from, date_to)

    # 构建 WHERE
    where = "WHERE tenant_id = :tid AND shop_id = :sid AND stat_date BETWEEN :df AND :dt"
    params = {"tid": tenant_id, "sid": shop_id, "df": date_from, "dt": date_to}
    if campaign_id:
        where += " AND campaign_id = :cid"
        params["cid"] = campaign_id
    kw_where = ""
    if keyword:
        kw_where = " HAVING keyword LIKE :kw"
        params["kw"] = f"%{keyword}%"

    # 全局汇总
    totals_sql = f"""
        SELECT COUNT(DISTINCT keyword) kw_count,
               SUM(impressions) imp, SUM(clicks) clk, SUM(spend) sp
        FROM keyword_daily_stats {where}
    """
    row = db.execute(text(totals_sql), params).fetchone()
    total_imp = int(row.imp or 0)
    total_clk = int(row.clk or 0)
    total_sp = _float(row.sp)
    avg_ctr = round(total_clk / total_imp * 100, 2) if total_imp > 0 else 0
    avg_cpc = round(total_sp / total_clk, 2) if total_clk > 0 else 0

    # 分组排序（全量，不分页）
    allowed_sorts = {"spend", "impressions", "clicks", "ctr", "cpc"}
    sort_col = sort_by if sort_by in allowed_sorts else "spend"
    order = "DESC" if sort_order == "desc" else "ASC"

    items_sql = f"""
        SELECT keyword,
               SUM(impressions) impressions, SUM(clicks) clicks, SUM(spend) spend,
               ROUND(SUM(clicks)/NULLIF(SUM(impressions),0)*100, 2) ctr,
               ROUND(SUM(spend)/NULLIF(SUM(clicks),0), 2) cpc,
               ROUND(SUM(spend)/{max(total_sp, 0.01)}*100, 1) spend_pct,
               GROUP_CONCAT(DISTINCT campaign_id) campaign_ids,
               GROUP_CONCAT(DISTINCT sku) skus
        FROM keyword_daily_stats {where}
        GROUP BY keyword
        {kw_where}
        ORDER BY {sort_col} {order}
    """
    rows = db.execute(text(items_sql), params).fetchall()

    # 单独查每个关键词的"绝对首次出现日期"（不受 date_from/date_to 过滤影响）
    # MIN(stat_date) 跨整个本店的历史，用户切换日期筛选时该字段不变
    first_seen_map = {}
    if rows:
        kws = [r.keyword for r in rows]
        # IN 列表用 expanding bindparam
        from sqlalchemy import bindparam
        fs_sql = text("""
            SELECT keyword, MIN(stat_date) first_seen
            FROM keyword_daily_stats
            WHERE tenant_id = :tid AND shop_id = :sid AND keyword IN :kws
            GROUP BY keyword
        """).bindparams(bindparam("kws", expanding=True))
        fs_rows = db.execute(fs_sql, {"tid": tenant_id, "sid": shop_id, "kws": kws}).fetchall()
        first_seen_map = {r.keyword: r.first_seen for r in fs_rows}

    # 效能标签计算：租户规则 > 系统默认
    rules = get_rules(db, tenant_id)
    distinct_count = len(rows)
    avg_imp = total_imp / max(distinct_count, 1)
    avg_sp = total_sp / max(distinct_count, 1)

    items_all = []
    for r in rows:
        imp = int(r.impressions or 0)
        clk = int(r.clicks or 0)
        sp = _float(r.spend)
        ctr_val = _float(r.ctr)
        cpc_val = _float(r.cpc)

        eff = classify(
            ctr=ctr_val, cpc=cpc_val, impressions=imp, spend=sp,
            avg_cpc=avg_cpc, avg_impressions=avg_imp, avg_spend=avg_sp,
            rules=rules,
        )

        fs = first_seen_map.get(r.keyword)
        items_all.append({
            "keyword": r.keyword,
            "impressions": imp,
            "clicks": clk,
            "spend": sp,
            "ctr": ctr_val,
            "cpc": cpc_val,
            "spend_pct": _float(r.spend_pct),
            "campaigns": [int(x) for x in (r.campaign_ids or "").split(",") if x.strip().isdigit()],
            "skus": [x for x in (r.skus or "").split(",") if x.strip() and x.strip() != "None"],
            "efficiency": eff,
            "first_seen": fs.isoformat() if fs else None,
        })

    # 效能 server-side filter（在 classify 之后）
    if efficiency in _VALID_EFF:
        items_all = [i for i in items_all if i["efficiency"] == efficiency]

    # 分页（filter 后）
    total = len(items_all)
    page_size = min(size, 200)
    offset = (page - 1) * page_size
    items = items_all[offset: offset + page_size]

    return {"code": 0, "data": {
        "total": total, "page": page, "size": page_size,
        "date_from": date_from, "date_to": date_to,
        "totals": {
            "keywords": int(row.kw_count or 0),
            "impressions": total_imp, "clicks": total_clk,
            "spend": total_sp, "avg_ctr": avg_ctr, "avg_cpc": avg_cpc,
        },
        "items": items,
    }}


def sku_detail(
    db: Session, tenant_id: int, shop_id: int, keyword: str,
    date_from: str = None, date_to: str = None,
) -> dict:
    """§3.2 关键词 SKU 明细"""
    date_from, date_to = _default_dates(date_from, date_to)
    sql = text("""
        SELECT sku, SUM(impressions) imp, SUM(clicks) clk, SUM(spend) sp,
               ROUND(SUM(clicks)/NULLIF(SUM(impressions),0)*100, 2) ctr,
               ROUND(SUM(spend)/NULLIF(SUM(clicks),0), 2) cpc
        FROM keyword_daily_stats
        WHERE tenant_id=:tid AND shop_id=:sid AND keyword=:kw
          AND stat_date BETWEEN :df AND :dt AND sku IS NOT NULL
        GROUP BY sku ORDER BY sp DESC
    """)
    rows = db.execute(sql, {"tid": tenant_id, "sid": shop_id, "kw": keyword,
                            "df": date_from, "dt": date_to}).fetchall()
    return {"code": 0, "data": {"items": [{
        "sku": r.sku, "impressions": int(r.imp or 0), "clicks": int(r.clk or 0),
        "spend": _float(r.sp), "ctr": _float(r.ctr), "cpc": _float(r.cpc),
    } for r in rows]}}


def trend(
    db: Session, tenant_id: int, shop_id: int,
    date_from: str = None, date_to: str = None,
    top: int = 10, metric: str = "impressions",
) -> dict:
    """§3.3 趋势数据"""
    date_from, date_to = _default_dates(date_from, date_to)
    allowed = {"impressions", "clicks", "spend"}
    col = metric if metric in allowed else "impressions"

    # TOP N 关键词
    top_sql = text(f"""
        SELECT keyword FROM keyword_daily_stats
        WHERE tenant_id=:tid AND shop_id=:sid AND stat_date BETWEEN :df AND :dt
        GROUP BY keyword ORDER BY SUM({col}) DESC LIMIT :top
    """)
    p = {"tid": tenant_id, "sid": shop_id, "df": date_from, "dt": date_to, "top": min(top, 20)}
    top_kws = [r.keyword for r in db.execute(top_sql, p).fetchall()]
    if not top_kws:
        return {"code": 0, "data": {"dates": [], "series": []}}

    # 日期列表
    d = date.fromisoformat(date_from)
    d_end = date.fromisoformat(date_to)
    dates = []
    while d <= d_end:
        dates.append(d.isoformat())
        d += timedelta(days=1)

    # 每个关键词按天取值
    series = []
    for kw in top_kws:
        row_sql = text(f"""
            SELECT stat_date, SUM({col}) val FROM keyword_daily_stats
            WHERE tenant_id=:tid AND shop_id=:sid AND keyword=:kw
              AND stat_date BETWEEN :df AND :dt
            GROUP BY stat_date
        """)
        rows = db.execute(row_sql, {"tid": tenant_id, "sid": shop_id,
                                     "kw": kw, "df": date_from, "dt": date_to}).fetchall()
        day_map = {r.stat_date.isoformat() if isinstance(r.stat_date, date) else str(r.stat_date): _float(r.val)
                   for r in rows}
        series.append({"keyword": kw, "values": [day_map.get(d, 0) for d in dates]})

    return {"code": 0, "data": {"dates": dates, "series": series}}


def negative_suggestions(
    db: Session, tenant_id: int, shop_id: int,
    date_from: str = None, date_to: str = None,
) -> dict:
    """§3.5 否定关键词建议"""
    date_from, date_to = _default_dates(date_from, date_to)
    sql = text("""
        SELECT keyword, SUM(impressions) imp, SUM(clicks) clk, SUM(spend) sp,
               ROUND(SUM(clicks)/NULLIF(SUM(impressions),0)*100, 2) ctr
        FROM keyword_daily_stats
        WHERE tenant_id=:tid AND shop_id=:sid AND stat_date BETWEEN :df AND :dt
        GROUP BY keyword
        HAVING sp > 0 AND (clk < 3 OR ctr < 0.5)
        ORDER BY sp DESC LIMIT 50
    """)
    rows = db.execute(sql, {"tid": tenant_id, "sid": shop_id,
                            "df": date_from, "dt": date_to}).fetchall()
    items = []
    for r in rows:
        sp = _float(r.sp)
        clk = int(r.clk or 0)
        ctr = _float(r.ctr)
        items.append({
            "keyword": r.keyword,
            "impressions": int(r.imp or 0),
            "clicks": clk,
            "spend": sp,
            "ctr": ctr,
            "reason": f"花费 {sp:.0f}₽ 仅 {clk} 次点击，CTR {ctr:.2f}%，建议设为否定关键词",
        })
    return {"code": 0, "data": {"items": items}}


def sync_status(db: Session, tenant_id: int, shop_id: int) -> dict:
    """§3.6 数据同步状态"""
    from app.models.shop import Shop
    shop = db.query(Shop).filter(Shop.id == shop_id, Shop.tenant_id == tenant_id).first()
    if not shop:
        return {"code": ErrorCode.SHOP_NOT_FOUND, "msg": "店铺不存在"}

    sql = text("""
        SELECT MIN(stat_date) earliest, MAX(stat_date) latest,
               COUNT(DISTINCT stat_date) total_days,
               COUNT(DISTINCT keyword) total_kw, COUNT(*) total_records
        FROM keyword_daily_stats
        WHERE tenant_id=:tid AND shop_id=:sid
    """)
    r = db.execute(sql, {"tid": tenant_id, "sid": shop_id}).fetchone()
    return {"code": 0, "data": {
        "shop_id": shop_id,
        "platform": shop.platform,
        "last_sync_date": r.latest.isoformat() if r.latest else None,
        "total_days": int(r.total_days or 0),
        "earliest_date": r.earliest.isoformat() if r.earliest else None,
        "latest_date": r.latest.isoformat() if r.latest else None,
        "total_keywords": int(r.total_kw or 0),
        "total_records": int(r.total_records or 0),
    }}
