from datetime import date, datetime
from typing import Optional
from sqlalchemy import BigInteger, String, Enum, Integer, DECIMAL, Date, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import BaseMixin


class InventoryStock(BaseMixin, Base):
    __tablename__ = "inventory_stocks"

    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    shop_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    warehouse_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reserved: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    min_threshold: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    max_threshold: Mapped[int] = mapped_column(Integer, nullable=False, default=1000)
    last_synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class PurchaseOrder(BaseMixin, Base):
    __tablename__ = "purchase_orders"

    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    po_number: Mapped[str] = mapped_column(String(50), nullable=False)
    supplier_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    total_amount: Mapped[float] = mapped_column(DECIMAL(10, 2), nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="CNY")
    status: Mapped[str] = mapped_column(
        Enum("draft", "pending", "approved", "ordered", "received", "cancelled", name="po_status"),
        nullable=False, default="draft"
    )
    expected_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False)


class PurchaseOrderItem(BaseMixin, Base):
    __tablename__ = "purchase_order_items"

    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    po_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[float] = mapped_column(DECIMAL(10, 2), nullable=False)
    total_price: Mapped[float] = mapped_column(DECIMAL(10, 2), nullable=False)
    received_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
