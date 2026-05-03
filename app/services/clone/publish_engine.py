"""店铺克隆上架引擎 — _publish_pending

详细规范: docs/api/store_clone.md §4.2

Phase 1 仅 Ozon 真实上架; WB/Yandex stub。

Ozon /v3/product/import 必填字段:
- depth/width/height (mm) + weight (g) → 优先用 B 店真实值, 没拉到才用 100×100×100mm/100g 占位
- dimension_unit → 'mm', weight_unit → 'g'
- currency_code → 'RUB'
- vat → '0' (默认无 VAT, 用户上架后到 Ozon 后台改)
- barcode (单值) → B 店 barcodes[0]
- 视频 → attr_id=21841 (URL list) + 21837 (封面), 跟 import 一起传, 不用单独 API
"""

import json
import re
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


# ==================== 品牌处理 (migration 064) ====================

# Ozon 通用属性 ID
OZON_ATTR_BRAND = 85          # Бренд (品牌)
OZON_ATTR_NAME = 4180         # Название (商品名)
OZON_ATTR_DESC = 4191         # Аннотация (描述)
OZON_ATTR_VIDEO = 21841       # Видео (视频 URL list, 老板拍 BUG 7)
OZON_ATTR_VIDEO_COVER = 21837 # Обложка видео (视频封面 URL)

# 老板拍 (BUG 5): 克隆时跳过这些 attr — 让 Ozon 后台显示空让用户填.
# 4389 = Страна-производитель (制造国); 4451 = 原产国 (老 attr_id);
# 9024 = 类似. 老板若发现遗漏 attr_id, 加到这个列表即可.
OZON_ATTR_SKIP_ON_CLONE = [4389, 4451, 9024]

# 品牌字典缓存 — 按 (cat_id, type_id) 缓存到 Redis, TTL 1 天 (字典几乎不变)
BRAND_DICT_CACHE_TTL = 86400


def _extract_b_brand(attributes: list) -> Optional[str]:
    """从 B 店 attributes 抽出品牌字符串 (attr_id=85)

    attributes 结构: [{id|attr_id, values: [{value} | str]}, ...]
    返回首个非空值, 没有返 None
    """
    for a in attributes or []:
        try:
            aid = int(a.get("id") or a.get("attr_id") or 0)
        except (TypeError, ValueError):
            continue
        if aid != OZON_ATTR_BRAND:
            continue
        for v in a.get("values") or []:
            val = v.get("value") if isinstance(v, dict) else v
            if val and str(val).strip():
                return str(val).strip()
    return None


def _strip_brand_from_text(text: str, brand: str) -> str:
    """从 title/description 里去除指定品牌名字符串 (大小写不敏感)

    - re.escape 防 brand 含正则特殊字符 (Pt.Girl 的点)
    - 不强制 \\b 词边界, 因为俄/英混排时 \\b 对 Cyrillic 不可靠
    - 多空格清理
    """
    if not text or not brand:
        return text
    pattern = re.compile(re.escape(brand), re.IGNORECASE)
    cleaned = pattern.sub("", text)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    cleaned = re.sub(r"^[\s,;:.\-—–·]+", "", cleaned).strip()
    return cleaned


