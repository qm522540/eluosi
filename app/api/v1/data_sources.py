"""数据源管理 API — 系统设置 → 数据源管理 Tab 用

3 个端点:
  GET  /data-sources/shop/{shop_id}              — 查该店所有数据源状态
  GET  /data-sources/shared                       — 查跨店共享数据源 (SEO 引擎等)
  PATCH /data-sources/shop/{shop_id}/api-switch  — 改店铺 API 总开关 (Level 1)
  PATCH /data-sources/shop/{shop_id}/{source_key} — 改单数据源开关 (Level 2)

规则 1: 全部 SQL 带 tenant_id (service 层做)
规则 4: 路径含 {shop_id} 全部 Depends(get_owned_shop)
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db, get_owned_shop, get_tenant_id
from app.services.data_source.service import (
    get_shop_status, get_shared_data_sources,
    update_shop_api_switch, update_data_source,
)
from app.utils.response import error, success

router = APIRouter()


@router.get("/shop/{shop_id}")
def shop_data_sources(
    shop_id: int,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
    shop=Depends(get_owned_shop),
):
    """查该店所有数据源 (含 Level 1 + Level 2 状态)。"""
    result = get_shop_status(db, tenant_id, shop_id)
    if result.get("code") != 0:
        return error(result["code"], result.get("msg", ""))
    return success(result["data"])


@router.get("/shared")
def shared_data_sources(
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """跨店共享数据源 (SEO 引擎等), 不属于任何 shop。"""
    result = get_shared_data_sources(db, tenant_id)
    return success(result["data"])


# ==================== Level 1: 店铺 API 总开关 ====================

class ShopApiSwitchBody(BaseModel):
    enabled: bool = Field(..., description="True=允许 API 调用, False=禁用紧急止血")
    reason: Optional[str] = Field(None, max_length=500,
                                   description="禁用必填,展示给所有人看 (如 'WB quota 静默期')")
    auto_resume_hours: Optional[int] = Field(None, ge=1, le=720,
                                              description="N 小时后自动启用 (1-720h, 不传则手动启用)")


@router.patch("/shop/{shop_id}/api-switch")
def patch_shop_api_switch(
    shop_id: int,
    body: ShopApiSwitchBody,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
    shop=Depends(get_owned_shop),
    current_user=Depends(get_current_user),
):
    """改店铺 API 总开关 (Level 1)。关闭后该店所有 API 类数据源全部 skip。"""
    user_id = getattr(current_user, "id", None)
    result = update_shop_api_switch(
        db, tenant_id, shop_id,
        enabled=body.enabled, reason=body.reason,
        auto_resume_hours=body.auto_resume_hours, user_id=user_id,
    )
    if result.get("code") != 0:
        return error(result["code"], result.get("msg", ""))
    return success(result["data"])


# ==================== Level 2: 单数据源开关 ====================

class DataSourceSwitchBody(BaseModel):
    enabled: bool = Field(..., description="True=启用, False=暂停")
    reason: Optional[str] = Field(None, max_length=500,
                                   description="暂停必填,展示给所有人看")


@router.patch("/shop/{shop_id}/{source_key}")
def patch_data_source(
    shop_id: int,
    source_key: str,
    body: DataSourceSwitchBody,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
    shop=Depends(get_owned_shop),
    current_user=Depends(get_current_user),
):
    """改单数据源开关 (Level 2)。Level 1 关闭时此开关不影响实际行为。"""
    user_id = getattr(current_user, "id", None)
    result = update_data_source(
        db, tenant_id, shop_id, source_key,
        enabled=body.enabled, reason=body.reason, user_id=user_id,
    )
    if result.get("code") != 0:
        return error(result["code"], result.get("msg", ""))
    return success(result["data"])
