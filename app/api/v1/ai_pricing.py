"""AI智能调价路由"""

from datetime import date
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_current_user, get_tenant_id
from app.schemas.ai_pricing import PricingConfigUpdate, AnalyzeRequest, ToggleAutoRequest
from app.services.ai_pricing.service import (
    get_configs, update_config,
    analyze_shop,
    get_suggestions, approve_suggestion, reject_suggestion,
    toggle_auto_execute, get_history,
)
from app.utils.response import success, error

router = APIRouter()


# ==================== 配置管理 ====================

@router.get("/configs/{shop_id}")
def config_list(
    shop_id: int,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """获取店铺调价配置"""
    result = get_configs(db, tenant_id, shop_id)
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"])


@router.put("/configs/{config_id}")
def config_update(
    config_id: int,
    req: PricingConfigUpdate,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """更新调价配置"""
    result = update_config(db, tenant_id, config_id, req.model_dump(exclude_none=True))
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"], msg="配置更新成功")


# ==================== AI分析 ====================

@router.post("/analyze/{shop_id}")
def analyze(
    shop_id: int,
    req: AnalyzeRequest = None,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """手动触发AI分析"""
    category_name = req.category_name if req else None
    campaign_ids = req.campaign_ids if req else None
    result = analyze_shop(db, tenant_id, shop_id,
                          category_name=category_name, campaign_ids=campaign_ids)
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"])


# ==================== 建议管理 ====================

@router.get("/suggestions/{shop_id}")
def suggestion_list(
    shop_id: int,
    status: str = Query("pending", description="状态筛选: pending/approved/rejected/executed/expired"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """获取待确认建议列表"""
    result = get_suggestions(db, tenant_id, shop_id, status=status, page=page, page_size=page_size)
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"])


@router.post("/suggestions/{suggestion_id}/approve")
def suggestion_approve(
    suggestion_id: int,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """确认执行建议"""
    result = approve_suggestion(db, tenant_id, suggestion_id)
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"], msg="建议已执行")


@router.post("/suggestions/{suggestion_id}/reject")
def suggestion_reject(
    suggestion_id: int,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """拒绝建议"""
    result = reject_suggestion(db, tenant_id, suggestion_id)
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"], msg="建议已拒绝")


# ==================== 模式切换 ====================

@router.post("/toggle-auto/{shop_id}")
def toggle_auto(
    shop_id: int,
    req: ToggleAutoRequest,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """切换自动/建议模式"""
    result = toggle_auto_execute(db, tenant_id, shop_id,
                                  auto_execute=req.auto_execute,
                                  category_name=req.category_name)
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"])


# ==================== 历史记录 ====================

@router.get("/history/{shop_id}")
def history_list(
    shop_id: int,
    status: str = Query(None, description="状态筛选: executed/rejected/expired"),
    start_date: str = Query(None, description="起始日期 YYYY-MM-DD"),
    end_date: str = Query(None, description="结束日期 YYYY-MM-DD"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """调价历史记录"""
    result = get_history(db, tenant_id, shop_id,
                         status=status, start_date=start_date, end_date=end_date,
                         page=page, page_size=page_size)
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"])
