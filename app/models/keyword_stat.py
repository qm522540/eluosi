"""关键词每日统计模型 + 效能评级规则"""

from datetime import datetime, date, timezone
from typing import Optional
from sqlalchemy import BigInteger, String, Enum, Integer, DECIMAL, Date, DateTime, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import BaseMixin


class KeywordDailyStat(Base):
    __tablename__ = "keyword_daily_stats"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    shop_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    platform: Mapped[str] = mapped_column(Enum("wb", "ozon", name="kw_platform"), nullable=False)
    campaign_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    platform_campaign_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    keyword: Mapped[str] = mapped_column(String(500), nullable=False)
    sku: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    stat_date: Mapped[date] = mapped_column(Date, nullable=False)
    impressions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    clicks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    spend: Mapped[float] = mapped_column(DECIMAL(12, 2), nullable=False, default=0)
    ctr: Mapped[float] = mapped_column(DECIMAL(8, 4), nullable=False, default=0)
    cpc: Mapped[float] = mapped_column(DECIMAL(10, 2), nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))


class KeywordEfficiencyRule(Base):
    """租户级关键词效能评级规则（每租户一行，rules_json 存阈值）

    无记录走代码默认（见 app/services/keyword_stats/rules.py DEFAULT_RULES）
    """
    __tablename__ = "keyword_efficiency_rules"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
    rules_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
