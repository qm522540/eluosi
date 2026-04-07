from datetime import datetime
from typing import Optional
from sqlalchemy import BigInteger, String, Enum, Integer, DateTime, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import BaseMixin


class TaskLog(BaseMixin, Base):
    __tablename__ = "task_logs"

    tenant_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    task_name: Mapped[str] = mapped_column(String(100), nullable=False)
    celery_task_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    params: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(
        Enum("pending", "running", "success", "failed", "retrying", name="task_status"),
        nullable=False, default="pending"
    )
    result: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
