"""出价管理模块模型（023_bid_management.sql 重建）

包含：
  - AiPricingConfig: 店铺级单行配置 + 三模板 JSON + 失败重试
  - AiPricingSuggestion: 精简版建议（platform_sku_id/sku_name/product_stage/decision_basis）
  - TimePricingRule: 店铺级分时调价规则
  - BidAdjustmentLog: 出价调整日志（分时+AI 合并）

#12 修复：所有 default 用 timezone-aware UTC 包装函数 _utc_now，
而不是已弃用的 _utc_now。
"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    JSON, BigInteger, DateTime, DECIMAL, Enum, Integer, SmallInteger, String, Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import BaseMixin


def _utc_now() -> datetime:
    """统一 timezone-aware UTC datetime（避免 _utc_now 弃用警告）"""
    return datetime.now(timezone.utc)


class AiPricingConfig(Base):
    """店铺级 AI 调价配置（一店一行 + 三模板 JSON）"""
    __tablename__ = "ai_pricing_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    shop_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    is_active: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    auto_execute: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    template_name: Mapped[str] = mapped_column(
        Enum("conservative", "default", "aggressive", name="ai_template_name"),
        nullable=False, default="default",
    )
    conservative_config: Mapped[dict] = mapped_column(JSON, nullable=False)
    default_config: Mapped[dict] = mapped_column(JSON, nullable=False)
    aggressive_config: Mapped[dict] = mapped_column(JSON, nullable=False)
    default_client_price: Mapped[float] = mapped_column(
        DECIMAL(10, 2), nullable=False, default=600.00,
        comment="默认客单价（卢布），商品表无数据时使用"
    )
    auto_remove_losing_sku: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0,
        comment="是否自动删除持续亏损SKU：0=不删除 1=自动删除"
    )
    losing_days_threshold: Mapped[int] = mapped_column(
        Integer, nullable=False, default=21,
        comment="亏损判断观察天数，默认21天"
    )
    last_executed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_execute_status: Mapped[Optional[str]] = mapped_column(
        Enum("success", "failed", "partial", name="ai_exec_status"), nullable=True,
    )
    last_error_msg: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    retry_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utc_now, onupdate=_utc_now,
    )


class AiPricingSuggestion(Base):
    """AI 调价建议（精简版，次日过期）"""
    __tablename__ = "ai_pricing_suggestions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    shop_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    campaign_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    platform_sku_id: Mapped[str] = mapped_column(String(100), nullable=False)
    sku_name: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    current_bid: Mapped[float] = mapped_column(DECIMAL(10, 2), nullable=False)
    suggested_bid: Mapped[float] = mapped_column(DECIMAL(10, 2), nullable=False)
    adjust_pct: Mapped[float] = mapped_column(DECIMAL(5, 2), nullable=False)
    product_stage: Mapped[str] = mapped_column(
        Enum("cold_start", "testing", "growing", "declining", "unknown",
             name="ai_product_stage"),
        nullable=False, default="unknown",
    )
    decision_basis: Mapped[str] = mapped_column(
        Enum("history_data", "shop_benchmark", "cold_start_baseline", "imported_data",
             name="ai_decision_basis"),
        nullable=False, default="shop_benchmark",
    )
    current_roas: Mapped[Optional[float]] = mapped_column(DECIMAL(5, 2), nullable=True)
    expected_roas: Mapped[Optional[float]] = mapped_column(DECIMAL(5, 2), nullable=True)
    data_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        Enum("pending", "approved", "rejected", name="ai_suggest_status"),
        nullable=False, default="pending",
    )
    generated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utc_now)
    executed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class TimePricingRule(Base):
    """店铺级分时调价规则"""
    __tablename__ = "time_pricing_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    shop_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    peak_hours: Mapped[list] = mapped_column(JSON, nullable=False)
    peak_ratio: Mapped[int] = mapped_column(Integer, nullable=False, default=120)
    mid_hours: Mapped[list] = mapped_column(JSON, nullable=False)
    mid_ratio: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    low_hours: Mapped[list] = mapped_column(JSON, nullable=False)
    low_ratio: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    is_active: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    last_executed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_execute_result: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utc_now, onupdate=_utc_now,
    )


class BidAdjustmentLog(Base):
    """出价调整日志（分时调价 + AI 调价 合并）"""
    __tablename__ = "bid_adjustment_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    shop_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    campaign_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    campaign_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    platform_sku_id: Mapped[str] = mapped_column(String(100), nullable=False)
    sku_name: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    old_bid: Mapped[float] = mapped_column(DECIMAL(10, 2), nullable=False)
    new_bid: Mapped[float] = mapped_column(DECIMAL(10, 2), nullable=False)
    adjust_pct: Mapped[float] = mapped_column(DECIMAL(5, 2), nullable=False)
    execute_type: Mapped[str] = mapped_column(
        Enum("time_pricing", "ai_auto", "ai_manual", "user_manual",
             "time_restore", "auto_remove",
             name="bid_execute_type"),
        nullable=False,
    )
    time_period: Mapped[Optional[str]] = mapped_column(
        Enum("peak", "mid", "low", name="bid_time_period"), nullable=True,
    )
    period_ratio: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    product_stage: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    moscow_hour: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    success: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    error_msg: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utc_now)
