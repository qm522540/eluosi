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
                  platform: str = None, shop_id: int = None,
                  page: int = 1, page_size: int = 20) -> dict:
    """获取商品列表"""
    try:
        query = db.query(Product).filter(
            Product.tenant_id == tenant_id,
            Product.status != "deleted"
        )
        # 店铺过滤：product 表直接带 shop_id（029 迁移后），不再需要 JOIN listing
        if shop_id:
            query = query.filter(Product.shop_id == shop_id)
        if platform:
            # platform 过滤：product 没有直接字段，通过 shop.platform 间接
            # 实际上选 shop_id 就已经确定平台，这个参数作为兼容保留
            from app.models.shop import Shop
            query = query.join(Shop, Shop.id == Product.shop_id).filter(
                Shop.platform == platform
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

        # 批量查本地分类名，避免 N+1
        cat_ids = [p.local_category_id for p in products if p.local_category_id]
        cat_name_map = {}
        if cat_ids:
            from app.models.category import LocalCategory
            for r in db.query(LocalCategory.id, LocalCategory.name).filter(
                LocalCategory.id.in_(set(cat_ids)),
                LocalCategory.tenant_id == tenant_id,
            ).all():
                cat_name_map[r.id] = r.name

        # 批量查 listings（前端列表行需要 listings[] 渲染销售价/平台/展开行）
        product_ids = [p.id for p in products]
        listings_map = {}
        if product_ids:
            all_listings = db.query(PlatformListing).filter(
                PlatformListing.tenant_id == tenant_id,
                PlatformListing.product_id.in_(product_ids),
                PlatformListing.status != "deleted",
            ).all()
            for l in all_listings:
                listings_map.setdefault(l.product_id, []).append(_listing_to_dict(l))

        items = []
        for p in products:
            d = _product_to_dict(p, cat_name_map=cat_name_map)
            d["listings"] = listings_map.get(p.id, [])
            d["platforms"] = sorted(set(l["platform"] for l in d["listings"]))
            items.append(d)
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

def _product_to_dict(p: Product, cat_name_map: dict = None) -> dict:
    cat_name_map = cat_name_map or {}
    return {
        "id": p.id,
        "tenant_id": p.tenant_id,
        "shop_id": p.shop_id,
        "sku": p.sku,
        "name_zh": p.name_zh,
        "name_ru": p.name_ru,
        "brand": p.brand,
        "category": p.category,
        "local_category_id": p.local_category_id,
        "local_category_name": cat_name_map.get(p.local_category_id) if p.local_category_id else None,
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
        "platform_category_id": l.platform_category_id,
        "platform_category_name": l.platform_category_name,
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
    last_sync = row.last_sync_at
    if last_sync.tzinfo is None:
        last_sync = last_sync.replace(tzinfo=timezone.utc)
    elapsed = (datetime.now(timezone.utc) - last_sync).total_seconds() / 60
    if elapsed >= SYNC_INTERVAL_MINUTES:
        return {"need_sync": True, "reason": f"上次同步{int(elapsed)}分钟前"}
    return {"need_sync": False, "elapsed_minutes": int(elapsed)}


def _load_platform_category_map(db: Session, tenant_id: int, platform: str) -> dict:
    """预加载平台分类 → 本地分类的映射字典，{platform_category_id_str: local_category_id}"""
    from app.models.category import CategoryPlatformMapping
    rows = db.query(
        CategoryPlatformMapping.platform_category_id,
        CategoryPlatformMapping.local_category_id,
    ).filter(
        CategoryPlatformMapping.tenant_id == tenant_id,
        CategoryPlatformMapping.platform == platform,
    ).all()
    return {str(r.platform_category_id): r.local_category_id for r in rows}


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
        # 同时拉商品内容 + 价格（两个 API 独立，并行）
        client = WBClient(shop_id=shop.id, api_key=shop.api_key)
        try:
            cards_task = client.fetch_products(limit=100)
            prices_task = client.fetch_prices(limit=1000)
            cards_res, prices_res = await asyncio.gather(cards_task, prices_task)
            return cards_res, prices_res
        finally:
            await client.close()
    loop = asyncio.new_event_loop()
    try:
        result, price_map = loop.run_until_complete(_fetch())
    finally:
        loop.close()
    cards = (result or {}).get("cards", []) if isinstance(result, dict) else []
    cat_map = _load_platform_category_map(db, tenant_id, "wb")  # subjectID → local_category_id
    synced = created = updated = 0
    for p in cards:
        nm_id_int = p.get("nmID")
        if not nm_id_int:
            continue
        nm_id = str(nm_id_int)
        listing = db.query(PlatformListing).filter(
            PlatformListing.tenant_id == tenant_id,
            PlatformListing.shop_id == shop.id,
            PlatformListing.platform == "wb",
            PlatformListing.platform_product_id == nm_id,
        ).first()
        # 从 price_map 取价格（内容 API 的 sizes 不含 price，必须用 discounts-prices API）
        price_info = price_map.get(nm_id_int) if isinstance(price_map, dict) else None
        price = None
        discount_price = None
        if price_info:
            raw_price = price_info.get("price")
            raw_disc = price_info.get("discountedPrice")
            if raw_price:
                price = float(raw_price)
            if raw_disc and raw_price and float(raw_disc) != float(raw_price):
                discount_price = float(raw_disc)
        photos = p.get("photos") or []
        image_url = (photos[0].get("big") or photos[0].get("tm")) if photos and isinstance(photos[0], dict) else None
        subject_id = p.get("subjectID") or p.get("subjectId")
        subject_name = p.get("subjectName") or ""
        subject_id_str = str(subject_id) if subject_id else None
        local_cat_id = cat_map.get(subject_id_str) if subject_id_str else None
        data = {
            "title_ru": (p.get("title") or subject_name or "")[:500],
            "description_ru": p.get("description"),
            "price": price,
            "discount_price": discount_price,
            # WB 的 sku_id 和 product_id 都是 nm_id，冗余写入方便广告 API 反查
            "platform_sku_id": nm_id,
            "platform_category_id": subject_id_str,
            "platform_category_name": subject_name[:300] if subject_name else None,
            "status": "active",
        }
        if listing:
            for k, v in data.items():
                if v is not None:
                    setattr(listing, k, v)
            # 回填 product 的本地分类（若已有就不覆盖，避免跨店铺冲突）
            if local_cat_id and listing.product_id:
                prod = db.query(Product).filter(Product.id == listing.product_id).first()
                if prod and not prod.local_category_id:
                    prod.local_category_id = local_cat_id
            updated += 1
        else:
            vendor_code = p.get("vendorCode") or f"WB-{nm_id}"
            # WB 重量：dimensions.weightBrutto 单位 kg → 转 g
            dims = p.get("dimensions") or {}
            weight_kg = dims.get("weightBrutto") if isinstance(dims, dict) else None
            weight_g = int(round(float(weight_kg) * 1000)) if weight_kg else None
            product = _get_or_create_product(
                db, tenant_id, name_ru=data["title_ru"], sku=vendor_code,
                shop_id=shop.id,
                brand=p.get("brand"), image_url=image_url,
                weight_g=weight_g,
                local_category_id=local_cat_id)
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
    import asyncio
    from app.services.platform.ozon import OzonClient

    async def _fetch_all():
        client = OzonClient(
            shop_id=shop.id, api_key=shop.api_key, client_id=shop.client_id,
            perf_client_id=shop.perf_client_id or "",
            perf_client_secret=shop.perf_client_secret or "")
        try:
            all_items = []
            last_id = ""
            for _ in range(50):
                r = await client.fetch_products(last_id=last_id, limit=1000)
                result = (r or {}).get("result", {})
                items = result.get("items") or []
                if not items:
                    break
                all_items.extend(items)
                next_last = result.get("last_id") or ""
                if not next_last or next_last == last_id:
                    break
                last_id = next_last
            product_ids = [it["product_id"] for it in all_items if it.get("product_id")]
            archived_map = {it["product_id"]: it.get("archived") for it in all_items}
            stock_map = {
                it["product_id"]: (it.get("has_fbo_stocks") or it.get("has_fbs_stocks"))
                for it in all_items
            }
            infos = []
            for i in range(0, len(product_ids), 500):
                chunk = product_ids[i:i + 500]
                infos.extend(await client.fetch_product_info(chunk))
            return infos, archived_map, stock_map
        finally:
            await client.close()

    loop = asyncio.new_event_loop()
    try:
        infos, archived_map, stock_map = loop.run_until_complete(_fetch_all())
    finally:
        loop.close()

    cat_map = _load_platform_category_map(db, tenant_id, "ozon")  # description_category_id → local_category_id
    synced = created = updated = 0
    for p in infos:
        pid = p.get("id") or p.get("product_id")
        if not pid:
            continue
        pid_str = str(pid)
        listing = db.query(PlatformListing).filter(
            PlatformListing.tenant_id == tenant_id,
            PlatformListing.shop_id == shop.id,
            PlatformListing.platform == "ozon",
            PlatformListing.platform_product_id == pid_str,
        ).first()

        if archived_map.get(pid) or p.get("is_archived"):
            status = "deleted"
        elif stock_map.get(pid) is False:
            status = "out_of_stock"
        else:
            status = "active"

        def _to_float(v):
            try:
                return float(v) if v not in (None, "", "0", "0.00") else None
            except (TypeError, ValueError):
                return None

        images = p.get("images") or []
        primary = p.get("primary_image") or (images[0] if images else None)
        if isinstance(primary, list):
            primary = primary[0] if primary else None
        barcodes = p.get("barcodes") or []
        barcode = barcodes[0] if barcodes else None
        title = (p.get("name") or "")[:500]
        price = _to_float(p.get("price"))
        old_price = _to_float(p.get("old_price"))
        # Ozon v3 info/list 分类字段：优先 description_category_id
        category_id = p.get("description_category_id") or p.get("type_id")
        category_id_str = str(category_id) if category_id else None
        local_cat_id = cat_map.get(category_id_str) if category_id_str else None

        # OZON 的 sku_id（广告 API 返回的 sku 字段），与 product_id 是两套 ID
        ozon_sku = p.get("sku")
        data = {
            "title_ru": title,
            "price": old_price or price,
            "discount_price": price if (old_price and price and old_price != price) else None,
            "barcode": barcode,
            "platform_sku_id": str(ozon_sku) if ozon_sku else None,
            "platform_category_id": category_id_str,
            # OZON info/list 不返回分类名称，此字段留空，init-from-ozon 里从分类树反查
            "status": status,
        }

        if listing:
            for k, v in data.items():
                if v is not None:
                    setattr(listing, k, v)
            if local_cat_id and listing.product_id:
                prod = db.query(Product).filter(Product.id == listing.product_id).first()
                if prod and not prod.local_category_id:
                    prod.local_category_id = local_cat_id
            updated += 1
        else:
            offer_id = p.get("offer_id") or f"OZ-{pid_str}"
            # OZON 重量：volume_weight（体积重，kg）→ g
            vw = p.get("volume_weight")
            ozon_weight_g = int(round(float(vw) * 1000)) if vw else None
            product = _get_or_create_product(
                db, tenant_id, name_ru=title, sku=offer_id,
                shop_id=shop.id,
                image_url=primary,
                weight_g=ozon_weight_g,
                local_category_id=local_cat_id)
            listing = PlatformListing(
                tenant_id=tenant_id, product_id=product.id,
                shop_id=shop.id, platform="ozon",
                platform_product_id=pid_str, **data)
            db.add(listing)
            created += 1
        synced += 1
    db.commit()
    _update_sync_time(db, shop.id, tenant_id)
    return {"code": 0, "data": {"synced": synced, "created": created, "updated": updated}}


def _get_or_create_product(db: Session, tenant_id: int,
                           name_ru: str, sku: str,
                           shop_id: Optional[int] = None,
                           brand: Optional[str] = None,
                           image_url: Optional[str] = None,
                           weight_g: Optional[int] = None,
                           local_category_id: Optional[int] = None):
    # 按 (tenant_id, shop_id, sku) 查重 —— 同一 SKU 在不同店铺是独立 product
    query = db.query(Product).filter(
        Product.tenant_id == tenant_id,
        Product.sku == sku,
    )
    if shop_id is not None:
        query = query.filter(Product.shop_id == shop_id)
    existing = query.first()
    if existing:
        if local_category_id and not existing.local_category_id:
            existing.local_category_id = local_category_id
        # 重量：已有不覆盖（尊重用户手动改的值）
        if weight_g and not existing.weight_g:
            existing.weight_g = weight_g
        return existing
    product = Product(
        tenant_id=tenant_id, shop_id=shop_id, sku=sku,
        name_zh=name_ru[:200] if name_ru else sku,
        name_ru=name_ru[:200] if name_ru else None,
        brand=brand,
        image_url=image_url,
        weight_g=weight_g,
        local_category_id=local_category_id,
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
