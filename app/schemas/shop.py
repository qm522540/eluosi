"""店铺模块 Pydantic 数据模型"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class ShopCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="店铺名称")
    platform: str = Field(..., pattern="^(wb|ozon|yandex)$", description="平台: wb/ozon/yandex")
    platform_seller_id: Optional[str] = Field(None, description="平台卖家ID")
    api_key: Optional[str] = Field(None, description="API Key")
    api_secret: Optional[str] = Field(None, description="API Secret")
    client_id: Optional[str] = Field(None, description="Client ID (Ozon卖家API)")
    oauth_token: Optional[str] = Field(None, description="OAuth Token (Yandex)")
    oauth_refresh_token: Optional[str] = Field(None, description="OAuth Refresh Token (Yandex)")
    perf_client_id: Optional[str] = Field(None, description="Ozon广告API Client ID")
    perf_client_secret: Optional[str] = Field(None, description="Ozon广告API Client Secret")
    yandex_business_id: Optional[str] = Field(None, description="Yandex Market Business ID")
    yandex_campaign_id: Optional[str] = Field(None, description="Yandex Market Campaign ID")
    currency: str = Field("RUB", description="货币")
    timezone: str = Field("Europe/Moscow", description="时区")


class ShopUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    platform_seller_id: Optional[str] = None
    api_key: Optional[str] = None
    api_secret: Optional[str] = None
    client_id: Optional[str] = None
    oauth_token: Optional[str] = None
    oauth_refresh_token: Optional[str] = None
    perf_client_id: Optional[str] = None
    perf_client_secret: Optional[str] = None
    yandex_business_id: Optional[str] = None
    yandex_campaign_id: Optional[str] = None
    currency: Optional[str] = None
    timezone: Optional[str] = None
    status: Optional[str] = Field(None, pattern="^(active|inactive)$")


class ShopInfo(BaseModel):
    id: int
    tenant_id: int
    name: str
    platform: str
    platform_seller_id: Optional[str] = None
    currency: str
    timezone: str
    status: str
    last_sync_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ShopDetail(ShopInfo):
    """店铺详情（包含凭证是否已配置的标记，不返回明文密钥）"""
    has_api_key: bool = False
    has_api_secret: bool = False
    has_client_id: bool = False
    has_oauth_token: bool = False
    has_perf_client_id: bool = False
    has_perf_client_secret: bool = False
