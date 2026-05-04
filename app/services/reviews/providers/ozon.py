"""Ozon 评价 Provider — Ozon Seller Review API (需 Premium 订阅)

API 端点:
- POST /v1/review/list           → 列表 (filter: status, rating)
- POST /v1/review/info           → 单条详情
- POST /v1/review/comment/create → 回复
- POST /v1/review/comment/list   → 拉回复历史 (existing_reply 用)
- POST /v1/review/change-status  → 标已读 (UNPROCESSED → PROCESSED)

字段 (从 Ozon 返):
- id (UUID str), rating (1-5), comment (str),
- created_at (ISO datetime), status (UNPROCESSED|PROCESSED),
- order_status, sku (int), is_rating_participant (bool)
- ❌ 无 userName 字段 → snapshot.customer_name = ""

订阅失败: 返 403 / 调用 list 时返 code 跟 search_insights 同款 → 业务层抛
ErrorCode 93001 ("订阅未开通"), API 路由捕获给前端友好提示

实现状态: stub - 真实 API 调用在下个 commit 接入
(OzonClient 加 fetch_reviews / post_review_comment / change_review_status 方法)
"""

from typing import Optional, List

from app.services.reviews.providers.base import BaseReviewProvider, ReviewSnapshot


class OzonReviewProvider(BaseReviewProvider):

    async def list_reviews(
        self,
        only_unanswered: bool = True,
        cursor: Optional[str] = None,
        limit: int = 100,
    ) -> tuple[List[ReviewSnapshot], Optional[str]]:
        # TODO Phase 1.1: 调 OzonClient.fetch_reviews(status, last_id, limit)
        # 字段映射:
        #   id              → platform_review_id
        #   rating          → rating
        #   comment         → content_ru
        #   sku             → platform_sku_id (int → str)
        #   created_at      → created_at_platform (UTC naive)
        #   status          → is_answered (PROCESSED=true, UNPROCESSED=false)
        #   (无 userName)   → customer_name="" (前端显示"匿名买家")
        #   (无 product_name) → platform_product_name="" (要 listing JOIN 反查)
        # 分页: cursor=last_id, 返 next_cursor = items[-1].id 直到 has_next=false
        # only_unanswered=true → filter.status=["UNPROCESSED"]
        # 订阅失败 (403): raise Exception("订阅未开通")
        raise NotImplementedError("OzonReviewProvider.list_reviews — Phase 1.1 待实现")

    async def post_reply(
        self, platform_review_id: str, reply_ru: str,
    ) -> dict:
        # TODO Phase 1.2: 调 OzonClient.post_review_comment(review_id, text=reply_ru,
        #                                                     mark_review_as_processed=true)
        # mark_review_as_processed=true 让回复后自动标已读, 跟 WB 行为对齐
        raise NotImplementedError("OzonReviewProvider.post_reply — Phase 1.2 待实现")

    async def mark_read(self, platform_review_id: str) -> dict:
        # TODO Phase 1.3: 调 OzonClient.change_review_status(review_id, status="PROCESSED")
        # 用户在 UI 不回复但选择"标已读"时走这条路径
        raise NotImplementedError("OzonReviewProvider.mark_read — Phase 1.3 待实现")
