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
        raw_client_id = kwargs.get("client_id", "")
        # Seller API 用纯数字 Client-Id
        self.client_id = raw_client_id.split("-")[0] if "-" in raw_client_id and "@" in raw_client_id else raw_client_id
        # Performance API OAuth 凭证（独立于 Seller API）
        self.perf_client_id = kwargs.get("perf_client_id", "")
        self.perf_client_secret = kwargs.get("perf_client_secret", "")
        self._perf_token: Optional[str] = None
        self._last_request_time = 0.0
        self._http_client: Optional[httpx.AsyncClient] = None
        self._perf_client: Optional[httpx.AsyncClient] = None
        logger.info(f"Ozon client init: seller_cid={self.client_id}, perf_cid={self.perf_client_id or 'N/A'}")

    def _get_seller_headers(self) -> dict:
        """卖家API请求头（纯数字Client-Id）"""
        return {
            "Client-Id": self.client_id,
            "Api-Key": self.api_key,
            "Content-Type": "application/json",
        }

    def _get_perf_headers(self) -> dict:
        """广告API请求头（Performance API用OAuth Bearer Token）"""
        headers = {"Content-Type": "application/json"}
        if self._perf_token:
            headers["Authorization"] = f"Bearer {self._perf_token}"
        else:
            # 降级：用 Seller API 凭证尝试
            headers["Client-Id"] = self.client_id
            headers["Api-Key"] = self.api_key
        return headers

    async def _ensure_perf_token(self):
        """获取 Performance API OAuth token"""
        if self._perf_token or not self.perf_client_id or not self.perf_client_secret:
            return
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.post(
                    f"{OZON_PERFORMANCE_API}/api/client/token",
                    json={
                        "client_id": self.perf_client_id,
                        "client_secret": self.perf_client_secret,
                        "grant_type": "client_credentials",
                    },
                )
                if r.status_code == 200:
                    self._perf_token = r.json().get("access_token", "")
                    # 重建 perf 客户端以携带新 token
                    if self._perf_client and not self._perf_client.is_closed:
                        await self._perf_client.aclose()
                    self._perf_client = None
                    logger.info(f"Ozon Performance API token获取成功，shop_id={self.shop_id}")
                else:
                    logger.warning(f"Ozon Performance API token获取失败: {r.status_code} {r.text[:200]}")
        except Exception as e:
            logger.warning(f"Ozon Performance API token获取异常: {e}")

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
        """测试API连接 — 依次尝试多个端点验证"""
        test_urls = [
            ("POST", f"{OZON_SELLER_API}/v3/product/info/stocks", {"filter": {"visibility": "ALL"}, "limit": 1}),
            ("POST", f"{OZON_SELLER_API}/v2/product/list", {"filter": {"visibility": "ALL"}, "limit": 1}),
            ("POST", f"{OZON_SELLER_API}/v1/seller/info", {}),
        ]
        for method, url, payload in test_urls:
            try:
                await self._request(method, url, json=payload)
                logger.info(f"Ozon 连接测试成功，shop_id={self.shop_id}，url={url}")
                return True
            except Exception:
                continue
        logger.error(f"Ozon 连接测试失败，shop_id={self.shop_id}")
        return False

    # ==================== 广告活动 ====================

    async def fetch_ad_campaigns(self) -> list:
        """拉取广告活动列表

        依次尝试多个Ozon广告API端点（新旧版本兼容）：
        1. Performance API (OAuth): GET /api/client/campaign (推荐)
        2. Seller API: POST /api/client/campaign/list
        3. Seller API: GET /api/client/campaign
        """
        # 先获取 Performance API token
        await self._ensure_perf_token()

        campaigns = []

        try:
            items = []

            # 方式1（优先）: Performance API + OAuth token
            if self._perf_token:
                try:
                    url = f"{OZON_PERFORMANCE_API}/api/client/campaign"
                    result = await self._request("GET", url, use_perf=True)
                    batch = result.get("list", result.get("campaigns", []))
                    if isinstance(batch, list):
                        items.extend(batch)
                    if items:
                        logger.info(f"Ozon shop_id={self.shop_id} Performance API 获取到 {len(items)} 个活动")
                except Exception as e:
                    logger.warning(f"Ozon Performance API 失败: {e}，尝试 Seller API")

            # 方式2: Seller API（降级）
            if not items:
                try:
                    url = f"{OZON_SELLER_API}/api/client/campaign"
                    result = await self._request("GET", url)
                    batch = result.get("list", result.get("campaigns", []))
                    if isinstance(batch, list):
                        items.extend(batch)
                    if items:
                        logger.info(f"Ozon shop_id={self.shop_id} Seller API 获取到 {len(items)} 个活动")
                except Exception as e:
                    logger.warning(f"Ozon Seller API 也失败: {e}")

            if not items:
                logger.info(f"Ozon shop_id={self.shop_id} 所有接口均无广告活动数据")
                return []

            # 去重（按id）
            seen_ids = set()
            unique_items = []
            for item in items:
                cid = item.get("id") or item.get("campaignId") or item.get("campaign_id")
                if cid and cid not in seen_ids:
                    seen_ids.add(cid)
                    unique_items.append(item)

            for item in unique_items:
                campaigns.append(self._parse_campaign(item))

            logger.info(
                f"Ozon shop_id={self.shop_id} 发现 {len(campaigns)} 个广告活动"
            )

        except Exception as e:
            logger.error(f"Ozon 拉取广告活动失败，shop_id={self.shop_id}: {e}")
            raise

        return campaigns

    def _parse_campaign(self, raw: dict) -> dict:
        """解析Ozon广告活动为标准格式（兼容新旧响应格式）"""
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
            "PRODUCT_PLACEMENT": "product_page",
            "ACTION": "recommendation",
        }

        # 兼容不同字段名
        campaign_id = str(
            raw.get("id") or raw.get("campaignId") or raw.get("campaign_id") or ""
        )
        ad_type_raw = raw.get("advObjectType") or raw.get("type") or raw.get("productCampaignMode") or ""
        ad_type = type_map.get(ad_type_raw, "search")
        ad_type_labels = {
            "product_page": "商品推广",
            "catalog": "品牌推广",
            "search": "搜索推广",
            "recommendation": "活动推广",
        }
        name = raw.get("title") or raw.get("name") or ""
        if not name.strip():
            name = f"{ad_type_labels.get(ad_type, '广告')}-{campaign_id}"

        state_raw = raw.get("state") or raw.get("status") or ""

        # 预算：兼容多种字段名
        daily_budget = raw.get("dailyBudget") or raw.get("daily_budget")
        total_budget = raw.get("budget") or raw.get("totalBudget") or raw.get("total_budget")

        # 日期
        start_date = raw.get("createdAt") or raw.get("created_at") or raw.get("startDate") or ""
        end_date = raw.get("endDate") or raw.get("end_date") or ""

        return {
            "platform_campaign_id": campaign_id,
            "name": name,
            "ad_type": ad_type,
            "daily_budget": daily_budget,
            "total_budget": total_budget,
            "status": state_map.get(state_raw, "paused"),
            "start_date": start_date[:10] if start_date else None,
            "end_date": end_date[:10] if end_date else None,
        }

    # ==================== 广告统计 ====================

    async def fetch_ad_stats(
        self, campaign_id: str, date_from: str, date_to: str
    ) -> list:
        """拉取广告活动统计数据

        依次尝试多个统计端点：
        1. Seller API: POST /api/client/statistics/daily
        2. Seller API: POST /api/client/statistics
        3. Performance API: POST /api/client/statistics/daily（旧版独立域名）
        """
        stats = []

        # 统计接口的请求体格式
        payloads = [
            # 格式1: campaigns传字符串数组
            {"campaigns": [str(campaign_id)], "dateFrom": date_from, "dateTo": date_to},
            # 格式2: campaignId传单个ID + 日期区间
            {"campaignId": str(campaign_id), "dateFrom": date_from, "dateTo": date_to},
        ]

        # 依次尝试多个端点
        endpoints = [
            (f"{OZON_SELLER_API}/api/client/statistics/daily", False),
            (f"{OZON_SELLER_API}/api/client/statistics", False),
            (f"{OZON_PERFORMANCE_API}/api/client/statistics/daily", True),
            (f"{OZON_PERFORMANCE_API}/api/client/statistics", True),
        ]

        result = None
        for url, use_perf in endpoints:
            for payload in payloads:
                try:
                    result = await self._request(
                        "POST", url, use_perf=use_perf, json=payload
                    )
                    if result and (result.get("rows") or result.get("data") or result.get("items")):
                        logger.info(f"Ozon 统计接口命中: {url}")
                        break
                    result = None
                except Exception:
                    continue
            if result:
                break

        if not result:
            logger.warning(
                f"Ozon 所有统计接口均不可用，shop_id={self.shop_id}，"
                f"campaign_id={campaign_id}"
            )
            return []

        try:
            # 兼容多种响应格式
            rows = result.get("rows") or result.get("data") or result.get("items") or []
            if isinstance(rows, list):
                for row in rows:
                    stat = self._parse_daily_stat(campaign_id, row)
                    if stat:
                        stats.append(stat)
        except Exception as e:
            logger.error(
                f"Ozon 解析广告统计失败，shop_id={self.shop_id}，"
                f"campaign_id={campaign_id}: {e}"
            )
            raise

        return stats

    def _parse_daily_stat(self, campaign_id: str, row: dict) -> Optional[dict]:
        """解析Ozon每日统计（兼容多种响应字段名）"""
        date_str = row.get("date") or row.get("statDate") or row.get("stat_date") or ""
        if not date_str:
            return None

        impressions = int(row.get("views") or row.get("impressions") or row.get("shows") or 0)
        clicks = int(row.get("clicks") or 0)
        spend = float(row.get("moneySpent") or row.get("spend") or row.get("cost") or 0)
        orders = int(row.get("orders") or row.get("conversions") or 0)
        revenue = float(
            row.get("ordersMoney") or row.get("revenue") or row.get("orderSum") or
            row.get("orders_money") or 0
        )

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

    # ==================== 广告活动商品 ====================

    async def fetch_campaign_products(self, campaign_id: str) -> list:
        """获取广告活动关联的商品列表及出价，并补充商品图片

        1. Performance API: GET /api/client/campaign/{id}/v2/products → SKU、出价、名称
        2. Seller API: POST /v2/product/info → 商品图片
        """
        await self._ensure_perf_token()
        if not self._perf_token:
            logger.warning(f"Ozon 无Performance API token，无法获取活动商品")
            return []

        try:
            url = f"{OZON_PERFORMANCE_API}/api/client/campaign/{campaign_id}/v2/products"
            result = await self._request("GET", url, use_perf=True)
            products = result.get("products", [])
            logger.info(f"Ozon 活动 {campaign_id} 获取到 {len(products)} 个商品")

            # 通过 Seller API 补充商品图片
            for product in products:
                sku = product.get("sku")
                if not sku:
                    continue
                try:
                    info = await self._request(
                        "POST", f"{OZON_SELLER_API}/v2/product/info",
                        json={"sku": int(sku)}
                    )
                    result_info = info.get("result", {})
                    images = result_info.get("images", result_info.get("primary_image", []))
                    if isinstance(images, list) and images:
                        product["image"] = images[0]
                    elif isinstance(images, str) and images:
                        product["image"] = images
                    # 补充更多信息
                    if not product.get("title") and result_info.get("name"):
                        product["title"] = result_info["name"]
                except Exception:
                    pass  # 图片获取失败不影响主流程

            return products
        except Exception as e:
            logger.error(f"Ozon 获取活动商品失败 campaign_id={campaign_id}: {e}")
            return []

    async def update_campaign_bid(self, campaign_id: str, sku: str, new_bid: str) -> bool:
        """修改广告活动中商品的出价

        Performance API:
        PUT /api/client/campaign/{id}/products  body: {"bids":[{"sku":"...","bid":"..."}]}
        """
        await self._ensure_perf_token()
        if not self._perf_token:
            return False

        try:
            url = f"{OZON_PERFORMANCE_API}/api/client/campaign/{campaign_id}/products"
            payload = {"bids": [{"sku": str(sku), "bid": str(new_bid)}]}
            result = await self._request("PUT", url, use_perf=True, json=payload)
            logger.info(f"Ozon 出价修改成功 campaign={campaign_id} sku={sku} bid={new_bid}")
            return True
        except Exception as e:
            logger.error(f"Ozon 出价修改失败: {e}")
            return False

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
