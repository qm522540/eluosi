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
from app.services.platform.base import (
    BasePlatformClient,
    PlatformClientFactory,
    SubscriptionRequiredError,
)
from app.utils.logger import setup_logger

logger = setup_logger("platform.ozon")
settings = get_settings()

# Ozon API 端点
OZON_SELLER_API = "https://api-seller.ozon.ru"
OZON_PERFORMANCE_API = "https://api-performance.ozon.ru"

MIN_REQUEST_INTERVAL = 60.0 / settings.OZON_RATE_LIMIT_PER_MINUTE


def _extract_ozon_min_bid(
    limits_resp: dict,
    category: Optional[str] = None,
    placement: Optional[str] = None,
    payment_method: str = "CPC",
) -> Optional[float]:
    """从 /api/client/limits/list 响应里提取最低出价（卢布）

    实际响应结构（2026-04-16 实测）：
      {"limits": [
        {"objectType": "SKU",
         "paymentMethod": "CPC",
         "placement": "CAMPAIGN_PLACEMENT_SEARCH_AND_CATEGORY",
         "minBid": 7, "maxBid": 200,
         "categories": [
           {"category": "Ванная комната", "bid": 7}, ...
         ]}, ...
      ]}

    参数：
      category: 传品类名时，从 categories[] 里找匹配的 bid；否则用组级 minBid
      placement: 指定 placement 筛选；不传就用所有组里最低的
      payment_method: CPC / CPM，默认 CPC（符合当前 Ozon 主流）
    """
    if not isinstance(limits_resp, dict):
        return None
    groups = limits_resp.get("limits") or []
    candidates = []
    for grp in groups:
        if grp.get("paymentMethod") != payment_method:
            continue
        if placement is not None and grp.get("placement") != placement:
            continue

        # 优先找品类匹配的 bid
        if category is not None:
            for cat in grp.get("categories") or []:
                if str(cat.get("category") or "") == str(category):
                    try:
                        candidates.append(float(cat.get("bid")))
                    except (TypeError, ValueError):
                        pass
                    break
        else:
            # 没传品类就用组级 minBid 兜底
            min_bid = grp.get("minBid")
            if min_bid is not None:
                try:
                    candidates.append(float(min_bid))
                except (TypeError, ValueError):
                    pass

    if not candidates:
        return None
    return min(candidates)