async def _resolve_brand_dictionary_id(
    client, description_category_id: int, type_id: int, target_brand: str,
) -> Optional[int]:
    """老板拍 BUG 3 v2: target_brand 改 attr_id=85 时反查 Ozon 品牌字典 ID,
    case-insensitive 匹配, 命中返 dictionary_value_id, 没命中返 None.

    Redis 缓存 (key: ozon:brand_dict:{cat}:{type}, TTL 1 天) 避免每次 publish 都拉.
    Ozon 品牌字典几千几万级, 缓存命中后字符串匹配 O(N) 也能在 ms 级.
    """
    if not target_brand:
        return None
    target_lower = target_brand.lower().strip()
    cache_key = f"ozon:brand_dict:{description_category_id}:{type_id}"

    # 1) 查 Redis 缓存
    redis_client = None
    try:
        from app.services.platform.wb import _get_redis_client
        redis_client = _get_redis_client()
        raw = redis_client.get(cache_key)
        if raw:
            try:
                cached = json.loads(raw)
                for entry in cached:
                    if str(entry.get("value", "")).lower().strip() == target_lower:
                        return int(entry["id"])
                logger.info(
                    f"brand_dict 缓存命中但未找到 '{target_brand}' "
                    f"(cat={description_category_id} type={type_id}, {len(cached)} entries)"
                )
                return None
            except Exception as e:
                logger.warning(f"brand_dict 缓存解析失败: {e}, 重拉")
    except Exception as e:
        logger.warning(f"brand_dict 读 Redis 失败: {e}, 跳过缓存直拉")

    # 2) 调 Ozon 拉品牌字典 (attribute_id=85)
    try:
        values = await client.fetch_attribute_values(
            description_category_id, type_id, OZON_ATTR_BRAND, limit=500,
        )
    except Exception as e:
        logger.error(
            f"_resolve_brand_dictionary_id 拉字典失败 cat={description_category_id} "
            f"type={type_id}: {e}"
        )
        return None

    if not values:
        logger.warning(
            f"Ozon 品牌字典空 cat={description_category_id} type={type_id}"
        )
        return None

    # 3) 写回 Redis
    if redis_client is not None:
        try:
            cache_data = [{"id": v.get("id"), "value": v.get("value")}
                          for v in values if v.get("id") and v.get("value")]
            redis_client.setex(cache_key, BRAND_DICT_CACHE_TTL, json.dumps(cache_data))
            logger.info(
                f"brand_dict 缓存写入 cat={description_category_id} type={type_id} "
                f"size={len(cache_data)}"
            )
        except Exception as e:
            logger.warning(f"brand_dict 写 Redis 失败: {e}")

    # 4) case-insensitive 匹配
    for v in values:
        if str(v.get("value", "")).lower().strip() == target_lower:
            return int(v.get("id") or 0) or None
    logger.warning(
        f"Ozon 品牌字典无 '{target_brand}' (cat={description_category_id} type={type_id}); "
        f"将保留 B 店原品牌. 老板可在 Ozon 后台先添加该品牌再克隆."
    )
    return None


def _override_brand_in_attributes(attributes: list, target_brand: str) -> list:
    """把 attributes 里的 attr_id=85 (Бренд) 强制覆盖为 target_brand;
    若 attributes 不含 attr_id=85, 主动追加一条
    """
    out = []
    found = False
    for a in attributes:
        try:
            aid = int(a.get("id") or 0)
        except (TypeError, ValueError):
            out.append(a)
            continue
        if aid == OZON_ATTR_BRAND:
            out.append({"id": OZON_ATTR_BRAND, "values": [{"value": target_brand}]})
            found = True
        else:
            out.append(a)
    if not found:
        out.append({"id": OZON_ATTR_BRAND, "values": [{"value": target_brand}]})
    return out


# ==================== Ozon 上架 ====================

