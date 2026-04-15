import re
import os

# 下载目录
DOWNLOAD_DIR = r"C:\Users\wcq\Downloads\product_management"
# 项目目录
PROJECT_DIR = r"D:\eluosi"

# ===== 1. 直接覆盖 Products.jsx（原来只有2行）=====
src = os.path.join(DOWNLOAD_DIR, "Products.jsx")
dst = os.path.join(PROJECT_DIR, "frontend", "src", "pages", "Products.jsx")
with open(src, 'r', encoding='utf-8') as f:
    content = f.read()
with open(dst, 'w', encoding='utf-8') as f:
    f.write(content)
print("✅ Products.jsx 覆盖完成")

# ===== 2. 直接新建 products.js =====
src = os.path.join(DOWNLOAD_DIR, "products.js")
dst = os.path.join(PROJECT_DIR, "frontend", "src", "api", "products.js")
with open(src, 'r', encoding='utf-8') as f:
    content = f.read()
with open(dst, 'w', encoding='utf-8') as f:
    f.write(content)
print("✅ products.js 新建完成")

# ===== 3. 合并 product.py（schemas）=====
path = os.path.join(PROJECT_DIR, "app", "schemas", "product.py")
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace(
    'from typing import Optional, List',
    'from typing import Optional, List, Dict, Any'
)
content = content.replace(
    '    image_url: Optional[str] = Field(None, max_length=500, description="图片URL")',
    '    image_url: Optional[str] = Field(None, max_length=500, description="图片URL")\n    net_margin: Optional[float] = Field(None, ge=0, le=1, description="净毛利率0-1")'
)
content = content.replace(
    '    status: Optional[str] = Field(None, pattern="^(active|inactive)$")',
    '    net_margin: Optional[float] = Field(None, ge=0, le=1)\n    status: Optional[str] = Field(None, pattern="^(active|inactive)$")'
)
content = content.replace(
    '    url: Optional[str] = Field(None, max_length=500, description="商品链接")',
    '    url: Optional[str] = Field(None, max_length=500, description="商品链接")\n    barcode: Optional[str] = Field(None, max_length=50)\n    description_ru: Optional[str] = None\n    variant_name: Optional[str] = Field(None, max_length=100)\n    variant_attrs: Optional[Dict[str, Any]] = None\n    platform_listed_at: Optional[datetime] = None'
)
content = content.replace(
    '    status: Optional[str] = Field(None, pattern="^(active|inactive|out_of_stock)$")',
    '    barcode: Optional[str] = Field(None, max_length=50)\n    description_ru: Optional[str] = None\n    variant_name: Optional[str] = Field(None, max_length=100)\n    variant_attrs: Optional[Dict[str, Any]] = None\n    oss_images: Optional[Dict[str, Any]] = None\n    oss_videos: Optional[Dict[str, Any]] = None\n    status: Optional[str] = Field(None, pattern="^(active|inactive|out_of_stock|blocked|deleted)$")'
)
content += '''

# ========== 商品同步 ==========

class ProductSyncRequest(BaseModel):
    shop_id: int
    force: bool = Field(False, description="强制同步，忽略30分钟限制")


# ========== 净毛利率快速编辑 ==========

class ProductMarginUpdate(BaseModel):
    net_margin: Optional[float] = Field(None, ge=0, le=1)


# ========== 描述AI改写 ==========

class GenerateDescriptionRequest(BaseModel):
    listing_id: int
    target_platform: str = Field(..., pattern="^(wb|ozon|yandex)$")


# ========== 铺货 ==========

class SpreadRequest(BaseModel):
    src_listing_ids: List[int]
    dst_shop_ids: List[int]
    price_mode: str = Field("original", pattern="^(original|manual|auto)$")
    manual_price: Optional[float] = Field(None, ge=0)
    ai_rewrite_title: bool = False
    ai_change_bg: bool = False
'''

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
print("✅ product.py 合并完成")


