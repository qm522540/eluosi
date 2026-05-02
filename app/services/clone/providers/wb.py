"""WB Seller API Provider — Phase 1 stub

Phase 1 用户拍"先 Ozon 一条路打通,WB/Yandex 接口留 stub"。
等 Ozon 跑通 + 真实场景验过后再实现。

实现时参考点:
- WBClient.fetch_products (app/services/platform/wb.py:1170)
- 04-24 已修的 WBSellerQuotaExhausted 防护必须经 _request 自动生效
- nm_id 作为 source_sku_id (B 平台 SKU)
- 描述/属性走另外的 cards/v2/detail 等接口

详细规范: docs/api/store_clone.md §2 §11
"""

from typing import Optional, List

from .base import BaseShopProvider, ProductSnapshot


class WBSellerProvider(BaseShopProvider):
    """WB Seller API 实现 — Phase 1 stub"""

    async def list_products(
        self, cursor: Optional[str] = None, limit: int = 100,
    ) -> tuple[List[ProductSnapshot], Optional[str]]:
        raise NotImplementedError(
            "WBSellerProvider Phase 1 未实现; 等 Ozon 跑通后启用。"
            "实现请走 WBClient.fetch_products + cards/v2/detail。"
        )

    async def get_product_detail(self, source_sku_id: str) -> Optional[ProductSnapshot]:
        raise NotImplementedError(
            "WBSellerProvider Phase 1 未实现; 等 Ozon 跑通后启用。"
        )
