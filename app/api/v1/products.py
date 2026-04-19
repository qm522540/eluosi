"""商品路由"""

from fastapi import APIRouter, Depends, Query, BackgroundTasks, UploadFile, File, Body
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_current_user, get_tenant_id
from app.schemas.product import (
    ProductCreate, ProductUpdate, ProductMarginUpdate, CostCopyRequest,
    ListingCreate, ListingUpdate,
    ProductSyncRequest, GenerateDescriptionRequest, SpreadRequest,
)
from app.services.product.service import (
    list_products, create_product, get_product,
    update_product, update_product_margin, delete_product,
    copy_cost_to_other_shops,
    list_listings, create_listing, update_listing, delete_listing,
    check_sync_needed, sync_products_from_platform, generate_description,
    optimize_title, download_listing_images_to_oss, get_platform_attributes,
)
from app.utils.response import success, error

router = APIRouter()


# ==================== 商品接口 ====================

@router.get("")
def product_list(
    keyword: str = Query(None, description="搜索关键词(SKU/名称)"),
    status: str = Query("active"),
    platform: str = Query(None),
    shop_id: int = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """获取商品列表"""
    result = list_products(db, tenant_id, keyword=keyword,
                           status=status, platform=platform, shop_id=shop_id,
                           page=page, page_size=page_size)
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


@router.post("/{product_id}/copy-cost-to-other-shops")
def product_copy_cost(
    product_id: int,
    req: CostCopyRequest,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """把成本/毛利等本地字段复制到同租户下其他店铺的同 SKU 商品。
    默认复制 cost_price + net_margin；target_shop_ids 不传 = 所有同 SKU 其他店铺。
    """
    result = copy_cost_to_other_shops(
        db, product_id, tenant_id,
        fields=req.fields, target_shop_ids=req.target_shop_ids,
    )
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"], msg=f"已复制到 {result['data']['copied']} 个店铺")


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
    # 同步前置校验：店铺存在 + 平台凭证齐全（避免 Celery 拿到任务才发现配置错而前端不感知）
    from app.models.shop import Shop
    shop = db.query(Shop).filter(
        Shop.id == req.shop_id, Shop.tenant_id == tenant_id, Shop.status == "active",
    ).first()
    if not shop:
        return error(30001, "店铺不存在或已停用")
    if not shop.api_key:
        return error(10002, "店铺未配置 API Key，去店铺设置补填")
    if shop.platform == "ozon" and not shop.client_id:
        return error(10002, "Ozon 店铺缺少 Client ID，去店铺设置补填")
    if shop.platform == "yandex" and not shop.yandex_business_id:
        return error(10002, "Yandex 店铺缺少 Business ID，去店铺设置补填")

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


@router.post("/listings/{listing_id}/optimize-title")
async def listing_optimize_title(
    listing_id: int,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """AI 标题优化：按 listing 所在平台风格生成优化建议（不修改 listing）"""
    result = await optimize_title(db, listing_id, tenant_id)
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"])


@router.get("/{product_id}/platform-attributes")
async def product_platform_attributes(
    product_id: int,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """拉取商品在平台上的全部属性（只读，实时拉平台 API）

    WB: characteristics 自带名字；
    OZON: attribute_mappings 反查名字（需要该分类做过映射），
    否则返回 "属性 #id"。
    """
    result = await get_platform_attributes(db, product_id, tenant_id)
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"])


@router.post("/{product_id}/download-images")
async def product_download_images(
    product_id: int,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """下载商品在平台的全部图片到阿里云 OSS，写入 listing.oss_images

    耗时：图片数量 × 平均 3-5 秒（串行下载+上传）。
    建议前端 timeout 设 120s。
    """
    result = await download_listing_images_to_oss(db, product_id, tenant_id)
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"], msg=f"已归档 {result['data']['uploaded']} 张图片")


@router.post("/spread")
def spread_products(
    req: SpreadRequest,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    return success({"task_id": "pending", "message": "铺货功能开发中"})


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


# ==================== 净毛利率批量导入 ====================

# 编码列识别关键词（按优先级，全部小写匹配）
_CODE_HEADER_KEYWORDS = [
    "本地编码", "本地sku", "商品编号", "商品编码", "sku编码",
    "sku", "编码", "编号", "code", "spu", "product_code",
]
# 净毛利率列识别关键词
_MARGIN_HEADER_KEYWORDS = [
    "净毛利率", "净利率", "毛利率",
    "net_margin", "net margin", "margin",
    "毛利", "利润率", "profit",
]


def _detect_column(headers: list, keywords: list) -> int:
    """按关键词优先级找匹配列，返回 index 或 -1"""
    norm_headers = [(str(h).strip().lower() if h is not None else "") for h in headers]
    for kw in keywords:
        kw_lower = kw.lower()
        # 完全相等优先
        for i, h in enumerate(norm_headers):
            if h == kw_lower:
                return i
        # 包含次之
        for i, h in enumerate(norm_headers):
            if h and kw_lower in h:
                return i
    return -1


def _normalize_margin(raw) -> tuple:
    """规整净毛利率：返回 (float|None, error_msg|None)
    - "28%" → 0.28
    - "28.5%" → 0.285
    - "28" → 0.28（推断为百分数）
    - "0.28" → 0.28
    - "" / "-" / NA / None → (None, "空值")
    """
    if raw is None:
        return None, "空值"
    s = str(raw).strip()
    if not s or s in ("-", "—", "NA", "N/A", "null", "None"):
        return None, "空值"
    is_pct = s.endswith("%")
    if is_pct:
        s = s[:-1].strip()
    try:
        v = float(s)
    except ValueError:
        return None, f"无法解析为数字: {raw}"
    # 归一化
    if is_pct:
        v = v / 100.0
    elif v > 1:  # "28" 推断百分数
        v = v / 100.0
    if v <= 0 or v >= 1:
        return None, f"超出合理范围 (0~1): {v}"
    return round(v, 4), None


def _parse_uploaded_file(filename: str, content: bytes) -> tuple:
    """解析上传文件 → (headers: list, rows: list of list)"""
    name_lower = (filename or "").lower()
    if name_lower.endswith(".csv"):
        import csv as _csv
        import io
        # 先猜编码
        for enc in ("utf-8-sig", "utf-8", "gbk", "gb18030"):
            try:
                text = content.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise ValueError("CSV 文件编码无法识别（试过 utf-8/gbk）")
        reader = _csv.reader(io.StringIO(text))
        all_rows = [r for r in reader]
        if not all_rows:
            return [], []
        return all_rows[0], all_rows[1:]
    elif name_lower.endswith((".xlsx", ".xlsm")):
        import openpyxl
        import io
        wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True, read_only=True)
        ws = wb.active
        rows_iter = ws.iter_rows(values_only=True)
        all_rows = list(rows_iter)
        if not all_rows:
            return [], []
        # 跳过开头空行（找第一行有内容的当 header）
        header_idx = 0
        for i, row in enumerate(all_rows):
            if any(c is not None and str(c).strip() for c in row):
                header_idx = i
                break
        headers = [c if c is not None else "" for c in all_rows[header_idx]]
        body = all_rows[header_idx + 1:]
        return headers, [list(r) for r in body]
    else:
        raise ValueError(f"不支持的文件格式（仅 .csv / .xlsx）: {filename}")


@router.post("/import-margin/preview")
async def import_margin_preview(
    file: UploadFile = File(...),
    code_col_index: int = -1,  # 用户手动指定列（-1 表示自动识别）
    margin_col_index: int = -1,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """上传净毛利率文件预览：解析文件 + 自动识别列 + 返回预览
    - 不会真的更新 DB
    - 返回结构供前端弹"确认"对话框
    """
    from app.models.product import Product
    try:
        content = await file.read()
        if len(content) > 10 * 1024 * 1024:  # 10MB
            return error(10002, "文件超过 10MB")
        headers, rows = _parse_uploaded_file(file.filename, content)
    except ValueError as e:
        return error(10002, str(e))
    except Exception as e:
        return error(10002, f"文件解析失败: {e}")

    if not headers or not rows:
        return error(10002, "文件为空或没有数据行")

    # 自动识别列（可被前端传参覆盖）
    detected_code_idx = code_col_index if code_col_index >= 0 else _detect_column(
        headers, _CODE_HEADER_KEYWORDS)
    detected_margin_idx = margin_col_index if margin_col_index >= 0 else _detect_column(
        headers, _MARGIN_HEADER_KEYWORDS)

    if detected_code_idx < 0:
        return error(10002, "未能识别出"商品编码"列，请检查表头或手动指定")
    if detected_margin_idx < 0:
        return error(10002, "未能识别出"净毛利率"列，请检查表头或手动指定")

    # 拉取本地所有商品 SKU 集合
    local_codes = {
        str(r[0]).strip(): r[1] for r in db.query(Product.sku, Product.net_margin)
        .filter(Product.tenant_id == tenant_id).all()
        if r[0]
    }

    # 解析每行
    items = []
    summary = {"total": 0, "valid": 0, "matched": 0, "format_err": 0,
               "code_not_found": 0, "empty_margin": 0}
    for ridx, row in enumerate(rows):
        if not row or all(c is None or str(c).strip() == "" for c in row):
            continue
        summary["total"] += 1
        code = str(row[detected_code_idx] or "").strip() if detected_code_idx < len(row) else ""
        margin_raw = row[detected_margin_idx] if detected_margin_idx < len(row) else None
        margin_val, m_err = _normalize_margin(margin_raw)

        item = {
            "row_no": ridx + 2,  # +2 = header 行 + 1-based
            "code": code,
            "margin_raw": "" if margin_raw is None else str(margin_raw),
            "margin_value": margin_val,
            "old_margin": None,
            "matched": False,
            "error": None,
        }
        if not code:
            item["error"] = "编码空"
        elif m_err:
            item["error"] = m_err
            summary["format_err"] += 1
        elif code not in local_codes:
            item["error"] = "本地找不到该编码"
            summary["code_not_found"] += 1
        else:
            item["matched"] = True
            item["old_margin"] = float(local_codes[code]) if local_codes[code] is not None else None
            summary["matched"] += 1
            summary["valid"] += 1
        items.append(item)

    return success({
        "headers": list(headers),
        "detected_code_col": detected_code_idx,
        "detected_code_header": str(headers[detected_code_idx]) if detected_code_idx >= 0 else None,
        "detected_margin_col": detected_margin_idx,
        "detected_margin_header": str(headers[detected_margin_idx]) if detected_margin_idx >= 0 else None,
        "summary": summary,
        "items": items[:200],  # 最多预览 200 行
        "items_total": len(items),
    })


@router.post("/import-margin/confirm")
def import_margin_confirm(
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """确认更新净毛利率：接收 [{code, margin_value}, ...] 批量 UPDATE products

    Q1=A 覆盖：默认覆盖已有值
    Q2=A 编码不存在：直接跳过 + 返回失败列表
    """
    from app.models.product import Product
    items = payload.get("items") or []
    if not items:
        return error(10002, "无更新条目")

    updated = 0
    not_found = []
    for it in items:
        code = (it.get("code") or "").strip()
        margin = it.get("margin_value")
        if not code or margin is None:
            continue
        try:
            margin = float(margin)
        except (TypeError, ValueError):
            continue
        if margin <= 0 or margin >= 1:
            continue
        # 按 sku 批量更新（同租户内）
        n = db.query(Product).filter(
            Product.tenant_id == tenant_id, Product.sku == code,
        ).update({"net_margin": margin}, synchronize_session=False)
        if n == 0:
            not_found.append(code)
        else:
            updated += n
    db.commit()
    return success({
        "updated": updated,
        "not_found": not_found,
        "not_found_count": len(not_found),
    })
