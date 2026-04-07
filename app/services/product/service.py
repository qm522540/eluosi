"""商品业务逻辑"""

from sqlalchemy.orm import Session

from app.models.product import Product, PlatformListing
from app.models.shop import Shop
from app.utils.errors import ErrorCode
from app.utils.logger import logger


# ==================== 商品 CRUD ====================

def list_products(db: Session, tenant_id: int, keyword: str = None,
                  category: str = None, status: str = None,
                  page: int = 1, page_size: int = 20) -> dict:
    """获取商品列表"""
    try:
        query = db.query(Product).filter(
            Product.tenant_id == tenant_id,
            Product.status != "deleted"
        )
        if keyword:
            query = query.filter(
                (Product.name_zh.contains(keyword)) |
                (Product.name_ru.contains(keyword)) |
                (Product.sku.contains(keyword))
            )
        if category:
            query = query.filter(Product.category == category)
        if status:
            query = query.filter(Product.status == status)

        total = query.count()
        products = query.order_by(Product.created_at.desc()).offset(
            (page - 1) * page_size
        ).limit(page_size).all()

        items = [_product_to_dict(p) for p in products]
        return {
            "code": ErrorCode.SUCCESS,
            "data": {
                "items": items,
                "total": total,
                "page": page,
                "page_size": page_size,
                "pages": (total + page_size - 1) // page_size,
            },
        }
    except Exception as e:
        logger.error(f"获取商品列表失败 tenant_id={tenant_id}: {e}")
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "获取商品列表失败"}


def create_product(db: Session, tenant_id: int, data: dict) -> dict:
    """创建商品"""
    try:
        # 检查SKU唯一性
        exists = db.query(Product).filter(
            Product.tenant_id == tenant_id,
            Product.sku == data.get("sku"),
            Product.status != "deleted"
        ).first()
        if exists:
            return {"code": ErrorCode.PRODUCT_SKU_DUPLICATE, "msg": f"SKU '{data['sku']}' 已存在"}

        product = Product(tenant_id=tenant_id, **data)
        db.add(product)
        db.commit()
        db.refresh(product)

        logger.info(f"商品创建成功: product_id={product.id} sku={product.sku} tenant_id={tenant_id}")
        return {"code": ErrorCode.SUCCESS, "data": _product_to_dict(product)}
    except Exception as e:
        db.rollback()
        logger.error(f"创建商品失败 tenant_id={tenant_id}: {e}")
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "创建商品失败"}


def get_product(db: Session, product_id: int, tenant_id: int) -> dict:
    """获取商品详情（含各平台Listing）"""
    try:
        product = db.query(Product).filter(
            Product.id == product_id,
            Product.tenant_id == tenant_id,
            Product.status != "deleted"
        ).first()

        if not product:
            return {"code": ErrorCode.PRODUCT_NOT_FOUND, "msg": "商品不存在"}

        detail = _product_to_dict(product)

        # 获取关联的平台Listing
        listings = db.query(PlatformListing).filter(
            PlatformListing.product_id == product_id,
            PlatformListing.tenant_id == tenant_id,
            PlatformListing.status != "deleted"
        ).all()
        detail["listings"] = [_listing_to_dict(l) for l in listings]

        return {"code": ErrorCode.SUCCESS, "data": detail}
    except Exception as e:
        logger.error(f"获取商品详情失败 product_id={product_id}: {e}")
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "获取商品详情失败"}


def update_product(db: Session, product_id: int, tenant_id: int, data: dict) -> dict:
    """更新商品"""
    try:
        product = db.query(Product).filter(
            Product.id == product_id,
            Product.tenant_id == tenant_id,
            Product.status != "deleted"
        ).first()

        if not product:
            return {"code": ErrorCode.PRODUCT_NOT_FOUND, "msg": "商品不存在"}

        for key, value in data.items():
            if value is not None:
                setattr(product, key, value)

        db.commit()
        db.refresh(product)

        logger.info(f"商品更新成功: product_id={product.id}")
        return {"code": ErrorCode.SUCCESS, "data": _product_to_dict(product)}
    except Exception as e:
        db.rollback()
        logger.error(f"更新商品失败 product_id={product_id}: {e}")
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "更新商品失败"}


def delete_product(db: Session, product_id: int, tenant_id: int) -> dict:
    """删除商品（软删除，同时软删除关联Listing）"""
    try:
        product = db.query(Product).filter(
            Product.id == product_id,
            Product.tenant_id == tenant_id,
            Product.status != "deleted"
        ).first()

        if not product:
            return {"code": ErrorCode.PRODUCT_NOT_FOUND, "msg": "商品不存在"}

        product.status = "deleted"

        # 同时软删除关联的Listing
        db.query(PlatformListing).filter(
            PlatformListing.product_id == product_id,
            PlatformListing.tenant_id == tenant_id,
            PlatformListing.status != "deleted"
        ).update({"status": "deleted"})

        db.commit()

        logger.info(f"商品已删除: product_id={product.id}")
        return {"code": ErrorCode.SUCCESS, "data": None}
    except Exception as e:
        db.rollback()
        logger.error(f"删除商品失败 product_id={product_id}: {e}")
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "删除商品失败"}


# ==================== 平台Listing CRUD ====================

