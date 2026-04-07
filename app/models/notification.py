from datetime import datetime
from typing import Optional
from sqlalchemy import BigInteger, String, Enum, DateTime, Text, SmallInteger
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import BaseMixin


class Notification(BaseMixin, Base):
    __tablename__ = "notifications"

    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    user_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    notification_type: Mapped[str] = mapped_column(
        Enum("roi_alert", "task_failure", "ai_decision", "daily_report",
             "stock_alert", "system", name="notification_type"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    channel: Mapped[str] = mapped_column(
        Enum("wechat_work", "in_app", "both", name="channel_type"),
        nullable=False, default="both"
    )
    is_read: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    read_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
