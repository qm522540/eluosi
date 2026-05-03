"""店铺克隆 API 路由

详细规范: docs/api/store_clone.md §5
路径前缀: /api/v1/clone

合规自查 (规则 1 + 4):
- {shop_id} 路径参数: 用 get_owned_shop 守卫 (路由层第一层防护)
- {task_id} 路径参数: service 层 .filter(CloneTask.tenant_id == tenant_id) 二层防护
- {pending_id} / {log_id} 同样 service 层 tenant 过滤
- 手动触发接口必须按 task_id / shop_id 过滤 (规则 4)
"""

from typing import Optional, List
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_current_user, get_tenant_id, get_owned_shop
from app.models.shop import Shop
from app.schemas.clone import (
    CloneTaskCreate, CloneTaskUpdate, RejectRequest,
    PendingPayloadUpdate, BatchActionRequest,
)


class ScanNowBody(BaseModel):
    """11.2: scan-now 接受 preview 后用户勾选的 sku 子集; 不传则全量立项 (兼容旧逻辑)"""
    selected_skus: Optional[List[str]] = None
from app.services.clone import task_service
from app.utils.errors import ErrorCode
from app.utils.logger import setup_logger
from app.utils.response import error, success

logger = setup_logger("api.clone")
router = APIRouter()


# ==================== §5.1 任务管理 ====================

@router.post("/tasks")
def create_clone_task(
    body: CloneTaskCreate,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
    current_user: dict = Depends(get_current_user),
):
    """POST /tasks — 创建克隆任务

    target_shop_id 在 service 层显式核 tenant 归属 (Pydantic 已校验 != source)。
    """
    r = task_service.create_task(db, tenant_id, body.model_dump())
    if r.get("code") == 0:
        return success(r["data"])
    return error(r["code"], r.get("msg"))


