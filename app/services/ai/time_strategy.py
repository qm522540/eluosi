"""莫斯科时段调价策略配置

五时段差异化出价：
- peak_morning  (10-14): 上午高峰，30分钟巡检，主动加价
- peak_evening  (19-23): 晚间高峰，30分钟巡检，重点抢量
- stable_morning (07-10): 早晨平稳，2小时巡检，维持观察
- stable_afternoon (14-19): 下午平稳，2小时巡检，ROI优化
- off_peak (23-07): 低谷期，2小时巡检，大幅降价
"""

from dataclasses import dataclass
from datetime import datetime, timezone, timedelta

# 莫斯科时区 UTC+3（固定偏移，不依赖pytz）
MOSCOW_TZ = timezone(timedelta(hours=3))


@dataclass
class TimeSlotStrategy:
    name: str                     # 时段名称
    slot_key: str                 # 时段标识键
    check_interval_minutes: int   # 巡检间隔（分钟）
    bid_adjust_direction: str     # 调价方向：up/down/neutral
    bid_adjust_min_pct: float     # 最小调整幅度%
    bid_adjust_max_pct: float     # 最大调整幅度%
    max_single_change_pct: float  # 单次最大变动幅度%（安全护栏）
    target_roas_multiplier: float # ROAS目标乘数
    description: str              # 策略说明


# 五时段策略定义
TIME_SLOT_STRATEGIES = {
    "peak_morning": TimeSlotStrategy(
        name="上午高峰",
        slot_key="peak_morning",
        check_interval_minutes=30,
        bid_adjust_direction="up",
        bid_adjust_min_pct=5.0,
        bid_adjust_max_pct=20.0,
        max_single_change_pct=10.0,
        target_roas_multiplier=0.85,
        description="10:00-14:00 莫斯科时间，流量高峰，主动加价抢曝光",
    ),
    "peak_evening": TimeSlotStrategy(
        name="晚间高峰",
        slot_key="peak_evening",
        check_interval_minutes=30,
        bid_adjust_direction="up",
        bid_adjust_min_pct=8.0,
        bid_adjust_max_pct=25.0,
        max_single_change_pct=10.0,
        target_roas_multiplier=0.80,
        description="19:00-23:00 莫斯科时间，转化率最高，重点抢量",
    ),
    "stable_morning": TimeSlotStrategy(
        name="早晨平稳",
        slot_key="stable_morning",
        check_interval_minutes=120,
        bid_adjust_direction="neutral",
        bid_adjust_min_pct=0.0,
        bid_adjust_max_pct=10.0,
        max_single_change_pct=15.0,
        target_roas_multiplier=1.0,
        description="07:00-10:00 莫斯科时间，流量回升期，维持观察",
    ),
    "stable_afternoon": TimeSlotStrategy(
        name="下午平稳",
        slot_key="stable_afternoon",
        check_interval_minutes=120,
        bid_adjust_direction="neutral",
        bid_adjust_min_pct=0.0,
        bid_adjust_max_pct=10.0,
        max_single_change_pct=15.0,
        target_roas_multiplier=1.0,
        description="14:00-19:00 莫斯科时间，平稳期，正常ROI优化",
    ),
    "off_peak": TimeSlotStrategy(
        name="低谷期",
        slot_key="off_peak",
        check_interval_minutes=120,
        bid_adjust_direction="down",
        bid_adjust_min_pct=30.0,
        bid_adjust_max_pct=50.0,
        max_single_change_pct=20.0,
        target_roas_multiplier=1.3,
        description="23:00-07:00 莫斯科时间，深夜低谷，大幅降价节省预算",
    ),
}


def get_current_moscow_hour() -> int:
    """获取当前莫斯科时间小时数"""
    return datetime.now(MOSCOW_TZ).hour


def get_strategy_for_hour(moscow_hour: int) -> TimeSlotStrategy:
    """根据莫斯科小时数获取对应时段策略"""
    if 10 <= moscow_hour < 14:
        return TIME_SLOT_STRATEGIES["peak_morning"]
    elif 19 <= moscow_hour < 23:
        return TIME_SLOT_STRATEGIES["peak_evening"]
    elif 7 <= moscow_hour < 10:
        return TIME_SLOT_STRATEGIES["stable_morning"]
    elif 14 <= moscow_hour < 19:
        return TIME_SLOT_STRATEGIES["stable_afternoon"]
    else:  # 23-07
        return TIME_SLOT_STRATEGIES["off_peak"]


def get_current_moscow_strategy() -> tuple:
    """获取当前莫斯科时间对应的时段策略

    Returns: (moscow_hour, TimeSlotStrategy)
    """
    hour = get_current_moscow_hour()
    return hour, get_strategy_for_hour(hour)


def should_run_now(last_run_iso: str, strategy: TimeSlotStrategy) -> bool:
    """判断当前时间是否应该触发巡检

    Args:
        last_run_iso: 上次执行时间的ISO格式字符串（UTC），None表示从未执行
        strategy: 当前时段策略

    Returns: True=应该执行
    """
    if not last_run_iso:
        return True

    try:
        last_run = datetime.fromisoformat(last_run_iso)
        # 确保有时区信息
        if last_run.tzinfo is None:
            last_run = last_run.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        elapsed_minutes = (now - last_run).total_seconds() / 60
        return elapsed_minutes >= strategy.check_interval_minutes
    except (ValueError, TypeError):
        return True


def check_cooldown(last_bid_iso: str, cooldown_minutes: int = 20) -> tuple:
    """检查调价冷却时间

    Args:
        last_bid_iso: 上次调价时间ISO字符串（UTC）
        cooldown_minutes: 冷却时间（分钟）

    Returns: (is_cooled_down: bool, remaining_minutes: float)
    """
    if not last_bid_iso:
        return True, 0

    try:
        last_bid = datetime.fromisoformat(last_bid_iso)
        if last_bid.tzinfo is None:
            last_bid = last_bid.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        elapsed = (now - last_bid).total_seconds() / 60
        if elapsed >= cooldown_minutes:
            return True, 0
        return False, round(cooldown_minutes - elapsed, 1)
    except (ValueError, TypeError):
        return True, 0
