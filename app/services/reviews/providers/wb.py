"""WB 评价 Provider — Wildberries Feedbacks API

API 端点 (Feedbacks 类型 token, 跟 seller token 不同):
- GET /api/v1/feedbacks?isAnswered=&take=&skip=  → 列表
- POST /api/v1/feedbacks/answer                  → 回复
- PATCH /api/v1/feedbacks/answer                 → 编辑回复 (本期不实现)
- GET /api/v1/feedbacks/count                    → 计数

字段 (从平台返:
- id (str), text (str), createdDate (RFC3339),
- productValuation (1-5 int), userName (str),
- productDetails: { nmId, productName, supplierArticle },
- answer: { text, editable, ... } | null
- isAnswered (bool)

Rate limit: 1 req/s (跟 seller token 共享, 撞 429 复用现有 silent-detector)

实现状态: stub - 真实 API 调用在下个 commit 接入
(WBClient 加 fetch_feedbacks / post_feedback_answer 方法)
"""

from typing import Optional, List

from app.services.reviews.providers.base import BaseReviewProvider, ReviewSnapshot


class WBReviewProvider(BaseReviewProvider):

    async def list_reviews(
        self,
        only_unanswered: bool = True,
        cursor: Optional[str] = None,
        limit: int = 100,
    ) -> tuple[List[ReviewSnapshot], Optional[str]]:
        # TODO Phase 1.1: 调 WBClient.fetch_feedbacks(isAnswered, take, skip)
        # 字段映射:
        #   id              → platform_review_id
        #   productValuation → rating
        #   text            → content_ru
        #   userName        → customer_name
        #   productDetails.nmId         → platform_sku_id
        #   productDetails.productName  → platform_product_name
        #   createdDate (RFC3339)       → created_at_platform (parse + 转 UTC naive)
        #   answer.text                 → existing_reply_ru (可空)
        #   isAnswered                  → is_answered
        # 分页: cursor 当 skip 用, 返 next_cursor = skip + len(items) 直到无新
        raise NotImplementedError("WBReviewProvider.list_reviews — Phase 1.1 待实现")

    async def post_reply(
        self, platform_review_id: str, reply_ru: str,
    ) -> dict:
        # TODO Phase 1.2: 调 WBClient.post_feedback_answer(id=review_id, text=reply_ru)
        # WB 端点: POST /api/v1/feedbacks/answer body: {id, text}
        # 成功后 WB 自动设 isAnswered=true, 不需要单独 mark_read
        raise NotImplementedError("WBReviewProvider.post_reply — Phase 1.2 待实现")

    async def mark_read(self, platform_review_id: str) -> dict:
        # WB no-op: 回复时 WB 自动设 isAnswered=true
        return {"ok": True, "msg": "WB 不需单独 mark_read, 回复时自动标记"}
