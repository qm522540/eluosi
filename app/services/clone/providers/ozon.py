"""Ozon Seller API Provider — Phase 1 实现

走 OzonClient.fetch_products / fetch_product_info / fetch_product_descriptions_batch /
fetch_product_attributes_batch (强制约定: 不绕路自己写 HTTP)。

Ozon 上"上新"的判定: 不在 Provider 层做时间过滤 (API 不支持 since), 全量分页拉,
靠 scan_engine 的 UNIQUE KEY (task_id, source_sku_id) 自然防重 + DB 比对识别新商品。

详细规范: docs/api/store_clone.md §2 §4.1
"""

from decimal import Decimal
from typing import Optional, List

from app.services.platform.ozon import OzonClient
from app.utils.logger import setup_logger

from .base import BaseShopProvider, ProductSnapshot

logger = setup_logger("clone.providers.ozon")


def _to_decimal(value) -> Decimal:
    """Ozon price 字段是字符串 (如 "2400.00"), 转 Decimal 兜底。"""
    if value in (None, "", "0", "0.00"):
        return Decimal("0")
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal("0")


def _aggregate_stock(p: dict) -> int:
    """Ozon info.stocks.stocks[].present 聚合所有仓 (fbo/fbs)。"""
    stocks_obj = p.get("stocks") or {}
    stocks_list = stocks_obj.get("stocks") or []
    return sum(
        int(s.get("present") or 0)
        for s in stocks_list
        if isinstance(s, dict)
    )


class OzonSellerProvider(BaseShopProvider):
    """Ozon Seller API 实现"""

    def __init__(self, db, source_shop):
        super().__init__(db, source_shop)
        self._client: Optional[OzonClient] = None

    def _get_client(self) -> OzonClient:
        if self._client is None:
            shop = self.source_shop
            self._client = OzonClient(
                shop_id=shop.id,
                api_key=shop.api_key,
                client_id=shop.client_id,
                perf_client_id=shop.perf_client_id or "",
                perf_client_secret=shop.perf_client_secret or "",
            )
        return self._client

    async def list_products(
        self, cursor: Optional[str] = None, limit: int = 100,
    ) -> tuple[List[ProductSnapshot], Optional[str]]:
        """分页拉 B 店商品

        流程:
        1. fetch_products(last_id=cursor, limit) → product_id 列表 + next_cursor
        2. fetch_product_info(product_ids)        → 批量详情 (name/price/images/...)
        3. fetch_product_descriptions_batch       → 批量描述
        4. fetch_product_attributes_batch         → 批量属性
        5. 组装 ProductSnapshot
        """
        client = self._get_client()
        try:
            raw = await client.fetch_products(last_id=cursor or "", limit=limit)
        except Exception as e:
            logger.error(
                f"Ozon list_products 失败 shop_id={self.source_shop.id} "
                f"cursor={cursor!r}: {e}"
            )
            raise

        result = (raw or {}).get("result") or {}
        items = result.get("items") or []
        next_cursor = result.get("last_id") or None

        if not items:
            return [], None

        product_ids = [int(it["product_id"]) for it in items if it.get("product_id")]
        if not product_ids:
            return [], next_cursor

        # 批量并行拉 info / desc / attrs
        try:
            info_list = await client.fetch_product_info(product_ids)
        except Exception as e:
            logger.error(f"Ozon fetch_product_info 失败 shop_id={self.source_shop.id}: {e}")
            return [], next_cursor

        descriptions = await client.fetch_product_descriptions_batch(product_ids)
        attributes_map = await client.fetch_product_attributes_batch(product_ids)

        info_map = {int(it.get("id") or it.get("product_id") or 0): it for it in info_list}

        snapshots: List[ProductSnapshot] = []
        for pid in product_ids:
            info = info_map.get(pid) or {}
            offer_id = str(info.get("offer_id") or "")
            if not offer_id:
                logger.warning(f"Ozon product_id={pid} 缺 offer_id, 跳过")
                continue

            desc_cat_id = info.get("description_category_id")
            platform_category_id = str(desc_cat_id) if desc_cat_id else ""

            images = info.get("images") or []
            # 部分 Ozon 商品 primary_image 是 list, 取首个并去重塞 images 头
            primary = info.get("primary_image")
            if isinstance(primary, list):
                primary = primary[0] if primary else None
            if primary and primary not in images:
                images = [primary] + list(images)

            snapshots.append(ProductSnapshot(
                source_platform="ozon",
                source_sku_id=offer_id,             # Ozon 用 offer_id 作 B 平台 SKU
                title_ru=(info.get("name") or "")[:500],
                description_ru=descriptions.get(pid, "") or "",
                price_rub=_to_decimal(info.get("price")),
                stock=_aggregate_stock(info),
                images=images,
                platform_category_id=platform_category_id,
                platform_category_name="",          # info/list 不返, scan_engine 走 028 反查
                attributes=attributes_map.get(pid) or [],
                raw=info,
            ))

        return snapshots, next_cursor

    async def get_product_detail(self, source_sku_id: str) -> Optional[ProductSnapshot]:
        """按 offer_id 拉单条详情

        Ozon API 没有"按 offer_id 直查"的稳定路径, 走 fetch_product_info 传 offer_id 列表。
        失败返 None (上层兜底)。
        """
        client = self._get_client()
        try:
            # fetch_product_info 接受 product_id list, 但底层 v3/info/list 也支持 offer_id
            # 直接走 _request 兜过去
            from app.services.platform.ozon import OZON_SELLER_API
            url = f"{OZON_SELLER_API}/v3/product/info/list"
            payload = {"offer_id": [str(source_sku_id)], "product_id": [], "sku": []}
            raw = await client._request("POST", url, json=payload)
            items = (raw or {}).get("result", {}).get("items") or raw.get("items") or []
            if not items:
                return None
            info = items[0]
        except Exception as e:
            logger.error(
                f"Ozon get_product_detail 失败 shop_id={self.source_shop.id} "
                f"sku={source_sku_id!r}: {e}"
            )
            return None

        pid = info.get("id") or info.get("product_id")
        if not pid:
            return None

        descriptions = await client.fetch_product_descriptions_batch([int(pid)])
        attributes_map = await client.fetch_product_attributes_batch([int(pid)])

        images = info.get("images") or []
        primary = info.get("primary_image")
        if isinstance(primary, list):
            primary = primary[0] if primary else None
        if primary and primary not in images:
            images = [primary] + list(images)

        return ProductSnapshot(
            source_platform="ozon",
            source_sku_id=str(info.get("offer_id") or source_sku_id),
            title_ru=(info.get("name") or "")[:500],
            description_ru=descriptions.get(int(pid), "") or "",
            price_rub=_to_decimal(info.get("price")),
            stock=_aggregate_stock(info),
            images=images,
            platform_category_id=str(info.get("description_category_id") or ""),
            platform_category_name="",
            attributes=attributes_map.get(int(pid)) or [],
            raw=info,
        )
