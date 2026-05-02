"""Provider 工厂 — 按 source_shop.platform dispatch

详细规范: docs/api/store_clone.md §2
"""

from sqlalchemy.orm import Session

from app.models.shop import Shop
from .base import BaseShopProvider


def get_provider(db: Session, source_shop: Shop) -> BaseShopProvider:
    """按平台返回对应的 SellerApi Provider 实例

    Phase 1 仅支持 seller_api 类型；Phase 2 公开 API 启用后扩展第二维度
    (source_type='public_api')。
    """
    platform = source_shop.platform

    if platform == "ozon":
        from .ozon import OzonSellerProvider
        return OzonSellerProvider(db, source_shop)

    if platform == "wb":
        from .wb import WBSellerProvider
        return WBSellerProvider(db, source_shop)

    if platform == "yandex":
        from .yandex import YandexSellerProvider
        return YandexSellerProvider(db, source_shop)

    raise ValueError(f"unsupported platform: {platform!r}")
