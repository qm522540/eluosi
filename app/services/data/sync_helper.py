"""数据同步辅助函数：按"45天窗口缺失"策略计算需要拉的日期段"""

from datetime import date, timedelta
from typing import List, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session


def find_missing_ranges(
    db: Session,
    shop_id: int,
    tenant_id: int,
    platform: str,
    window_days: int,
    first_sync_days: int,
) -> Tuple[List[Tuple[date, date]], bool]:
    """找出过去 window_days 天内 ad_stats 缺失的日期段。

    策略：
      - DB 无历史数据 → 首次同步，只拉最近 first_sync_days 天
      - DB 有数据 → 查 window_days 窗口内所有缺失的日期，分组成连续区间

    返回: (ranges, is_first_sync)
      - ranges: [(date_from, date_to), ...] 每段闭区间，按时间升序
      - is_first_sync: True=首次同步（DB空），False=增量/补齐
    """
    yesterday = date.today() - timedelta(days=1)
    window_start = date.today() - timedelta(days=window_days)

    # 查已有的 stat_date
    rows = db.execute(text("""
        SELECT DISTINCT s.stat_date
        FROM ad_stats s
        JOIN ad_campaigns c ON s.campaign_id = c.id
        WHERE c.shop_id = :shop_id AND c.tenant_id = :tenant_id
          AND s.platform = :platform
          AND s.stat_date >= :window_start
    """), {
        "shop_id": shop_id, "tenant_id": tenant_id,
        "platform": platform, "window_start": window_start,
    }).fetchall()

    existing_dates = {r.stat_date for r in rows if r.stat_date}

    if not existing_dates:
        # 首次同步
        return [(yesterday - timedelta(days=first_sync_days - 1), yesterday)], True

    # 在窗口内找缺失
    missing = []
    d = window_start
    while d <= yesterday:
        if d not in existing_dates:
            missing.append(d)
        d += timedelta(days=1)

    # 无缺失
    if not missing:
        return [], False

    # 分组成连续区间
    ranges: List[Tuple[date, date]] = []
    start = missing[0]
    prev = missing[0]
    for dm in missing[1:]:
        if (dm - prev).days == 1:
            prev = dm
        else:
            ranges.append((start, prev))
            start = dm
            prev = dm
    ranges.append((start, prev))

    return ranges, False
