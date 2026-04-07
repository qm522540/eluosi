"""财务模块 Pydantic 数据模型"""

from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel, Field


class FinanceCostCreate(BaseModel):
    shop_id: int = Field(..., description="店铺ID")
    listing_id: Optional[int] = Field(None, description="Listing ID")
    cost_date: date = Field(..., description="费用日期")
    cost_type: str = Field(..., pattern="^(ad_spend|logistics|commission|storage|other)$", description="费用类型")
    amount: float = Field(..., ge=0, description="金额(RUB)")
    currency: str = Field("RUB", description="货币")
    notes: Optional[str] = Field(None, max_length=500, description="备注")


class FinanceCostInfo(BaseModel):
    id: int
    shop_id: int
    listing_id: Optional[int] = None
    cost_date: date
    cost_type: str
    amount: float
    currency: str
    notes: Optional[str] = None
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class RoiSnapshotInfo(BaseModel):
    shop_id: int
    snapshot_date: date
    period: str
    total_revenue: float = 0
    total_cost: float = 0
    ad_spend: float = 0
    gross_profit: float = 0
    roi: Optional[float] = None
    roas: Optional[float] = None

    model_config = {"from_attributes": True}


class DashboardOverview(BaseModel):
    """首页大盘统计"""
    shop_count: int = 0
    product_count: int = 0
    active_campaigns: int = 0
    today_revenue: float = 0
    today_spend: float = 0
    today_roi: Optional[float] = None
