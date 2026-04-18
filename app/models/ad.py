from datetime import date, datetime
from typing import Optional
from sqlalchemy import BigInteger, String, Enum, Integer, DECIMAL, Date, DateTime, SmallInteger, JSON, func
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
        Enum("search", "catalog", "product_page", "recommendation", "auction", name="ad_type"),
        nullable=False,
    )
    payment_type: Mapped[str] = mapped_column(
        Enum("cpm", "cpc", "cpo", name="payment_type"),
        nullable=False, default="cpm"
    )
    daily_budget: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 2), nullable=True)
    total_budget: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 2), nullable=True)
    status: Mapped[str] = mapped_column(
        Enum("active", "paused", "archived", "draft", name="campaign_status"),
        nullable=False, default="active"
    )
    start_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    # 旧的 pricing_config_id / custom_* 字段已由 023_bid_management.sql 迁移移除


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
    # 023_bid_management.sql 新增字段
    user_managed: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    user_managed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    original_bid: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 2), nullable=True)
    last_auto_bid: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 2), nullable=True)


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


class AdAutomationRule(BaseMixin, Base):
    """广告自动化规则"""
    __tablename__ = "ad_automation_rules"

    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    rule_type: Mapped[str] = mapped_column(
        Enum("pause_low_roi", "auto_bid", "budget_cap", "schedule", "inventory_link", name="rule_type"),
        nullable=False,
    )
    # 规则条件与动作以JSON存储，灵活扩展
    conditions: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    actions: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    # 作用范围
    platform: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    campaign_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    shop_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    # 状态与执行记录
    enabled: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    last_triggered_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    trigger_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class AdBidLog(BaseMixin, Base):
    """出价调整日志"""
    __tablename__ = "ad_bid_logs"

    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    campaign_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    platform: Mapped[str] = mapped_column(String(20), nullable=False)
    campaign_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    group_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    group_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    old_bid: Mapped[float] = mapped_column(DECIMAL(10, 2), nullable=False)
    new_bid: Mapped[float] = mapped_column(DECIMAL(10, 2), nullable=False)
    change_pct: Mapped[float] = mapped_column(DECIMAL(8, 2), nullable=False)
    reason: Mapped[str] = mapped_column(String(200), nullable=False)
    rule_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    rule_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)


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
    impressions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    clicks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    spend: Mapped[float] = mapped_column(DECIMAL(10, 2), nullable=False, default=0)
    orders: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    revenue: Mapped[float] = mapped_column(DECIMAL(10, 2), nullable=False, default=0)


class AdKeywordProtected(BaseMixin, Base):
    """关键词智能屏蔽白名单（粒度 A：tenant + shop + campaign + nm_id + keyword）

    勾入此表的 (campaign_id, nm_id, keyword) 即使被效能规则判为 waste，
    也不会出现在"建议屏蔽"列表 + "一键屏蔽"会自动剔除。
    """
    __tablename__ = "ad_keyword_protected"

    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    shop_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    campaign_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    nm_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    keyword: Mapped[str] = mapped_column(String(500), nullable=False)


class AdCampaignAutoExclude(BaseMixin, Base):
    """活动级自动屏蔽托管开关 + 最近一次运行快照

    规则参数复用租户级 efficiency_rules（不为活动单独配置规则）。
    """
    __tablename__ = "ad_campaign_auto_exclude"

    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    shop_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    campaign_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    enabled: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    last_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_run_excluded: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_run_saved: Mapped[float] = mapped_column(DECIMAL(12, 2), nullable=False, default=0)


class AdAutoExcludeLog(BaseMixin, Base):
    """自动屏蔽日志：每个被屏蔽词一条，含节省金额估算"""
    __tablename__ = "ad_auto_exclude_log"

    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    shop_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    campaign_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    nm_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    keyword: Mapped[str] = mapped_column(String(500), nullable=False)
    run_id: Mapped[str] = mapped_column(String(50), nullable=False)
    excluded_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    saved_per_day: Mapped[float] = mapped_column(DECIMAL(12, 4), nullable=False, default=0)
    reason: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
