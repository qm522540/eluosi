"""AI智能调价模型"""

from datetime import datetime
from typing import Optional
from sqlalchemy import BigInteger, Integer, String, DECIMAL, Text, DateTime, SmallInteger, Enum
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import BaseMixin


class AiPricingConfig(BaseMixin, Base):
    """品类调价配置"""
    __tablename__ = "ai_pricing_configs"

    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    shop_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    category_name: Mapped[str] = mapped_column(String(100), nullable=False)
    target_roas: Mapped[float] = mapped_column(DECIMAL(5, 2), nullable=False, default=2.00)
    min_roas: Mapped[float] = mapped_column(DECIMAL(5, 2), nullable=False, default=1.20)
    gross_margin: Mapped[float] = mapped_column(DECIMAL(5, 2), nullable=False, default=0.50)
    daily_budget_limit: Mapped[float] = mapped_column(DECIMAL(10, 2), nullable=False, default=1000.00)
    max_bid: Mapped[float] = mapped_column(DECIMAL(10, 2), nullable=False, default=200.00)
    min_bid: Mapped[float] = mapped_column(DECIMAL(10, 2), nullable=False, default=3.00)
    max_adjust_pct: Mapped[float] = mapped_column(DECIMAL(5, 2), nullable=False, default=30.00)
    auto_execute: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    is_active: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)


class AiPricingSuggestion(BaseMixin, Base):
    """AI调价建议记录"""
    __tablename__ = "ai_pricing_suggestions"

    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    shop_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    campaign_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    product_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    product_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    image_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    current_bid: Mapped[float] = mapped_column(DECIMAL(10, 2), nullable=False)
    suggested_bid: Mapped[float] = mapped_column(DECIMAL(10, 2), nullable=False)
    adjust_pct: Mapped[float] = mapped_column(DECIMAL(5, 2), nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    current_roas: Mapped[Optional[float]] = mapped_column(DECIMAL(5, 2), nullable=True)
    expected_roas: Mapped[Optional[float]] = mapped_column(DECIMAL(5, 2), nullable=True)
    current_spend: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 2), nullable=True)
    daily_budget: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 2), nullable=True)
    ai_model: Mapped[str] = mapped_column(String(50), nullable=False, default="deepseek")
    status: Mapped[str] = mapped_column(
        Enum("pending", "approved", "rejected", "executed", "expired", name="suggestion_status"),
        nullable=False, default="pending"
    )
    auto_executed: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    executed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    decision_basis: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, default="today_only")
    history_avg_roas: Mapped[Optional[float]] = mapped_column(DECIMAL(5, 2), nullable=True, default=0)
    data_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=0)
    time_slot: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    moscow_hour: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
