from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import BigInteger, String, Enum, DateTime, Text, JSON, DECIMAL, Integer, SmallInteger
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import BaseMixin


class SeoKeyword(BaseMixin, Base):
    __tablename__ = "seo_keywords"

    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    platform: Mapped[str] = mapped_column(
        Enum("wb", "ozon", "yandex", name="seo_platform"), nullable=False
    )
    keyword_ru: Mapped[str] = mapped_column(String(200), nullable=False)
    keyword_zh: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    search_volume: Mapped[Optional[int]] = mapped_column(nullable=True)
    competition: Mapped[Optional[str]] = mapped_column(
        Enum("low", "medium", "high", name="competition_level"), nullable=True
    )
    category: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    source: Mapped[str] = mapped_column(
        Enum("platform", "manual", "ai_suggested", name="keyword_source"),
        nullable=False, default="manual"
    )
    status: Mapped[str] = mapped_column(
        Enum("active", "inactive", name="seo_kw_status"),
        nullable=False, default="active"
    )


class SeoTemplate(BaseMixin, Base):
    __tablename__ = "seo_templates"

    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    platform: Mapped[str] = mapped_column(
        Enum("wb", "ozon", "yandex", name="tpl_platform"), nullable=False
    )
    category: Mapped[str] = mapped_column(String(200), nullable=False)
    template_type: Mapped[str] = mapped_column(
        Enum("title", "description", "bullet_points", "rich_content", name="template_type"),
        nullable=False,
    )
    template_text: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(String(5), nullable=False, default="ru")
    status: Mapped[str] = mapped_column(
        Enum("active", "inactive", name="tpl_status"),
        nullable=False, default="active"
    )


class SeoGeneratedContent(BaseMixin, Base):
    __tablename__ = "seo_generated_contents"

    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    listing_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    content_type: Mapped[str] = mapped_column(
        Enum("title", "description", "bullet_points", "rich_content", name="content_type"),
        nullable=False,
    )
    original_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    generated_text: Mapped[str] = mapped_column(Text, nullable=False)
    keywords_used: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    ai_model: Mapped[str] = mapped_column(
        Enum("deepseek", "kimi", "glm", name="seo_ai_model"), nullable=False
    )
    ai_decision_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    approval_status: Mapped[str] = mapped_column(
        Enum("pending", "approved", "rejected", "applied", name="approval_status"),
        nullable=False, default="pending"
    )
    approved_by: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    applied_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class SeoKeywordCandidate(Base):
    """SEO 优化候选词池（多源融合，付费反哺自然）

    一期仅接入源 A（付费词）+ C1-a（本店同类目付费聚合）。
    二期接源 B（自然词），三期接 Wordstat。
    sources JSON 数组元素为 {"type": "paid|organic|wordstat", "scope": "self|category"}。
    """
    __tablename__ = "seo_keyword_candidates"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    shop_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    product_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    keyword: Mapped[str] = mapped_column(String(200), nullable=False)
    sources: Mapped[list] = mapped_column(JSON, nullable=False)
    score: Mapped[float] = mapped_column(DECIMAL(6, 2), nullable=False, default=0)

    paid_roas: Mapped[Optional[float]] = mapped_column(DECIMAL(8, 2), nullable=True)
    paid_orders: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    paid_spend: Mapped[Optional[float]] = mapped_column(DECIMAL(12, 2), nullable=True)
    paid_revenue: Mapped[Optional[float]] = mapped_column(DECIMAL(12, 2), nullable=True)

    organic_impressions: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    organic_add_to_cart: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    organic_orders: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    wordstat_volume: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    in_title: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    in_attrs: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)

    status: Mapped[str] = mapped_column(
        Enum("pending", "adopted", "ignored", "processed", name="seo_cand_status"),
        nullable=False, default="pending"
    )
    adopted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    adopted_by: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