def filter_returns_by_city(returns_list: list, city_map: dict,
                           date_from: str, date_to: str):
    """从预拉的 returns_list 按窗口过滤 + 按 city_map 反查聚合。纯函数不走网络。

    用于 backfill 场景：先一次性拉齐 returns + posting map，按天循环时反复调用此函数。

    Returns: (city_to_count_dict, windowed_total, unknown_count)
    """
    from datetime import date as _date
    d_from = _date.fromisoformat(date_from)
    d_to = _date.fromisoformat(date_to)
    out: dict = {}
    windowed = 0
    unknown = 0
    for item in returns_list:
        rd = (item.get("logistic") or {}).get("return_date") or ""
        if not rd:
            continue
        try:
            rd_date = _date.fromisoformat(rd[:10])
        except ValueError:
            continue
        if not (d_from <= rd_date <= d_to):
            continue
        windowed += 1
        pn = item.get("posting_number") or ""
        city = city_map.get(pn)
        if not city:
            unknown += 1
            continue
        out[city] = out.get(city, 0) + 1
    return out, windowed, unknown


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
        logger.info(f"Ozon client init: shop_id={self.shop_id}, has_perf={'yes' if self.perf_client_id else 'no'}")

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

        # Performance API 的 statistics 接口限速远比 Seller API 严（估计每分钟 3-5 次）
        # 老策略 5/10/15 秒三次就放弃，根本熬不过一个窗口
        is_perf_heavy = use_perf and "/api/client/statistics" in url
        max_retries = 6 if is_perf_heavy else 3
        backoff = [15, 30, 60, 90, 120, 180] if is_perf_heavy else [5, 10, 15]

        for attempt in range(max_retries):
            try:
                response = await client.request(method, url, **kwargs)

                if response.status_code == 429:
                    # 优先用服务端给的 Retry-After
                    retry_after = response.headers.get("Retry-After")
                    wait_time = int(retry_after) if retry_after and retry_after.isdigit() else backoff[min(attempt, len(backoff) - 1)]
                    logger.warning(
                        f"Ozon API 限速(429)，shop_id={self.shop_id}，"
                        f"等待{wait_time}秒 ({attempt+1}/{max_retries}) url={url.rsplit('/', 1)[-1]}"
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
                try:
                    body = e.response.text[:500]
                except Exception:
                    body = "<no body>"
                logger.error(
                    f"Ozon API 错误，shop_id={self.shop_id}，"
                    f"status={e.response.status_code}，url={url}，"
                    f"body={body}"
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
            "CAMPAIGN_STATE_FINISHED": "archived",
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

        # 付费类型：Ozon 字段 paymentType（CPC/CPO/CPM）
        raw_pt = (raw.get("paymentType") or raw.get("payment_type") or "CPC").upper()
        payment_type = raw_pt.lower() if raw_pt.lower() in ("cpc", "cpm", "cpo") else "cpc"

        return {
            "platform_campaign_id": campaign_id,
            "name": name,
            "ad_type": ad_type,
            "payment_type": payment_type,
            "daily_budget": daily_budget,
            "total_budget": total_budget,
            "status": state_map.get(state_raw, "paused"),
            "start_date": start_date[:10] if start_date else None,
            "end_date": end_date[:10] if end_date else None,
        }

    # ==================== 广告统计 ====================

    async def fetch_ad_stats(
        self, campaign_id, date_from: str, date_to: str
    ) -> list:
        """拉取广告活动统计数据（Performance API 异步统计流程）

        Args:
            campaign_id: 单个活动ID (str) 或多个活动ID列表 (list[str])
            date_from: 起始日期 YYYY-MM-DD
            date_to: 结束日期 YYYY-MM-DD

        流程：
        1. POST /api/client/statistics → 提交异步任务得到 UUID
        2. GET /api/client/statistics/{UUID} → 轮询直到 state=OK（最多60秒）
        3. 解析 rows 返回标准格式（每行含 campaignId 用于区分活动）

        注：Seller API 被 Ozon WAF 拦截，全部走 Performance API。
        """
        import asyncio as _asyncio

        # 支持传单个ID或列表
        if isinstance(campaign_id, list):
            campaign_ids = [str(c) for c in campaign_id]
        else:
            campaign_ids = [str(campaign_id)]

        await self._ensure_perf_token()

        # Step 1: 提交异步统计请求（一次性传所有活动ID）
        try:
            submit = await self._request(
                "POST",
                f"{OZON_PERFORMANCE_API}/api/client/statistics",
                use_perf=True,
                json={
                    "campaigns": campaign_ids,
                    "dateFrom": date_from,
                    "dateTo": date_to,
                    "groupBy": "DATE",
                },
            )
        except Exception as e:
            logger.error(f"Ozon 统计提交失败 shop_id={self.shop_id}: {e}")
            return []

        uuid = submit.get("UUID")
        if not uuid:
            logger.warning(f"Ozon 统计接口未返回 UUID: {submit}")
            return []

        # Step 2: 轮询结果（最多等 60 秒）
        result = None
        for attempt in range(12):
            await _asyncio.sleep(5)
            try:
                data = await self._request(
                    "GET",
                    f"{OZON_PERFORMANCE_API}/api/client/statistics/{uuid}",
                    use_perf=True,
                )
            except Exception as e:
                logger.warning(f"Ozon 统计轮询失败 attempt={attempt+1}: {e}")
                continue

            state = data.get("state", "")
            if state == "OK":
                result = data
                break
            elif state in ("ERROR", "FAILED"):
                logger.error(f"Ozon 统计任务失败 UUID={uuid}: {data}")
                return []

        if not result:
            logger.warning(f"Ozon 统计超时 UUID={uuid} shop_id={self.shop_id}")
            return []

        # Step 3: 解析结果
        stats = []
        rows = result.get("rows") or []
        for row in rows:
            # 每行有 campaignId 字段区分来源活动
            cid = str(row.get("campaignId") or campaign_ids[0])
            stat = self._parse_daily_stat(cid, row)
            if stat:
                stats.append(stat)

        logger.info(f"Ozon 统计完成: {len(campaign_ids)}个活动 → {len(stats)}条数据")
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

            return products
        except Exception as e:
            logger.error(f"Ozon 获取活动商品失败 campaign_id={campaign_id}: {e}")
            return []

    async def remove_campaign_product(self, campaign_id: str, sku: str) -> dict:
        """从 Ozon 广告活动中移除指定商品

        Performance API: POST /api/client/campaign/{id}/products/delete
        Body: {"skus": ["sku_id"]}
        """
        await self._ensure_perf_token()
        try:
            url = f"{OZON_PERFORMANCE_API}/api/client/campaign/{campaign_id}/products/delete"
            await self._request("POST", url, use_perf=True, json={"skus": [str(sku)]})
            logger.info(f"Ozon 移除商品成功 campaign={campaign_id} sku={sku}")
            return {"ok": True}
        except Exception as e:
            logger.error(f"Ozon 移除商品失败 campaign={campaign_id} sku={sku}: {e}")
            return {"ok": False, "error": str(e)}

    async def update_campaign_bid(self, campaign_id: str, sku: str, new_bid: str) -> dict:
        """修改广告活动中商品的出价（支持最低出价自动兜底重试）

        Performance API:
        PUT /api/client/campaign/{id}/products  body: {"bids":[{"sku":"...","bid":"..."}]}

        策略（对齐 WB update_campaign_cpm 行为）：
          1. 第一次用 AI 建议值尝试
          2. 若 Ozon 返回 "min"/"minimum"/"too low" 类错误，正则提取 min 值
          3. 用 min 值重试一次
          4. 如果错误里没 min 值，fallback 调 /api/client/limits/list 拿类目最低，再重试
          5. 仍失败 → 返回错误

        new_bid 单位：micro-rubles（整数字符串），和 AI executor 里的换算一致

        返回 {"ok": bool, "error": str|None, "actual_bid_rub": float}
        """
        import re as _re

        await self._ensure_perf_token()
        if not self._perf_token:
            return {"ok": False, "error": "no_perf_token"}

        url = f"{OZON_PERFORMANCE_API}/api/client/campaign/{campaign_id}/products"
        attempt_bid = str(new_bid)
        last_error = ""

        for attempt in range(2):
            try:
                payload = {"bids": [{"sku": str(sku), "bid": attempt_bid}]}
                result = await self._request("PUT", url, use_perf=True, json=payload)
                actual_bid_rub = int(attempt_bid) / 1_000_000
                logger.info(
                    f"Ozon 出价修改成功 campaign={campaign_id} sku={sku} "
                    f"bid_micro={attempt_bid} actual_rub={actual_bid_rub} "
                    f"attempt={attempt} result={result}"
                )
                return {
                    "ok": True,
                    "error": None,
                    "actual_bid_rub": actual_bid_rub,
                }
            except Exception as e:
                err_str = str(e)
                last_error = err_str
                logger.warning(
                    f"Ozon 出价修改失败 attempt={attempt} "
                    f"campaign={campaign_id} sku={sku} bid={attempt_bid}: {err_str}"
                )

                if attempt >= 1:
                    break

                # ① 从错误信息正则提取 min（可能以 micro-rubles 或卢布出现）
                min_match = _re.search(
                    r'min[^\d]{0,20}(\d+)', err_str, _re.IGNORECASE
                )
                if min_match:
                    min_val = min_match.group(1)
                    # 启发式：<=1000 视为卢布，否则 micro-rubles
                    if int(min_val) <= 1000:
                        attempt_bid = str(int(min_val) * 1_000_000)
                    else:
                        attempt_bid = str(min_val)
                    logger.warning(
                        f"Ozon 出价低于最低 → 从错误里提取 min={min_val}，"
                        f"自动用最低值重试 (micro={attempt_bid})"
                    )
                    continue

                # ② 错误里没 min，调 /api/client/limits/list 拿类目最低
                try:
                    limits_url = f"{OZON_PERFORMANCE_API}/api/client/limits/list"
                    limits_resp = await self._request("GET", limits_url, use_perf=True)
                    min_rub = _extract_ozon_min_bid(limits_resp, category=None)
                    if min_rub and min_rub > 0:
                        attempt_bid = str(int(min_rub * 1_000_000))
                        logger.warning(
                            f"Ozon 出价低于最低 → /limits/list 返回 min={min_rub}₽，"
                            f"自动用最低值重试 (micro={attempt_bid})"
                        )
                        continue
                except Exception as fetch_err:
                    logger.warning(f"Ozon /limits/list 查询失败: {fetch_err}")

                # ③ 没法兜底，退出
                break

        return {"ok": False, "error": last_error or "Ozon 出价修改失败"}

    # ==================== 商品 ====================

    async def fetch_products(self, last_id: str = "", limit: int = 1000) -> dict:
        """拉取商品列表（v3），只含 product_id/offer_id/stocks/archived
        返回 {"result": {"items": [...], "total": N, "last_id": "cursor"}}
        分页：用返回的 last_id 再传回来直到 items 为空或 last_id 为空
        """
        try:
            url = f"{OZON_SELLER_API}/v3/product/list"
            payload = {
                "filter": {"visibility": "ALL"},
                "last_id": last_id,
                "limit": limit,
            }
            result = await self._request("POST", url, json=payload)
            return result
        except Exception as e:
            logger.error(f"Ozon 拉取商品失败，shop_id={self.shop_id}: {e}")
            raise

    async def fetch_product_info(self, product_ids: list) -> list:
        """批量拉取商品详情（v3）。单次最多 1000 个 product_id
        返回 items 列表；每项含 id/name/price/old_price/images/primary_image/barcodes/is_archived/...
        """
        if not product_ids:
            return []
        try:
            url = f"{OZON_SELLER_API}/v3/product/info/list"
            payload = {
                "product_id": [int(pid) for pid in product_ids],
                "offer_id": [],
                "sku": [],
            }
            result = await self._request("POST", url, json=payload)
            return (result or {}).get("result", {}).get("items", []) or result.get("items", [])
        except Exception as e:
            logger.error(f"Ozon 拉取商品详情失败，shop_id={self.shop_id}: {e}")
            raise

    async def fetch_product_description(self, product_id) -> Optional[str]:
        """拉单个商品描述。

        API: POST /v1/product/info/description
        body: {"product_id": <int>}
        response: {"result": {"id": ..., "offer_id": ..., "name": ..., "description": "..."}}

        Ozon 的 v3/product/info/list 不返 description, 必须走这个单独接口。
        失败返 None (上层兜底,不影响主流程)。
        """
        if not product_id:
            return None
        try:
            url = f"{OZON_SELLER_API}/v1/product/info/description"
            result = await self._request("POST", url, json={"product_id": int(product_id)})
            res = (result or {}).get("result") or {}
            desc = res.get("description")
            return desc if desc else None
        except Exception as e:
            logger.warning(f"Ozon 拉描述失败 shop={self.shop_id} pid={product_id}: {e}")
            return None

    async def fetch_product_descriptions_batch(
        self, product_ids: list, concurrency: int = 30,
    ) -> dict:
        """并发拉一批商品描述,返回 {product_id: description_str}。

        concurrency 控制 Ozon API 并发上限,默认 30。850 商品 ~30s 跑完。
        部分失败不抛,返 dict 中缺失对应 pid 即可。
        """
        if not product_ids:
            return {}
        sem = asyncio.Semaphore(concurrency)
        results: dict = {}

        async def _one(pid):
            async with sem:
                desc = await self.fetch_product_description(pid)
                if desc:
                    results[int(pid)] = desc

        await asyncio.gather(*[_one(p) for p in product_ids], return_exceptions=True)
        return results

    async def update_product_name(self, offer_id: str, new_name: str) -> dict:
        """改商品名(标题), 走 /v1/product/attributes/update 异步任务。

        body 只传 offer_id + attributes 数组, attribute_id=4180 是 "Название товара"。
        其它属性不动。返回 {task_id} 或 {error}。
        task_id 可用 /v1/product/import/info 查状态, 1-5 分钟生效。
        """
        if not offer_id or not new_name:
            return {"error": "offer_id 或 new_name 为空"}
        url = f"{OZON_SELLER_API}/v1/product/attributes/update"
        # attribute_id=4180 是 "Название товара" (商品名)
        body = {
            "items": [{
                "offer_id": str(offer_id),
                "attributes": [{
                    "id": 4180,
                    "values": [{"value": new_name[:500]}],
                }],
            }],
        }
        try:
            result = await self._request("POST", url, json=body)
            task_id = (result or {}).get("result", {}).get("task_id")
            if task_id:
                logger.info(f"Ozon 改商品名 task_id={task_id} offer={offer_id}")
                return {"task_id": task_id}
            return {"error": "Ozon 未返 task_id", "raw": result}
        except Exception as e:
            logger.error(f"Ozon 改商品名失败 offer={offer_id}: {e}")
            return {"error": f"{type(e).__name__}: {str(e)[:120]}"}

    async def fetch_product_attributes_batch(
        self, product_ids: list, batch_size: int = 100,
    ) -> dict:
        """批量拉商品属性,返回 {product_id: [{id, values:[{value}]}, ...]}。

        API: POST /v4/product/info/attributes
        body: {"filter": {"product_id": [...], "visibility": "ALL"}, "limit": 100, "last_id": ""}
        每次最多 1000 product_id,但属性大时返回包很大,按 100 一批稳。

        部分失败 (网络 / 单批 5xx) 不抛,继续其余批次。
        AI 描述生成靠这字段,所以对接调用方应在 sync 时调一次。
        """
        if not product_ids:
            return {}
        url = f"{OZON_SELLER_API}/v4/product/info/attributes"
        results: dict = {}
        for i in range(0, len(product_ids), batch_size):
            chunk = [str(p) for p in product_ids[i:i + batch_size]]
            try:
                # 大商品 (~100 个 attr_id) 单批 100 商品 ~5MB,limit 给足,last_id 走分页
                last_id = ""
                for _ in range(20):  # 最多 20 页 (单批理论上 1 页就够)
                    body = {
                        "filter": {"product_id": chunk, "visibility": "ALL"},
                        "limit": 1000,
                        "last_id": last_id,
                    }
                    resp = await self._request("POST", url, json=body)
                    items = (resp or {}).get("result") or []
                    for it in items:
                        pid = it.get("id") or it.get("product_id")
                        if not pid:
                            continue
                        attrs = it.get("attributes") or []
                        if attrs:
                            results[int(pid)] = attrs
                    next_id = (resp or {}).get("last_id") or ""
                    if not next_id or next_id == last_id:
                        break
                    last_id = next_id
            except Exception as e:
                logger.warning(
                    f"Ozon 属性批量拉取失败 shop={self.shop_id} batch[{i}:{i+batch_size}]: {e}"
                )
        return results

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

    # ==================== 地区销售 ====================

    async def fetch_region_sales(self, date_from: str, date_to: str,
                                 delivered_only: bool = True) -> list:
        """按 city 聚合地区销售（Ozon analytics/data 不支持 region dimension，
        只能从 posting 的 analytics_data.city 聚合）。

        口径（与 WB region-sale 有差异，用户需知）：
        - region_name 实际是 city（城市级，WB 是联邦主体级）
        - delivered_only=True（默认）：只算 status=delivered 的 posting（真实销售口径）
        - delivered_only=False：算所有非 cancelled 的 posting（含在途，偏乐观）
        - revenue = products.price × quantity 汇总
        - returns 不在本接口（需另一个 /returns API，当前返回 0）

        Returns: [{region_name, orders, revenue}]
        """
        try:
            url = f"{OZON_SELLER_API}/v2/posting/fbo/list"
            all_postings = []
            offset = 0
            for _ in range(20):
                payload = {
                    "dir": "ASC",
                    "filter": {
                        "since": f"{date_from}T00:00:00.000Z",
                        "to": f"{date_to}T23:59:59.999Z",
                        "status": "",
                    },
                    "limit": 1000, "offset": offset,
                    "with": {"analytics_data": True, "financial_data": True},
                }
                r = await self._request("POST", url, json=payload)
                items = (r or {}).get("result") or []
                if not items:
                    break
                all_postings.extend(items)
                if len(items) < 1000:
                    break
                offset += 1000

            agg: dict = {}
            kept = 0
            for p in all_postings:
                status = p.get("status") or ""
                if delivered_only:
                    if status != "delivered":
                        continue
                elif status == "cancelled":
                    continue
                city = ((p.get("analytics_data") or {}).get("city") or "").strip()
                if not city:
                    continue
                rev = 0.0
                for prod in (p.get("products") or []):
                    try:
                        rev += float(prod.get("price") or 0) * int(prod.get("quantity") or 0)
                    except (TypeError, ValueError):
                        continue
                if city not in agg:
                    agg[city] = {"region_name": city, "orders": 0, "revenue": 0.0}
                agg[city]["orders"] += 1
                agg[city]["revenue"] += rev
                kept += 1
            items_out = [v for v in agg.values() if v["orders"] > 0 or v["revenue"] > 0]
            for v in items_out:
                v["revenue"] = round(v["revenue"], 2)
            logger.info(
                f"Ozon 地区销售 {date_from}~{date_to}: {len(items_out)} 城市 / "
                f"保留 {kept}/{len(all_postings)} postings "
                f"(delivered_only={delivered_only})"
            )
            return items_out
        except Exception as e:
            logger.error(f"Ozon 地区销售拉取失败 shop_id={self.shop_id}: {e}")
            return []

    async def fetch_region_sales_by_sku(self, date_from: str, date_to: str,
                                        city_name: str = None,
                                        delivered_only: bool = True) -> list:
        """按 city × sku 双维度聚合 FBO posting 销售（Ozon 版 region TOP SKU）。

        口径与 fetch_region_sales 一致：默认 delivered_only=True（只算已妥投）。
        city_name 传入则仅返回该城市；不传返回全部。

        Returns: [{region_name (city), sku_id (Ozon), offer_id (商家编码),
                   orders (商品件数), revenue}]
        """
        try:
            url = f"{OZON_SELLER_API}/v2/posting/fbo/list"
            all_postings = []
            offset = 0
            for _ in range(20):
                payload = {
                    "dir": "ASC",
                    "filter": {
                        "since": f"{date_from}T00:00:00.000Z",
                        "to": f"{date_to}T23:59:59.999Z",
                        "status": "",
                    },
                    "limit": 1000, "offset": offset,
                    "with": {"analytics_data": True, "financial_data": True},
                }
                r = await self._request("POST", url, json=payload)
                items = (r or {}).get("result") or []
                if not items:
                    break
                all_postings.extend(items)
                if len(items) < 1000:
                    break
                offset += 1000

            agg: dict = {}
            for p in all_postings:
                status = p.get("status") or ""
                if delivered_only:
                    if status != "delivered":
                        continue
                elif status == "cancelled":
                    continue
                city = ((p.get("analytics_data") or {}).get("city") or "").strip()
                if not city:
                    continue
                if city_name and city != city_name:
                    continue
                for prod in (p.get("products") or []):
                    sku_id = prod.get("sku")
                    if sku_id is None:
                        continue
                    try:
                        qty = int(prod.get("quantity") or 0)
                        rev = float(prod.get("price") or 0) * qty
                    except (TypeError, ValueError):
                        continue
                    offer_id = prod.get("offer_id") or ""
                    key = (city, str(sku_id))
                    if key not in agg:
                        agg[key] = {
                            "region_name": city, "sku_id": str(sku_id),
                            "offer_id": offer_id, "orders": 0, "revenue": 0.0,
                        }
                    agg[key]["orders"] += qty
                    agg[key]["revenue"] += rev
            items_out = [v for v in agg.values() if v["orders"] > 0 or v["revenue"] > 0]
            for v in items_out:
                v["revenue"] = round(v["revenue"], 2)
            return items_out
        except Exception as e:
            logger.error(f"Ozon 按 SKU 拉地区销售失败 shop_id={self.shop_id}: {e}")
            return []

    async def fetch_returns_list(self, max_pages: int = 30) -> list:
        """拉取 FBO 退货列表（/v1/returns/list）。

        重要坑点：该接口的 filter 字段**全部无效**（传 logistic_return_date/since 等
        都被忽略不报错）。排序按 id ASC（最早退货先返回），只能全量拉后在 Python
        侧按 logistic.return_date 过滤。店铺级退货通常 <5000 条，可接受。

        Returns: 原始退货列表
        """
        try:
            url = f"{OZON_SELLER_API}/v1/returns/list"
            all_returns = []
            last_id = 0
            for _ in range(max_pages):
                payload = {"filter": {}, "limit": 500, "last_id": last_id}
                r = await self._request("POST", url, json=payload)
                rets = (r or {}).get("returns") or []
                if not rets:
                    break
                all_returns.extend(rets)
                last_id = rets[-1].get("id") or 0
                if not (r or {}).get("has_next"):
                    break
            return all_returns
        except Exception as e:
            logger.error(f"Ozon 拉取退货列表失败 shop_id={self.shop_id}: {e}")
            return []

    async def build_posting_city_map(self, date_from: str, date_to: str) -> dict:
        """拉 FBO posting 建 {posting_number: city} 反查表。

        用于退货按 city 聚合——因 /v1/returns/list 不返回 city。
        窗口应覆盖"退货日期前 30-45 天下单的 posting"，调用方自行设置。
        """
        try:
            url = f"{OZON_SELLER_API}/v2/posting/fbo/list"
            mp = {}
            offset = 0
            for _ in range(20):
                payload = {
                    "dir": "ASC",
                    "filter": {
                        "since": f"{date_from}T00:00:00.000Z",
                        "to": f"{date_to}T23:59:59.999Z",
                        "status": "",
                    },
                    "limit": 1000, "offset": offset,
                    "with": {"analytics_data": True},
                }
                r = await self._request("POST", url, json=payload)
                items = (r or {}).get("result") or []
                if not items:
                    break
                for p in items:
                    pn = p.get("posting_number") or ""
                    city = ((p.get("analytics_data") or {}).get("city") or "").strip()
                    if pn and city:
                        mp[pn] = city
                if len(items) < 1000:
                    break
                offset += 1000
            return mp
        except Exception as e:
            logger.error(f"Ozon 建 posting-city map 失败 shop_id={self.shop_id}: {e}")
            return {}

    async def fetch_returns_by_city(self, date_from: str, date_to: str,
                                    lookback_days: int = 60) -> dict:
        """按 city 聚合窗口内退货数（Ozon 版，对齐 WB fetch_sales_returns_by_region）。

        - date_from/date_to 是退货日期窗口（按 logistic.return_date 过滤）
        - lookback_days：posting 反查窗口起点向前延多少天（退货通常订单后 7-30 天，
          给 60 天冗余确保覆盖）
        - 无法反查 city 的退货会丢（log 中 count 出来）

        Returns: {city: returns_count}
        """
        from datetime import date, timedelta
        d_from = date.fromisoformat(date_from)

        # 1) 拉全量 returns + posting map
        all_rets = await self.fetch_returns_list()
        posting_from = (d_from - timedelta(days=lookback_days)).isoformat()
        city_map = await self.build_posting_city_map(posting_from, date_to)

        # 2) 按日期 + city 聚合
        out, windowed_cnt, unknown = filter_returns_by_city(
            all_rets, city_map, date_from, date_to)
        logger.info(
            f"Ozon 退货按 city 聚合 {date_from}~{date_to}: "
            f"{windowed_cnt} 条退货 / {len(out)} 城市 / {unknown} 条无法反查 city "
            f"(posting map 覆盖 {len(city_map)} 条)"
        )
        return out

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

    # ==================== 佣金 ====================

    async def fetch_commissions(self, product_ids: list) -> dict:
        """批量拉佣金率（v5/product/info/prices）。
        返回 {product_id: commission_percent}，取 FBO/FBS 中较高值（更严格）。
        API: POST /v5/product/info/prices
        """
        if not product_ids:
            return {}
        result_map: dict = {}
        try:
            url = f"{OZON_SELLER_API}/v5/product/info/prices"
            cursor = ""
            for _ in range(20):
                payload = {
                    "filter": {
                        "product_id": [str(pid) for pid in product_ids],
                        "visibility": "ALL",
                    },
                    "cursor": cursor,
                    "limit": 1000,
                }
                result = await self._request("POST", url, json=payload)
                items = (result or {}).get("items") or (result or {}).get("result", {}).get("items") or []
                for it in items:
                    pid = it.get("product_id")
                    commissions = it.get("commissions") or {}
                    fbo = commissions.get("sales_percent_fbo") or commissions.get("fbo_sales_percent")
                    fbs = commissions.get("sales_percent_fbs") or commissions.get("fbs_sales_percent")
                    rate = None
                    for v in (fbo, fbs):
                        try:
                            fv = float(v)
                            if rate is None or fv > rate:
                                rate = fv
                        except (TypeError, ValueError):
                            continue
                    if pid and rate is not None:
                        result_map[int(pid)] = rate
                cursor = (result or {}).get("cursor") or ""
                if not cursor:
                    break
            return result_map
        except Exception as e:
            logger.warning(f"Ozon 拉取佣金失败 shop_id={self.shop_id}: {e}")
            return {}

    # ==================== 分类/属性（用于铺货映射） ====================

    async def fetch_category_tree(self, language: str = "DEFAULT") -> list:
        """拉取 Ozon 分类树（description-category）

        返回格式：树形结构，叶子节点含 type_id（铺货时必须用 type_id）
        [{description_category_id, category_name, disabled, children: [
            {type_id, type_name, disabled, children: [...]}
         ]}, ...]
        API: POST /v1/description-category/tree
        """
        try:
            url = f"{OZON_SELLER_API}/v1/description-category/tree"
            payload = {"language": language}
            result = await self._request("POST", url, json=payload)
            return (result or {}).get("result") or []
        except Exception as e:
            logger.error(f"Ozon 拉取分类树失败，shop_id={self.shop_id}: {e}")
            raise

    async def fetch_category_attributes(
        self, description_category_id: int, type_id: int,
        language: str = "DEFAULT"
    ) -> list:
        """拉取 Ozon 分类的属性定义

        返回格式：[{id, name, description, type, is_collection, is_required,
                   dictionary_id, group_id, category_dependent}, ...]
        dictionary_id != 0 时是枚举类型，需要再调 attribute/values 拉枚举值
        API: POST /v1/description-category/attribute
        """
        try:
            url = f"{OZON_SELLER_API}/v1/description-category/attribute"
            payload = {
                "description_category_id": description_category_id,
                "type_id": type_id,
                "language": language,
            }
            result = await self._request("POST", url, json=payload)
            return (result or {}).get("result") or []
        except Exception as e:
            logger.error(
                f"Ozon 拉取分类属性失败 cat={description_category_id} type={type_id}: {e}"
            )
            raise

    async def fetch_attribute_values(
        self, description_category_id: int, type_id: int, attribute_id: int,
        limit: int = 500, language: str = "DEFAULT"
    ) -> list:
        """拉取 Ozon 属性的枚举值（按字典）

        返回格式：[{id, value, info?, picture?}, ...]
        支持 last_value_id 游标分页，这里一次拉到尽（limit=500）
        API: POST /v1/description-category/attribute/values
        """
        try:
            url = f"{OZON_SELLER_API}/v1/description-category/attribute/values"
            all_values = []
            last_value_id = 0
            for _ in range(20):  # 最多 20 页 = 1 万枚举值
                payload = {
                    "description_category_id": description_category_id,
                    "type_id": type_id,
                    "attribute_id": attribute_id,
                    "last_value_id": last_value_id,
                    "limit": limit,
                    "language": language,
                }
                result = await self._request("POST", url, json=payload)
                values = (result or {}).get("result") or []
                if not values:
                    break
                all_values.extend(values)
                has_next = (result or {}).get("has_next", False)
                if not has_next:
                    break
                last_value_id = values[-1].get("id", 0)
                if not last_value_id:
                    break
            return all_values
        except Exception as e:
            logger.error(
                f"Ozon 拉取属性值失败 attr_id={attribute_id}: {e}"
            )
            raise

    # ==================== 搜索词洞察（SEO流量）====================

    async def fetch_product_queries_details(
        self,
        skus: list,
        date_from: str,
        date_to: str,
        limit_by_sku: int = 15,
        sort_by: str = "gmv",
        sort_dir: str = "DESC",
    ) -> list:
        """拉取"用户搜哪些词点进了指定 SKU"（词粒度）

        API: POST /v1/analytics/product-queries/details
        需要 Ozon Premium 订阅；无订阅返回 403 "available starting from the premium subscription"。

        Args:
            skus: Ozon SKU 字符串列表（≤ 50）
            date_from / date_to: YYYY-MM-DD —— 内部自动转 RFC3339
            limit_by_sku: 每个 SKU 返回的 TOP N 词，范围 (0, 15]
            sort_by / sort_dir: 排序字段与方向

        Returns:
            [{sku, query, frequency, impressions, clicks, add_to_cart,
              orders, revenue, view_conversion, extra}, ...]

        Raises:
            SubscriptionRequiredError: 店铺未开通 Premium
        """
        if not skus:
            return []
        url = f"{OZON_SELLER_API}/v1/analytics/product-queries/details"
        # Ozon 要求 RFC3339 timestamp，不是纯日期
        df = f"{date_from}T00:00:00Z" if "T" not in date_from else date_from
        dt_ = f"{date_to}T00:00:00Z" if "T" not in date_to else date_to
        base_payload = {
            "date_from": df,
            "date_to": dt_,
            "skus": [str(s) for s in skus[:50]],
            "limit_by_sku": max(1, min(int(limit_by_sku), 15)),
            "page_size": 100,
            "sort_by": sort_by,
            "sort_dir": sort_dir,
        }

        # 实测响应结构（2026-04-19）：
        # {"analytics_period":{...}, "queries":[{sku, query, unique_search_users,
        #   unique_view_users, gmv, order_count, view_conversion, position,
        #   query_index, currency}, ...], "total": N, "page_count": M}
        # 分页必要：total 远大于 page_size 时需循环
        out = []
        page = 1
        max_pages = 50  # 硬上限防失控
        while page <= max_pages:
            payload = dict(base_payload, page=page)
            try:
                result = await self._request("POST", url, json=payload)
            except httpx.HTTPStatusError as e:
                status = e.response.status_code
                body = ""
                try:
                    body = e.response.text or ""
                except Exception:
                    pass
                if status == 403 and ("premium" in body.lower() or "PermissionDenied" in body):
                    raise SubscriptionRequiredError("ozon", body[:200])
                logger.warning(
                    f"Ozon product-queries/details 失败 shop_id={self.shop_id} page={page}: "
                    f"status={status} body={body[:200]}"
                )
                break
            except Exception as e:
                logger.warning(
                    f"Ozon product-queries/details 异常 shop_id={self.shop_id} page={page}: {e}"
                )
                break

            items = (result.get("queries") if isinstance(result, dict) else None) or []
            if not items:
                break

            for q in items:
                if not isinstance(q, dict):
                    continue
                sku = q.get("sku")
                out.append({
                    "sku": str(sku) if sku is not None else "",
                    "query": q.get("query") or "",
                    "frequency": int(q.get("unique_search_users") or 0),
                    "impressions": int(q.get("unique_view_users") or 0),
                    "clicks": 0,  # Ozon product-queries/details 不返点击
                    "add_to_cart": 0,  # Ozon product-queries/details 不返加购
                    "orders": int(q.get("order_count") or 0),
                    "revenue": float(q.get("gmv") or 0),
                    "position": float(q.get("position") or 0) or None,
                    "view_conversion": float(q.get("view_conversion") or 0) or None,
                    "extra": {
                        "currency": q.get("currency"),
                        "query_index": q.get("query_index"),
                        "unique_view_users": q.get("unique_view_users"),
                    },
                })

            page_count = int(result.get("page_count") or 1) if isinstance(result, dict) else 1
            if page >= page_count:
                break
            page += 1

        return out

    async def close(self):
        """关闭HTTP客户端"""
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()
        if self._perf_client and not self._perf_client.is_closed:
            await self._perf_client.aclose()


# 注册到工厂
PlatformClientFactory.register("ozon", OzonClient)
