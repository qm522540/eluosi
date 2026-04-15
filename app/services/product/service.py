"""商品业务逻辑"""

from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import text

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
        "net_margin": float(p.net_margin) if p.net_margin else None,
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
        "barcode": l.barcode,
        "description_ru": l.description_ru,
        "variant_name": l.variant_name,
        "variant_attrs": l.variant_attrs,
        "title_ru": l.title_ru,
        "price": float(l.price) if l.price else None,
        "discount_price": float(l.discount_price) if l.discount_price else None,
        "commission_rate": float(l.commission_rate) if l.commission_rate else None,
        "url": l.url,
        "rating": float(l.rating) if l.rating else None,
        "review_count": l.review_count,
        "status": l.status,
        "publish_status": l.publish_status,
        "oss_images": l.oss_images,
        "oss_videos": l.oss_videos,
        "source_listing_id": l.source_listing_id,
        "platform_listed_at": l.platform_listed_at.isoformat() if l.platform_listed_at else None,
        "created_at": l.created_at.isoformat() if l.created_at else None,
        "updated_at": l.updated_at.isoformat() if l.updated_at else None,
    }


SYNC_INTERVAL_MINUTES = 30


def update_product_margin(db: Session, product_id: int, tenant_id: int,
                          net_margin) -> dict:
    try:
        product = db.query(Product).filter(
            Product.id == product_id,
            Product.tenant_id == tenant_id,
            Product.status != "deleted"
        ).first()
        if not product:
            return {"code": ErrorCode.PRODUCT_NOT_FOUND, "msg": "商品不存在"}
        product.net_margin = net_margin
        db.commit()
        return {"code": ErrorCode.SUCCESS,
                "data": {"id": product_id, "net_margin": net_margin}}
    except Exception as e:
        db.rollback()
        logger.error(f"更新净毛利率失败: {e}")
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "更新净毛利率失败"}


def check_sync_needed(db: Session, shop_id: int, tenant_id: int,
                      force: bool = False) -> dict:
    if force:
        return {"need_sync": True, "reason": "强制同步"}
    row = db.execute(text("""
        SELECT last_sync_at FROM shop_data_init_status
        WHERE shop_id = :shop_id AND tenant_id = :tenant_id
    """), {"shop_id": shop_id, "tenant_id": tenant_id}).fetchone()
    if not row or not row.last_sync_at:
        return {"need_sync": True, "reason": "首次同步"}
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    elapsed = (now - row.last_sync_at).total_seconds() / 60
    if elapsed >= SYNC_INTERVAL_MINUTES:
        return {"need_sync": True, "reason": f"上次同步{int(elapsed)}分钟前"}
    return {"need_sync": False, "elapsed_minutes": int(elapsed)}


def sync_products_from_platform(db: Session, shop_id: int, tenant_id: int) -> dict:
    from app.models.shop import Shop
    shop = db.query(Shop).filter(
        Shop.id == shop_id, Shop.tenant_id == tenant_id,
    ).first()
    if not shop:
        return {"code": ErrorCode.SHOP_NOT_FOUND, "msg": "店铺不存在"}
    if shop.platform == "wb":
        return _sync_wb_products(db, shop, tenant_id)
    elif shop.platform == "ozon":
        return _sync_ozon_products(db, shop, tenant_id)
    return {"code": 0, "data": {"synced": 0}}


