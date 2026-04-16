"""映射管理相关的 Pydantic schema"""

from typing import Optional, List
from pydantic import BaseModel, Field


# ==================== 本地分类 ====================

class LocalCategoryCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    name_ru: Optional[str] = Field(None, max_length=200)
    parent_id: Optional[int] = None
    sort_order: int = 0


class LocalCategoryUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    name_ru: Optional[str] = Field(None, max_length=200)
    parent_id: Optional[int] = None
    sort_order: Optional[int] = None
    status: Optional[str] = None


# ==================== 品类映射 ====================

class CategoryMappingCreate(BaseModel):
    local_category_id: int
    platform: str = Field(..., pattern="^(wb|ozon|yandex)$")
    platform_category_id: str
    platform_category_extra_id: Optional[str] = None
    platform_category_name: Optional[str] = None
    platform_parent_path: Optional[str] = None
    ai_suggested: int = 0
    ai_confidence: int = 0


class CategoryMappingUpdate(BaseModel):
    platform_category_id: Optional[str] = None
    platform_category_extra_id: Optional[str] = None
    platform_category_name: Optional[str] = None
    platform_parent_path: Optional[str] = None
    is_confirmed: Optional[int] = None


# ==================== 属性映射 ====================

class AttributeMappingCreate(BaseModel):
    local_category_id: int
    local_attr_name: str = Field(..., min_length=1, max_length=200)
    local_attr_name_ru: Optional[str] = None
    platform: str = Field(..., pattern="^(wb|ozon|yandex)$")
    platform_attr_id: Optional[str] = None
    platform_attr_name: str = Field(..., min_length=1, max_length=200)
    is_required: int = 0
    value_type: str = "string"
    platform_dict_id: Optional[str] = None
    ai_suggested: int = 0
    ai_confidence: int = 0


class AttributeMappingUpdate(BaseModel):
    local_attr_name: Optional[str] = None
    local_attr_name_ru: Optional[str] = None
    platform_attr_id: Optional[str] = None
    platform_attr_name: Optional[str] = None
    is_required: Optional[int] = None
    value_type: Optional[str] = None
    platform_dict_id: Optional[str] = None
    is_confirmed: Optional[int] = None


# ==================== 属性值映射 ====================

class AttributeValueMappingCreate(BaseModel):
    attribute_mapping_id: int
    local_value: str = Field(..., min_length=1, max_length=500)
    local_value_ru: Optional[str] = None
    platform_value: str = Field(..., min_length=1, max_length=500)
    platform_value_id: Optional[str] = None
    ai_suggested: int = 0
    ai_confidence: int = 0


class AttributeValueMappingUpdate(BaseModel):
    local_value: Optional[str] = None
    local_value_ru: Optional[str] = None
    platform_value: Optional[str] = None
    platform_value_id: Optional[str] = None
    is_confirmed: Optional[int] = None


# ==================== AI 推荐 ====================

class AISuggestCategoryRequest(BaseModel):
    """AI 推荐品类映射"""
    local_category_id: int
    platforms: List[str] = ["wb", "ozon"]
    shop_id: int  # 用哪个店铺的凭证拉平台分类


class AISuggestAttributesRequest(BaseModel):
    """AI 推荐属性映射"""
    local_category_id: int
    shop_id: int
    platform: str
