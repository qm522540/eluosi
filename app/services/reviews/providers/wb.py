"""WB 评价 Provider — Wildberries Feedbacks API

API 端点 (Feedbacks 类型 token, 跟 seller token 不同):
- GET /api/v1/feedbacks?isAnswered=&take=&skip=  → 列表
- POST /api/v1/feedbacks/answer                  → 回复
- GET /api/v1/feedbacks/count                    → 计数

字段 (从平台返):
- id (str), text (str), createdDate (RFC3339),
- productValuation (1-5 int), userName (str),
- productDetails: { nmId, productName, supplierArticle },
- answer: { text, editable, createDate, ... } | null
- isAnswered (bool)

Rate limit: 1 req/s (跟 seller token 共享, 撞 429 复用现有 silent-detector)
"""

from datetime import datetime, timezone
from typing import Optional, List

from app.services.reviews.providers.base import BaseReviewProvider, ReviewSnapshot
from app.utils.logger import setup_logger

logger = setup_logger("reviews.providers.wb")


def _parse_wb_datetime(raw: str) -> Optional[datetime]:
    """RFC3339 (e.g. "2026-05-04T10:23:45Z") → UTC naive datetime"""
    if not raw:
        return None
    try:
        # Python fromisoformat 处理 Z 后缀: replace Z → +00:00
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            return dt
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    except (ValueError, TypeError) as e:
        logger.debug(f"WB 时间解析失败 raw={raw!r}: {e}")
        return None


def _wb_feedback_to_snapshot(fb: dict) -> ReviewSnapshot:
    """WB feedback 原始 dict → 统一 ReviewSnapshot"""
    pd = fb.get("productDetails") or {}
    answer = fb.get("answer") or {}

    return ReviewSnapshot(
        source_platform="wb",
        platform_review_id=str(fb.get("id") or ""),
        rating=int(fb.get("productValuation") or 0),
        content_ru=fb.get("text") or "",
        customer_name=fb.get("userName") or "",
        platform_sku_id=str(pd.get("nmId") or ""),
        platform_product_name=pd.get("productName") or "",
        created_at_platform=_parse_wb_datetime(fb.get("createdDate") or ""),
        existing_reply_ru=answer.get("text") or "",
        existing_reply_at=_parse_wb_datetime(answer.get("createDate") or ""),
        is_answered=bool(fb.get("isAnswered")),
        raw=fb,
    )


class WBReviewProvider(BaseReviewProvider):

    async def list_reviews(
        self,
        only_unanswered: bool = True,
        cursor: Optional[str] = None,
        limit: int = 100,
    ) -> tuple[List[ReviewSnapshot], Optional[str]]:
        """拉 WB 评价列表 (分页用 skip 偏移)

        cursor 当 skip 用 (str int): None=从头开始, "100"=skip 100 条
        """
        from app.services.platform.wb import WBClient

        try:
            skip = int(cursor) if cursor else 0
        except (TypeError, ValueError):
            skip = 0

        client = WBClient(shop_id=self.shop.id, api_key=self.shop.api_key)
        try:
            r = await client.fetch_feedbacks(
                is_answered=not only_unanswered,
                take=limit,
                skip=skip,
            )
            feedbacks = r.get("feedbacks") or []
            snapshots: List[ReviewSnapshot] = []
            for fb in feedbacks:
                try:
                    snapshots.append(_wb_feedback_to_snapshot(fb))
                except Exception as e:
                    logger.warning(
                        f"WB feedback 解析失败 shop_id={self.shop.id} "
                        f"fid={fb.get('id')}: {e}"
                    )
                    continue
            # 拿满 limit 假定还有 → 返 next_cursor; 不满 limit 就是尾页 → None
            next_cursor = str(skip + limit) if len(feedbacks) >= limit else None
            return snapshots, next_cursor
        finally:
            await client.close()

    async def post_reply(
        self, platform_review_id: str, reply_ru: str,
    ) -> dict:
        """对单条 WB 评价发回复. 成功后 WB 自动设 isAnswered=true."""
        from app.services.platform.wb import WBClient

        client = WBClient(shop_id=self.shop.id, api_key=self.shop.api_key)
        try:
            return await client.post_feedback_answer(
                feedback_id=platform_review_id, text=reply_ru,
            )
        finally:
            await client.close()

    async def mark_read(self, platform_review_id: str) -> dict:
        """WB no-op: 回复时 WB 自动设 isAnswered=true (跟 Ozon 不同)"""
        return {"ok": True, "msg": "WB 不需单独 mark_read, 回复时自动标记"}
