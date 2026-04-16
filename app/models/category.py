"""映射管理模型：本地统一分类 + 品类/属性/属性值三层映射"""

from datetime import datetime
from typing import Optional, Any
from sqlalchemy import BigInteger, String, Enum, Integer, DECIMAL, Text, DateTime, SmallInteger
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import BaseMixin


class LocalCategory(BaseMixin, Base):
    """本地统一分类树（租户级）"""
    __tablename__ = "local_categories"

    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    parent_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, comment="分类名称（中文）")
    name_ru: Mapped[Optional[str]] = mapped_column(String(200), nullable=True, comment="分类名称（俄文）")
    level: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(
        Enum("active", "inactive", name="local_category_status"),
        nullable=False, default="active"
    )


class CategoryPlatformMapping(BaseMixin, Base):
    """品类映射：本地分类 → 各平台分类"""
    __tablename__ = "category_platform_mappings"

    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    local_category_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    platform: Mapped[str] = mapped_column(String(20), nullable=False)
    platform_category_id: Mapped[str] = mapped_column(String(100), nullable=False, comment="WB=subjectID, Ozon=description_category_id")
    platform_category_extra_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, comment="Ozon=type_id, WB 为空")
    platform_category_name: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    platform_parent_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    ai_suggested: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    ai_confidence: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    is_confirmed: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class AttributeMapping(BaseMixin, Base):
    """属性映射：本地属性 → 各平台属性"""
    __tablename__ = "attribute_mappings"

    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    local_category_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    local_attr_name: Mapped[str] = mapped_column(String(200), nullable=False)
    local_attr_name_ru: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    platform: Mapped[str] = mapped_column(String(20), nullable=False)
    platform_attr_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    platform_attr_name: Mapped[str] = mapped_column(String(200), nullable=False)
    is_required: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    value_type: Mapped[str] = mapped_column(String(20), nullable=False, default="string")
    platform_dict_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    ai_suggested: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    ai_confidence: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    is_confirmed: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class AttributeValueMapping(BaseMixin, Base):
    """属性值映射：本地属性值 → 各平台枚举值"""
    __tablename__ = "attribute_value_mappings"

    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    attribute_mapping_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    local_value: Mapped[str] = mapped_column(String(500), nullable=False)
    local_value_ru: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    platform_value: Mapped[str] = mapped_column(String(500), nullable=False)
    platform_value_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    ai_suggested: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    ai_confidence: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    is_confirmed: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
