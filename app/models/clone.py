"""店铺克隆模块 ORM 模型（migration 061 + 062）

包含：
  - CloneTask: 克隆任务（A 店 ← B 店关系 + 配置 + 运行状态快照）
  - ClonePendingProduct: 待审核商品队列（核心交互区）
  - CloneLog: 克隆日志（扫描/审核/发布/跟价）
  - ClonePublishedLink: 已发布关系（追溯 + follow_price_change 跟价数据源）

合规自查：
  - 规则 1: tenant_id 第一字段，service 层 SQL where 必须 AND tenant_id
  - 规则 6: 时间字段 default=utc_now_naive（naive UTC），与 DateTime 列直接匹配
  - 不动 platform_listings.status ENUM，草稿用 status='inactive' + clone_task_id IS NOT NULL

关联文档: docs/api/store_clone.md §3
关联迁移: database/migrations/versions/061 + 062
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON, BigInteger, DateTime, DECIMAL, Enum, Integer, SmallInteger, String, Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.utils.moscow_time import utc_now_naive


class CloneTask(Base):
    """克隆任务（A 店 ← B 店关系 + 配置 + 运行状态快照）"""
    __tablename__ = "clone_tasks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    target_shop_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False,
        comment="A 店（落地店）；路由层 get_owned_shop 守卫归属",
    )
    source_shop_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, nullable=True,
        comment="B 店；Phase 1 必填，Phase 2 公开 API 模式可空",
    )
    source_type: Mapped[str] = mapped_column(
        Enum("seller_api", "public_api", name="clone_source_type"),
        nullable=False, default="seller_api",
    )

    # Phase 2 公开 API 留口（Phase 1 全 NULL）
    source_platform: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    source_external_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    source_sku_whitelist: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)

    is_active: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)

    # 配置
    title_mode: Mapped[str] = mapped_column(
        Enum("original", "ai_rewrite", name="clone_title_mode"),
        nullable=False, default="original",
    )
    desc_mode: Mapped[str] = mapped_column(
        Enum("original", "ai_rewrite", name="clone_desc_mode"),
        nullable=False, default="original",
    )
    price_mode: Mapped[str] = mapped_column(
        Enum("same", "adjust_pct", name="clone_price_mode"),
        nullable=False, default="same",
    )
    price_adjust_pct: Mapped[Optional[float]] = mapped_column(
        DECIMAL(5, 2), nullable=True,
        comment="正数=涨，负数=跌；price_mode=adjust_pct 时必填，范围 [-50, 200]",
    )
    default_stock: Mapped[int] = mapped_column(Integer, nullable=False, default=999)
    follow_price_change: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    follow_status_change: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0,
        comment="是否跟 B 店上下架 (migration 063); status_sync beat 处理",
    )

    category_strategy: Mapped[str] = mapped_column(
        Enum("same_platform", "use_local_map", "reject_if_missing",
             name="clone_category_strategy"),
        nullable=False, default="use_local_map",
    )

    # 运行状态
    last_check_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_found_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_publish_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_skip_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error_msg: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now_naive,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now_naive, onupdate=utc_now_naive,
    )


class ClonePendingProduct(Base):
    """待审核商品队列（核心交互区，UNIQUE task_id+source_sku_id 永久跳过）"""
    __tablename__ = "clone_pending_products"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    task_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # 来源
    source_shop_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    source_platform: Mapped[str] = mapped_column(String(20), nullable=False)
    source_sku_id: Mapped[str] = mapped_column(
        String(100), nullable=False,
        comment="B 平台 SKU（WB nm_id / Ozon offer_id / Yandex offerId）",
    )

    # B 商品快照
    source_snapshot: Mapped[dict] = mapped_column(
        JSON, nullable=False,
        comment="完整 ProductSnapshot dict",
    )

    # 应用规则后的 A 商品 payload
    proposed_payload: Mapped[dict] = mapped_column(
        JSON, nullable=False,
        comment="JSON: {title_ru, description_ru, price_rub, stock, images_oss, "
                "platform_category_id, attributes, _ai_rewrite_failed_*}",
    )

    # 关联 platform_listings 草稿
    draft_listing_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    # 状态机
    status: Mapped[str] = mapped_column(
        Enum("pending", "approved", "rejected", "published", "failed",
             name="clone_pending_status"),
        nullable=False, default="pending",
    )
    category_mapping_status: Mapped[str] = mapped_column(
        Enum("ok", "missing", "ai_suggested", name="clone_category_mapping_status"),
        nullable=False, default="ok",
    )
    reject_reason: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    publish_error_msg: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # 审计
    detected_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    reviewed_by: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    target_platform_sku_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now_naive,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now_naive, onupdate=utc_now_naive,
    )


class CloneLog(Base):
    """克隆日志（扫描/审核/发布/跟价；detail JSON 含跳过明细）"""
    __tablename__ = "clone_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    task_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, nullable=True,
        comment="系统级日志可空，任务相关必填",
    )
    log_type: Mapped[str] = mapped_column(
        Enum("scan", "review", "publish", "price_sync", name="clone_log_type"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        Enum("success", "partial", "failed", "skipped", name="clone_log_status"),
        nullable=False,
    )
    rows_affected: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    detail: Mapped[Optional[dict]] = mapped_column(
        JSON, nullable=True,
        comment="scan 类型含 found/new/skip_*/skipped_skus；其它类型按需填",
    )
    error_msg: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now_naive,
    )


class ClonePublishedLink(Base):
    """已发布关系（追溯 + follow_price_change 跟价数据源）

    source_shop_id 不冗余存储；跟价时通过 task_id JOIN clone_tasks 反查。
    """
    __tablename__ = "clone_published_links"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    task_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    pending_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False,
        comment="关联 clone_pending_products.id（一一对应，UNIQUE）",
    )
    source_platform: Mapped[str] = mapped_column(String(20), nullable=False)
    source_sku_id: Mapped[str] = mapped_column(String(100), nullable=False)
    target_shop_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    target_platform_sku_id: Mapped[str] = mapped_column(String(100), nullable=False)
    target_listing_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    # 跟价数据
    last_synced_price: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 2), nullable=True)
    last_synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    published_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now_naive,
    )
