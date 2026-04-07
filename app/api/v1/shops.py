"""店铺路由"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_current_user, get_tenant_id
from app.schemas.shop import ShopCreate, ShopUpdate
from app.services.shop.service import (
    list_shops,
    create_shop,
    get_shop,
    update_shop,
    delete_shop,
    test_connection,
)
from app.utils.response import success, error

router = APIRouter()


@router.get("")
def shop_list(
    platform: str = Query(None, description="平台筛选: wb/ozon/yandex"),
    status: str = Query(None, description="状态筛选: active/inactive"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """获取店铺列表"""
    result = list_shops(db, tenant_id, platform=platform, status=status,
                        page=page, page_size=page_size)
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"])


@router.post("")
def shop_create(
    req: ShopCreate,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """创建店铺"""
    result = create_shop(db, tenant_id, req.model_dump(exclude_none=True))
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"], msg="店铺创建成功")


@router.get("/{shop_id}")
def shop_detail(
    shop_id: int,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """获取店铺详情"""
    result = get_shop(db, shop_id, tenant_id)
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"])


@router.put("/{shop_id}")
def shop_update(
    shop_id: int,
    req: ShopUpdate,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """更新店铺"""
    result = update_shop(db, shop_id, tenant_id, req.model_dump(exclude_none=True))
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"], msg="店铺更新成功")


@router.delete("/{shop_id}")
def shop_delete(
    shop_id: int,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """删除店铺（软删除）"""
    result = delete_shop(db, shop_id, tenant_id)
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(msg="店铺已删除")


@router.post("/{shop_id}/test-connection")
async def shop_test_connection(
    shop_id: int,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """测试店铺API连接"""
    result = await test_connection(db, shop_id, tenant_id)
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"])