def _sync_wb_products(db: Session, shop, tenant_id: int) -> dict:
    import asyncio
    from app.services.platform.wb import WBClient
    async def _fetch():
        client = WBClient(shop_id=shop.id, api_key=shop.api_key)
        try:
            return await client.fetch_products(limit=100)
        finally:
            await client.close()
    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(_fetch())
    finally:
        loop.close()
    cards = (result or {}).get("cards", []) if isinstance(result, dict) else []
    synced = created = updated = 0
    for p in cards:
        nm_id = str(p.get("nmID") or "")
        if not nm_id:
            continue
        listing = db.query(PlatformListing).filter(
            PlatformListing.tenant_id == tenant_id,
            PlatformListing.shop_id == shop.id,
            PlatformListing.platform == "wb",
            PlatformListing.platform_product_id == nm_id,
        ).first()
        price = None
        for sz in (p.get("sizes") or []):
            if sz.get("price"):
                price = float(sz["price"])
                break
        photos = p.get("photos") or []
        image_url = (photos[0].get("big") or photos[0].get("tm")) if photos and isinstance(photos[0], dict) else None
        data = {
            "title_ru": (p.get("title") or p.get("subjectName") or "")[:500],
            "description_ru": p.get("description"),
            "price": price,
            "status": "active",
        }
        if listing:
            for k, v in data.items():
                if v is not None:
                    setattr(listing, k, v)
            updated += 1
        else:
            vendor_code = p.get("vendorCode") or f"WB-{nm_id}"
            product = _get_or_create_product(
                db, tenant_id, name_ru=data["title_ru"], sku=vendor_code,
                brand=p.get("brand"), image_url=image_url)
            listing = PlatformListing(
                tenant_id=tenant_id, product_id=product.id,
                shop_id=shop.id, platform="wb",
                platform_product_id=nm_id, **data)
            db.add(listing)
            created += 1
        synced += 1
    db.commit()
    _update_sync_time(db, shop.id, tenant_id)
    return {"code": 0, "data": {"synced": synced, "created": created, "updated": updated}}


def _sync_ozon_products(db: Session, shop, tenant_id: int) -> dict:
    return {"code": 0, "data": {"synced": 0, "created": 0, "updated": 0},
            "msg": "Ozon 商品同步对接中（/v3/product/list 端点升级待完成）"}


def _get_or_create_product(db: Session, tenant_id: int,
                           name_ru: str, sku: str,
                           brand: Optional[str] = None,
                           image_url: Optional[str] = None):
    existing = db.query(Product).filter(
        Product.tenant_id == tenant_id,
        Product.sku == sku,
    ).first()
    if existing:
        return existing
    product = Product(
        tenant_id=tenant_id, sku=sku,
        name_zh=name_ru[:200] if name_ru else sku,
        name_ru=name_ru[:200] if name_ru else None,
        brand=brand,
        image_url=image_url,
        status="active",
    )
    db.add(product)
    db.flush()
    return product


def _update_sync_time(db: Session, shop_id: int, tenant_id: int):
    db.execute(text("""
        UPDATE shop_data_init_status SET last_sync_at = NOW()
        WHERE shop_id = :shop_id AND tenant_id = :tenant_id
    """), {"shop_id": shop_id, "tenant_id": tenant_id})
    db.commit()


async def generate_description(db: Session, listing_id: int,
                               tenant_id: int, target_platform: str) -> dict:
    from app.config import get_settings
    from app.services.ai.kimi import KimiClient
    listing = db.query(PlatformListing).filter(
        PlatformListing.id == listing_id,
        PlatformListing.tenant_id == tenant_id,
    ).first()
    if not listing:
        return {"code": ErrorCode.LISTING_NOT_FOUND, "msg": "Listing不存在"}
    if not listing.description_ru and not listing.title_ru:
        return {"code": ErrorCode.PARAM_ERROR, "msg": "商品暂无描述内容"}
    style = {
        "wb": "简洁直接，200-500字，突出材质工艺",
        "ozon": "详细结构化，500-1000字，分段落",
        "yandex": "SEO导向，300-600字，融入关键词",
    }
    prompt = f"""你是俄罗斯电商文案专家。
商品标题：{listing.title_ru or ""}
原描述：{listing.description_ru or listing.title_ru or ""}
请改写为{target_platform.upper()}平台风格：{style.get(target_platform, "")}
只返回改写后内容，不要解释。"""
    settings = get_settings()
    client = KimiClient(api_key=settings.KIMI_API_KEY)
    try:
        result = await client.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7, max_tokens=2000)
        return {"code": 0, "data": {"description": result.get("content", "")}}
    except Exception as e:
        logger.error(f"Kimi改写失败: {e}")
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "AI改写失败"}
