"""大促周期识别器

识别当前日期处于大促的哪个阶段，给出出价系数和数据处理策略。
使用同步SQLAlchemy Session。
"""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.models.promo_calendar import PromoCalendar
from app.utils.logger import setup_logger

logger = setup_logger("ai.promo_detector")


@dataclass
class PromoContext:
    is_promo_period: bool
    promo_phase: Optional[str]      # pre_heat/peak/recovery/None
    promo_name: Optional[str]
    bid_multiplier: float
    data_strategy: str              # normal/promo_only/recovery_tagged
    strategy_hint: str
    days_to_promo: Optional[int]


def detect_promo_context(db: Session, tenant_id: int) -> PromoContext:
    """检测当前日期是否处于大促周期"""
    today = date.today()

    # 查询近期大促（未来1天 + 过去3天）
    promos = db.query(PromoCalendar).filter(
        PromoCalendar.tenant_id == tenant_id,
        PromoCalendar.is_active == 1,
        PromoCalendar.promo_date >= today - timedelta(days=3),
        PromoCalendar.promo_date <= today + timedelta(days=1),
    ).all()

    if not promos:
        return PromoContext(
            is_promo_period=False, promo_phase=None, promo_name=None,
            bid_multiplier=1.0, data_strategy="normal",
            strategy_hint="当前非大促期，按正常策略执行",
            days_to_promo=None,
        )

    # 找最近的大促
    promo = min(promos, key=lambda p: abs((p.promo_date - today).days))
    days_diff = (promo.promo_date - today).days

    # 预热期（大促前1天）
    if days_diff == 1:
        return PromoContext(
            is_promo_period=True, promo_phase="pre_heat",
            promo_name=promo.promo_name,
            bid_multiplier=float(promo.pre_heat_multiplier),
            data_strategy="normal",
            strategy_hint=f"【{promo.promo_name}预热期】明天大促，出价x{promo.pre_heat_multiplier}预热，提前锁定排名",
            days_to_promo=1,
        )

    # 冲刺期（大促当天）
    if days_diff == 0:
        return PromoContext(
            is_promo_period=True, promo_phase="peak",
            promo_name=promo.promo_name,
            bid_multiplier=float(promo.peak_multiplier),
            data_strategy="promo_only",
            strategy_hint=f"【{promo.promo_name}冲刺期】大促当天，出价x{promo.peak_multiplier}，忽略ROAS限制冲销量，今日数据不纳入历史均值",
            days_to_promo=0,
        )

    # 恢复期（大促后1-3天）
    if -3 <= days_diff < 0:
        recovery_day = abs(days_diff)
        multipliers = [
            float(promo.recovery_day1_multiplier),
            float(promo.recovery_day2_multiplier),
            float(promo.recovery_day3_multiplier),
        ]
        multiplier = multipliers[min(recovery_day - 1, 2)]
        return PromoContext(
            is_promo_period=True, promo_phase="recovery",
            promo_name=promo.promo_name,
            bid_multiplier=multiplier,
            data_strategy="recovery_tagged",
            strategy_hint=f"【{promo.promo_name}恢复期第{recovery_day}天】逐步降价恢复正常，出价x{multiplier}，不要被大促高ROAS误导",
            days_to_promo=days_diff,
        )

    return PromoContext(
        is_promo_period=False, promo_phase=None, promo_name=None,
        bid_multiplier=1.0, data_strategy="normal",
        strategy_hint="当前非大促期",
        days_to_promo=None,
    )