def list_listings(db: Session, tenant_id: int, product_id: int = None,
                  shop_id: int = None, platform: str = None,
                  page: int = 1, page_size: int = 20) -> dict:
    """获取平台Listing列表"""
    try:
        query = db.query(PlatformListing).filter(
            PlatformListing.tenant_id == tenant_id,
            PlatformListing.status != "deleted"
        )
        if product_id:
            query = query.filter(PlatformListing.product_id == product_id)
        if shop_id:
            query = query.filter(PlatformListing.shop_id == shop_id)
        if platform:
            query = query.filter(PlatformListing.platform == platform)

        total = query.count()
        listings = query.order_by(PlatformListing.created_at.desc()).offset(
            (page - 1) * page_size
        ).limit(page_size).all()

        items = [_listing_to_dict(l) for l in listings]
        return {
            "code": ErrorCode.SUCCESS,
            "data": {
                "items": items,
                "total": total,
                "page": page,
                "page_size": page_size,
                "pages": (total + page_size - 1) // page_size,
            },
        }
    except Exception as e:
        logger.error(f"获取Listing列表失败 tenant_id={tenant_id}: {e}")
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "获取Listing列表失败"}


def create_listing(db: Session, tenant_id: int, data: dict) -> dict:
    """创建平台Listing"""
    try:
        # 验证商品存在
        product = db.query(Product).filter(
            Product.id == data.get("product_id"),
            Product.tenant_id == tenant_id,
            Product.status != "deleted"
        ).first()
        if not product:
            return {"code": ErrorCode.PRODUCT_NOT_FOUND, "msg": "关联商品不存在"}

        # 验证店铺存在且平台匹配
        shop = db.query(Shop).filter(
            Shop.id == data.get("shop_id"),
            Shop.tenant_id == tenant_id,
            Shop.status != "deleted"
        ).first()
        if not shop:
            return {"code": ErrorCode.SHOP_NOT_FOUND, "msg": "关联店铺不存在"}
        if shop.platform != data.get("platform"):
            return {"code": ErrorCode.PARAM_ERROR, "msg": "平台与店铺不匹配"}

        listing = PlatformListing(tenant_id=tenant_id, **data)
        db.add(listing)
        db.commit()
        db.refresh(listing)

        logger.info(f"Listing创建成功: listing_id={listing.id} platform={listing.platform}")
        return {"code": ErrorCode.SUCCESS, "data": _listing_to_dict(listing)}
    except Exception as e:
        db.rollback()
        logger.error(f"创建Listing失败 tenant_id={tenant_id}: {e}")
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "创建Listing失败"}


def update_listing(db: Session, listing_id: int, tenant_id: int, data: dict) -> dict:
    """更新平台Listing"""
    try:
        listing = db.query(PlatformListing).filter(
            PlatformListing.id == listing_id,
            PlatformListing.tenant_id == tenant_id,
            PlatformListing.status != "deleted"
        ).first()

        if not listing:
            return {"code": ErrorCode.LISTING_NOT_FOUND, "msg": "Listing不存在"}

        for key, value in data.items():
            if value is not None:
                setattr(listing, key, value)

        db.commit()
        db.refresh(listing)

        logger.info(f"Listing更新成功: listing_id={listing.id}")
        return {"code": ErrorCode.SUCCESS, "data": _listing_to_dict(listing)}
    except Exception as e:
        db.rollback()
        logger.error(f"更新Listing失败 listing_id={listing_id}: {e}")
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "更新Listing失败"}


def delete_listing(db: Session, listing_id: int, tenant_id: int) -> dict:
    """删除平台Listing（软删除）"""
    try:
        listing = db.query(PlatformListing).filter(
            PlatformListing.id == listing_id,
            PlatformListing.tenant_id == tenant_id,
            PlatformListing.status != "deleted"
        ).first()

        if not listing:
            return {"code": ErrorCode.LISTING_NOT_FOUND, "msg": "Listing不存在"}

        listing.status = "deleted"
        db.commit()

        logger.info(f"Listing已删除: listing_id={listing.id}")
        return {"code": ErrorCode.SUCCESS, "data": None}
    except Exception as e:
        db.rollback()
        logger.error(f"删除Listing失败 listing_id={listing_id}: {e}")
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "删除Listing失败"}


# ==================== 辅助函数 ====================

def _product_to_dict(p: Product) -> dict:
    return {
        "id": p.id,
        "tenant_id": p.tenant_id,
        "sku": p.sku,
        "name_zh": p.name_zh,
        "name_ru": p.name_ru,
        "brand": p.brand,
        "category": p.category,
        "cost_price": float(p.cost_price) if p.cost_price else None,
        "weight_g": p.weight_g,
        "image_url": p.image_url,
        "status": p.status,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


def _listing_to_dict(l: PlatformListing) -> dict:
    return {
        "id": l.id,
        "tenant_id": l.tenant_id,
        "product_id": l.product_id,
        "shop_id": l.shop_id,
        "platform": l.platform,
        "platform_product_id": l.platform_product_id,
        "title_ru": l.title_ru,
        "price": float(l.price) if l.price else None,
        "discount_price": float(l.discount_price) if l.discount_price else None,
        "commission_rate": float(l.commission_rate) if l.commission_rate else None,
        "url": l.url,
        "rating": float(l.rating) if l.rating else None,
        "review_count": l.review_count,
        "status": l.status,
        "created_at": l.created_at.isoformat() if l.created_at else None,
        "updated_at": l.updated_at.isoformat() if l.updated_at else None,
    }
