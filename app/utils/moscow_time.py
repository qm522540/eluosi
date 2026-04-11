"""莫斯科时间工具

为出价管理模块提供统一的"当前时段"判断和"下次执行时间"计算。

调度约定：每小时莫斯科时间 :05 分由 Celery 触发执行。

老林规范要求的函数签名（docs/api/bid_management.md §11）：
    now_moscow() -> datetime
    moscow_hour() -> int
    moscow_today() -> date
    get_current_period(rule) -> Literal['peak','mid','low']
    get_dashboard_info(db, shop_id) -> dict
"""

import json
from datetime import date, datetime
from typing import Optional

import pytz

MOSCOW_TZ = pytz.timezone("Europe/Moscow")
EXECUTE_MINUTE = 5  # 每小时第5分钟由 Celery 触发


def now_moscow() -> datetime:
    """返回带 tzinfo 的莫斯科当前时间"""
    return datetime.now(MOSCOW_TZ)


def moscow_hour() -> int:
    """返回莫斯科当前小时 0-23"""
    return now_moscow().hour


def moscow_today() -> date:
    """返回莫斯科当前日期（用于建议次日过期判断）"""
    return now_moscow().date()


def get_current_period(rule) -> Optional[str]:
    """根据 time_pricing_rules 行判断当前时段

    Args:
        rule: time_pricing_rules 表的一行（SQLAlchemy Row 或 dict）

    Returns:
        'peak' / 'mid' / 'low' / None（未匹配，理论上不应发生因为24小时全覆盖）
    """
    if rule is None:
        return None

    hour = moscow_hour()
    peak = _parse_hours(_get_attr(rule, "peak_hours"))
    mid = _parse_hours(_get_attr(rule, "mid_hours"))
    low = _parse_hours(_get_attr(rule, "low_hours"))

    if hour in peak:
        return "peak"
    if hour in mid:
        return "mid"
    if hour in low:
        return "low"
    return None


def get_dashboard_info(db, shop_id: int) -> dict:
    """组装 GET /bid-management/dashboard/{shop_id} 接口返回数据

    返回字段（与 docs/api/bid_management.md §1.1 对齐）：
        moscow_time, moscow_hour, current_period, current_period_name,
        current_ratio, next_execute_at, next_execute_minutes,
        last_executed_at, last_execute_result, last_execute_status, active_mode
    """
    from sqlalchemy import text

    now = now_moscow()
    hour = now.hour

    # 计算下次执行时间（每小时第 EXECUTE_MINUTE 分）
    if now.minute < EXECUTE_MINUTE:
        next_str = f"{hour:02d}:{EXECUTE_MINUTE:02d}"
        remaining = EXECUTE_MINUTE - now.minute
    else:
        next_hour = (hour + 1) % 24
        next_str = f"{next_hour:02d}:{EXECUTE_MINUTE:02d}"
        remaining = 60 - now.minute + EXECUTE_MINUTE

    # 一次查询拿到分时和AI两边的状态
    row = db.execute(text("""
        SELECT
            t.is_active           AS time_active,
            t.last_executed_at    AS time_last,
            t.last_execute_result AS time_result,
            t.peak_hours          AS peak_hours,
            t.peak_ratio          AS peak_ratio,
            t.mid_hours           AS mid_hours,
            t.mid_ratio           AS mid_ratio,
            t.low_hours           AS low_hours,
            t.low_ratio           AS low_ratio,
            a.is_active           AS ai_active,
            a.last_executed_at    AS ai_last,
            a.last_execute_status AS ai_status,
            a.last_error_msg      AS ai_error
        FROM shops s
        LEFT JOIN time_pricing_rules t ON s.id = t.shop_id
        LEFT JOIN ai_pricing_configs a ON s.id = a.shop_id
        WHERE s.id = :shop_id
        LIMIT 1
    """), {"shop_id": shop_id}).fetchone()

    period: Optional[str] = None
    period_name = "基准期"
    ratio: Optional[int] = None
    active_mode = "none"
    last_executed_at = None
    last_execute_result = None
    last_execute_status = None

    if row:
        if row.time_active:
            active_mode = "time_pricing"
            period = get_current_period(row)
            if period == "peak":
                period_name = "高峰期"
                ratio = row.peak_ratio
            elif period == "mid":
                period_name = "次高峰期"
                ratio = row.mid_ratio
            elif period == "low":
                period_name = "低谷期"
                ratio = row.low_ratio
            last_executed_at = _iso(row.time_last)
            last_execute_result = row.time_result
            last_execute_status = "success" if row.time_last else None
        elif row.ai_active:
            active_mode = "ai"
            last_executed_at = _iso(row.ai_last)
            last_execute_status = row.ai_status
            last_execute_result = row.ai_error if row.ai_status == "failed" else "AI模式"

    return {
        "shop_id": shop_id,
        "moscow_time": now.isoformat(),
        "moscow_hour": hour,
        "current_period": period or "none",
        "current_period_name": period_name,
        "current_ratio": ratio,
        "next_execute_at": next_str,
        "next_execute_minutes": remaining,
        "last_executed_at": last_executed_at,
        "last_execute_result": last_execute_result,
        "last_execute_status": last_execute_status or "none",
        "active_mode": active_mode,
    }


# ==================== 内部工具 ====================

def _get_attr(obj, name: str):
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _parse_hours(value) -> list:
    """解析存储为 JSON / list / 字符串的小时数组"""
    if value is None:
        return []
    if isinstance(value, list):
        return [int(x) for x in value]
    if isinstance(value, str):
        try:
            data = json.loads(value)
            if isinstance(data, list):
                return [int(x) for x in data]
        except (ValueError, TypeError):
            pass
    return []


def _iso(dt) -> Optional[str]:
    """datetime → ISO 8601 字符串（带 +03:00 时区信息）

    数据库里 last_executed_at 是 naive datetime（CURRENT_TIMESTAMP）。
    服务器假设按 UTC 存。这里加上 UTC tzinfo 再转莫斯科。
    """
    if dt is None:
        return None
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            # 假设 naive 的 last_executed_at 来自 NOW()，按服务器时区。
            # 服务器 Celery 时区设置为 Europe/Moscow，所以 NOW() 已经是莫斯科时间。
            dt = MOSCOW_TZ.localize(dt)
        else:
            dt = dt.astimezone(MOSCOW_TZ)
        return dt.isoformat()
    return str(dt)
