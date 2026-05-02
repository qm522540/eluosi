"""Yandex Seller API Provider — Phase 1 stub

Phase 1 用户拍"先 Ozon 一条路打通,WB/Yandex 接口留 stub"。
Yandex 还在 token 调试阶段 (老张多日 P0 等用户), 实现优先级最低。

实现时参考点:
- YandexClient.fetch_products (app/services/platform/yandex.py:386)
- offerId 作为 source_sku_id

详细规范: docs/api/store_clone.md §2 §11
"""

from typing import Optional, List

from .base import BaseShopProvider, ProductSnapshot


class YandexSellerProvider(BaseShopProvider):
    """Yandex Seller API 实现 — Phase 1 stub"""

    async def list_products(
        self, cursor: Optional[str] = None, limit: int = 100,
    ) -> tuple[List[ProductSnapshot], Optional[str]]:
        raise NotImplementedError(
            "YandexSellerProvider Phase 1 未实现; 等 Yandex token 到位 + Ozon 跑通后启用。"
        )

    async def get_product_detail(self, source_sku_id: str) -> Optional[ProductSnapshot]:
        raise NotImplementedError(
            "YandexSellerProvider Phase 1 未实现; 等 Ozon 跑通后启用。"
        )
