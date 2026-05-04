"""评价管理模块 ORM 模型 (migration 067)

包含:
  - ShopReview: 评价主表 (WB Feedbacks + Ozon Review 统一存)
  - ShopReviewReply: 回复历史 (草稿 + 真实发送, 多版本留痕)
  - ShopReviewSettings: 店铺级配置 (自动回复开关 + 语气 + 品牌签名)

合规自查:
  - 规则 1 多租户: tenant_id 第一字段 (id 后), service 层 SQL where 必须 AND tenant_id
  - 规则 6 时区: 时间字段 default=utc_now_naive (naive UTC), 跟 DateTime 列直接匹配
  - UNIQUE KEY uk_review (tenant_id, shop_id, platform, platform_review_id)
    防同店同 review 重复入库 (sync 走 INSERT ON DUPLICATE KEY UPDATE 幂等)

关联文档: docs/api/reviews.md (Phase 1.4 待写)
关联迁移: database/migrations/versions/067
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON, BigInteger, DateTime, Enum, SmallInteger, String, Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.utils.moscow_time import utc_now_naive


class ShopReview(Base):
    """评价主表 — WB Feedbacks + Ozon Review 统一存"""
    __tablename__ = "shop_reviews"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    shop_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    platform: Mapped[str] = mapped_column(
        Enum("wb", "ozon", name="review_platform"),
        nullable=False,
    )
    platform_review_id: Mapped[str] = mapped_column(
        String(64), nullable=False,
        comment="WB feedback.id / Ozon review.id (UUID)",
    )
    rating: Mapped[int] = mapped_column(
        SmallInteger, nullable=False,
        comment="1-5 星",
    )
    content_ru: Mapped[str] = mapped_column(Text, nullable=False)
    content_zh: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True,
        comment="AI 中文翻译, 异步填",
    )
    sentiment: Mapped[str] = mapped_column(
        Enum("positive", "neutral", "negative", "unknown", name="review_sentiment"),
        nullable=False, default="unknown",
    )
    customer_name: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True,
        comment="WB userName 有, Ozon 接口不返 → NULL",
    )
    platform_sku_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    platform_product_name: Mapped[Optional[str]] = mapped_column(
        String(500), nullable=True,
        comment="WB 直接含, Ozon 要 sku JOIN platform_listings 反查",
    )
    product_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, nullable=True,
        comment="本地 products.id 反查关联",
    )
    created_at_platform: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True,
        comment="平台评价原始时间 (UTC naive)",
    )
    existing_reply_ru: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    existing_reply_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    is_answered: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0,
        comment="平台 isAnswered / PROCESSED",
    )
    status: Mapped[str] = mapped_column(
        Enum("unread", "read", "replied", "auto_replied", "ignored",
             name="review_status"),
        nullable=False, default="unread",
        comment="本系统业务状态 (跟 is_answered 不等价)",
    )
    raw_payload: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now_naive,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now_naive, onupdate=utc_now_naive,
    )


class ShopReviewReply(Base):
    """评价回复历史 — 含草稿 + 真实发送, 多版本留痕"""
    __tablename__ = "shop_review_replies"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    review_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False,
        comment="shop_reviews.id",
    )
    # AI 草稿
    draft_content_ru: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    draft_content_zh: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    custom_hint: Mapped[Optional[str]] = mapped_column(
        String(500), nullable=True,
        comment="用户输入的重点 (重生成时塞 prompt)",
    )
    generated_count: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0,
        comment="第几次重新生成 (0=首次)",
    )
    ai_model: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    # 真实发送
    final_content_ru: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    final_content_zh: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    sent_status: Mapped[str] = mapped_column(
        Enum("draft", "pending", "sent", "failed", name="review_reply_status"),
        nullable=False, default="draft",
    )
    sent_error_msg: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    is_auto: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0,
        comment="是否走自动回复路径",
    )
    sent_by: Mapped[Optional[int]] = mapped_column(
        BigInteger, nullable=True,
        comment="user_id (auto 时 NULL)",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now_naive,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now_naive, onupdate=utc_now_naive,
    )


class ShopReviewSettings(Base):
    """店铺级评价回复配置 (一店一行)"""
    __tablename__ = "shop_review_settings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    shop_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    auto_reply_enabled: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0,
        comment="自动回复开关 (默认关, 老板验收 AI 草稿质量后再开)",
    )
    auto_reply_rating_floor: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=4,
        comment="自动回复评分下限 (≥ 此星才自动回, 默认 4 即 4-5 星)",
    )
    reply_tone: Mapped[str] = mapped_column(
        Enum("formal", "friendly", "warm", name="review_reply_tone"),
        nullable=False, default="friendly",
    )
    brand_signature: Mapped[Optional[str]] = mapped_column(
        String(200), nullable=True,
        comment="结尾签名 (С любовью, Sharino 等)",
    )
    custom_prompt_extra: Mapped[Optional[str]] = mapped_column(
        String(1000), nullable=True,
        comment="用户自定义 prompt 补充 (品牌特殊调性)",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now_naive,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now_naive, onupdate=utc_now_naive,
    )