@router.get("/tasks")
def list_clone_tasks(
    target_shop_id: Optional[int] = Query(None),
    is_active: Optional[bool] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    r = task_service.list_tasks(db, tenant_id, target_shop_id, is_active, page, size)
    if r.get("code") == 0:
        return success(r["data"])
    return error(r["code"], r.get("msg"))


@router.get("/tasks/{task_id}")
def get_clone_task(
    task_id: int,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    r = task_service.get_task_detail(db, tenant_id, task_id)
    if r.get("code") == 0:
        return success(r["data"])
    return error(r["code"], r.get("msg"))


@router.put("/tasks/{task_id}")
def update_clone_task(
    task_id: int,
    body: CloneTaskUpdate,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    # exclude_unset: 仅传入的字段; PUT 半更新语义
    r = task_service.update_task(db, tenant_id, task_id, body.model_dump(exclude_unset=True))
    if r.get("code") == 0:
        return success(r["data"])
    return error(r["code"], r.get("msg"))


@router.post("/tasks/{task_id}/enable")
def enable_clone_task(
    task_id: int,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    r = task_service.enable_task(db, tenant_id, task_id)
    if r.get("code") == 0:
        return success(r["data"])
    return error(r["code"], r.get("msg"))


@router.post("/tasks/{task_id}/disable")
def disable_clone_task(
    task_id: int,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    r = task_service.disable_task(db, tenant_id, task_id)
    if r.get("code") == 0:
        return success(r["data"])
    return error(r["code"], r.get("msg"))


@router.post("/tasks/{task_id}/scan-now")
async def scan_now_clone_task(
    task_id: int,
    body: Optional[ScanNowBody] = None,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """同步触发一次扫描 (规则 4 手动触发按 task_id 过滤)

    body.selected_skus:
      - None / 缺省: 全量立项 (兼容老板"快捷模式")
      - [sku1, sku2, ...]: 11.2 预览后只立项勾选的 SKU
    """
    selected = body.selected_skus if body else None
    r = await task_service.scan_now(db, tenant_id, task_id, selected_skus=selected)
    if r.get("code") == 0:
        return success(r["data"])
    return error(r["code"], r.get("msg"))


@router.post("/tasks/{task_id}/scan-preview")
async def scan_preview_clone_task(
    task_id: int,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """11.2 扫描预览 — 干跑只返候选清单, 不写库

    用户在前端 Modal 勾选后, 再调 scan-now(selected_skus) 真立项.
    """
    r = await task_service.scan_preview(db, tenant_id, task_id)
    if r.get("code") == 0:
        return success(r["data"])
    return error(r["code"], r.get("msg"))


@router.delete("/tasks/{task_id}")
def delete_clone_task(
    task_id: int,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    r = task_service.delete_task(db, tenant_id, task_id)
    if r.get("code") == 0:
        return success(r["data"])
    return error(r["code"], r.get("msg"))


# ==================== §5.2 待审核商品 ====================

@router.get("/pending")
def list_pending(
    task_id: Optional[int] = Query(None),
    status: str = Query("pending"),
    category_mapping_status: Optional[str] = Query(None),
    keyword: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    r = task_service.list_pending(
        db, tenant_id, task_id, status, category_mapping_status, keyword, page, size,
    )
    if r.get("code") == 0:
        return success(r["data"])
    return error(r["code"], r.get("msg"))


@router.post("/pending/{pending_id}/approve")
def approve_pending(
    pending_id: int,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
    current_user: dict = Depends(get_current_user),
):
    r = task_service.approve_pending(db, tenant_id, pending_id, current_user.get("user_id"))
    if r.get("code") == 0:
        return success(r["data"])
    return error(r["code"], r.get("msg"))


@router.post("/pending/{pending_id}/reject")
def reject_pending(
    pending_id: int,
    body: RejectRequest = RejectRequest(),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
    current_user: dict = Depends(get_current_user),
):
    r = task_service.reject_pending(
        db, tenant_id, pending_id, body.reject_reason, current_user.get("user_id"),
    )
    if r.get("code") == 0:
        return success(r["data"])
    return error(r["code"], r.get("msg"))


@router.post("/pending/{pending_id}/restore")
def restore_pending(
    pending_id: int,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
    current_user: dict = Depends(get_current_user),
):
    """误拒恢复 (规范 §5.2.4)"""
    r = task_service.restore_pending(db, tenant_id, pending_id, current_user.get("user_id"))
    if r.get("code") == 0:
        return success(r["data"])
    return error(r["code"], r.get("msg"))


@router.put("/pending/{pending_id}")
def update_pending(
    pending_id: int,
    body: PendingPayloadUpdate,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    r = task_service.update_pending_payload(db, tenant_id, pending_id, body.proposed_payload)
    if r.get("code") == 0:
        return success(r["data"])
    return error(r["code"], r.get("msg"))


@router.post("/pending/approve-batch")
def batch_approve_pending(
    body: BatchActionRequest,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
    current_user: dict = Depends(get_current_user),
):
    r = task_service.batch_approve(db, tenant_id, body.ids, current_user.get("user_id"))
    if r.get("code") == 0:
        return success(r["data"])
    return error(r["code"], r.get("msg"))


@router.post("/pending/reject-batch")
def batch_reject_pending(
    body: BatchActionRequest,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
    current_user: dict = Depends(get_current_user),
):
    r = task_service.batch_reject(
        db, tenant_id, body.ids, body.reject_reason, current_user.get("user_id"),
    )
    if r.get("code") == 0:
        return success(r["data"])
    return error(r["code"], r.get("msg"))


@router.post("/pending/delete-batch")
def batch_delete_pending_route(
    body: BatchActionRequest,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """物理 DELETE 3 张表 (pending + listing + product) — 不可逆.
    删后下次扫描遇到同 SKU 不再去重跳过, 重新作为新候选立项.
    限制: 只允许 status in (pending/rejected/failed); approved/published 拒绝.
    """
    r = task_service.batch_delete_pending(db, tenant_id, body.ids)
    if r.get("code") == 0:
        return success(r["data"])
    return error(r["code"], r.get("msg"))


# ==================== §5.3 日志 ====================

@router.get("/logs")
def list_clone_logs(
    task_id: Optional[int] = Query(None),
    log_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    r = task_service.list_logs(
        db, tenant_id, task_id, log_type, status, start_date, end_date, page, size,
    )
    if r.get("code") == 0:
        return success(r["data"])
    return error(r["code"], r.get("msg"))


# ==================== §5.4 配置辅助 ====================

@router.get("/available-shops")
def list_available_shops(
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    r = task_service.list_available_shops(db, tenant_id)
    if r.get("code") == 0:
        return success(r["data"])
    return error(r["code"], r.get("msg"))


@router.get("/category-coverage/{task_id}")
def category_coverage(
    task_id: int,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    r = task_service.check_category_coverage(db, tenant_id, task_id)
    if r.get("code") == 0:
        return success(r["data"])
    return error(r["code"], r.get("msg"))