# ===== 4. 合并 service.py =====
path = os.path.join(PROJECT_DIR, "app", "services", "product", "service.py")
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace(
    'from sqlalchemy.orm import Session',
    'from datetime import datetime, timezone\nfrom typing import Optional\nfrom sqlalchemy.orm import Session\nfrom sqlalchemy import text'
)
content = content.replace(
    '        "cost_price": float(p.cost_price) if p.cost_price else None,',
    '        "cost_price": float(p.cost_price) if p.cost_price else None,\n        "net_margin": float(p.net_margin) if p.net_margin else None,'
)
content = content.replace(
    '        "platform_product_id": l.platform_product_id,',
    '        "platform_product_id": l.platform_product_id,\n        "barcode": l.barcode,\n        "description_ru": l.description_ru,\n        "variant_name": l.variant_name,\n        "variant_attrs": l.variant_attrs,'
)
content = content.replace(
    '        "status": l.status,',
    '        "status": l.status,\n        "publish_status": l.publish_status,\n        "oss_images": l.oss_images,\n        "oss_videos": l.oss_videos,\n        "source_listing_id": l.source_listing_id,\n        "platform_listed_at": l.platform_listed_at.isoformat() if l.platform_listed_at else None,'
)

content += '''

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
            return await client.fetch_all_products()
        finally:
            await client.close()
    loop = asyncio.new_event_loop()
    try:
        products = loop.run_until_complete(_fetch())
    finally:
        loop.close()
    synced = created = updated = 0
    for p in (products or []):
        nm_id = str(p.get("nmID") or p.get("nmId") or "")
        if not nm_id:
            continue
        listing = db.query(PlatformListing).filter(
            PlatformListing.tenant_id == tenant_id,
            PlatformListing.shop_id == shop.id,
            PlatformListing.platform == "wb",
            PlatformListing.platform_product_id == nm_id,
        ).first()
        data = {
            "title_ru": (p.get("subjectName") or p.get("name") or "")[:500],
            "price": float(p.get("salePriceU", 0)) / 100 if p.get("salePriceU") else None,
            "status": "active" if int(p.get("quantityFull", 0)) > 0 else "out_of_stock",
        }
        if listing:
            for k, v in data.items():
                if v is not None:
                    setattr(listing, k, v)
            updated += 1
        else:
            product = _get_or_create_product(
                db, tenant_id, name_ru=data["title_ru"], sku=f"WB-{nm_id}")
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
    async def _fetch():
        client = OzonClient(
            shop_id=shop.id, api_key=shop.api_key, client_id=shop.client_id,
            perf_client_id=shop.perf_client_id or "",
            perf_client_secret=shop.perf_client_secret or "")
        try:
            return await client.fetch_all_products()
        finally:
            await client.close()
    loop = asyncio.new_event_loop()
    try:
        products = loop.run_until_complete(_fetch())
    finally:
        loop.close()
    synced = created = updated = 0
    status_map = {
        "VISIBLE": "active", "INVISIBLE": "inactive",
        "OUT_OF_STOCK": "out_of_stock", "BANNED": "blocked", "ARCHIVED": "deleted"
    }
    for p in (products or []):
        product_id = str(p.get("product_id") or "")
        if not product_id:
            continue
        listing = db.query(PlatformListing).filter(
            PlatformListing.tenant_id == tenant_id,
            PlatformListing.shop_id == shop.id,
            PlatformListing.platform == "ozon",
            PlatformListing.platform_product_id == product_id,
        ).first()
        data = {
            "title_ru": (p.get("name") or "")[:500],
            "price": float(p.get("price") or 0) or None,
            "discount_price": float(p.get("marketing_price") or 0) or None,
            "status": status_map.get((p.get("visibility") or "").upper(), "active"),
        }
        if listing:
            for k, v in data.items():
                if v is not None:
                    setattr(listing, k, v)
            updated += 1
        else:
            product = _get_or_create_product(
                db, tenant_id, name_ru=data["title_ru"], sku=f"OZ-{product_id}")
            listing = PlatformListing(
                tenant_id=tenant_id, product_id=product.id,
                shop_id=shop.id, platform="ozon",
                platform_product_id=product_id, **data)
            db.add(listing)
            created += 1
        synced += 1
    db.commit()
    _update_sync_time(db, shop.id, tenant_id)
    return {"code": 0, "data": {"synced": synced, "created": created, "updated": updated}}


def _get_or_create_product(db: Session, tenant_id: int,
                           name_ru: str, sku: str):
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
'''

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
print("✅ service.py 合并完成")


