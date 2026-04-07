"""广告路由"""

from datetime import date, timedelta
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_current_user, get_tenant_id
from app.schemas.ad import AdCampaignUpdate
from app.services.ad.service import (
    list_campaigns, get_campaign, update_campaign,
    get_ad_stats, get_ad_summary,
)
from app.utils.response import success, error

router = APIRouter()


@router.get("/campaigns")
def campaign_list(
    shop_id: int = Query(None, description="店铺ID筛选"),
    platform: str = Query(None, description="平台筛选: wb/ozon/yandex"),
    status: str = Query(None, description="状态筛选: active/paused/archived"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """获取广告活动列表"""
    result = list_campaigns(db, tenant_id, shop_id=shop_id, platform=platform,
                            status=status, page=page, page_size=page_size)
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"])


@router.get("/campaigns/{campaign_id}")
def campaign_detail(
    campaign_id: int,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """获取广告活动详情（含广告组）"""
    result = get_campaign(db, campaign_id, tenant_id)
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"])


@router.put("/campaigns/{campaign_id}")
def campaign_update(
    campaign_id: int,
    req: AdCampaignUpdate,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """更新广告活动（调整预算/状态）"""
    result = update_campaign(db, campaign_id, tenant_id, req.model_dump(exclude_none=True))
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"], msg="广告活动更新成功")


@router.get("/stats")
def ad_stats(
    start_date: date = Query(..., description="开始日期"),
    end_date: date = Query(..., description="结束日期"),
    shop_id: int = Query(None, description="店铺ID"),
    campaign_id: int = Query(None, description="广告活动ID"),
    platform: str = Query(None, description="平台筛选"),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """查询广告统计数据（按天+平台汇总）"""
    result = get_ad_stats(db, tenant_id, start_date, end_date,
                          shop_id=shop_id, campaign_id=campaign_id, platform=platform)
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"])


@router.get("/summary")
def ad_summary(
    start_date: date = Query(None, description="开始日期(默认今天)"),
    end_date: date = Query(None, description="结束日期(默认今天)"),
    shop_id: int = Query(None, description="店铺ID"),
    platform: str = Query(None, description="平台筛选"),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """获取广告汇总数据（Dashboard用）"""
    today = date.today()
    if not start_date:
        start_date = today
    if not end_date:
        end_date = today
    result = get_ad_summary(db, tenant_id, start_date, end_date,
                            shop_id=shop_id, platform=platform)
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"])
