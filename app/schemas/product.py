"""商品模块 Pydantic 数据模型"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


# ========== 商品（Product）==========

class ProductCreate(BaseModel):
    sku: str = Field(..., min_length=1, max_length=50, description="商品SKU")
    name_zh: str = Field(..., min_length=1, max_length=200, description="中文名称")
    name_ru: Optional[str] = Field(None, max_length=200, description="俄语名称")
    brand: Optional[str] = Field(None, max_length=100, description="品牌")
    category: Optional[str] = Field(None, max_length=200, description="分类")
    cost_price: Optional[float] = Field(None, ge=0, description="成本价(CNY)")
    weight_g: Optional[int] = Field(None, ge=0, description="重量(克)")
    image_url: Optional[str] = Field(None, max_length=500, description="图片URL")
    net_margin: Optional[float] = Field(None, ge=0, le=1, description="净毛利率0-1")


class ProductUpdate(BaseModel):
    name_zh: Optional[str] = Field(None, max_length=200)
    name_ru: Optional[str] = Field(None, max_length=200)
    brand: Optional[str] = Field(None, max_length=100)
    category: Optional[str] = Field(None, max_length=200)
    cost_price: Optional[float] = Field(None, ge=0)
    weight_g: Optional[int] = Field(None, ge=0)
    image_url: Optional[str] = Field(None, max_length=500)
    net_margin: Optional[float] = Field(None, ge=0, le=1)
    status: Optional[str] = Field(None, pattern="^(active|inactive)$")


# ========== 平台Listing ==========

class ListingCreate(BaseModel):
    product_id: int = Field(..., description="关联主商品ID")
    shop_id: int = Field(..., description="关联店铺ID")
    platform: str = Field(..., pattern="^(wb|ozon|yandex)$", description="平台")
    platform_product_id: str = Field(..., max_length=100, description="平台商品ID")
    title_ru: Optional[str] = Field(None, max_length=500, description="俄语标题")
    price: Optional[float] = Field(None, ge=0, description="售价(RUB)")
    discount_price: Optional[float] = Field(None, ge=0, description="折扣价(RUB)")
    commission_rate: Optional[float] = Field(None, ge=0, le=100, description="佣金率(%)")
    url: Optional[str] = Field(None, max_length=500, description="商品链接")
    barcode: Optional[str] = Field(None, max_length=50)
    description_ru: Optional[str] = None
    variant_name: Optional[str] = Field(None, max_length=100)
    variant_attrs: Optional[Dict[str, Any]] = None
    platform_listed_at: Optional[datetime] = None


class ListingUpdate(BaseModel):
    title_ru: Optional[str] = Field(None, max_length=500)
    price: Optional[float] = Field(None, ge=0)
    discount_price: Optional[float] = Field(None, ge=0)
    commission_rate: Optional[float] = Field(None, ge=0, le=100)
    url: Optional[str] = Field(None, max_length=500)
    barcode: Optional[str] = Field(None, max_length=50)
    description_ru: Optional[str] = None
    variant_name: Optional[str] = Field(None, max_length=100)
    variant_attrs: Optional[Dict[str, Any]] = None
    oss_images: Optional[Dict[str, Any]] = None
    oss_videos: Optional[Dict[str, Any]] = None
    status: Optional[str] = Field(None, pattern="^(active|inactive|out_of_stock|blocked|deleted)$")


# ========== 商品同步 ==========

class ProductSyncRequest(BaseModel):
    shop_id: int
    force: bool = Field(False, description="强制同步，忽略30分钟限制")


# ========== 净毛利率快速编辑 ==========

class ProductMarginUpdate(BaseModel):
    net_margin: Optional[float] = Field(None, ge=0, le=1)


# ========== 描述AI改写 ==========

class GenerateDescriptionRequest(BaseModel):
    listing_id: int
    target_platform: str = Field(..., pattern="^(wb|ozon|yandex)$")


# ========== 铺货 ==========

class SpreadRequest(BaseModel):
    src_listing_ids: List[int]
    dst_shop_ids: List[int]
    price_mode: str = Field("original", pattern="^(original|manual|auto)$")
    manual_price: Optional[float] = Field(None, ge=0)
    ai_rewrite_title: bool = False
    ai_change_bg: bool = False
