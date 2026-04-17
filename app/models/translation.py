from sqlalchemy import String, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import BaseMixin


class RuZhDict(Base, BaseMixin):
    """俄→中翻译字典，全局共享（无 tenant_id）"""

    __tablename__ = "ru_zh_dict"

    text_ru_hash: Mapped[str] = mapped_column(String(32), nullable=False)
    text_ru: Mapped[str] = mapped_column(String(500), nullable=False)
    text_zh: Mapped[str] = mapped_column(String(500), nullable=False)
    field_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="attr_value"
    )
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="kimi")

    __table_args__ = (
        Index("uk_hash_type", "text_ru_hash", "field_type", unique=True),
    )
