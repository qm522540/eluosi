from typing import Optional
from sqlalchemy import BigInteger, String, Enum, Integer, DECIMAL, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import BaseMixin


class AiDecisionLog(BaseMixin, Base):
    __tablename__ = "ai_decision_logs"

    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    task_type: Mapped[str] = mapped_column(
        Enum("ad_optimization", "seo_generation", "roi_analysis",
             "inventory_forecast", "report_generation", name="ai_task_type"),
        nullable=False,
    )
    ai_model: Mapped[str] = mapped_column(
        Enum("deepseek", "kimi", "glm", name="ai_model"), nullable=False
    )
    input_data: Mapped[dict] = mapped_column(JSON, nullable=False)
    output_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    prompt_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 6), nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(
        Enum("pending", "success", "failed", "timeout", name="ai_status"),
        nullable=False, default="pending"
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    triggered_by: Mapped[str] = mapped_column(
        Enum("manual", "scheduled", "alert", name="trigger_type"),
        nullable=False, default="scheduled"
    )
    user_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
