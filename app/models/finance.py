from datetime import date
from typing import Optional
from sqlalchemy import BigInteger, String, Enum, Integer, DECIMAL, Date
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import BaseMixin


class FinanceCost(BaseMixin, Base):
    __tablename__ = "finance_costs"

    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    shop_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    listing_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    cost_date: Mapped[date] = mapped_column(Date, nullable=False)
    cost_type: Mapped[str] = mapped_column(
        Enum("ad_spend", "logistics", "commission", "storage", "other", name="cost_type"),
        nullable=False,
    )
    amount: Mapped[float] = mapped_column(DECIMAL(10, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="RUB")
    notes: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)


class FinanceRevenue(BaseMixin, Base):
    __tablename__ = "finance_revenues"

    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    shop_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    listing_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    revenue_date: Mapped[date] = mapped_column(Date, nullable=False)
    orders_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    revenue: Mapped[float] = mapped_column(DECIMAL(10, 2), nullable=False, default=0)
    returns_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    returns_amount: Mapped[float] = mapped_column(DECIMAL(10, 2), nullable=False, default=0)
    net_revenue: Mapped[float] = mapped_column(DECIMAL(10, 2), nullable=False, default=0)


class FinanceRoiSnapshot(BaseMixin, Base):
    __tablename__ = "finance_roi_snapshots"

    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    shop_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    period: Mapped[str] = mapped_column(
        Enum("daily", "weekly", "monthly", name="roi_period"), nullable=False
    )
    total_revenue: Mapped[float] = mapped_column(DECIMAL(10, 2), nullable=False, default=0)
    total_cost: Mapped[float] = mapped_column(DECIMAL(10, 2), nullable=False, default=0)
    ad_spend: Mapped[float] = mapped_column(DECIMAL(10, 2), nullable=False, default=0)
    gross_profit: Mapped[float] = mapped_column(DECIMAL(10, 2), nullable=False, default=0)
    roi: Mapped[Optional[float]] = mapped_column(DECIMAL(8, 4), nullable=True)
    roas: Mapped[Optional[float]] = mapped_column(DECIMAL(8, 4), nullable=True)
