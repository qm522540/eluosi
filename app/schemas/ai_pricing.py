"""AI智能调价 Pydantic 数据模型"""

from typing import Optional, List
from pydantic import BaseModel, Field


class PricingConfigUpdate(BaseModel):
    """更新调价配置"""
    target_roas: Optional[float] = Field(None, gt=0, le=99.99)
    min_roas: Optional[float] = Field(None, gt=0, le=99.99)
    gross_margin: Optional[float] = Field(None, gt=0, lt=1)
    daily_budget_limit: Optional[float] = Field(None, gt=0)
    max_bid: Optional[float] = Field(None, gt=0)
    min_bid: Optional[float] = Field(None, gt=0)
    max_adjust_pct: Optional[float] = Field(None, ge=1, le=100)
    auto_execute: Optional[bool] = None
    is_active: Optional[bool] = None


class AnalyzeRequest(BaseModel):
    """手动触发AI分析"""
    campaign_ids: Optional[List[int]] = None


class ToggleAutoRequest(BaseModel):
    """切换自动/建议模式"""
    auto_execute: bool


class CampaignPricingConfigUpdate(BaseModel):
    """活动调价配置绑定/覆盖"""
    pricing_config_id: Optional[int] = None
    custom_max_bid: Optional[float] = Field(None, gt=0)
    custom_daily_budget: Optional[float] = Field(None, gt=0)
    custom_target_roas: Optional[float] = Field(None, gt=0, le=99.99)
