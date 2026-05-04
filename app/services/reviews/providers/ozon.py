"""Ozon 评价 Provider — Ozon Seller Review API (需 Premium 订阅)

API 端点:
- POST /v1/review/list           → 列表 (filter: status, rating)
- POST /v1/review/info           → 单条详情 (本期不用, 列表已含核心字段)
- POST /v1/review/comment/create → 回复 + 自动标已读
- POST /v1/review/comment/list   → 拉回复历史 (existing_reply 用, service 层做)
- POST /v1/review/change-status  → 标已读 (UNPROCESSED → PROCESSED)

字段 (从 Ozon 返):
- id (UUID str), rating (1-5), text (str),
- published_at (ISO datetime), status (UNPROCESSED|PROCESSED),
- order_status, sku (int), is_rating_participant (bool)
- ❌ 无 userName 字段 → snapshot.customer_name=""

订阅失败: WBClient 抛 SubscriptionRequiredError (跟 search_insights 同款),
service 层 try/except 捕获 → 业务层抛 ErrorCode 93001 给前端.
"""

from datetime import datetime, timezone
from typing import Optional, List

from app.services.reviews.providers.base import BaseReviewProvider, ReviewSnapshot
from app.utils.logger import setup_logger

logger = setup_logger("reviews.providers.ozon")


def _parse_ozon_datetime(raw: str) -> Optional[datetime]:
    """ISO datetime (e.g. "2026-05-04T10:23:45.123Z") → UTC naive datetime"""
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            return dt
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    except (ValueError, TypeError) as e:
        logger.debug(f"Ozon 时间解析失败 raw={raw!r}: {e}")
        return None


def _ozon_review_to_snapshot(rv: dict) -> ReviewSnapshot:
    """Ozon review 原始 dict → 统一 ReviewSnapshot"""
    return ReviewSnapshot(
        source_platform="ozon",
        platform_review_id=str(rv.get("id") or ""),
        rating=int(rv.get("rating") or 0),
        content_ru=rv.get("text") or "",
        customer_name="",                      # Ozon API 不返买家名
        platform_sku_id=str(rv.get("sku") or ""),
        platform_product_name="",              # service 层按 sku JOIN platform_listings 反查
        created_at_platform=_parse_ozon_datetime(rv.get("published_at") or ""),
        # existing_reply: service 层用 fetch_review_comments 单独拉 (Ozon 评价
        # 的回复在另一接口, 不在 list 响应里)
        existing_reply_ru="",
        existing_reply_at=None,
        is_answered=(str(rv.get("status") or "") == "PROCESSED"),
        raw=rv,
    )


def _build_ozon_client(shop):
    """统一 Ozon client 实例化 (含 client_id + perf 凭证)"""
    from app.services.platform.ozon import OzonClient
    return OzonClient(
        shop_id=shop.id,
        api_key=shop.api_key,
        client_id=shop.client_id or "",
        perf_client_id=getattr(shop, "perf_client_id", "") or "",
        perf_client_secret=getattr(shop, "perf_client_secret", "") or "",
    )


class OzonReviewProvider(BaseReviewProvider):

    async def list_reviews(
        self,
        only_unanswered: bool = True,
        cursor: Optional[str] = None,
        limit: int = 100,
    ) -> tuple[List[ReviewSnapshot], Optional[str]]:
        """拉 Ozon 评价列表 (分页用 last_id 游标)"""
        client = _build_ozon_client(self.shop)
        try:
            r = await client.fetch_reviews(
                status="UNPROCESSED" if only_unanswered else "ALL",
                last_id=cursor or "",
                limit=limit,
                sort_dir="DESC",
            )
            reviews = r.get("reviews") or []
            snapshots: List[ReviewSnapshot] = []
            for rv in reviews:
                try:
                    snapshots.append(_ozon_review_to_snapshot(rv))
                except Exception as e:
                    logger.warning(
                        f"Ozon review 解析失败 shop_id={self.shop.id} "
                        f"rid={rv.get('id')}: {e}"
                    )
                    continue
            next_cursor = r.get("last_id") if r.get("has_next") else None
            return snapshots, next_cursor
        finally:
            await client.close()

    async def post_reply(
        self, platform_review_id: str, reply_ru: str,
    ) -> dict:
        """对单条 Ozon 评价发回复. mark_as_processed=True 让 Ozon 自动标已读,
        跟 WB 行为对齐 (WB 回复后自动 isAnswered=true)."""
        client = _build_ozon_client(self.shop)
        try:
            return await client.post_review_comment(
                review_id=platform_review_id,
                text=reply_ru,
                mark_as_processed=True,
            )
        finally:
            await client.close()

    async def mark_read(self, platform_review_id: str) -> dict:
        """用户在 UI 不回复但选 '标已读' 时走这条路径"""
        client = _build_ozon_client(self.shop)
        try:
            return await client.change_review_status(
                review_ids=[platform_review_id], status="PROCESSED",
            )
        finally:
            await client.close()
