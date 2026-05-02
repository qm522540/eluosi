"""店铺克隆上架引擎 — _publish_pending

详细规范: docs/api/store_clone.md §4.2

Phase 1 仅 Ozon 真实上架; WB/Yandex stub。

Ozon /v3/product/import 必填字段 (B 店 ProductSnapshot 缺的, 用合理占位):
- depth/width/height (商品尺寸 mm) → 默认 100x100x100
- weight + weight_unit (重量) → 默认 100g
- dimension_unit → 'mm'
- currency_code → 'RUB'
- vat → '0' (默认无 VAT, 用户上架后到 Ozon 后台改)

用户上架后必须到 Ozon 后台补全 dimensions/weight, 否则 Ozon 会下架。
"""

import uuid
from typing import Optional

from sqlalchemy.orm import Session

from app.models.clone import (
    CloneTask, ClonePendingProduct, CloneLog, ClonePublishedLink,
)
from app.models.product import Product, PlatformListing
from app.models.shop import Shop
from app.utils.errors import ErrorCode
from app.utils.logger import setup_logger
from app.utils.moscow_time import utc_now_naive

logger = setup_logger("clone.publish_engine")


# ==================== Ozon 上架 ====================

async def _publish_to_ozon(target_shop: Shop, payload: dict) -> dict:
    """调 Ozon /v3/product/import 异步上架

    Returns: {"code": 0, "data": {"task_id": ..., "offer_id": ...}}
            或 {"code": <err>, "msg": ...}

    Ozon import 是异步任务: 返回 task_id 后用户上架可能需 1-5 分钟生效。
    我们记 task_id 到日志, 真 platform_sku_id 通过下次 sync_products 回填。
    """
    from app.services.platform.ozon import OzonClient, OZON_SELLER_API

    client = OzonClient(target_shop)

    # 新 offer_id (我们生成, Ozon 接受任意字符串作商家 SKU)
    new_offer_id = f"clone-{uuid.uuid4().hex[:12]}"

    title = (payload.get("title_ru") or "").strip()[:500]
    description = (payload.get("description_ru") or "").strip()[:6000]
    images = payload.get("images_oss") or []
    price = float(payload.get("price_rub") or 0)
    cat_id = payload.get("platform_category_id")
    if not (title and cat_id and price > 0):
        return {"code": ErrorCode.CLONE_PUBLISH_FAILED,
                "msg": "缺必填字段 (title / category_id / price)"}

    # 把 attributes (B 店原属性) 透传 — Ozon import 接受 [{id, values:[{value}]}, ...]
    attributes = []
    src_attrs = payload.get("attributes") or []
    for a in src_attrs:
        try:
            attr_id = int(a.get("id") or a.get("attr_id") or 0)
        except (TypeError, ValueError):
            continue
        if not attr_id:
            continue
        values = a.get("values") or []
        # values 可能是 [{value}] 或 [str]
        normalized_vals = []
        for v in values:
            if isinstance(v, dict):
                if v.get("value") is not None:
                    normalized_vals.append({"value": str(v["value"])})
            else:
                normalized_vals.append({"value": str(v)})
        if normalized_vals:
            attributes.append({"id": attr_id, "values": normalized_vals})

    # 必填属性兜底 (4180 名称, 4191 描述; Ozon import 不要求重复传, 但显式传更稳)
    if not any(a["id"] == 4180 for a in attributes):
        attributes.append({"id": 4180, "values": [{"value": title}]})
    if description and not any(a["id"] == 4191 for a in attributes):
        attributes.append({"id": 4191, "values": [{"value": description}]})

    item = {
        "offer_id": new_offer_id,
        "name": title,
        "description_category_id": int(cat_id),
        "price": str(price),
        "old_price": str(price),
        "vat": "0",                      # 占位, 用户后台改
        "currency_code": "RUB",
        "images": images[:15],           # Ozon 限制最多 15 张
        # 尺寸/重量占位 (用户必须到 Ozon 后台补全)
        "depth": 100, "width": 100, "height": 100, "dimension_unit": "mm",
        "weight": 100, "weight_unit": "g",
        "attributes": attributes,
    }

    try:
        url = f"{OZON_SELLER_API}/v3/product/import"
        result = await client._request("POST", url, json={"items": [item]})
    except Exception as e:
        logger.error(f"Ozon import 调用失败 shop={target_shop.id}: {e}")
        return {"code": ErrorCode.CLONE_PUBLISH_FAILED,
                "msg": f"Ozon import 调用失败: {str(e)[:200]}"}

    task_id_resp = (result or {}).get("result", {}).get("task_id") or (result or {}).get("task_id")
    if not task_id_resp:
        return {"code": ErrorCode.CLONE_PUBLISH_FAILED,
                "msg": f"Ozon 未返 task_id: {str(result)[:300]}"}

    return {"code": 0, "data": {
        "task_id": task_id_resp,
        "offer_id": new_offer_id,
    }}


