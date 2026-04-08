"""Ozon Seller API 客户端

对接 Ozon 卖家后台 API，实现数据采集。
- API文档: https://docs.ozon.ru/api/seller
- 认证方式: Client-Id + Api-Key 请求头

主要接口：
- 广告 (Performance API): https://performance.ozon.ru
- 卖家 (Seller API): https://api-seller.ozon.ru
"""

import asyncio
import time
from datetime import datetime, date, timedelta
from typing import Optional

import httpx

from app.config import get_settings
from app.services.platform.base import BasePlatformClient, PlatformClientFactory
from app.utils.logger import setup_logger

logger = setup_logger("platform.ozon")
settings = get_settings()

# Ozon API 端点
OZON_SELLER_API = "https://api-seller.ozon.ru"
OZON_PERFORMANCE_API = "https://api-performance.ozon.ru"

MIN_REQUEST_INTERVAL = 60.0 / settings.OZON_RATE_LIMIT_PER_MINUTE


class OzonClient(BasePlatformClient):
    """Ozon 平台客户端

    认证需要两个凭证:
    - client_id: 通过 kwargs['client_id'] 传入
    - api_key: 通过 api_key 参数传入
    """

    def __init__(self, shop_id: int, api_key: str, **kwargs):
        super().__init__(shop_id=shop_id, api_key=api_key, **kwargs)
        self.client_id = kwargs.get("client_id", "")
        self._last_request_time = 0.0
        self._http_client: Optional[httpx.AsyncClient] = None
        self._perf_client: Optional[httpx.AsyncClient] = None

    def _get_seller_headers(self) -> dict:
        """卖家API请求头"""
        return {
            "Client-Id": self.client_id,
            "Api-Key": self.api_key,
            "Content-Type": "application/json",
        }

    def _get_perf_headers(self) -> dict:
        """广告API请求头（Performance API使用同样的认证）"""
        return {
            "Client-Id": self.client_id,
            "Api-Key": self.api_key,
            "Content-Type": "application/json",
        }

    async def _get_seller_client(self) -> httpx.AsyncClient:
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                headers=self._get_seller_headers(),
                timeout=httpx.Timeout(30.0, connect=10.0),
                follow_redirects=True,
            )
        return self._http_client

    async def _get_perf_client(self) -> httpx.AsyncClient:
        if self._perf_client is None or self._perf_client.is_closed:
            self._perf_client = httpx.AsyncClient(
                headers=self._get_perf_headers(),
                timeout=httpx.Timeout(30.0, connect=10.0),
                follow_redirects=True,
            )
        return self._perf_client

    async def _rate_limit(self):
        now = time.monotonic()
        elapsed = now - self._last_request_time
        if elapsed < MIN_REQUEST_INTERVAL:
            await asyncio.sleep(MIN_REQUEST_INTERVAL - elapsed)
        self._last_request_time = time.monotonic()

    async def _request(
        self, method: str, url: str, use_perf: bool = False, **kwargs
    ) -> dict:
        """统一请求，带限速和重试"""
        await self._rate_limit()
        client = await (self._get_perf_client() if use_perf else self._get_seller_client())

        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = await client.request(method, url, **kwargs)

                if response.status_code == 429:
                    wait_time = min(30, 5 * (attempt + 1))
                    logger.warning(
                        f"Ozon API 限速(429)，shop_id={self.shop_id}，"
                        f"等待{wait_time}秒 ({attempt+1}/{max_retries})"
                    )
                    await asyncio.sleep(wait_time)
                    continue

                response.raise_for_status()

                if response.status_code == 204 or not response.content:
                    return {}

                return response.json()

            except httpx.TimeoutException:
                logger.error(
                    f"Ozon API 超时，shop_id={self.shop_id}，url={url}，"
                    f"重试 ({attempt+1}/{max_retries})"
                )
                if attempt == max_retries - 1:
                    raise
                await asyncio.sleep(2 * (attempt + 1))

            except httpx.HTTPStatusError as e:
                logger.error(
                    f"Ozon API 错误，shop_id={self.shop_id}，"
                    f"status={e.response.status_code}，url={url}"
                )
                raise

        return {}

    # ==================== 连接测试 ====================

    async def test_connection(self) -> bool:
        """测试API连接 — 通过获取卖家信息验证"""
        try:
            url = f"{OZON_SELLER_API}/v1/seller/info"
            await self._request("POST", url, json={})
            logger.info(f"Ozon 连接测试成功，shop_id={self.shop_id}")
            return True
        except Exception as e:
            logger.error(f"Ozon 连接测试失败，shop_id={self.shop_id}: {e}")
            return False

    # ==================== 广告活动 ====================

    async def fetch_ad_campaigns(self) -> list:
        """拉取广告活动列表

        Ozon Performance API:
        GET /api/client/campaign → 获取广告活动列表
        """
        campaigns = []

        try:
            url = f"{OZON_PERFORMANCE_API}/api/client/campaign"

            # 获取运行中的活动
            result = await self._request(
                "GET", url, use_perf=True,
                params={"state": "CAMPAIGN_STATE_RUNNING"},
            )

            items = result.get("list", []) if isinstance(result, dict) else []

            # 也获取暂停的活动
            result_paused = await self._request(
                "GET", url, use_perf=True,
                params={"state": "CAMPAIGN_STATE_STOPPED"},
            )
            paused_items = result_paused.get("list", []) if isinstance(result_paused, dict) else []
            items.extend(paused_items)

            if not items:
                logger.info(f"Ozon shop_id={self.shop_id} 暂无广告活动")
                return []

            for item in items:
                campaigns.append(self._parse_campaign(item))

            logger.info(
                f"Ozon shop_id={self.shop_id} 发现 {len(campaigns)} 个广告活动"
            )

        except Exception as e:
            logger.error(f"Ozon 拉取广告活动失败，shop_id={self.shop_id}: {e}")
            raise

        return campaigns

    def _parse_campaign(self, raw: dict) -> dict:
        """解析Ozon广告活动为标准格式"""
        # Ozon状态映射
        state_map = {
            "CAMPAIGN_STATE_RUNNING": "active",
            "CAMPAIGN_STATE_PLANNED": "draft",
            "CAMPAIGN_STATE_STOPPED": "paused",
            "CAMPAIGN_STATE_INACTIVE": "paused",
            "CAMPAIGN_STATE_ARCHIVED": "archived",
            "CAMPAIGN_STATE_MODERATION": "draft",
        }
        # Ozon广告类型映射
        type_map = {
            "SKU": "product_page",
            "BANNER": "catalog",
            "BRAND_SHELF": "catalog",
            "SEARCH_PROMO": "search",
            "ACTION": "recommendation",
        }

        return {
            "platform_campaign_id": str(raw.get("id", "")),
            "name": raw.get("title", ""),
            "ad_type": type_map.get(raw.get("advObjectType", ""), "search"),
            "daily_budget": raw.get("dailyBudget"),
            "total_budget": raw.get("budget"),
            "status": state_map.get(raw.get("state", ""), "paused"),
            "start_date": raw.get("createdAt", "")[:10] if raw.get("createdAt") else None,
            "end_date": raw.get("endDate", "")[:10] if raw.get("endDate") else None,
        }

    # ==================== 广告统计 ====================

    async def fetch_ad_stats(
        self, campaign_id: str, date_from: str, date_to: str
    ) -> list:
        """拉取广告活动统计数据

        Ozon Performance API:
        POST /api/client/statistics/daily → 每日统计
        """
        stats = []

        try:
            url = f"{OZON_PERFORMANCE_API}/api/client/statistics/daily"
            payload = {
                "campaigns": [campaign_id],
                "dateFrom": date_from,
                "dateTo": date_to,
            }
            result = await self._request("POST", url, use_perf=True, json=payload)

            rows = result.get("rows", [])
            for row in rows:
                stat = self._parse_daily_stat(campaign_id, row)
                if stat:
                    stats.append(stat)

        except Exception as e:
            logger.error(
                f"Ozon 拉取广告统计失败，shop_id={self.shop_id}，"
                f"campaign_id={campaign_id}: {e}"
            )
            raise

        return stats

    def _parse_daily_stat(self, campaign_id: str, row: dict) -> Optional[dict]:
        """解析Ozon每日统计"""
        date_str = row.get("date", "")
        if not date_str:
            return None

        impressions = int(row.get("views", 0))
        clicks = int(row.get("clicks", 0))
        spend = float(row.get("moneySpent", 0))
        orders = int(row.get("orders", 0))
        revenue = float(row.get("ordersMoney", 0))

        ctr = (clicks / impressions * 100) if impressions > 0 else 0
        cpc = (spend / clicks) if clicks > 0 else 0
        acos = (spend / revenue * 100) if revenue > 0 else 0
        roas = (revenue / spend) if spend > 0 else 0

        return {
            "campaign_id": campaign_id,
            "platform": "ozon",
            "stat_date": date_str[:10],
            "stat_hour": None,
            "impressions": impressions,
            "clicks": clicks,
            "spend": round(spend, 2),
            "orders": orders,
            "revenue": round(revenue, 2),
            "ctr": round(ctr, 4),
            "cpc": round(cpc, 2),
            "acos": round(acos, 4),
            "roas": round(roas, 4),
        }

    # ==================== 商品 ====================

    async def fetch_products(self, page: int = 1, limit: int = 100) -> dict:
        """拉取商品列表"""
        try:
            url = f"{OZON_SELLER_API}/v2/product/list"
            payload = {
                "filter": {"visibility": "ALL"},
                "last_id": "",
                "limit": limit,
            }
            result = await self._request("POST", url, json=payload)
            return result
        except Exception as e:
            logger.error(f"Ozon 拉取商品失败，shop_id={self.shop_id}: {e}")
            raise

    # ==================== 订单 ====================

    async def fetch_orders(self, date_from: str, date_to: str) -> list:
        """拉取订单列表"""
        orders = []
        offset = 0
        limit = 1000

        try:
            while True:
                url = f"{OZON_SELLER_API}/v3/posting/fbs/list"
                payload = {
                    "dir": "ASC",
                    "filter": {
                        "since": f"{date_from}T00:00:00.000Z",
                        "to": f"{date_to}T23:59:59.999Z",
                        "status": "",
                    },
                    "limit": limit,
                    "offset": offset,
                    "with": {"analytics_data": True, "financial_data": True},
                }
                result = await self._request("POST", url, json=payload)

                postings = result.get("result", {}).get("postings", [])
                if not postings:
                    break

                orders.extend(postings)
                if len(postings) < limit:
                    break
                offset += limit

        except Exception as e:
            logger.error(f"Ozon 拉取订单失败，shop_id={self.shop_id}: {e}")
            raise

        return orders

    # ==================== 库存 ====================

    async def fetch_inventory(self) -> list:
        """拉取库存/仓库数据"""
        try:
            url = f"{OZON_SELLER_API}/v2/product/info/stocks"
            payload = {
                "filter": {"visibility": "ALL"},
                "last_id": "",
                "limit": 1000,
            }
            result = await self._request("POST", url, json=payload)
            items = result.get("result", {}).get("items", [])
            return items
        except Exception as e:
            logger.error(f"Ozon 拉取库存失败，shop_id={self.shop_id}: {e}")
            raise

    async def close(self):
        """关闭HTTP客户端"""
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()
        if self._perf_client and not self._perf_client.is_closed:
            await self._perf_client.aclose()


# 注册到工厂
PlatformClientFactory.register("ozon", OzonClient)
