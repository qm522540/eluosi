"""大促日历模型"""

from datetime import date, datetime
from typing import Optional
from sqlalchemy import BigInteger, Integer, String, DECIMAL, Date, DateTime, SmallInteger
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import BaseMixin


class PromoCalendar(BaseMixin, Base):
    """大促日历"""
    __tablename__ = "promo_calendars"

    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    promo_name: Mapped[str] = mapped_column(String(100), nullable=False)
    promo_date: Mapped[date] = mapped_column(Date, nullable=False)
    pre_heat_days: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    recovery_days: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    pre_heat_multiplier: Mapped[float] = mapped_column(DECIMAL(4, 2), nullable=False, default=1.30)
    peak_multiplier: Mapped[float] = mapped_column(DECIMAL(4, 2), nullable=False, default=1.70)
    recovery_day1_multiplier: Mapped[float] = mapped_column(DECIMAL(4, 2), nullable=False, default=0.90)
    recovery_day2_multiplier: Mapped[float] = mapped_column(DECIMAL(4, 2), nullable=False, default=0.95)
    recovery_day3_multiplier: Mapped[float] = mapped_column(DECIMAL(4, 2), nullable=False, default=1.00)
    is_active: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
