"""平台API抽象基类

所有平台(WB/Ozon/Yandex)必须实现此接口。
业务层不直接调用平台API，通过 PlatformClientFactory 获取客户端。
"""

from abc import ABC, abstractmethod
from typing import Optional


class BasePlatformClient(ABC):
    """平台API客户端抽象基类"""

    def __init__(self, shop_id: int, api_key: str, **kwargs):
        self.shop_id = shop_id
        self.api_key = api_key

    @abstractmethod
    async def fetch_products(self, page: int = 1, limit: int = 100) -> dict:
        """拉取商品列表"""
        pass

    @abstractmethod
    async def fetch_ad_campaigns(self) -> list:
        """拉取广告活动"""
        pass

    @abstractmethod
    async def fetch_ad_stats(self, campaign_id: str, date_from: str, date_to: str) -> list:
        """拉取广告统计数据"""
        pass

    @abstractmethod
    async def fetch_orders(self, date_from: str, date_to: str) -> list:
        """拉取订单数据"""
        pass

    @abstractmethod
    async def fetch_inventory(self) -> list:
        """拉取库存数据"""
        pass

    @abstractmethod
    async def test_connection(self) -> bool:
        """测试API连接是否正常"""
        pass


class PlatformClientFactory:
    """平台客户端工厂"""

    _clients = {}

    @classmethod
    def register(cls, platform: str, client_class: type):
        cls._clients[platform] = client_class

    @classmethod
    def get_client(cls, platform: str, shop_id: int, api_key: str, **kwargs) -> BasePlatformClient:
        client_class = cls._clients.get(platform)
        if not client_class:
            # 懒加载：按平台名直接导入对应模块，触发注册
            try:
                import importlib
                importlib.import_module(f"app.services.platform.{platform}")
                client_class = cls._clients.get(platform)
            except ImportError:
                pass
        if not client_class:
            raise ValueError(f"不支持的平台: {platform}")
        return client_class(shop_id=shop_id, api_key=api_key, **kwargs)
