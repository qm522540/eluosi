"""BaseReviewProvider 抽象 + ReviewSnapshot dataclass

照老林 store_clone provider 模式 (app/services/clone/providers/base.py).
Provider 实现把各平台评价 API 响应转成统一 ReviewSnapshot;
service / api 层不依赖具体平台 SDK 字段。

强制约定 (跟 store_clone 规则 §11 同):
- 实现内必须调 app/services/platform/{wb,ozon}.py 暴露的 *Client
  (新增方法 WBClient.fetch_feedbacks / OzonClient.fetch_reviews 等)
- 不允许自己写 HTTP / httpx 直调, 否则绕过 04-24 已修的 quota cooldown 防护
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List

from sqlalchemy.orm import Session

from app.models.shop import Shop


@dataclass
class ReviewSnapshot:
    """平台评价的统一快照 (provider-agnostic)

    字段对照 (WB ↔ Ozon, 详见 docs/api/reviews.md §字段映射):
    - WB GET /api/v1/feedbacks 返 productValuation / text / userName / productDetails.nmId
    - Ozon POST /v1/review/list 返 rating / comment / sku (无 userName)
    """
    source_platform: str                # wb / ozon
    platform_review_id: str             # WB feedback.id / Ozon review.id (UUID)
    rating: int                         # 1-5 星
    content_ru: str                     # 买家原文 (WB text / Ozon comment)
    customer_name: str = ""             # WB userName / Ozon 不返 → 留空
    platform_sku_id: str = ""           # WB productDetails.nmId / Ozon sku
    platform_product_name: str = ""     # WB productDetails.productName / Ozon (要二次拉)
    created_at_platform: Optional[datetime] = None  # 平台时间戳 (UTC naive)
    # 平台已有的回复 (WB feedback.answer / Ozon review.comment/list 后单独回填)
    existing_reply_ru: str = ""
    existing_reply_at: Optional[datetime] = None
    # 平台标记的处理状态 (WB isAnswered / Ozon status UNPROCESSED|PROCESSED)
    is_answered: bool = False
    raw: dict = field(default_factory=dict)   # 原始 API 响应 (debug + 后续字段扩展)


class BaseReviewProvider(ABC):
    """店铺评价 Provider 抽象

    Phase 1 子类: WBReviewProvider / OzonReviewProvider
    Phase 4 兜底: YandexReviewProvider (待 Yandex 评价 API 决策)
    """

    def __init__(self, db: Session, shop: Shop):
        self.db = db
        self.shop = shop

    @abstractmethod
    async def list_reviews(
        self,
        only_unanswered: bool = True,
        cursor: Optional[str] = None,
        limit: int = 100,
    ) -> tuple[List[ReviewSnapshot], Optional[str]]:
        """拉评价列表 (分页)

        Args:
            only_unanswered: True 只拉未回复的 (默认, 增量同步用),
                             False 拉全部 (首次初始化或对账)
            cursor: 平台分页游标 (WB 用 skip 偏移, Ozon 用 last_id)
            limit: 每页条数

        Returns:
            (snapshots, next_cursor)
            - next_cursor=None 表示已到尾页
        """

    @abstractmethod
    async def post_reply(
        self, platform_review_id: str, reply_ru: str,
    ) -> dict:
        """对单条评价发送俄语回复

        Returns:
            {"ok": True/False, "msg": "...", "platform_status": "..."}
            失败时 ok=False, msg 含 API 真错原因 (透传给前端)
        """

    @abstractmethod
    async def mark_read(self, platform_review_id: str) -> dict:
        """标已读 (Ozon: change-status; WB: 回复后自动 isAnswered=true 不需调)

        WB 子类: 实现为 no-op return {"ok": True}
        Ozon 子类: 调 POST /v1/review/change-status

        Returns:
            {"ok": True/False, "msg": "..."}
        """