async def _publish_to_ozon(
    target_shop: Shop, payload: dict,
    source_offer_id: Optional[str] = None,
    target_brand: Optional[str] = None,
) -> dict:
    """调 Ozon /v3/product/import 异步上架

    Returns: {"code": 0, "data": {"task_id": ..., "offer_id": ...}}
            或 {"code": <err>, "msg": ...}

    Ozon import 是异步任务: 返回 task_id 后用户上架可能需 1-5 分钟生效。
    我们记 task_id 到日志, 真 platform_sku_id 通过下次 sync_products 回填。
    """
    from app.services.platform.ozon import OzonClient, OZON_SELLER_API

    client = OzonClient(
        shop_id=target_shop.id,
        api_key=target_shop.api_key,
        client_id=target_shop.client_id,
        perf_client_id=target_shop.perf_client_id or "",
        perf_client_secret=target_shop.perf_client_secret or "",
    )

    # offer_id 策略 (migration 064 后):
    #   1. 优先用 source_offer_id (B 店原 offer_id) — 老板要求"本地编码默认一样"
    #   2. 没传或冲突时降级 clone-{uuid} (Ozon 接受任意字符串作商家 SKU)
    # Ozon offer_id 是 per-shop unique, A/B 不同店复用 B 店 offer_id 不冲突
    new_offer_id = (source_offer_id or "").strip() or f"clone-{uuid.uuid4().hex[:12]}"

    title = (payload.get("title_ru") or "").strip()[:500]
    description = (payload.get("description_ru") or "").strip()[:6000]
    images = payload.get("images_oss") or []
    price = float(payload.get("price_rub") or 0)
    # 老板拍: 折扣价 — 用户在编辑 Modal 配; 没配则等于平台价 (无折扣展示)
    discount_raw = payload.get("discount_price_rub")
    try:
        discount_price = float(discount_raw) if discount_raw not in (None, "", 0) else 0.0
    except (TypeError, ValueError):
        discount_price = 0.0
    cat_id = payload.get("platform_category_id")
    type_id_raw = payload.get("type_id") or ""
    try:
        type_id = int(type_id_raw) if type_id_raw else 0
    except (TypeError, ValueError):
        type_id = 0
    if not (title and cat_id and price > 0):
        return {"code": ErrorCode.CLONE_PUBLISH_FAILED,
                "msg": "缺必填字段 (title / category_id / price)"}
    if type_id <= 0:
        return {"code": ErrorCode.CLONE_PUBLISH_FAILED,
                "msg": "缺 type_id (Ozon /v3/product/import 必填) — 旧版 scan 未采集, 见 publish_engine fallback 反查"}

    # 把 attributes (B 店原属性) 透传 — Ozon import 接受 [{id, complex_id, values:[...]}, ...]
    # 修 BUG (老板 2026-05-03 21 时报): 字典型属性 (品牌/HS/原产国/材料) 必须保留
    # dictionary_value_id, 只传 value 字符串会被 Ozon 当成"未选择"显示红框.
    attributes = []
    src_attrs = payload.get("attributes") or []
    for a in src_attrs:
        try:
            attr_id = int(a.get("id") or a.get("attr_id") or 0)
        except (TypeError, ValueError):
            continue
        if not attr_id:
            continue
        # 老板拍 BUG 5: 跳过克隆时不该透传的 attr (原产国等)
        if attr_id in OZON_ATTR_SKIP_ON_CLONE:
            continue
        # complex_id 用于多层嵌套属性 (尺码/颜色组合等), 顶层透传
        try:
            complex_id = int(a.get("complex_id") or 0)
        except (TypeError, ValueError):
            complex_id = 0
        values = a.get("values") or []
        normalized_vals = []
        for v in values:
            if isinstance(v, dict):
                nv = {}
                # 字典 ID 优先 — 这是修 BUG 关键: Ozon 字典型属性必须有 ID
                if v.get("dictionary_value_id"):
                    try:
                        nv["dictionary_value_id"] = int(v["dictionary_value_id"])
                    except (TypeError, ValueError):
                        pass
                if v.get("value") is not None:
                    nv["value"] = str(v["value"])
                if nv:
                    normalized_vals.append(nv)
            else:
                normalized_vals.append({"value": str(v)})
        if normalized_vals:
            entry = {"id": attr_id, "values": normalized_vals}
            if complex_id:
                entry["complex_id"] = complex_id
            attributes.append(entry)

    # migration 064 v3 (老板 BUG 3): target_brand 真换品牌 — 反查 Ozon 品牌字典
    # 拿 dictionary_value_id, 命中才覆盖 attr_id=85; 未命中保留 B 店原品牌 + 警告
    b_brand = _extract_b_brand(attributes)
    if target_brand and b_brand and b_brand.lower() != target_brand.lower():
        title = _strip_brand_from_text(title, b_brand)
        description = _strip_brand_from_text(description, b_brand)
    if target_brand:
        try:
            brand_dict_id = await _resolve_brand_dictionary_id(
                client, int(cat_id), int(type_id), target_brand,
            )
        except Exception as e:
            logger.error(f"resolve_brand_dictionary_id 异常 brand={target_brand}: {e}")
            brand_dict_id = None
        if brand_dict_id:
            # 覆盖 attr_id=85 — 同时给 dictionary_value_id 和 value, Ozon 才接受
            attributes = [a for a in attributes if a.get("id") != OZON_ATTR_BRAND]
            attributes.append({
                "id": OZON_ATTR_BRAND,
                "values": [{"dictionary_value_id": brand_dict_id, "value": target_brand}],
            })
            logger.info(
                f"target_brand 替换成功 offer={new_offer_id} brand={target_brand} "
                f"dict_id={brand_dict_id}"
            )
        else:
            logger.warning(
                f"target_brand 替换跳过 offer={new_offer_id} — "
                f"'{target_brand}' 不在 Ozon 品牌字典 (cat={cat_id} type={type_id}); "
                f"保留 B 店原品牌. 老板可在 Ozon 后台先注册品牌再克隆."
            )

    # 必填属性兜底 (4180 名称, 4191 描述; Ozon import 不要求重复传, 但显式传更稳)
    # 用最终处理过的 title/description, 不是原始 payload 的
    attributes = [a for a in attributes if a["id"] not in (OZON_ATTR_NAME, OZON_ATTR_DESC)]
    attributes.append({"id": OZON_ATTR_NAME, "values": [{"value": title}]})
    if description:
        attributes.append({"id": OZON_ATTR_DESC, "values": [{"value": description}]})

    # 视频 (BUG 7) — Ozon 视频是 attribute 形式 (attr_id=21841 视频/21837 封面),
    # 跟 import 一起传, 不需要单独 API. 老板拍"一起做好" 2026-05-03 凌晨.
    # B 店 attributes 透传时可能已含 21841/21837, 这里覆盖以确保用我们采集到的最新值.
    src_videos = payload.get("videos") or []
    src_video_cover = (payload.get("video_cover") or "").strip()
    if src_videos:
        attributes = [a for a in attributes if a["id"] != OZON_ATTR_VIDEO]
        # Ozon 视频 attribute 接受多 value, 每个 value 一个 URL
        attributes.append({
            "id": OZON_ATTR_VIDEO,
            "values": [{"value": str(v)} for v in src_videos if v],
        })
        logger.info(f"publish offer={new_offer_id} 视频塞 import: {len(src_videos)} 个")
    if src_video_cover:
        attributes = [a for a in attributes if a["id"] != OZON_ATTR_VIDEO_COVER]
        attributes.append({
            "id": OZON_ATTR_VIDEO_COVER,
            "values": [{"value": src_video_cover}],
        })

    # 物流字段 — 修 BUG (老板 2026-05-03): 之前 hardcode 100×100×100 + 100g 占位
    # 现在从 payload 拿 B 店真实值, 没拉到才用占位 + WARN 日志
    def _int_or(v, default):
        try:
            n = int(v) if v not in (None, "", 0) else 0
            return n if n > 0 else default
        except (TypeError, ValueError):
            return default

    depth_mm = _int_or(payload.get("depth_mm"), 100)
    width_mm = _int_or(payload.get("width_mm"), 100)
    height_mm = _int_or(payload.get("height_mm"), 100)
    weight_g = _int_or(payload.get("weight_g"), 100)
    barcode = (payload.get("barcode") or "").strip()
    if not (payload.get("depth_mm") and payload.get("width_mm")
            and payload.get("height_mm") and payload.get("weight_g")):
        logger.warning(
            f"publish offer={new_offer_id}: B 店缺尺寸/重量, 用占位 "
            f"{depth_mm}×{width_mm}×{height_mm}mm / {weight_g}g (用户需到 Ozon 后台补全)"
        )

    item = {
        "offer_id": new_offer_id,
        "name": title,
        "description_category_id": int(cat_id),
        "type_id": type_id,              # 必填, 见上方 type_id_raw 校验
        # Ozon 语义: price = 当前售价 (实付), old_price = 划线价 (原价显示)
        # 没配折扣 → price = old_price = 平台价, 无划线
        # 配了折扣 (0 < discount < price) → price = 折扣价, old_price = 平台价
        "price": str(discount_price if 0 < discount_price < price else price),
        "old_price": str(price),
        "vat": "0",                      # 占位, 用户后台改
        "currency_code": "RUB",
        "images": images[:15],           # Ozon 限制最多 15 张
        # 物流字段 — 从 payload 取 B 店真实数据, 兜底占位
        "depth": depth_mm,
        "width": width_mm,
        "height": height_mm,
        "dimension_unit": "mm",
        "weight": weight_g,
        "weight_unit": "g",
        "attributes": attributes,
    }
    # 条形码 — Ozon import 接受 barcode 字段 (单值, 不是数组)
    if barcode:
        item["barcode"] = barcode

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

    # type_id fallback: 兼容旧版 scan 未采集 type_id 的现有 pending
    # 调 source_shop 的 Ozon API 现拉 type_id, 写回 proposed_payload
    if not payload.get("type_id") and target_shop.platform == "ozon":
        source_shop = db.query(Shop).filter(Shop.id == task.source_shop_id).first()
        if source_shop and source_shop.platform == "ozon":
            try:
                from app.services.platform.ozon import OzonClient, OZON_SELLER_API
                sclient = OzonClient(
                    shop_id=source_shop.id,
                    api_key=source_shop.api_key,
                    client_id=source_shop.client_id,
                    perf_client_id=source_shop.perf_client_id or "",
                    perf_client_secret=source_shop.perf_client_secret or "",
                )
                src_url = f"{OZON_SELLER_API}/v3/product/info/list"
                src_r = await sclient._request("POST", src_url, json={
                    "offer_id": [pending.source_sku_id], "product_id": [], "sku": [],
                })
                src_items = (src_r or {}).get("result", {}).get("items") or src_r.get("items", [])
                if src_items:
                    src_type_id = src_items[0].get("type_id")
                    if src_type_id:
                        payload = {**payload, "type_id": str(src_type_id)}
                        pending.proposed_payload = payload
                        db.commit()
                        logger.info(f"type_id fallback 反查成功 pending={pending.id}: {src_type_id}")
            except Exception as e:
                logger.error(f"type_id fallback 反查失败 pending={pending.id}: {e}")

    # 草稿期 images_oss 是 B 店原图 URL, 这里下载到 OSS 后写回
    # (扫描不下图: 否则 385 件全量 × 串行 25s/件 = 2.5h, 同步触发必 timeout;
    #  被拒商品也省 OSS 流量。审核期 review 用 source URL 显示完全可用)
    source_images = payload.get("images_oss") or []
    if source_images:
        try:
            from app.utils.oss_client import download_images_batch
            prefix = f"clone/{tenant_id}/{task.id}/{pending.source_sku_id}"
            oss_urls = await download_images_batch(source_images, prefix)
            if oss_urls:
                payload = {**payload, "images_oss": oss_urls}
                pending.proposed_payload = payload
                db.commit()
        except Exception as e:
            logger.error(
                f"OSS 下图失败 pending={pending.id}: {e}, fallback 用 source URL"
            )
            # source URL 给 Ozon 也能过, 只是审核期 B 店改图会失效

    # 按平台 dispatch
    if target_shop.platform == "ozon":
        # 老板拍: A 店 offer_id 优先用 payload.target_sku (preview 行可改),
        # 缺省回退 pending.source_sku_id (= B 店 offer_id, "本地编码默认一样")
        a_shop_sku = (payload.get("target_sku") or pending.source_sku_id or "").strip()
        r = await _publish_to_ozon(
            target_shop, payload,
            source_offer_id=a_shop_sku,                   # 实际是 A 店 offer_id, 命名延续旧参数
            target_brand=(task.target_brand or None),     # migration 064: 品牌替换
        )
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
            listing.publish_status = "published"  # 修小瑕疵: publish 成功后字段语义对齐
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
