from datetime import datetime
from typing import Optional, Any
from sqlalchemy import BigInteger, String, Enum, Integer, DECIMAL, Text, JSON, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import BaseMixin


class Product(BaseMixin, Base):
    __tablename__ = "products"

    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    shop_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, comment="所属店铺ID（同一SKU在不同店铺独立记录）")
    sku: Mapped[str] = mapped_column(String(50), nullable=False)
    name_zh: Mapped[str] = mapped_column(String(200), nullable=False)
    name_ru: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    brand: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    local_category_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, comment="本地统一分类ID")
    cost_price: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 2), nullable=True)
    net_margin: Mapped[Optional[float]] = mapped_column(
        DECIMAL(5, 2), nullable=True,
        comment="商品净毛利率(0-1)，为空则使用店铺默认配置gross_margin"
    )
    weight_g: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    length_mm: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="长(毫米)")
    width_mm: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="宽(毫米)")
    height_mm: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="高(毫米)")
    image_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(
        Enum("active", "inactive", "deleted", "archived", name="product_status"),
        nullable=False, default="active"
    )


class PlatformListing(BaseMixin, Base):
    __tablename__ = "platform_listings"

    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    shop_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    platform: Mapped[str] = mapped_column(
        Enum("wb", "ozon", "yandex", name="listing_platform"), nullable=False
    )
    platform_product_id: Mapped[str] = mapped_column(String(100), nullable=False)
    platform_sku_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, comment="OZON sku_id / WB nm_id（广告 API 返回的 sku）")
    platform_category_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, comment="平台分类ID")
    platform_category_name: Mapped[Optional[str]] = mapped_column(String(300), nullable=True, comment="平台分类名称")
    platform_category_extra_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, comment="Ozon=type_id, WB/Yandex 为空")
    barcode: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    title_ru: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    description_ru: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    variant_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    variant_attrs: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    platform_listed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    oss_images: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    oss_videos: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    source_listing_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    publish_status: Mapped[str] = mapped_column(
        Enum("draft", "pending", "published", name="listing_publish_status"),
        nullable=False, default="published"
    )
    price: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 2), nullable=True)
    stock: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="当前可售库存")
    stock_updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    discount_price: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 2), nullable=True)
    commission_rate: Mapped[Optional[float]] = mapped_column(DECIMAL(5, 2), nullable=True)
    url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    rating: Mapped[Optional[float]] = mapped_column(DECIMAL(3, 2), nullable=True)
    review_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(
        Enum("active", "inactive", "deleted", "out_of_stock", "blocked", "archived", name="listing_status"),
        nullable=False, default="active"
    )
    clone_task_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, nullable=True,
        comment="关联 clone_tasks.id; 非 NULL = 店铺克隆草稿; NULL = 普通 listing"
    )
