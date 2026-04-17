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
        "length_mm": p.length_mm,
        "width_mm": p.width_mm,
        "height_mm": p.height_mm,
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
        "stock": l.stock or 0,
        "stock_updated_at": l.stock_updated_at.isoformat() if l.stock_updated_at else None,
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


def _flatten_ozon_category_tree(tree: list) -> dict:
    """把 Ozon 分类树压平为 {(description_category_id, type_id): "面包屑名称"}。
    叶子节点才含 type_id；用 (desc_cat_id, type_id) 双键唯一标识。
    """
    result: dict = {}

    def _walk(nodes, trail):
        for n in nodes or []:
            if not isinstance(n, dict):
                continue
            desc_cat_id = n.get("description_category_id")
            type_id = n.get("type_id")
            name = n.get("category_name") or n.get("type_name") or ""
            new_trail = trail + [name] if name else trail
            if desc_cat_id is not None and type_id is not None:
                result[(int(desc_cat_id), int(type_id))] = " / ".join(new_trail)
            children = n.get("children") or []
            if children:
                _walk(children, new_trail)

    _walk(tree, [])
    return result


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
        # 并行拉：内容卡片 + 价格 + 库存
        client = WBClient(shop_id=shop.id, api_key=shop.api_key)
        try:
            cards_task = client.fetch_products(limit=100)
            prices_task = client.fetch_prices(limit=1000)
            inv_task = client.fetch_inventory()
            cards_res, prices_res, inv_res = await asyncio.gather(
                cards_task, prices_task, inv_task,
                return_exceptions=True,
            )
            # 库存失败不阻塞主流程
            if isinstance(inv_res, Exception):
                logger.warning(f"WB 库存拉取失败 shop={shop.id}: {inv_res}")
                inv_res = []
            return cards_res, prices_res, inv_res
        finally:
            await client.close()
    loop = asyncio.new_event_loop()
    try:
        result, price_map, inv_rows = loop.run_until_complete(_fetch())
    finally:
        loop.close()
    # 聚合库存：按 nm_id 求和（一个 SKU 分布在多个仓库）
    stock_map = {}
    for row in (inv_rows or []):
        if not isinstance(row, dict):
            continue
        nm_id = row.get("nmId")
        qty = row.get("quantity") or 0
        if nm_id is None:
            continue
        stock_map[int(nm_id)] = stock_map.get(int(nm_id), 0) + int(qty)
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
        # WB 重量/尺寸：dimensions 字段（cm/kg → mm/g），两个分支都要用
        dims = p.get("dimensions") or {}
        if not isinstance(dims, dict):
            dims = {}
        weight_kg = dims.get("weightBrutto")
        weight_g = int(round(float(weight_kg) * 1000)) if weight_kg else None
        def _cm_to_mm(v):
            try:
                return int(round(float(v) * 10)) if v else None
            except (TypeError, ValueError):
                return None
        length_mm = _cm_to_mm(dims.get("length"))
        width_mm = _cm_to_mm(dims.get("width"))
        height_mm = _cm_to_mm(dims.get("height"))
        from datetime import datetime, timezone
        data = {
            "title_ru": (p.get("title") or subject_name or "")[:500],
            "description_ru": p.get("description"),
            "price": price,
            "discount_price": discount_price,
            "stock": stock_map.get(int(nm_id_int), 0),
            "stock_updated_at": datetime.now(timezone.utc),
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
            # 回填 product 的本地分类 + 尺寸/重量（已有不覆盖）
            if listing.product_id:
                prod = db.query(Product).filter(Product.id == listing.product_id).first()
                if prod:
                    if local_cat_id and not prod.local_category_id:
                        prod.local_category_id = local_cat_id
                    if weight_g and not prod.weight_g:
                        prod.weight_g = weight_g
                    if length_mm and not prod.length_mm:
                        prod.length_mm = length_mm
                    if width_mm and not prod.width_mm:
                        prod.width_mm = width_mm
                    if height_mm and not prod.height_mm:
                        prod.height_mm = height_mm
            updated += 1
        else:
            vendor_code = p.get("vendorCode") or f"WB-{nm_id}"
            product = _get_or_create_product(
                db, tenant_id, name_ru=data["title_ru"], sku=vendor_code,
                shop_id=shop.id,
                brand=p.get("brand"), image_url=image_url,
                weight_g=weight_g,
                length_mm=length_mm, width_mm=width_mm, height_mm=height_mm,
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
            # 并行：info 拉详情 + 分类树（名称反查用）
            info_task = asyncio.gather(*[
                client.fetch_product_info(product_ids[i:i + 500])
                for i in range(0, len(product_ids), 500)
            ])
            tree_task = client.fetch_category_tree()
            info_chunks, tree = await asyncio.gather(
                info_task, tree_task, return_exceptions=True,
            )
            if isinstance(info_chunks, Exception):
                raise info_chunks
            if isinstance(tree, Exception):
                logger.warning(f"Ozon 分类树拉取失败 shop={shop.id}: {tree}")
                tree = []
            infos = [it for chunk in info_chunks for it in chunk]
            return infos, archived_map, stock_map, tree
        finally:
            await client.close()

    loop = asyncio.new_event_loop()
    try:
        infos, archived_map, stock_map, tree = loop.run_until_complete(_fetch_all())
    finally:
        loop.close()

    cat_name_map = _flatten_ozon_category_tree(tree)  # {(desc_cat_id, type_id): name}

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
        # Ozon v3 info/list 分类字段：description_category_id + type_id 双 ID
        desc_cat_id = p.get("description_category_id")
        type_id = p.get("type_id")
        category_id_str = str(desc_cat_id) if desc_cat_id else (
            str(type_id) if type_id else None)
        type_id_str = str(type_id) if type_id else None
        local_cat_id = cat_map.get(category_id_str) if category_id_str else None
        # 从分类树反查面包屑名称（info/list 不返回）
        category_name = None
        if desc_cat_id and type_id:
            category_name = cat_name_map.get((int(desc_cat_id), int(type_id)))

        # OZON 的 sku_id（广告 API 返回的 sku 字段），与 product_id 是两套 ID
        ozon_sku = p.get("sku")
        # 库存：info.stocks.stocks[].present 聚合所有源（fbo/fbs）
        stocks_obj = p.get("stocks") or {}
        stocks_list = stocks_obj.get("stocks") or []
        ozon_stock = sum(int(s.get("present") or 0) for s in stocks_list if isinstance(s, dict))

        from datetime import datetime, timezone
        data = {
            "title_ru": title,
            "price": old_price or price,
            "discount_price": price if (old_price and price and old_price != price) else None,
            "barcode": barcode,
            "stock": ozon_stock,
            "stock_updated_at": datetime.now(timezone.utc),
            "platform_sku_id": str(ozon_sku) if ozon_sku else None,
            "platform_category_id": category_id_str,
            "platform_category_name": category_name[:300] if category_name else None,
            "platform_category_extra_id": type_id_str,
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
                           length_mm: Optional[int] = None,
                           width_mm: Optional[int] = None,
                           height_mm: Optional[int] = None,
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
        # 尺寸/重量：已有不覆盖（尊重用户手动改的值）
        if weight_g and not existing.weight_g:
            existing.weight_g = weight_g
        if length_mm and not existing.length_mm:
            existing.length_mm = length_mm
        if width_mm and not existing.width_mm:
            existing.width_mm = width_mm
        if height_mm and not existing.height_mm:
            existing.height_mm = height_mm
        return existing
    product = Product(
        tenant_id=tenant_id, shop_id=shop_id, sku=sku,
        name_zh=name_ru[:200] if name_ru else sku,
        name_ru=name_ru[:200] if name_ru else None,
        brand=brand,
        image_url=image_url,
        weight_g=weight_g,
        length_mm=length_mm,
        width_mm=width_mm,
        height_mm=height_mm,
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


async def get_platform_attributes(
    db: Session, product_id: int, tenant_id: int,
) -> dict:
    """拉取商品在平台上的属性列表（只读展示）

    WB: cards/list 的 characteristics 字段，自带 name + value
    OZON: /v4/product/info/attributes 返回 id + values，需要从 attribute_mappings
          反查属性名称（如果该分类做过 init-from-ozon 或手动映射过）
    """
    from app.models.shop import Shop
    from app.models.category import AttributeMapping

    product = db.query(Product).filter(
        Product.id == product_id, Product.tenant_id == tenant_id,
    ).first()
    if not product:
        return {"code": ErrorCode.PRODUCT_NOT_FOUND, "msg": "商品不存在"}
    listing = db.query(PlatformListing).filter(
        PlatformListing.tenant_id == tenant_id,
        PlatformListing.product_id == product_id,
        PlatformListing.status != "deleted",
    ).first()
    if not listing:
        return {"code": ErrorCode.LISTING_NOT_FOUND, "msg": "商品未关联任何 listing"}
    shop = db.query(Shop).filter(Shop.id == listing.shop_id).first()
    if not shop:
        return {"code": ErrorCode.SHOP_NOT_FOUND, "msg": "店铺不存在"}

    if listing.platform == "wb":
        return await _wb_attributes(shop, listing)
    elif listing.platform == "ozon":
        return await _ozon_attributes(db, tenant_id, shop, listing)
    else:
        return {"code": 0, "data": {"platform": listing.platform, "attributes": []}}


async def _wb_attributes(shop, listing) -> dict:
    """WB: 从 cards/list 找到这个 nm_id 的 characteristics"""
    from app.services.platform.wb import WBClient
    client = WBClient(shop_id=shop.id, api_key=shop.api_key)
    try:
        res = await client.fetch_products(limit=100)
        cards = (res or {}).get("cards") or []
        target = next((c for c in cards
                       if str(c.get("nmID")) == str(listing.platform_product_id)), None)
        if not target:
            return {"code": 0, "data": {"platform": "wb", "attributes": []}}
        chars = target.get("characteristics") or []
        attrs = []
        for c in chars:
            value = c.get("value")
            if isinstance(value, list):
                value = ", ".join(str(v) for v in value)
            attrs.append({
                "id": c.get("id"),
                "name": c.get("name", ""),
                "value": str(value) if value is not None else "",
            })
        return {"code": 0, "data": {"platform": "wb", "attributes": attrs}}
    finally:
        await client.close()


async def _ozon_attributes(db, tenant_id, shop, listing) -> dict:
    """OZON: /v4/product/info/attributes，从 attribute_mappings 反查属性名"""
    import httpx
    from app.models.category import AttributeMapping, CategoryPlatformMapping
    url = "https://api-seller.ozon.ru/v4/product/info/attributes"
    headers = {
        "Client-Id": shop.client_id, "Api-Key": shop.api_key,
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, headers=headers, json={
                "filter": {
                    "product_id": [str(listing.platform_product_id)],
                    "visibility": "ALL",
                },
                "limit": 100,
            })
            if resp.status_code != 200:
                logger.warning(f"OZON 属性接口 {resp.status_code}: {resp.text[:200]}")
                return {"code": ErrorCode.UNKNOWN_ERROR, "msg": f"OZON 属性拉取失败 {resp.status_code}"}
            data = resp.json()
            items = data.get("result") or []
            if not items:
                return {"code": 0, "data": {"platform": "ozon", "attributes": []}}
            ozon_attrs = items[0].get("attributes") or []
    except Exception as e:
        logger.error(f"OZON 属性拉取异常: {e}")
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "OZON 属性拉取异常"}

    # 尝试从 attribute_mappings 反查属性名
    # 先找到该 listing 对应的 local_category_id
    name_map = {}
    cat_mapping = db.query(CategoryPlatformMapping).filter(
        CategoryPlatformMapping.tenant_id == tenant_id,
        CategoryPlatformMapping.platform == "ozon",
        CategoryPlatformMapping.platform_category_id == listing.platform_category_id,
    ).first()
    if cat_mapping:
        attr_rows = db.query(
            AttributeMapping.platform_attr_id,
            AttributeMapping.platform_attr_name,
            AttributeMapping.local_attr_name,
        ).filter(
            AttributeMapping.tenant_id == tenant_id,
            AttributeMapping.local_category_id == cat_mapping.local_category_id,
            AttributeMapping.platform == "ozon",
        ).all()
        for r in attr_rows:
            name_map[str(r.platform_attr_id)] = {
                "ru": r.platform_attr_name,
                "zh": r.local_attr_name,
            }

    attrs = []
    for a in ozon_attrs:
        attr_id = str(a.get("id", ""))
        values = a.get("values") or []
        # 组装值文本
        val_parts = []
        for v in values:
            if isinstance(v, dict):
                val = v.get("value") or v.get("dictionary_value_id", "")
                if val:
                    val_parts.append(str(val))
        name_info = name_map.get(attr_id, {})
        attrs.append({
            "id": int(attr_id) if attr_id.isdigit() else attr_id,
            "name": name_info.get("zh") or name_info.get("ru") or f"属性 #{attr_id}",
            "name_ru": name_info.get("ru", ""),
            "value": " | ".join(val_parts)[:500],
        })
    return {"code": 0, "data": {"platform": "ozon", "attributes": attrs}}


async def download_listing_images_to_oss(
    db: Session, product_id: int, tenant_id: int,
) -> dict:
    """下载平台全量图片到阿里云 OSS，写入 listing.oss_images

    流程：
    1. 查 product → 拿到当前店铺的 listing
    2. 按 listing.platform 调对应 API 拉全量图片 URL 列表
       - WB: cards/list 的 photos[].big
       - OZON: info/list 的 images[]
    3. 串行下载上传 OSS，返回 URL 列表
    4. 写入 listing.oss_images（JSON 数组）
    """
    from app.utils.oss_client import download_images_batch, is_configured
    from app.models.shop import Shop

    if not is_configured():
        return {"code": ErrorCode.UNKNOWN_ERROR,
                "msg": "OSS 未配置，请联系管理员在 .env 配置 OSS 凭证"}

    product = db.query(Product).filter(
        Product.id == product_id, Product.tenant_id == tenant_id,
    ).first()
    if not product:
        return {"code": ErrorCode.PRODUCT_NOT_FOUND, "msg": "商品不存在"}
    listings = db.query(PlatformListing).filter(
        PlatformListing.tenant_id == tenant_id,
        PlatformListing.product_id == product_id,
        PlatformListing.status != "deleted",
    ).all()
    if not listings:
        return {"code": ErrorCode.LISTING_NOT_FOUND, "msg": "商品未关联任何 listing"}

    listing = listings[0]  # product 已按店铺拆分，一个 product 只有一条 listing
    shop = db.query(Shop).filter(Shop.id == listing.shop_id).first()
    if not shop:
        return {"code": ErrorCode.SHOP_NOT_FOUND, "msg": "店铺不存在"}

    # 1. 从平台拉全量图片 URL
    source_urls = await _fetch_platform_image_urls(shop, listing)
    if not source_urls:
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "平台未返回任何图片"}

    # 2. 批量下载 + 上传 OSS
    prefix = f"products/{tenant_id}/{shop.id}/{listing.platform_product_id}"
    oss_urls = await download_images_batch(source_urls, prefix)
    if not oss_urls:
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "所有图片下载或上传失败"}

    # 3. 写入 listing.oss_images
    listing.oss_images = oss_urls
    # 同时更新 product.image_url 指向 OSS 首图（替换平台外链，避免链接失效）
    if not product.image_url or product.image_url.startswith(("http://basket", "https://basket", "https://cdn1.ozone.ru")):
        product.image_url = oss_urls[0]
    db.commit()

    return {"code": 0, "data": {
        "total_source": len(source_urls),
        "uploaded": len(oss_urls),
        "oss_images": oss_urls,
    }}


async def _fetch_platform_image_urls(shop, listing) -> list:
    """从平台拉全量图片 URL，返回 ['https://...', ...]"""
    if listing.platform == "wb":
        from app.services.platform.wb import WBClient
        client = WBClient(shop_id=shop.id, api_key=shop.api_key)
        try:
            res = await client.fetch_products(limit=100)
            cards = (res or {}).get("cards") or []
            target = next((c for c in cards if str(c.get("nmID")) == str(listing.platform_product_id)), None)
            if not target:
                return []
            photos = target.get("photos") or []
            urls = []
            for p in photos:
                if isinstance(p, dict):
                    # 优先取 big/hq 大图
                    u = p.get("big") or p.get("hq") or p.get("c516x688") or p.get("tm")
                    if u:
                        urls.append(u)
            return urls
        finally:
            await client.close()
    elif listing.platform == "ozon":
        from app.services.platform.ozon import OzonClient
        client = OzonClient(
            shop_id=shop.id, api_key=shop.api_key, client_id=shop.client_id,
            perf_client_id=shop.perf_client_id or "",
            perf_client_secret=shop.perf_client_secret or "",
        )
        try:
            infos = await client.fetch_product_info([int(listing.platform_product_id)])
            if not infos:
                return []
            info = infos[0]
            images = info.get("images") or []
            # OZON images 可能是字符串数组或对象数组
            urls = []
            for img in images:
                if isinstance(img, str):
                    urls.append(img)
                elif isinstance(img, dict):
                    u = img.get("url") or img.get("file_name")
                    if u:
                        urls.append(u)
            # 补上 primary_image
            primary = info.get("primary_image")
            if primary:
                if isinstance(primary, list):
                    for p in primary:
                        if isinstance(p, str) and p not in urls:
                            urls.insert(0, p)
                elif isinstance(primary, str) and primary not in urls:
                    urls.insert(0, primary)
            return urls
        finally:
            await client.close()
    return []


async def optimize_title(db: Session, listing_id: int, tenant_id: int) -> dict:
    “””AI 标题优化：富上下文版（热搜词 + 平台属性 + 商品属性 + 价格）

    prompt 里尽量喂真实数据，让 AI 基于流量数据选词组标题。
    不修改 listing，仅返回建议文本让用户手动到平台后台改。
    “””
    from app.config import get_settings
    from app.services.ai.kimi import KimiClient
    listing = db.query(PlatformListing).filter(
        PlatformListing.id == listing_id,
        PlatformListing.tenant_id == tenant_id,
    ).first()
    if not listing:
        return {“code”: ErrorCode.LISTING_NOT_FOUND, “msg”: “Listing不存在”}
    if not listing.title_ru:
        return {“code”: ErrorCode.PARAM_ERROR, “msg”: “商品暂无标题”}

    product = db.query(Product).filter(Product.id == listing.product_id).first()
    zh_context = product.name_zh if product else “”

    # ── 1. 本地分类 + 平台属性 ──
    category_name = “”
    attributes_text = “”
    if product and product.local_category_id:
        from app.models.category import LocalCategory, AttributeMapping
        cat = db.query(LocalCategory).filter(
            LocalCategory.id == product.local_category_id,
            LocalCategory.tenant_id == tenant_id,
        ).first()
        if cat:
            category_name = f”{cat.name}” + (f”（{cat.name_ru}）” if cat.name_ru else “”)

        attrs = db.query(AttributeMapping).filter(
            AttributeMapping.tenant_id == tenant_id,
            AttributeMapping.local_category_id == product.local_category_id,
            AttributeMapping.platform == listing.platform,
        ).order_by(AttributeMapping.is_required.desc()).limit(15).all()
        if attrs:
            required = [a for a in attrs if a.is_required]
            optional = [a for a in attrs if not a.is_required]
            parts = []
            if required:
                parts.append(“必填属性：” + “、”.join(
                    f”{a.local_attr_name}({a.platform_attr_name})” for a in required
                ))
            if optional[:5]:
                parts.append(“可选属性：” + “、”.join(
                    f”{a.local_attr_name}” for a in optional[:5]
                ))
            attributes_text = “\n”.join(parts)

    # ── 2. 商品自身属性 ──
    product_attrs = []
    if product:
        if product.brand:
            product_attrs.append(f”品牌：{product.brand}”)
        if product.weight_g:
            product_attrs.append(f”重量：{product.weight_g}g”)
        if product.length_mm and product.width_mm:
            product_attrs.append(f”尺寸：{product.length_mm}×{product.width_mm}mm”)
    if listing.price:
        product_attrs.append(f”售价：{listing.price}₽”)
    if listing.discount_price:
        product_attrs.append(f”折后价：{listing.discount_price}₽”)
    product_attrs_text = “、”.join(product_attrs) if product_attrs else “暂无”

    # ── 3. 热搜关键词（keyword_daily_stats 表可能还没建，graceful 降级）──
    hot_keywords_text = “”
    context_sources = []
    try:
        from sqlalchemy import text as sa_text
        rows = db.execute(sa_text(“””
            SELECT keyword, SUM(impressions) AS imp, SUM(clicks) AS clk
            FROM keyword_daily_stats
            WHERE tenant_id = :tid AND shop_id = :sid
              AND stat_date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
            GROUP BY keyword
            ORDER BY imp DESC
            LIMIT 20
        “””), {“tid”: tenant_id, “sid”: listing.shop_id}).fetchall()
        if rows:
            lines = []
            for i, r in enumerate(rows, 1):
                lines.append(f”  {i}. {r.keyword} — 曝光 {r.imp}, 点击 {r.clk}”)
            hot_keywords_text = “\n”.join(lines)
            context_sources.append(f”热搜词TOP{len(rows)}”)
    except Exception:
        pass

    if category_name:
        context_sources.append(“本地分类”)
    if attributes_text:
        context_sources.append(“平台属性”)
    if product_attrs:
        context_sources.append(“商品属性”)

    # ── 4. 组装 prompt ──
    platform_style = {
        “wb”: (
            “WB（Wildberries）标题风格：60-100 字符，关键词前置，”
            “强调用途/材质/尺寸/适用场景，常见套路如”
            “「商品类型 + 关键属性 + 用途场景 + 受众」”
        ),
        “ozon”: (
            “Ozon 标题风格：60-120 字符，SEO 导向，关键词自然融入，”
            “突出产品名、品牌、型号、核心规格”
        ),
        “yandex”: (
            “Yandex Market 标题风格：品牌 + 型号 + 关键规格，”
            “简洁精准，40-80 字符”
        ),
    }
    style_desc = platform_style.get(listing.platform, platform_style[“ozon”])

    prompt_parts = [
        f”你是俄罗斯电商标题优化专家。请针对 {listing.platform.upper()} 平台优化下面的商品标题。”,
        f”\n【平台规则】\n{style_desc}”,
        f”\n【当前标题】\n{listing.title_ru}”,
        f”\n【中文参考】\n{zh_context}” if zh_context else “”,
        f”\n【商品分类】\n{category_name}” if category_name else “”,
        f”\n【商品属性】\n{product_attrs_text}”,
        f”\n【平台属性清单（标题中应体现核心属性）】\n{attributes_text}” if attributes_text else “”,
    ]
    if hot_keywords_text:
        prompt_parts.append(
            f”\n【该店铺近30天热搜关键词（按曝光排序，标题应尽量包含高流量词）】\n{hot_keywords_text}”
        )
    prompt_parts.append(“””
【要求】
- 输出 3 个优化方案，每行一个，纯俄文标题，不加编号/引号/解释
- 尽量把高曝光的热搜关键词自然融入标题
- 保留核心商品信息，不要增加虚假属性
- 关键词靠前，长度符合平台要求
- 3 个方案分别侧重：①高流量词堆叠 ②自然语感 ③突出差异化卖点”””)

    prompt = “\n”.join(p for p in prompt_parts if p)

    settings = get_settings()
    client = KimiClient(api_key=settings.KIMI_API_KEY)
    try:
        result = await client.chat(
            messages=[{“role”: “user”, “content”: prompt}],
            temperature=0.6, max_tokens=600,
        )
        content = (result.get(“content”) or “”).strip()
        titles = [
            line.strip().lstrip('0123456789.）)、').lstrip('””«').rstrip('””»').strip()
            for line in content.split('\n')
            if line.strip() and len(line.strip()) > 10
        ][:3]
        if not titles:
            titles = [content]
        return {“code”: 0, “data”: {
            “suggestions”: titles,
            “original_title”: listing.title_ru,
            “platform”: listing.platform,
            “context_sources”: context_sources,
            “hot_keywords_used”: bool(hot_keywords_text),
            “category”: category_name,
        }}
    except Exception as e:
        logger.error(f”Kimi 标题优化失败: {e}”)
        return {“code”: ErrorCode.UNKNOWN_ERROR, “msg”: “AI 标题优化失败”}


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
