"""Yandex Market API 客户端

对接 Yandex Market Partner API，实现数据采集。
- API文档: https://yandex.ru/dev/market/partner-api/doc/
- 认证方式: OAuth2 Bearer Token

主要接口：
- 商家API: https://api.partner.market.yandex.ru
- 广告API (Yandex Direct): https://api.direct.yandex.com/json/v5
"""

import asyncio
import time
from datetime import datetime, date, timedelta
from typing import Optional

import httpx

from app.config import get_settings
from app.services.platform.base import BasePlatformClient, PlatformClientFactory
from app.utils.logger import setup_logger

logger = setup_logger("platform.yandex")
settings = get_settings()

# Yandex API 端点
YANDEX_MARKET_API = "https://api.partner.market.yandex.ru"
YANDEX_DIRECT_API = "https://api.direct.yandex.com/json/v5"

MIN_REQUEST_INTERVAL = 60.0 / settings.YANDEX_RATE_LIMIT_PER_MINUTE


class YandexClient(BasePlatformClient):
    """Yandex Market + Direct 客户端

    认证凭证:
    - api_key: 这里存放 OAuth token
    - kwargs['campaign_id']: Yandex Market 商家 campaign ID
    - kwargs['business_id']: Yandex Market business ID
    """

    def __init__(self, shop_id: int, api_key: str, **kwargs):
        super().__init__(shop_id=shop_id, api_key=api_key, **kwargs)
        self.oauth_token = api_key  # OAuth token
        self.campaign_id = kwargs.get("campaign_id", "")
        self.business_id = kwargs.get("business_id", "")
        self._last_request_time = 0.0
        self._http_client: Optional[httpx.AsyncClient] = None
        self._direct_client: Optional[httpx.AsyncClient] = None

    def _get_market_headers(self) -> dict:
        """Market API 请求头"""
        return {
            "Authorization": f"Bearer {self.oauth_token}",
            "Content-Type": "application/json",
        }

    def _get_direct_headers(self) -> dict:
        """Direct API 请求头"""
        return {
            "Authorization": f"Bearer {self.oauth_token}",
            "Content-Type": "application/json",
            "Accept-Language": "ru",
        }

    async def _get_market_client(self) -> httpx.AsyncClient:
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                headers=self._get_market_headers(),
                timeout=httpx.Timeout(30.0, connect=10.0),
                follow_redirects=True,
            )
        return self._http_client

    async def _get_direct_client(self) -> httpx.AsyncClient:
        if self._direct_client is None or self._direct_client.is_closed:
            self._direct_client = httpx.AsyncClient(
                headers=self._get_direct_headers(),
                timeout=httpx.Timeout(60.0, connect=10.0),
                follow_redirects=True,
            )
        return self._direct_client

    async def _rate_limit(self):
        now = time.monotonic()
        elapsed = now - self._last_request_time
        if elapsed < MIN_REQUEST_INTERVAL:
            await asyncio.sleep(MIN_REQUEST_INTERVAL - elapsed)
        self._last_request_time = time.monotonic()

    async def _request(
        self, method: str, url: str, use_direct: bool = False, **kwargs
    ) -> dict:
        """统一请求，带限速和重试"""
        await self._rate_limit()
        client = await (
            self._get_direct_client() if use_direct else self._get_market_client()
        )

        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = await client.request(method, url, **kwargs)

                if response.status_code == 429:
                    wait_time = min(30, 5 * (attempt + 1))
                    logger.warning(
                        f"Yandex API 限速(429)，shop_id={self.shop_id}，"
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
                    f"Yandex API 超时，shop_id={self.shop_id}，url={url}，"
                    f"重试 ({attempt+1}/{max_retries})"
                )
                if attempt == max_retries - 1:
                    raise
                await asyncio.sleep(2 * (attempt + 1))

            except httpx.HTTPStatusError as e:
                logger.error(
                    f"Yandex API 错误，shop_id={self.shop_id}，"
                    f"status={e.response.status_code}，url={url}"
                )
                raise

        return {}

    # ==================== 连接测试 ====================

    async def test_connection(self) -> bool:
        """测试API连接 — 通过获取商家信息验证"""
        try:
            if self.campaign_id:
                url = f"{YANDEX_MARKET_API}/campaigns/{self.campaign_id}"
                await self._request("GET", url)
            else:
                url = f"{YANDEX_MARKET_API}/campaigns"
                await self._request("GET", url)
            logger.info(f"Yandex 连接测试成功，shop_id={self.shop_id}")
            return True
        except Exception as e:
            logger.error(f"Yandex 连接测试失败，shop_id={self.shop_id}: {e}")
            return False

    # ==================== 广告活动 (Yandex Direct) ====================

    async def fetch_ad_campaigns(self) -> list:
        """拉取Yandex Direct广告活动列表

        Yandex Direct API v5:
        POST /campaigns → 获取广告活动
        """
        campaigns = []

        try:
            url = f"{YANDEX_DIRECT_API}/campaigns"
            payload = {
                "method": "get",
                "params": {
                    "SelectionCriteria": {},
                    "FieldNames": [
                        "Id", "Name", "State", "Status", "Type",
                        "DailyBudget", "StartDate", "EndDate",
                    ],
                },
            }
            result = await self._request("POST", url, use_direct=True, json=payload)

            items = result.get("result", {}).get("Campaigns", [])
            for item in items:
                campaigns.append(self._parse_campaign(item))

            logger.info(
                f"Yandex shop_id={self.shop_id} 发现 {len(campaigns)} 个广告活动"
            )

        except Exception as e:
            logger.error(
                f"Yandex 拉取广告活动失败，shop_id={self.shop_id}: {e}"
            )
            raise

        return campaigns

    def _parse_campaign(self, raw: dict) -> dict:
        """解析Yandex Direct活动为标准格式"""
        # Yandex Direct 状态映射
        state_map = {
            "ON": "active",
            "OFF": "paused",
            "SUSPENDED": "paused",
            "ENDED": "archived",
            "CONVERTED": "archived",
            "ARCHIVED": "archived",
        }
        # 广告类型映射
        type_map = {
            "TEXT_CAMPAIGN": "search",
            "DYNAMIC_TEXT_CAMPAIGN": "search",
            "MOBILE_APP_CAMPAIGN": "recommendation",
            "CPM_BANNER_CAMPAIGN": "catalog",
            "SMART_CAMPAIGN": "recommendation",
            "UNIFIED_CAMPAIGN": "search",
        }

        # 日预算 (Yandex Direct 以微单位存储, 需要 / 1000000)
        daily_budget_raw = raw.get("DailyBudget", {})
        daily_budget = None
        if daily_budget_raw and daily_budget_raw.get("Amount"):
            daily_budget = int(daily_budget_raw["Amount"]) / 1000000

        campaign_id = str(raw.get("Id", ""))
        ad_type = type_map.get(raw.get("Type", ""), "search")
        ad_type_labels = {
            "search": "搜索广告",
            "catalog": "展示广告",
            "recommendation": "智能广告",
        }
        name = raw.get("Name") or ""
        if not name.strip():
            name = f"{ad_type_labels.get(ad_type, '广告')}-{campaign_id}"

        return {
            "platform_campaign_id": campaign_id,
            "name": name,
            "ad_type": ad_type,
            "daily_budget": daily_budget,
            "total_budget": None,
            "status": state_map.get(raw.get("State", ""), "paused"),
            "start_date": raw.get("StartDate"),
            "end_date": raw.get("EndDate"),
        }

    # ==================== 广告统计 ====================

    async def fetch_ad_stats(
        self, campaign_id: str, date_from: str, date_to: str
    ) -> list:
        """拉取广告统计数据

        使用 Yandex Direct Reports API:
        POST /reports → TSV格式统计报表
        """
        stats = []

        try:
            url = f"{YANDEX_DIRECT_API}/reports"
            payload = {
                "params": {
                    "SelectionCriteria": {
                        "Filter": [
                            {
                                "Field": "CampaignId",
                                "Operator": "EQUALS",
                                "Values": [campaign_id],
                            }
                        ],
                        "DateFrom": date_from,
                        "DateTo": date_to,
                    },
                    "FieldNames": [
                        "Date", "Impressions", "Clicks", "Cost",
                        "Conversions", "Revenue",
                    ],
                    "ReportName": f"ad_stats_{campaign_id}_{date_from}",
                    "ReportType": "CUSTOM_REPORT",
                    "DateRangeType": "CUSTOM_DATE",
                    "Format": "TSV",
                    "IncludeVAT": "YES",
                },
            }

            # Direct Reports API 返回 TSV，需要特殊处理
            await self._rate_limit()
            client = await self._get_direct_client()

            max_retries = 3
            for attempt in range(max_retries):
                try:
                    response = await client.post(url, json=payload)

                    if response.status_code == 201:
                        # 报表在生成中，需要等待重试
                        retry_in = int(response.headers.get("retryIn", 5))
                        logger.info(
                            f"Yandex报表生成中，{retry_in}秒后重试"
                        )
                        await asyncio.sleep(retry_in)
                        continue

                    if response.status_code == 202:
                        # 报表还未就绪
                        await asyncio.sleep(10)
                        continue

                    response.raise_for_status()

                    if response.status_code == 200:
                        stats = self._parse_tsv_stats(
                            campaign_id, response.text
                        )
                        break

                except httpx.TimeoutException:
                    if attempt == max_retries - 1:
                        raise
                    await asyncio.sleep(5)

        except Exception as e:
            logger.error(
                f"Yandex 拉取广告统计失败，shop_id={self.shop_id}，"
                f"campaign_id={campaign_id}: {e}"
            )
            raise

        return stats

    def _parse_tsv_stats(self, campaign_id: str, tsv_text: str) -> list:
        """解析Yandex Direct TSV报表"""
        stats = []
        lines = tsv_text.strip().split("\n")

        # 跳过表头行（第一行是报表名，第二行是列名）
        if len(lines) < 3:
            return []

        header = lines[1].split("\t")
        col_map = {name: idx for idx, name in enumerate(header)}

        for line in lines[2:]:
            if line.startswith("Total") or not line.strip():
                continue

            cols = line.split("\t")
            if len(cols) < len(header):
                continue

            try:
                date_str = cols[col_map.get("Date", 0)]
                impressions = int(cols[col_map.get("Impressions", 1)])
                clicks = int(cols[col_map.get("Clicks", 2)])
                # Yandex Direct 的 Cost 以微单位存储
                spend = float(cols[col_map.get("Cost", 3)]) / 1000000
                orders = int(cols[col_map.get("Conversions", 4)])
                revenue = float(cols[col_map.get("Revenue", 5)]) / 1000000

                ctr = (clicks / impressions * 100) if impressions > 0 else 0
                cpc = (spend / clicks) if clicks > 0 else 0
                acos = (spend / revenue * 100) if revenue > 0 else 0
                roas = (revenue / spend) if spend > 0 else 0

                stats.append({
                    "campaign_id": campaign_id,
                    "platform": "yandex",
                    "stat_date": date_str,
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
                })
            except (ValueError, IndexError) as e:
                logger.warning(f"Yandex TSV行解析失败: {line}, error: {e}")
                continue

        return stats

    # ==================== 商品 (Market API) ====================

    async def fetch_products(self, page: int = 1, limit: int = 100) -> dict:
        """拉取商品列表 (Yandex Market)"""
        try:
            if self.business_id:
                url = (
                    f"{YANDEX_MARKET_API}/businesses/{self.business_id}"
                    f"/offer-mappings"
                )
            else:
                url = (
                    f"{YANDEX_MARKET_API}/campaigns/{self.campaign_id}"
                    f"/offer-mapping-entries"
                )

            params = {"page": page, "pageSize": limit}
            result = await self._request("GET", url, params=params)
            return result
        except Exception as e:
            logger.error(f"Yandex 拉取商品失败，shop_id={self.shop_id}: {e}")
            raise

    # ==================== 订单 (Market API) ====================

    async def fetch_orders(self, date_from: str, date_to: str) -> list:
        """拉取订单列表"""
        orders = []
        page = 1

        try:
            while True:
                url = (
                    f"{YANDEX_MARKET_API}/campaigns/{self.campaign_id}"
                    f"/orders"
                )
                params = {
                    "fromDate": date_from.replace("-", ""),  # Yandex用DDMMYYYY
                    "toDate": date_to.replace("-", ""),
                    "page": page,
                    "pageSize": 50,
                }
                # 实际上 Yandex 用 dd-MM-yyyy 格式
                params["fromDate"] = self._to_yandex_date(date_from)
                params["toDate"] = self._to_yandex_date(date_to)

                result = await self._request("GET", url, params=params)

                page_orders = result.get("orders", [])
                if not page_orders:
                    break

                orders.extend(page_orders)

                pager = result.get("pager", {})
                total_pages = pager.get("pagesCount", 1)
                if page >= total_pages:
                    break
                page += 1

        except Exception as e:
            logger.error(f"Yandex 拉取订单失败，shop_id={self.shop_id}: {e}")
            raise

        return orders

    @staticmethod
    def _to_yandex_date(iso_date: str) -> str:
        """ISO日期 → Yandex格式 dd-MM-yyyy"""
        parts = iso_date.split("-")
        if len(parts) == 3:
            return f"{parts[2]}-{parts[1]}-{parts[0]}"
        return iso_date

    # ==================== 库存 (Market API) ====================

    async def fetch_inventory(self) -> list:
        """拉取库存数据"""
        try:
            url = (
                f"{YANDEX_MARKET_API}/campaigns/{self.campaign_id}"
                f"/offers/stocks"
            )
            payload = {"pageSize": 200}
            result = await self._request("POST", url, json=payload)
            warehouses = result.get("result", {}).get("warehouses", [])
            return warehouses
        except Exception as e:
            logger.error(f"Yandex 拉取库存失败，shop_id={self.shop_id}: {e}")
            raise

    async def close(self):
        """关闭HTTP客户端"""
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()
        if self._direct_client and not self._direct_client.is_closed:
            await self._direct_client.aclose()


# 注册到工厂
PlatformClientFactory.register("yandex", YandexClient)
