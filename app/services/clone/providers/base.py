"""BaseShopProvider 抽象 + ProductSnapshot dataclass

详细规范: docs/api/store_clone.md §2
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Optional, List

from sqlalchemy.orm import Session

from app.models.shop import Shop


@dataclass
class ProductSnapshot:
    """B 店商品的完整业务快照（provider-agnostic）

    Provider 实现负责把各平台 API 响应转成统一 ProductSnapshot;
    scan_engine / publish_engine 不依赖具体平台 SDK 字段。
    """
    source_platform: str             # wb / ozon / yandex
    source_sku_id: str               # B 平台 SKU (WB nm_id / Ozon offer_id / Yandex offerId)
    title_ru: str
    description_ru: str
    price_rub: Decimal                                            # B 店当前售价 (Ozon API price 字段, 折扣后实付)
    old_price_rub: Optional[Decimal] = None                       # B 店划线原价 (Ozon API old_price; 无折扣 None/0)
    stock: int = 0
    images: List[str] = field(default_factory=list)              # 图片 URL 列表
    platform_category_id: str = ""                                # B 平台分类 ID
    platform_category_name: str = ""
    type_id: str = ""                                              # Ozon 商品类型 ID (description_category 下的子 type, import 必填)
    attributes: List[dict] = field(default_factory=list)         # [{key, value, ...}]
    raw: dict = field(default_factory=dict)                       # 原始 API 响应 (debug)
    detected_at: Optional[datetime] = None                        # utc_now_naive() 由 scan_engine 注入


class BaseShopProvider(ABC):
    """店铺克隆 Provider 抽象。Phase 1 各平台 SellerApi 子类实现。

    强制约定（store_clone.md §2 + §11）：
    - 实现内必须调 app/services/platform/{ozon,wb,yandex}.py 暴露的 *Client
      (OzonClient.fetch_products / WBClient.fetch_products / ...)
    - 不允许自己写 HTTP / httpx 直调，否则绕过 04-24 已修的 quota cooldown 防护
    """

    def __init__(self, db: Session, source_shop: Shop):
        self.db = db
        self.source_shop = source_shop

    @abstractmethod
    async def list_products(
        self, cursor: Optional[str] = None, limit: int = 100,
    ) -> tuple[List[ProductSnapshot], Optional[str]]:
        """列 B 店商品（分页）

        Returns:
            (snapshots, next_cursor)
            - snapshots: 当前批次的 ProductSnapshot 列表
            - next_cursor: 下页游标; None 表示已到尾页

        scan_engine 调用方式:
            cursor = None
            while True:
                snaps, cursor = await provider.list_products(cursor, limit=100)
                # 处理 snaps...
                if not cursor: break
        """

    @abstractmethod
    async def get_product_detail(self, source_sku_id: str) -> Optional[ProductSnapshot]:
        """按 SKU 拉单条详情

        用于 follow_price_change 跟价（实时拿 B 店最新价）。
        失败返 None（上层兜底，不阻断流程）。
        """
