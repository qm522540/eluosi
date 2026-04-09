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


class AdCampaignCreate(BaseModel):
    """创建广告活动"""
    shop_id: int
    platform: str = Field(..., pattern="^(wb|ozon|yandex)$")
    name: str = Field(..., max_length=200)
    ad_type: str = Field(..., pattern="^(search|catalog|product_page|recommendation|auction)$")
    daily_budget: Optional[float] = Field(None, ge=0)
    total_budget: Optional[float] = Field(None, ge=0)
    status: str = Field("draft", pattern="^(active|paused|draft)$")
    start_date: Optional[date] = None
    end_date: Optional[date] = None


class AdCampaignUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=200)
    daily_budget: Optional[float] = Field(None, ge=0)
    total_budget: Optional[float] = Field(None, ge=0)
    status: Optional[str] = Field(None, pattern="^(active|paused)$")


class AdGroupCreate(BaseModel):
    """创建广告组"""
    campaign_id: int
    name: str = Field(..., max_length=200)
    bid: Optional[float] = Field(None, ge=0)
    listing_id: Optional[int] = None
    status: str = Field("active", pattern="^(active|paused)$")


class AdGroupUpdate(BaseModel):
    """更新广告组"""
    name: Optional[str] = Field(None, max_length=200)
    bid: Optional[float] = Field(None, ge=0)
    listing_id: Optional[int] = None
    status: Optional[str] = Field(None, pattern="^(active|paused|archived)$")


class AdKeywordCreate(BaseModel):
    """创建关键词"""
    ad_group_id: int
    keyword: str = Field(..., max_length=200)
    match_type: str = Field("broad", pattern="^(exact|phrase|broad)$")
    bid: Optional[float] = Field(None, ge=0)
    is_negative: int = Field(0, ge=0, le=1)
    status: str = Field("active", pattern="^(active|paused)$")


class AdKeywordUpdate(BaseModel):
    """更新关键词"""
    keyword: Optional[str] = Field(None, max_length=200)
    match_type: Optional[str] = Field(None, pattern="^(exact|phrase|broad)$")
    bid: Optional[float] = Field(None, ge=0)
    is_negative: Optional[int] = Field(None, ge=0, le=1)
    status: Optional[str] = Field(None, pattern="^(active|paused|deleted)$")


class AdKeywordBatchCreate(BaseModel):
    """批量创建关键词"""
    ad_group_id: int
    keywords: List[str] = Field(..., min_length=1, max_length=100)
    match_type: str = Field("broad", pattern="^(exact|phrase|broad)$")
    bid: Optional[float] = Field(None, ge=0)
    is_negative: int = Field(0, ge=0, le=1)


class BidOptimizeRequest(BaseModel):
    """出价优化请求"""
    campaign_id: int
    target_roas: float = Field(2.0, gt=0, description="目标ROAS")
    max_bid_increase: float = Field(30, ge=0, le=100, description="最大加价比例%")
    max_bid_decrease: float = Field(30, ge=0, le=100, description="最大降价比例%")


class AlertConfigUpdate(BaseModel):
    """告警阈值配置"""
    acos_warning: Optional[float] = Field(None, ge=0, le=100, description="ACOS警告阈值%")
    acos_critical: Optional[float] = Field(None, ge=0, le=100, description="ACOS严重阈值%")
    roas_warning: Optional[float] = Field(None, ge=0, description="ROAS警告阈值")
    budget_usage_threshold: Optional[float] = Field(None, ge=0, le=1, description="预算使用率阈值")
    roas_critical_with_budget: Optional[float] = Field(None, ge=0, description="预算超标时ROAS阈值")


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


# ==================== 自动化规则 ====================

class AutoRuleCreate(BaseModel):
    """创建自动化规则"""
    name: str = Field(..., max_length=200)
    rule_type: str = Field(..., pattern="^(pause_low_roi|auto_bid|budget_cap|schedule|inventory_link)$")
    conditions: Optional[dict] = None
    actions: Optional[dict] = None
    platform: Optional[str] = Field(None, pattern="^(wb|ozon|yandex)$")
    campaign_id: Optional[int] = None
    shop_id: Optional[int] = None
    enabled: int = Field(1, ge=0, le=1)


class AutoRuleUpdate(BaseModel):
    """更新自动化规则"""
    name: Optional[str] = Field(None, max_length=200)
    conditions: Optional[dict] = None
    actions: Optional[dict] = None
    platform: Optional[str] = Field(None, pattern="^(wb|ozon|yandex)$")
    campaign_id: Optional[int] = None
    shop_id: Optional[int] = None
    enabled: Optional[int] = Field(None, ge=0, le=1)
