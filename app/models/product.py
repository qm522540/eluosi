from typing import Optional
from sqlalchemy import BigInteger, String, Enum, Integer, DECIMAL
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import BaseMixin


class Product(BaseMixin, Base):
    __tablename__ = "products"

    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    sku: Mapped[str] = mapped_column(String(50), nullable=False)
    name_zh: Mapped[str] = mapped_column(String(200), nullable=False)
    name_ru: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    brand: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    cost_price: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 2), nullable=True)
    weight_g: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    image_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(
        Enum("active", "inactive", "deleted", name="product_status"),
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
    title_ru: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    price: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 2), nullable=True)
    discount_price: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 2), nullable=True)
    commission_rate: Mapped[Optional[float]] = mapped_column(DECIMAL(5, 2), nullable=True)
    url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    rating: Mapped[Optional[float]] = mapped_column(DECIMAL(3, 2), nullable=True)
    review_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(
        Enum("active", "inactive", "deleted", "out_of_stock", name="listing_status"),
        nullable=False, default="active"
    )
