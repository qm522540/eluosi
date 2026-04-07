"""通知路由"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_current_user, get_tenant_id
from app.services.notification.service import (
    get_notifications, mark_notification_read, process_pending_notifications,
)
from app.utils.response import success, error

router = APIRouter()


@router.get("")
def notification_list(
    is_read: int = Query(None, description="已读状态: 0=未读, 1=已读"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """获取通知列表"""
    result = get_notifications(db, tenant_id, is_read=is_read,
                               page=page, page_size=page_size)
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"])


@router.put("/{notification_id}/read")
def notification_read(
    notification_id: int,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """标记通知为已读"""
    result = mark_notification_read(db, notification_id, tenant_id)
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(msg="已标记为已读")


@router.post("/send-pending")
async def send_pending(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """手动触发发送待处理通知（管理员操作）"""
    result = await process_pending_notifications(db)
    return success(data=result, msg="通知处理完成")
