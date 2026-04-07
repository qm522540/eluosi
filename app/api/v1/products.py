"""商品路由"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_current_user, get_tenant_id
from app.schemas.product import ProductCreate, ProductUpdate, ListingCreate, ListingUpdate
from app.services.product.service import (
    list_products, create_product, get_product, update_product, delete_product,
    list_listings, create_listing, update_listing, delete_listing,
)
from app.utils.response import success, error

router = APIRouter()


# ==================== 商品接口 ====================

@router.get("")
def product_list(
    keyword: str = Query(None, description="搜索关键词(SKU/名称)"),
    category: str = Query(None, description="分类筛选"),
    status: str = Query(None, description="状态筛选: active/inactive"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """获取商品列表"""
    result = list_products(db, tenant_id, keyword=keyword, category=category,
                           status=status, page=page, page_size=page_size)
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"])


@router.post("")
def product_create(
    req: ProductCreate,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """创建商品"""
    result = create_product(db, tenant_id, req.model_dump(exclude_none=True))
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"], msg="商品创建成功")


@router.get("/{product_id}")
def product_detail(
    product_id: int,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """获取商品详情（含各平台Listing）"""
    result = get_product(db, product_id, tenant_id)
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"])


@router.put("/{product_id}")
def product_update(
    product_id: int,
    req: ProductUpdate,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """更新商品"""
    result = update_product(db, product_id, tenant_id, req.model_dump(exclude_none=True))
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"], msg="商品更新成功")


@router.delete("/{product_id}")
def product_delete(
    product_id: int,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """删除商品（软删除，关联Listing一并删除）"""
    result = delete_product(db, product_id, tenant_id)
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(msg="商品已删除")


# ==================== 平台Listing接口 ====================

@router.get("/listings/list")
def listing_list(
    product_id: int = Query(None, description="商品ID筛选"),
    shop_id: int = Query(None, description="店铺ID筛选"),
    platform: str = Query(None, description="平台筛选: wb/ozon/yandex"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """获取平台Listing列表"""
    result = list_listings(db, tenant_id, product_id=product_id, shop_id=shop_id,
                           platform=platform, page=page, page_size=page_size)
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"])


@router.post("/listings")
def listing_create(
    req: ListingCreate,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """创建平台Listing"""
    result = create_listing(db, tenant_id, req.model_dump(exclude_none=True))
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"], msg="Listing创建成功")


@router.put("/listings/{listing_id}")
def listing_update(
    listing_id: int,
    req: ListingUpdate,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """更新平台Listing"""
    result = update_listing(db, listing_id, tenant_id, req.model_dump(exclude_none=True))
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"], msg="Listing更新成功")


@router.delete("/listings/{listing_id}")
def listing_delete(
    listing_id: int,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """删除平台Listing（软删除）"""
    result = delete_listing(db, listing_id, tenant_id)
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(msg="Listing已删除")
