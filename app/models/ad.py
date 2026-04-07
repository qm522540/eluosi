from datetime import date
from typing import Optional
from sqlalchemy import BigInteger, String, Enum, Integer, DECIMAL, Date, SmallInteger
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import BaseMixin


class AdCampaign(BaseMixin, Base):
    __tablename__ = "ad_campaigns"

    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    shop_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    platform: Mapped[str] = mapped_column(
        Enum("wb", "ozon", "yandex", name="ad_platform"), nullable=False
    )
    platform_campaign_id: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    ad_type: Mapped[str] = mapped_column(
        Enum("search", "catalog", "product_page", "recommendation", name="ad_type"),
        nullable=False,
    )
    daily_budget: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 2), nullable=True)
    total_budget: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 2), nullable=True)
    status: Mapped[str] = mapped_column(
        Enum("active", "paused", "archived", "draft", name="campaign_status"),
        nullable=False, default="active"
    )
    start_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)


class AdGroup(BaseMixin, Base):
    __tablename__ = "ad_groups"

    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    campaign_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    platform_group_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    listing_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    bid: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 2), nullable=True)
    status: Mapped[str] = mapped_column(
        Enum("active", "paused", "archived", name="adgroup_status"),
        nullable=False, default="active"
    )


class AdKeyword(BaseMixin, Base):
    __tablename__ = "ad_keywords"

    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    ad_group_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    keyword: Mapped[str] = mapped_column(String(200), nullable=False)
    match_type: Mapped[str] = mapped_column(
        Enum("exact", "phrase", "broad", name="match_type"),
        nullable=False, default="broad"
    )
    bid: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 2), nullable=True)
    is_negative: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    status: Mapped[str] = mapped_column(
        Enum("active", "paused", "deleted", name="keyword_status"),
        nullable=False, default="active"
    )


class AdStat(BaseMixin, Base):
    __tablename__ = "ad_stats"

    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    campaign_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    ad_group_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    keyword_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    platform: Mapped[str] = mapped_column(
        Enum("wb", "ozon", "yandex", name="stat_platform"), nullable=False
    )
    stat_date: Mapped[date] = mapped_column(Date, nullable=False)
    stat_hour: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    impressions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    clicks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    spend: Mapped[float] = mapped_column(DECIMAL(10, 2), nullable=False, default=0)
    orders: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    revenue: Mapped[float] = mapped_column(DECIMAL(10, 2), nullable=False, default=0)
    ctr: Mapped[Optional[float]] = mapped_column(DECIMAL(8, 4), nullable=True)
    cpc: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 2), nullable=True)
    acos: Mapped[Optional[float]] = mapped_column(DECIMAL(8, 4), nullable=True)
    roas: Mapped[Optional[float]] = mapped_column(DECIMAL(8, 4), nullable=True)
