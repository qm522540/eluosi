"""广告模块 Pydantic 数据模型"""

from datetime import date, datetime
from typing import Optional, List
from pydantic import BaseModel, Field


class AdCampaignInfo(BaseModel):
    id: int
    tenant_id: int
    shop_id: int
    platform: str
    platform_campaign_id: str
    name: str
    ad_type: str
    daily_budget: Optional[float] = None
    total_budget: Optional[float] = None
    status: str
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class AdCampaignUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=200)
    daily_budget: Optional[float] = Field(None, ge=0)
    total_budget: Optional[float] = Field(None, ge=0)
    status: Optional[str] = Field(None, pattern="^(active|paused)$")


class AdStatQuery(BaseModel):
    """广告统计查询参数"""
    shop_id: Optional[int] = None
    campaign_id: Optional[int] = None
    platform: Optional[str] = Field(None, pattern="^(wb|ozon|yandex)$")
    start_date: date = Field(..., description="开始日期")
    end_date: date = Field(..., description="结束日期")


class AdStatInfo(BaseModel):
    stat_date: date
    platform: str
    impressions: int = 0
    clicks: int = 0
    spend: float = 0
    orders: int = 0
    revenue: float = 0
    ctr: Optional[float] = None
    cpc: Optional[float] = None
    acos: Optional[float] = None
    roas: Optional[float] = None

    model_config = {"from_attributes": True}


class AdSummary(BaseModel):
    """广告汇总数据"""
    total_impressions: int = 0
    total_clicks: int = 0
    total_spend: float = 0
    total_orders: int = 0
    total_revenue: float = 0
    avg_ctr: Optional[float] = None
    avg_cpc: Optional[float] = None
    overall_acos: Optional[float] = None
    overall_roas: Optional[float] = None
