from datetime import datetime, date, timezone
from typing import Optional
from sqlalchemy import BigInteger, String, Enum, Integer, DECIMAL, Date, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class RegionDailyStat(Base):
    __tablename__ = "region_daily_stats"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    shop_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    platform: Mapped[str] = mapped_column(Enum("wb", "ozon", name="region_platform"), nullable=False)
    region_name: Mapped[str] = mapped_column(String(200), nullable=False)
    stat_date: Mapped[date] = mapped_column(Date, nullable=False)
    orders: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    revenue: Mapped[float] = mapped_column(DECIMAL(14, 2), nullable=False, default=0)
    returns: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
