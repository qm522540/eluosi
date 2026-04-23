"""项目统一时间工具 — 时间规范 §6

统一时间策略（2026-04-23 大改造后）：
    - DATETIME 字段全部存真 UTC（naive）
    - 业务判断（"是不是凌晨/今天"）用 moscow_hour() / moscow_today() / now_moscow()
    - UI 展示用 _iso() 等工具从 UTC naive → MSK ISO 串
    - Celery beat 配 timezone="Europe/Moscow"，触发时刻按真 MSK 对齐
    - 禁用：datetime.now()（无 tz）/ MySQL 裸 NOW()、CURRENT_TIMESTAMP（在 INSERT/UPDATE 运行时）
    - 唯一写入入口：utc_now_naive() 或 utc_now()

老林规范要求的函数签名（docs/api/bid_management.md §11）：
    now_moscow() -> datetime
    moscow_hour() -> int
    moscow_today() -> date
    utc_now() -> datetime          (aware UTC)
    utc_now_naive() -> datetime    (naive UTC，DB 写入用)
    get_current_period(rule) -> Literal['peak','mid','low']
    get_dashboard_info(db, shop_id) -> dict
"""

import json
from datetime import date, datetime, timezone
from typing import Optional

import pytz

MOSCOW_TZ = pytz.timezone("Europe/Moscow")
EXECUTE_MINUTE = 5  # 每小时第5分钟由 Celery 触发


def now_moscow() -> datetime:
    """返回带 tzinfo 的莫斯科当前时间（业务判断用）"""
    return datetime.now(MOSCOW_TZ)


def moscow_hour() -> int:
    """返回莫斯科当前小时 0-23"""
    return now_moscow().hour


def moscow_today() -> date:
    """返回莫斯科当前日期（用于建议次日过期判断）"""
    return now_moscow().date()


def utc_now() -> datetime:
    """返回带 tzinfo 的 UTC 当前时间（与 datetime.now(timezone.utc) 等价）"""
    return datetime.now(timezone.utc)


def utc_now_naive() -> datetime:
    """返回 naive UTC 当前时间 — DB INSERT/UPDATE 时间字段的**唯一正确写入源**

    用法：
        db.execute(text("... SET updated_at = :now_utc ..."),
                   {"now_utc": utc_now_naive(), ...})

    不要用：
        - NOW() / CURRENT_TIMESTAMP（MySQL session time_zone 影响结果）
        - datetime.now()（无 tz 且依赖 OS 时区）
        - datetime.utcnow()（Python 3.12 已弃用）
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


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


def get_dashboard_info(db, shop_id: int, tenant_id: int) -> dict:
    """组装 GET /bid-management/dashboard/{shop_id} 接口返回数据

    多租户隔离：必须传 tenant_id，所有 JOIN 都按 tenant_id 过滤

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

    # 一次查询拿到分时和AI两边的状态（多租户过滤）
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
        LEFT JOIN time_pricing_rules t
            ON s.id = t.shop_id AND t.tenant_id = :tenant_id
        LEFT JOIN ai_pricing_configs a
            ON s.id = a.shop_id AND a.tenant_id = :tenant_id
        WHERE s.id = :shop_id AND s.tenant_id = :tenant_id
        LIMIT 1
    """), {"shop_id": shop_id, "tenant_id": tenant_id}).fetchone()

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
            else:
                # 4 档语义：未匹配 = 平谷期，保持原价不动
                period = "base"
                period_name = "平谷期"
                ratio = 100
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

    #14 修复：注释和代码保持一致。
    项目约定：MySQL 服务器时区配置为 UTC，所有 NOW()/CURRENT_TIMESTAMP 存的是 UTC naive。
    Celery 配置 enable_utc=True，写库时用 datetime.now(timezone.utc)（去掉 tzinfo 存）。
    所以 naive datetime 一律按 UTC 解释，再 convert 到莫斯科展示。
    """
    if dt is None:
        return None
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = pytz.UTC.localize(dt)
        dt = dt.astimezone(MOSCOW_TZ)
        return dt.isoformat()
    return str(dt)
