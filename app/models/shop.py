from datetime import datetime
from typing import Optional
from sqlalchemy import BigInteger, String, Enum, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import BaseMixin


class Shop(BaseMixin, Base):
    __tablename__ = "shops"

    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    platform: Mapped[str] = mapped_column(
        Enum("wb", "ozon", "yandex", name="platform_type"), nullable=False
    )
    platform_seller_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    api_key: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    api_secret: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    client_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    oauth_token: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
    oauth_refresh_token: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
    oauth_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # Ozon Performance API（广告）独立凭证
    perf_client_id: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    perf_client_secret: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="RUB")
    timezone: Mapped[str] = mapped_column(String(50), nullable=False, default="Europe/Moscow")
    status: Mapped[str] = mapped_column(
        Enum("active", "inactive", "deleted", name="shop_status"),
        nullable=False, default="active"
    )
    last_sync_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
