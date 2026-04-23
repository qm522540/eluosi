"""财务路由"""

from datetime import date, timedelta
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_current_user, get_tenant_id
from app.schemas.finance import FinanceCostCreate
from app.services.finance.service import (
    get_revenue_list, get_cost_list, create_cost,
    get_roi_snapshots, get_finance_summary, get_dashboard_overview,
)
from app.utils.moscow_time import moscow_today
from app.utils.response import success, error

router = APIRouter()


@router.get("/revenue")
def revenue_list(
    start_date: date = Query(..., description="开始日期"),
    end_date: date = Query(..., description="结束日期"),
    shop_id: int = Query(None, description="店铺ID"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """获取收入明细"""
    result = get_revenue_list(db, tenant_id, start_date, end_date,
                              shop_id=shop_id, page=page, page_size=page_size)
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"])


@router.get("/costs")
def cost_list(
    start_date: date = Query(..., description="开始日期"),
    end_date: date = Query(..., description="结束日期"),
    shop_id: int = Query(None, description="店铺ID"),
    cost_type: str = Query(None, description="费用类型: ad_spend/logistics/commission/storage/other"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """获取费用明细"""
    result = get_cost_list(db, tenant_id, start_date, end_date,
                           shop_id=shop_id, cost_type=cost_type,
                           page=page, page_size=page_size)
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"])


@router.post("/costs")
def cost_create(
    req: FinanceCostCreate,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """手动录入费用"""
    result = create_cost(db, tenant_id, req.model_dump(exclude_none=True))
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"], msg="费用录入成功")


@router.get("/roi")
def roi_snapshots(
    start_date: date = Query(..., description="开始日期"),
    end_date: date = Query(..., description="结束日期"),
    shop_id: int = Query(None, description="店铺ID"),
    period: str = Query("daily", description="周期: daily/weekly/monthly"),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """获取ROI趋势数据"""
    result = get_roi_snapshots(db, tenant_id, start_date, end_date,
                               shop_id=shop_id, period=period)
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"])


@router.get("/summary")
def finance_summary(
    start_date: date = Query(None, description="开始日期(默认最近7天)"),
    end_date: date = Query(None, description="结束日期(默认今天)"),
    shop_id: int = Query(None, description="店铺ID"),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """获取财务汇总（收入/成本/利润/ROI）"""
    today = moscow_today()
    if not end_date:
        end_date = today
    if not start_date:
        start_date = today - timedelta(days=6)
    result = get_finance_summary(db, tenant_id, start_date, end_date, shop_id=shop_id)
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"])


@router.get("/dashboard")
def dashboard_overview(
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """首页大盘统计数据"""
    result = get_dashboard_overview(db, tenant_id)
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"])
