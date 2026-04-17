"""全局映射建议 ORM（跨租户共享）"""
from sqlalchemy import String, Integer, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import BaseMixin


class GlobalCategoryHint(Base, BaseMixin):
    """单平台分类"大家怎么叫它"建议"""

    __tablename__ = "global_category_hints"

    platform: Mapped[str] = mapped_column(String(16), nullable=False)
    platform_category_id: Mapped[str] = mapped_column(String(100), nullable=False)
    platform_category_name_ru: Mapped[str] = mapped_column(String(500), nullable=True)
    suggested_local_name_zh: Mapped[str] = mapped_column(String(200), nullable=True)
    top_name_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_confirmed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        Index("uk_platform_cat", "platform", "platform_category_id", unique=True),
    )


class GlobalCrossPlatformCategoryHint(Base, BaseMixin):
    """跨平台分类共现建议"""

    __tablename__ = "global_cross_platform_category_hints"

    platform_a: Mapped[str] = mapped_column(String(16), nullable=False)
    category_a_id: Mapped[str] = mapped_column(String(100), nullable=False)
    platform_b: Mapped[str] = mapped_column(String(16), nullable=False)
    category_b_id: Mapped[str] = mapped_column(String(100), nullable=False)
    co_confirmed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        Index("uk_pair", "platform_a", "category_a_id",
              "platform_b", "category_b_id", unique=True),
        Index("idx_lookup", "platform_a", "category_a_id"),
    )


class GlobalAttributeHint(Base, BaseMixin):
    """单平台属性"大家怎么叫它"建议"""

    __tablename__ = "global_attribute_hints"

    platform: Mapped[str] = mapped_column(String(16), nullable=False)
    platform_attr_id: Mapped[str] = mapped_column(String(100), nullable=False)
    platform_attr_name_ru: Mapped[str] = mapped_column(String(500), nullable=True)
    suggested_local_name_zh: Mapped[str] = mapped_column(String(200), nullable=True)
    top_name_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_confirmed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        Index("uk_platform_attr", "platform", "platform_attr_id", unique=True),
    )