# ===== 5. 合并 products.py（API路由）=====
path = os.path.join(PROJECT_DIR, "app", "api", "v1", "products.py")
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace(
    'from fastapi import APIRouter, Depends, Query',
    'from fastapi import APIRouter, Depends, Query, BackgroundTasks'
)
content = content.replace(
    'from app.schemas.product import ProductCreate, ProductUpdate, ListingCreate, ListingUpdate',
    'from app.schemas.product import (\n    ProductCreate, ProductUpdate, ProductMarginUpdate,\n    ListingCreate, ListingUpdate,\n    ProductSyncRequest, GenerateDescriptionRequest, SpreadRequest,\n)'
)
content = content.replace(
    'from app.services.product.service import (\n    list_products, create_product, get_product, update_product, delete_product,\n    list_listings, create_listing, update_listing, delete_listing,\n)',
    'from app.services.product.service import (\n    list_products, create_product, get_product,\n    update_product, update_product_margin, delete_product,\n    list_listings, create_listing, update_listing, delete_listing,\n    check_sync_needed, sync_products_from_platform, generate_description,\n)'
)
content = content.replace(
    '    status: str = Query(None, description="状态筛选: active/inactive"),',
    '    status: str = Query("active"),\n    platform: str = Query(None),\n    shop_id: int = Query(None),'
)

content += '''

@router.patch("/{product_id}/margin")
def product_margin_update(
    product_id: int,
    req: ProductMarginUpdate,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    result = update_product_margin(db, product_id, tenant_id, req.net_margin)
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"])


@router.get("/sync/check")
def sync_check(
    shop_id: int = Query(...),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    result = check_sync_needed(db, shop_id, tenant_id)
    return success(result)


@router.post("/sync")
def sync_products(
    req: ProductSyncRequest,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    check = check_sync_needed(db, req.shop_id, tenant_id, force=req.force)
    if not check["need_sync"]:
        return success({"syncing": False, "message": "无需重复同步"})
    from app.tasks.daily_sync_task import sync_shop_products
    task = sync_shop_products.delay(req.shop_id, tenant_id)
    return success({"syncing": True, "task_id": task.id, "message": "同步任务已启动"})


@router.post("/listings/{listing_id}/generate-description")
async def listing_generate_description(
    listing_id: int,
    req: GenerateDescriptionRequest,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    result = await generate_description(db, listing_id, tenant_id, req.target_platform)
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"])


@router.post("/spread")
def spread_products(
    req: SpreadRequest,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    from app.tasks.daily_sync_task import spread_products_task
    task = spread_products_task.delay(
        tenant_id=tenant_id,
        src_listing_ids=req.src_listing_ids,
        dst_shop_ids=req.dst_shop_ids,
        price_mode=req.price_mode,
        manual_price=req.manual_price,
    )
    return success({
        "task_id": task.id,
        "message": f"铺货任务已提交，共{len(req.src_listing_ids)}个商品"
    })


@router.get("/spread/records")
def spread_records(
    shop_id: int = Query(None),
    status: str = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    from sqlalchemy import text
    where = "WHERE tenant_id = :tenant_id"
    params = {"tenant_id": tenant_id}
    if shop_id:
        where += " AND dst_shop_id = :shop_id"
        params["shop_id"] = shop_id
    if status:
        where += " AND status = :status"
        params["status"] = status
    total = db.execute(
        text(f"SELECT COUNT(*) FROM spread_records {where}"), params
    ).scalar()
    rows = db.execute(text(f"""
        SELECT * FROM spread_records {where}
        ORDER BY created_at DESC LIMIT :limit OFFSET :offset
    """), {**params, "limit": page_size, "offset": (page-1)*page_size}).fetchall()
    return success({
        "items": [dict(r._mapping) for r in rows],
        "total": total, "page": page
    })
'''

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
print("✅ products.py 合并完成")

print("\n🎉 所有文件处理完成！")
print("下一步：git add . && git commit -m 'feat(product): 商品管理升级' && git push origin main")