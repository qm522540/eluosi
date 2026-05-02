"""Provider 抽象层 — BaseShopProvider + ProductSnapshot + factory

详细规范: docs/api/store_clone.md §2

使用：
    from app.services.clone.providers import get_provider
    provider = get_provider(db, source_shop)
    snaps, cursor = await provider.list_products()
"""

from .base import BaseShopProvider, ProductSnapshot
from .factory import get_provider

__all__ = ["BaseShopProvider", "ProductSnapshot", "get_provider"]
