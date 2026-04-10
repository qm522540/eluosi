"""店铺数据初始化状态模型"""

from datetime import datetime, date
from typing import Optional
from sqlalchemy import BigInteger, Integer, SmallInteger, Date, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import BaseMixin


class ShopDataInitStatus(BaseMixin, Base):
    """记录每个店铺是否已完成首次数据拉取"""
    __tablename__ = "shop_data_init_status"

    shop_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    is_initialized: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    initialized_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_sync_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    last_sync_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
