"""Wildberries 平台 API 客户端

对接 WB 广告API和统计API，实现数据采集。
- 广告API: https://advert-api.wildberries.ru
- 统计API: https://statistics-api.wildberries.ru
- 内容API: https://content-api.wildberries.ru

认证方式: Authorization header 携带 API Key
"""

import asyncio
import time
from datetime import datetime, date, timedelta
from typing import Optional

import httpx

from app.config import get_settings
from app.services.platform.base import BasePlatformClient, PlatformClientFactory
from app.utils.logger import setup_logger

logger = setup_logger("platform.wb")
settings = get_settings()

# WB API 端点
WB_ADVERT_API = "https://advert-api.wildberries.ru"
WB_STATISTICS_API = "https://statistics-api.wildberries.ru"
WB_CONTENT_API = "https://content-api.wildberries.ru"
WB_COMMON_API = "https://common-api.wildberries.ru"

# 限速控制：两次请求之间的最小间隔(秒)
MIN_REQUEST_INTERVAL = 60.0 / settings.WB_RATE_LIMIT_PER_MINUTE


class WBClient(BasePlatformClient):
    """Wildberries 平台客户端"""

    def __init__(self, shop_id: int, api_key: str, **kwargs):
        super().__init__(shop_id=shop_id, api_key=api_key, **kwargs)
        self._last_request_time = 0.0
        self._http_client: Optional[httpx.AsyncClient] = None

    def _get_headers(self) -> dict:
        return {
            "Authorization": self.api_key,
            "Content-Type": "application/json",
        }

    async def _get_client(self) -> httpx.AsyncClient:
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                headers=self._get_headers(),
                timeout=httpx.Timeout(30.0, connect=10.0),
            )
        return self._http_client

    async def _rate_limit(self):
        """限速控制，防止被封"""
        now = time.monotonic()
        elapsed = now - self._last_request_time
        if elapsed < MIN_REQUEST_INTERVAL:
            await asyncio.sleep(MIN_REQUEST_INTERVAL - elapsed)
        self._last_request_time = time.monotonic()

    async def _request(self, method: str, url: str, **kwargs) -> dict:
        """统一请求方法，带限速和重试"""
        await self._rate_limit()
        client = await self._get_client()

        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = await client.request(method, url, **kwargs)

                if response.status_code == 429:
                    # 被限速，等待后重试
                    wait_time = min(30, 5 * (attempt + 1))
                    logger.warning(
                        f"WB API 限速(429)，shop_id={self.shop_id}，"
                        f"等待{wait_time}秒后重试 ({attempt+1}/{max_retries})"
                    )
                    await asyncio.sleep(wait_time)
                    continue

                response.raise_for_status()

                if response.status_code == 204 or not response.content:
                    return {}

                return response.json()

            except httpx.TimeoutException:
                logger.error(
                    f"WB API 超时，shop_id={self.shop_id}，url={url}，"
                    f"重试 ({attempt+1}/{max_retries})"
                )
                if attempt == max_retries - 1:
                    raise
                await asyncio.sleep(2 * (attempt + 1))

            except httpx.HTTPStatusError as e:
                logger.error(
                    f"WB API 错误，shop_id={self.shop_id}，"
                    f"status={e.response.status_code}，url={url}"
                )
                raise

        return {}

    # ==================== 连接测试 ====================

    async def test_connection(self) -> bool:
        """测试API连接 — 通过获取广告活动列表验证"""
        try:
            url = f"{WB_ADVERT_API}/adv/v1/promotion/count"
            result = await self._request("GET", url)
            logger.info(f"WB 连接测试成功，shop_id={self.shop_id}")
            return True
        except Exception as e:
            logger.error(f"WB 连接测试失败，shop_id={self.shop_id}: {e}")
            return False

    # ==================== 广告活动 ====================

    async def fetch_ad_campaigns(self) -> list:
        """拉取所有广告活动

        WB广告API流程：
        1. GET /adv/v1/promotion/count 获取各状态活动数量
        2. POST /adv/v1/promotion/adverts 按状态获取活动ID列表
        3. POST /adv/v1/promotion/adverts/info 获取活动详情（批量，最多50个）
        """
        campaigns = []

        try:
            # Step 1: 获取活动数量统计
            count_url = f"{WB_ADVERT_API}/adv/v1/promotion/count"
            count_data = await self._request("GET", count_url)

            if not count_data or "adverts" not in count_data:
                logger.info(f"WB shop_id={self.shop_id} 暂无广告活动")
                return []

            # Step 2: 遍历各状态获取活动ID
            all_campaign_ids = []
            for status_group in count_data.get("adverts", []):
                status = status_group.get("status")
                advert_list = status_group.get("advert_list", [])
                if advert_list:
                    for adv in advert_list:
                        adv_id = adv.get("advertId")
                        if adv_id:
                            all_campaign_ids.append(adv_id)

            if not all_campaign_ids:
                return []

            logger.info(
                f"WB shop_id={self.shop_id} 发现 {len(all_campaign_ids)} 个广告活动"
            )

            # Step 3: 批量获取活动详情（每批最多50个）
            info_url = f"{WB_ADVERT_API}/adv/v1/promotion/adverts"
            batch_size = 50
            for i in range(0, len(all_campaign_ids), batch_size):
                batch_ids = all_campaign_ids[i:i + batch_size]
                info_data = await self._request(
                    "POST", info_url,
                    json=batch_ids
                )
                if isinstance(info_data, list):
                    for item in info_data:
                        campaigns.append(self._parse_campaign(item))
                elif isinstance(info_data, dict) and info_data:
                    campaigns.append(self._parse_campaign(info_data))

        except Exception as e:
            logger.error(f"WB 拉取广告活动失败，shop_id={self.shop_id}: {e}")
            raise

        return campaigns

    def _parse_campaign(self, raw: dict) -> dict:
        """解析WB广告活动数据为标准格式"""
        # WB的type映射: 4=catalog, 5=product_page, 6=search, 7=recommendation, 8=search+catalog, 9=search+recommendation
        type_map = {
            4: "catalog",
            5: "product_page",
            6: "search",
            7: "recommendation",
            8: "search",
            9: "search",
        }
        # WB的status映射: -1=删除中, 4=就绪, 7=活跃, 8=结算中, 9=已暂停, 11=已暂停（预算不足）
        status_map = {
            4: "draft",
            7: "active",
            8: "active",
            9: "paused",
            11: "paused",
        }

        return {
            "platform_campaign_id": str(raw.get("advertId", "")),
            "name": raw.get("name", ""),
            "ad_type": type_map.get(raw.get("type"), "search"),
            "daily_budget": raw.get("dailyBudget"),
            "total_budget": None,
            "status": status_map.get(raw.get("status"), "paused"),
            "start_date": raw.get("createTime", "")[:10] if raw.get("createTime") else None,
            "end_date": raw.get("endTime", "")[:10] if raw.get("endTime") else None,
        }

    # ==================== 广告统计 ====================

    async def fetch_ad_stats(
        self, campaign_id: str, date_from: str, date_to: str
    ) -> list:
        """拉取指定广告活动的统计数据

        使用 /adv/v2/fullstats 接口，获取完整统计（展示/点击/花费/订单/收入）
        date_from/date_to 格式: "YYYY-MM-DD"

        返回标准化的统计数据列表，每条对应一天的数据。
        """
        stats = []

        try:
            url = f"{WB_ADVERT_API}/adv/v2/fullstats"
            payload = [
                {
                    "id": int(campaign_id),
                    "dates": [date_from, date_to],
                }
            ]
            result = await self._request("POST", url, json=payload)

            if not result:
                return []

            # 响应是一个列表，每个元素是一个campaign的统计
            if isinstance(result, list):
                for campaign_stats in result:
                    days = campaign_stats.get("days", [])
                    for day_data in days:
                        stat = self._parse_daily_stat(campaign_id, day_data)
                        if stat:
                            stats.append(stat)

        except Exception as e:
            logger.error(
                f"WB 拉取广告统计失败，shop_id={self.shop_id}，"
                f"campaign_id={campaign_id}: {e}"
            )
            raise

        return stats

    def _parse_daily_stat(self, campaign_id: str, day_data: dict) -> Optional[dict]:
        """解析每日统计数据为标准格式"""
        date_str = day_data.get("date", "")
        if not date_str:
            return None

        # 聚合该天下所有app的数据
        total_views = 0
        total_clicks = 0
        total_spend = 0.0
        total_orders = 0
        total_revenue = 0.0

        apps = day_data.get("apps", [])
        for app in apps:
            for nm in app.get("nm", []):
                total_views += nm.get("views", 0)
                total_clicks += nm.get("clicks", 0)
                total_spend += nm.get("sum", 0.0)
                total_orders += nm.get("orders", 0)
                total_revenue += nm.get("ordersSumRub", 0.0)

        # 计算衍生指标
        ctr = (total_clicks / total_views * 100) if total_views > 0 else 0
        cpc = (total_spend / total_clicks) if total_clicks > 0 else 0
        acos = (total_spend / total_revenue * 100) if total_revenue > 0 else 0
        roas = (total_revenue / total_spend) if total_spend > 0 else 0

        return {
            "campaign_id": campaign_id,
            "platform": "wb",
            "stat_date": date_str[:10],
            "stat_hour": None,  # 日级数据
            "impressions": total_views,
            "clicks": total_clicks,
            "spend": round(total_spend, 2),
            "orders": total_orders,
            "revenue": round(total_revenue, 2),
            "ctr": round(ctr, 4),
            "cpc": round(cpc, 2),
            "acos": round(acos, 4),
            "roas": round(roas, 4),
        }

    # ==================== 商品 ====================

    async def fetch_products(self, page: int = 1, limit: int = 100) -> dict:
        """拉取商品列表 (使用内容API)"""
        try:
            url = f"{WB_CONTENT_API}/content/v2/get/cards/list"
            payload = {
                "settings": {
                    "cursor": {"limit": limit},
                    "filter": {"withPhoto": -1},
                }
            }
            result = await self._request("POST", url, json=payload)
            return result
        except Exception as e:
            logger.error(f"WB 拉取商品失败，shop_id={self.shop_id}: {e}")
            raise

    # ==================== 订单 ====================

    async def fetch_orders(self, date_from: str, date_to: str) -> list:
        """拉取订单数据（统计API）"""
        try:
            url = f"{WB_STATISTICS_API}/api/v1/supplier/orders"
            params = {"dateFrom": date_from}
            result = await self._request("GET", url, params=params)
            if isinstance(result, list):
                return result
            return []
        except Exception as e:
            logger.error(f"WB 拉取订单失败，shop_id={self.shop_id}: {e}")
            raise

    # ==================== 库存 ====================

    async def fetch_inventory(self) -> list:
        """拉取库存/仓库数据"""
        try:
            url = f"{WB_STATISTICS_API}/api/v1/supplier/stocks"
            params = {"dateFrom": "2020-01-01"}
            result = await self._request("GET", url, params=params)
            if isinstance(result, list):
                return result
            return []
        except Exception as e:
            logger.error(f"WB 拉取库存失败，shop_id={self.shop_id}: {e}")
            raise

    async def close(self):
        """关闭HTTP客户端"""
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()


# 注册到工厂
PlatformClientFactory.register("wb", WBClient)