# ==================== 主入口 ====================

async def _publish_pending(db: Session, pending_id: int) -> dict:
    """把 status='approved' 的 pending 推到 A 店上架

    被 clone-publish-pending Beat 每 5 分钟扫一次调用。
    """
    pending = db.query(ClonePendingProduct).filter(
        ClonePendingProduct.id == pending_id,
    ).first()
    if not pending:
        return {"code": ErrorCode.CLONE_PENDING_NOT_FOUND, "msg": "待审核记录不存在"}
    if pending.status != "approved":
        return {"code": ErrorCode.CLONE_PENDING_INVALID_STATUS,
                "msg": f"当前状态 {pending.status} 不允许 publish"}

    tenant_id = pending.tenant_id
    task = db.query(CloneTask).filter(
        CloneTask.id == pending.task_id, CloneTask.tenant_id == tenant_id,
    ).first()
    if not task:
        return {"code": ErrorCode.CLONE_TASK_NOT_FOUND, "msg": "克隆任务不存在"}

    target_shop = db.query(Shop).filter(Shop.id == task.target_shop_id).first()
    if not target_shop:
        return {"code": ErrorCode.SHOP_NOT_FOUND, "msg": "目标店铺不存在"}

    t0 = utc_now_naive()
    payload = pending.proposed_payload or {}

    # 按平台 dispatch
    if target_shop.platform == "ozon":
        r = await _publish_to_ozon(target_shop, payload)
    elif target_shop.platform == "wb":
        r = {"code": ErrorCode.CLONE_PUBLISH_FAILED,
             "msg": "WB 上架 Phase 1 未实现"}
    elif target_shop.platform == "yandex":
        r = {"code": ErrorCode.CLONE_PUBLISH_FAILED,
             "msg": "Yandex 上架 Phase 1 未实现"}
    else:
        r = {"code": ErrorCode.CLONE_PUBLISH_FAILED,
             "msg": f"未知平台 {target_shop.platform}"}

    duration_ms = int((utc_now_naive() - t0).total_seconds() * 1000)

    if r["code"] != 0:
        # 失败: pending 标 failed, 写日志
        pending.status = "failed"
        pending.publish_error_msg = r.get("msg", "")[:500]
        db.commit()
        db.add(CloneLog(
            tenant_id=tenant_id, task_id=task.id,
            log_type="publish", status="failed",
            duration_ms=duration_ms,
            detail={"pending_id": pending_id, "error_msg": r.get("msg")},
            error_msg=r.get("msg", "")[:500],
        ))
        db.commit()
        return r

    # 成功
    new_offer_id = r["data"]["offer_id"]
    task_id_resp = r["data"]["task_id"]

    # 1) 草稿 listing 转 active + 回填真实 SKU (但 Ozon import 是异步, 真 platform_product_id
    #    需要下次 sync_products 才回填; 我们先标 active + offer_id 占位)
    if pending.draft_listing_id:
        listing = db.query(PlatformListing).filter(
            PlatformListing.id == pending.draft_listing_id,
            PlatformListing.tenant_id == tenant_id,
        ).first()
        if listing:
            listing.status = "active"
            listing.platform_sku_id = new_offer_id
            if listing.product_id:
                product = db.query(Product).filter(
                    Product.id == listing.product_id,
                    Product.tenant_id == tenant_id,
                ).first()
                if product:
                    product.status = "active"
                    product.sku = new_offer_id

    # 2) pending 标 published
    pending.status = "published"
    pending.published_at = utc_now_naive()
    pending.target_platform_sku_id = new_offer_id

    # 3) clone_published_links INSERT
    link = ClonePublishedLink(
        tenant_id=tenant_id,
        task_id=task.id,
        pending_id=pending.id,
        source_platform=pending.source_platform,
        source_sku_id=pending.source_sku_id,
        target_shop_id=task.target_shop_id,
        target_platform_sku_id=new_offer_id,
        target_listing_id=pending.draft_listing_id,
        last_synced_price=payload.get("price_rub"),
        last_synced_at=utc_now_naive(),
        published_at=utc_now_naive(),
    )
    db.add(link)

    # 4) 写日志
    db.add(CloneLog(
        tenant_id=tenant_id, task_id=task.id,
        log_type="publish", status="success",
        rows_affected=1,
        duration_ms=duration_ms,
        detail={
            "pending_id": pending_id,
            "target_platform_sku_id": new_offer_id,
            "ozon_import_task_id": task_id_resp,
        },
    ))
    db.commit()

    return {"code": 0, "data": {
        "id": pending.id, "status": "published",
        "target_platform_sku_id": new_offer_id,
        "ozon_import_task_id": task_id_resp,
    }}
