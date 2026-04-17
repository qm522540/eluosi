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
WB_PRICES_API = "https://discounts-prices-api.wildberries.ru"

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
                follow_redirects=True,
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

        流程：
        1. GET /adv/v1/promotion/count 获取活动ID列表和状态/类型
        2. GET /api/advert/v2/adverts?ids=... 分批获取活动名称 (settings.name)
        3. GET /adv/v1/budget?id=X 逐个获取活动预算余额
        4. 组装数据

        说明：
          旧接口 /adv/v1/promotion/adverts 已被WB废弃 (返回404)，
          新接口 /api/advert/v2/adverts 单次最多支持50个id，返回字段包含
          settings.name (活动名称) + timestamps (created/updated) + status。
        """
        campaigns = []

        try:
            # 第1步: 获取活动ID列表及状态信息
            count_url = f"{WB_ADVERT_API}/adv/v1/promotion/count"
            count_data = await self._request("GET", count_url)

            if not count_data or "adverts" not in count_data:
                logger.info(f"WB shop_id={self.shop_id} 暂无广告活动")
                return []

            # 收集所有活动ID及其状态/类型
            advert_info = {}  # advertId -> {status, type, changeTime}
            for status_group in count_data.get("adverts", []):
                group_status = status_group.get("status")
                group_type = status_group.get("type")
                advert_list = status_group.get("advert_list", [])
                if not advert_list:
                    continue
                for adv in advert_list:
                    advert_id = adv.get("advertId")
                    if advert_id:
                        advert_info[advert_id] = {
                            "status": adv.get("status", group_status),
                            "type": adv.get("type", group_type),
                            "changeTime": adv.get("changeTime"),
                        }

            if not advert_info:
                return []

            # 第2步: 分批调用 /api/advert/v2/adverts 拉取活动名称、付费类型
            name_map, payment_type_map, deleted_ids = await self._fetch_advert_names(
                list(advert_info.keys())
            )

            # 跳过已删除的活动
            if deleted_ids:
                for d_id in deleted_ids:
                    advert_info.pop(d_id, None)
                logger.info(
                    f"WB shop_id={self.shop_id} 跳过{len(deleted_ids)}个"
                    f"已在WB后台删除的活动: {sorted(deleted_ids)}"
                )

            if not advert_info:
                return []

            # 第3步: 逐个获取预算余额
            budget_map = {}  # advertId -> budget total
            for advert_id in advert_info:
                try:
                    budget_url = f"{WB_ADVERT_API}/adv/v1/budget"
                    budget_data = await self._request(
                        "GET", budget_url, params={"id": advert_id}
                    )
                    if isinstance(budget_data, dict):
                        budget_map[advert_id] = budget_data.get("total")
                except Exception:
                    pass  # 预算获取失败不影响主流程

            # 第4步: 组装数据
            for advert_id, info in advert_info.items():
                merged = {
                    "advertId": advert_id,
                    "status": info["status"],
                    "type": info["type"],
                    "name": name_map.get(advert_id, ""),
                    "dailyBudget": budget_map.get(advert_id),
                    "createTime": info.get("changeTime"),
                    "endTime": None,
                    "payment_type": payment_type_map.get(advert_id, "cpm"),
                }
                campaigns.append(self._parse_campaign(merged))

            logger.info(
                f"WB shop_id={self.shop_id} 发现 {len(campaigns)} 个广告活动，"
                f"其中 {sum(1 for n in name_map.values() if n)} 个带真实名称"
            )

        except Exception as e:
            logger.error(f"WB 拉取广告活动失败，shop_id={self.shop_id}: {e}")
            raise

        return campaigns

    async def _fetch_advert_names(self, advert_ids: list) -> tuple:
        """通过 /api/advert/v2/adverts 批量拉取活动名称、付费类型和删除状态

        Returns:
            (name_map, payment_type_map, deleted_ids) 元组:
              - name_map: {advert_id: name}
              - payment_type_map: {advert_id: "cpm" | "cpc"}（从 settings.payment_type 读）
              - deleted_ids: 在WB后台已软删除的活动ID集合
        """
        if not advert_ids:
            return {}, {}, set()

        name_map: dict = {}
        payment_type_map: dict = {}
        deleted_ids: set = set()
        batch_size = 50  # WB API 单次最多50个id

        for i in range(0, len(advert_ids), batch_size):
            batch = advert_ids[i:i + batch_size]
            ids_param = ",".join(str(x) for x in batch)
            url = f"{WB_ADVERT_API}/api/advert/v2/adverts"

            try:
                resp = await self._request("GET", url, params={"ids": ids_param})
            except Exception as e:
                logger.warning(
                    f"WB /api/advert/v2/adverts 批次失败 size={len(batch)}: {e}"
                )
                continue

            # 兼容多种响应格式: {adverts: [...]} 或 [...]
            adverts = []
            if isinstance(resp, dict):
                adverts = resp.get("adverts") or []
            elif isinstance(resp, list):
                adverts = resp

            for adv in adverts:
                adv_id = adv.get("id")
                if not adv_id:
                    continue

                # 识别软删除：timestamps.deleted 是真实时间(非2100+哨兵值)
                # WB用 "2100-01-01T00:00:00+03:00" 表示"未删除"
                deleted_ts = (adv.get("timestamps") or {}).get("deleted") or ""
                if deleted_ts and not deleted_ts.startswith("21"):
                    deleted_ids.add(adv_id)
                    continue  # 已删除的活动不再提取名称

                settings_obj = adv.get("settings") or {}
                name = settings_obj.get("name") or adv.get("name") or ""
                if name:
                    name_map[adv_id] = name.strip()

                # 付费类型：WB settings.payment_type 取值 cpm/cpc
                pt = (settings_obj.get("payment_type") or "cpm").lower()
                payment_type_map[adv_id] = pt if pt in ("cpm", "cpc") else "cpm"

        logger.info(
            f"WB shop_id={self.shop_id} 获取活动元信息 "
            f"请求{len(advert_ids)}个 命中名称{len(name_map)}个 "
            f"已删除{len(deleted_ids)}个"
        )
        return name_map, payment_type_map, deleted_ids

    def _parse_campaign(self, raw: dict) -> dict:
        """解析WB广告活动数据为标准格式"""
        # WB的type映射:
        # 4=目录推广(CPM), 5=商品卡片, 6=搜索推广,
        # 7=推荐推广, 8=自动广告(已废弃), 9=竞价广告/CPM(Auction)
        type_map = {
            4: "catalog",
            5: "product_page",
            6: "search",
            7: "recommendation",
            8: "auction",
            9: "auction",
        }
        # WB的status映射:
        # -1=删除中, 4=准备就绪, 7=投放中, 8=结算中(已废弃),
        # 9=投放中(统一广告,新类型), 11=已暂停
        status_map = {
            -1: "archived",
            4: "draft",
            7: "active",
            8: "active",
            9: "active",
            11: "paused",
        }

        advert_id = str(raw.get("advertId", ""))
        ad_type = type_map.get(raw.get("type"), "search")
        ad_type_labels = {
            "catalog": "目录推广",
            "product_page": "商品卡片",
            "search": "搜索推广",
            "recommendation": "推荐推广",
            "auction": "竞价广告(CPM)",
        }
        # WB的count接口不一定返回name，用类型+ID生成有意义的名称
        name = raw.get("name") or ""
        if not name.strip():
            name = f"{ad_type_labels.get(ad_type, '广告')}-{advert_id}"

        return {
            "platform_campaign_id": advert_id,
            "name": name,
            "ad_type": ad_type,
            "payment_type": raw.get("payment_type") or "cpm",
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

        依次尝试多个WB统计接口：
        1. GET /adv/v3/fullstats (新版，用from/to查询参数)
        2. POST /adv/v2/fullstats (旧版)
        3. POST /adv/v1/fullstats (旧版)
        date_from/date_to 格式: "YYYY-MM-DD"
        """
        stats = []
        result = None

        # GET /adv/v3/fullstats（参数: ids, beginDate, endDate，最多31天）
        try:
            url = f"{WB_ADVERT_API}/adv/v3/fullstats"
            result = await self._request(
                "GET", url,
                params={"ids": str(campaign_id), "beginDate": date_from, "endDate": date_to}
            )
            if result and result != {}:
                logger.info(f"WB v3/fullstats 命中 campaign_id={campaign_id}")
        except Exception:
            result = None

        if not result or result == {}:
            logger.warning(
                f"WB 所有统计接口均无数据，shop_id={self.shop_id}，"
                f"campaign_id={campaign_id}"
            )
            return []

        try:
            # v3返回格式可能不同，兼容处理
            # _parse_daily_stat 现在返回 list（SKU 级别拆分），用 extend
            if isinstance(result, list):
                for campaign_stats in result:
                    days = campaign_stats.get("days", [])
                    for day_data in days:
                        sku_stats = self._parse_daily_stat(campaign_id, day_data)
                        if sku_stats:
                            stats.extend(sku_stats)
            elif isinstance(result, dict):
                days = result.get("days", [])
                if days:
                    for day_data in days:
                        sku_stats = self._parse_daily_stat(campaign_id, day_data)
                        if sku_stats:
                            stats.extend(sku_stats)
                elif result.get("views") or result.get("clicks"):
                    sku_stats = self._parse_daily_stat(campaign_id, result)
                    if sku_stats:
                        stats.extend(sku_stats)
        except Exception as e:
            logger.error(
                f"WB 解析广告统计失败，shop_id={self.shop_id}，"
                f"campaign_id={campaign_id}: {e}"
            )
            raise

        return stats

    def _parse_daily_stat(self, campaign_id: str, day_data: dict) -> Optional[list]:
        """解析每日统计数据为 SKU 级别的列表

        WB fullstats 返回结构: days[] → apps[] → nm[]
        每个 nm 就是一个商品（nm_id），包含独立的 views/clicks/spend/orders/revenue。
        按 nm_id 逐条返回，存入 ad_stats 时 ad_group_id = nm_id。

        Returns:
            [{campaign_id, platform, stat_date, nm_id, impressions, clicks, ...}, ...]
            如果该天无数据返回 None
        """
        date_str = day_data.get("date", "")
        if not date_str:
            return None

        results = []
        apps = day_data.get("apps", [])
        for app in apps:
            # v3 API 返回 "nms"（复数），兼容旧版 "nm"
            nms = app.get("nms") or app.get("nm") or []
            for nm in nms:
                nm_id = nm.get("nmId") or nm.get("nm_id")
                if not nm_id:
                    continue

                views = nm.get("views", 0)
                clicks = nm.get("clicks", 0)
                spend = float(nm.get("sum", 0.0))
                orders = nm.get("orders", 0)
                # v3 用 sum_price，旧版用 ordersSumRub
                revenue = float(nm.get("sum_price") or nm.get("ordersSumRub") or 0.0)

                # 跳过完全无数据的 SKU
                if views == 0 and spend == 0:
                    continue

                ctr = (clicks / views * 100) if views > 0 else 0
                cpc = (spend / clicks) if clicks > 0 else 0
                acos = (spend / revenue * 100) if revenue > 0 else 0
                roas = (revenue / spend) if spend > 0 else 0

                # DB 列是 DECIMAL(8,4)，极端值截断避免溢出
                results.append({
                    "campaign_id": campaign_id,
                    "platform": "wb",
                    "stat_date": date_str[:10],
                    "stat_hour": None,
                    "nm_id": int(nm_id),
                    "nm_name": nm.get("name", ""),
                    "impressions": views,
                    "clicks": clicks,
                    "spend": round(spend, 2),
                    "orders": orders,
                    "revenue": round(revenue, 2),
                    "ctr": round(min(ctr, 9999), 4),
                    "cpc": round(min(cpc, 99999999), 2),
                    "acos": round(min(acos, 9999), 4),
                    "roas": round(min(roas, 9999), 4),
                })

        return results if results else None

    # ==================== 广告活动商品 ====================

    async def _patch_bids_once(
        self, advert_id: int, nm_id: int, bid_kopecks: int, placements: list,
    ) -> dict:
        """单次 PATCH /api/advert/v1/bids 调用，返回 {status, detail}"""
        url = f"{WB_ADVERT_API}/api/advert/v1/bids"
        payload = {
            "bids": [
                {
                    "advert_id": advert_id,
                    "nm_bids": [
                        {"nm_id": nm_id, "bid_kopecks": bid_kopecks, "placement": p}
                        for p in placements
                    ],
                }
            ],
        }
        try:
            await self._rate_limit()
            client = await self._get_client()
            r = await client.request("PATCH", url, json=payload)
        except Exception as e:
            logger.error(
                f"WB PATCH bids 异常 shop_id={self.shop_id} "
                f"advert_id={advert_id} nm_id={nm_id}: {e}"
            )
            return {"status": 0, "detail": str(e)}

        if r.status_code < 400:
            return {"status": r.status_code, "detail": None}

        try:
            err_body = r.json()
            detail = err_body.get("detail") or err_body.get("title") or r.text[:300]
        except Exception:
            detail = r.text[:300]
        return {"status": r.status_code, "detail": detail}

    async def update_campaign_cpm(
        self, advert_id: str, nm_id: int, cpm_rub: float,
        placements: Optional[list] = None,
    ) -> dict:
        """修改 WB 广告活动中某个 SKU 的 CPM 出价

        调 PATCH /api/advert/v1/bids 接口。WB 的 placement 取值和 bid_type 对应：
          - bid_type='unified'（统一出价，新版默认）→ placement='combined'
            一次性同时影响搜索和推荐两个广告位（对应 WB 后台 UI 的"一个输入框"）
          - bid_type='manual'（每广告位独立出价，旧版）→ placement='search' 或 'recommendations'

        策略：
          1. 默认先用 ['combined']（unified 类型，绝大多数活动）
          2. 如果 combined 被拒绝 ("placement is disabled" / "not applicable")，
             自动 fallback 到 ['search', 'recommendations']
          3. 在 search/recommendations 层再做 disabled 回退

        Args:
            advert_id: WB advertId
            nm_id:     WB nmId (SKU)
            cpm_rub:   新出价，卢布单位（内部转戈比）
            placements: 覆盖默认顺序（调试用），默认 None 走自动策略

        Returns:
            {
              "ok": bool,
              "error": str|None,
              "updated": list,   # 实际改成功的 placement
              "skipped": list,   # 被 WB 拒绝的 placement
            }
        """
        bid_kopecks = int(round(float(cpm_rub) * 100))
        if bid_kopecks <= 0:
            return {"ok": False, "error": "出价必须大于 0", "updated": [], "skipped": []}

        advert_id_int = int(advert_id)
        nm_id_int = int(nm_id)

        # 生成候选列表：先试 combined，如果失败再试 [search, recommendations]
        if placements is not None:
            candidate_lists = [list(placements)]
        else:
            candidate_lists = [["combined"], ["search", "recommendations"]]

        skipped: list = []

        for candidate in candidate_lists:
            remaining = list(candidate)
            # 对单个候选列表内再做 disabled 回退
            for _ in range(len(candidate) + 1):
                if not remaining:
                    break
                result = await self._patch_bids_once(
                    advert_id_int, nm_id_int, bid_kopecks, remaining,
                )
                if result["status"] and result["status"] < 400:
                    logger.info(
                        f"WB 修改 CPM 成功 shop_id={self.shop_id} "
                        f"advert={advert_id} nm={nm_id} kopecks={bid_kopecks} "
                        f"updated={remaining} skipped={skipped}"
                    )
                    return {
                        "ok": True,
                        "error": None,
                        "updated": remaining,
                        "skipped": skipped,
                        "actual_bid_rub": bid_kopecks / 100,
                    }

                detail = (result.get("detail") or "").lower()
                # 识别 "X placement is disabled" → 移除该 placement 重试
                disabled = None
                for p in remaining:
                    if f"{p} placement is disabled" in detail:
                        disabled = p
                        break
                if disabled:
                    remaining.remove(disabled)
                    skipped.append(disabled)
                    logger.warning(
                        f"WB placement={disabled} disabled，重试 remaining={remaining}"
                    )
                    continue

                # 识别 "wrong bid value: X; min: Y" → 自动用 min 值重试
                import re as _re
                min_match = _re.search(r'min:\s*(\d+)', detail)
                if min_match and 'wrong bid value' in detail:
                    min_kopecks = int(min_match.group(1))
                    logger.warning(
                        f"WB 出价 {bid_kopecks} 低于最低 {min_kopecks}，自动用最低值重试"
                    )
                    bid_kopecks = min_kopecks
                    continue

                # 其它错误 → 这个候选列表彻底失败，跳出让外层换下一个候选
                logger.warning(
                    f"WB 修改 CPM 响应 {result['status']} "
                    f"candidate={candidate} advert={advert_id} nm={nm_id}: "
                    f"{result.get('detail')}"
                )
                remaining = []  # 跳出内循环
                last_error = result.get("detail") or f"HTTP {result['status']}"
                break

        # 所有候选都失败了
        # 优先展示具体错误（如 "wrong bid value: 5600; min: 8000"），
        # 而非笼统的 "广告位未启用"
        error_msg = locals().get("last_error", "")
        if not error_msg and skipped:
            error_msg = f"该活动所有广告位均未启用（已尝试：{', '.join(skipped)}）"
        elif not error_msg:
            error_msg = "未知错误"
        return {
            "ok": False,
            "error": error_msg,
            "updated": [],
            "skipped": skipped,
        }

    async def fetch_min_bid(self, advert_id: str, nm_id: int,
                             placement: str = "combined",
                             payment_type: str = "cpm") -> Optional[float]:
        """查询 WB 广告活动下某 SKU 的最低 CPM 出价（卢布）

        调 POST /api/advert/v1/bids/min
        Body: {
            "advert_id": int, "nm_ids": [int],
            "payment_type": "cpm", "placement_types": ["combined"]
        }
        响应: {"bids": [{"bids": [{"value": kopecks, ...}], "nm_id": ...}]}
        返回 kopecks / 100 → 卢布。失败时返回 None。
        """
        try:
            url = f"{WB_ADVERT_API}/api/advert/v1/bids/min"
            body = {
                "advert_id": int(advert_id),
                "nm_ids": [int(nm_id)],
                "payment_type": payment_type,
                "placement_types": [placement],
            }
            resp = await self._request("POST", url, json=body)
        except Exception as e:
            logger.warning(
                f"WB 查询最低出价失败 advert={advert_id} nm={nm_id}: {e}"
            )
            return None

        if not isinstance(resp, dict):
            return None

        # 解析嵌套 bids 结构
        outer = resp.get("bids") or []
        if not outer:
            return None

        # 取该 nm_id 对应的出价（通常只有一个）
        for group in outer:
            if int(group.get("nm_id", 0)) == int(nm_id):
                inner = group.get("bids") or []
                for b in inner:
                    if b.get("type") == placement:
                        val = b.get("value")
                        if val:
                            return int(val) / 100.0
                # 没匹配到 placement 就取第一个
                if inner and inner[0].get("value"):
                    return int(inner[0]["value"]) / 100.0

        return None

    async def fetch_excluded_keywords(
        self, advert_id: str, nm_ids: list,
    ) -> dict:
        """获取 SKU 级屏蔽关键词列表

        API: POST /adv/v0/normquery/get-minus
        Body: {"items": [{"advert_id": int, "nm_id": int}, ...]}（最多100项）
        返回: {nm_id: [屏蔽词1, 屏蔽词2, ...], ...}
        """
        if not nm_ids:
            return {}
        try:
            url = f"{WB_ADVERT_API}/adv/v0/normquery/get-minus"
            body = {
                "items": [
                    {"advert_id": int(advert_id), "nm_id": int(nm)}
                    for nm in nm_ids[:100]
                ]
            }
            resp = await self._request("POST", url, json=body)
        except Exception as e:
            logger.warning(f"WB 拉取屏蔽关键词失败 advert={advert_id}: {e}")
            return {}

        if not isinstance(resp, dict):
            return {}

        result = {}
        for item in resp.get("items") or []:
            nm = item.get("nm_id")
            words = item.get("norm_queries") or []
            if nm:
                result[int(nm)] = words

        logger.info(
            f"WB advert={advert_id} 屏蔽关键词: "
            + ", ".join(f"nm={k}:{len(v)}个" for k, v in result.items())
        )
        return result

    async def set_excluded_keywords(
        self, advert_id: str, nm_id: int, words: list,
    ) -> dict:
        """设置 SKU 级屏蔽关键词（替换模式：传入的 words 会覆盖已有列表）

        API: POST /adv/v0/normquery/set-minus
        Body: {"advert_id": int, "nm_id": int, "words": ["词1", "词2"]}
        """
        try:
            url = f"{WB_ADVERT_API}/adv/v0/normquery/set-minus"
            body = {
                "advert_id": int(advert_id),
                "nm_id": int(nm_id),
                "words": words,
            }
            await self._request("POST", url, json=body)
            logger.info(f"WB 设置屏蔽关键词成功 advert={advert_id} nm={nm_id} words={len(words)}")
            return {"ok": True}
        except Exception as e:
            logger.error(f"WB 设置屏蔽关键词失败: {e}")
            return {"ok": False, "error": str(e)}

    async def fetch_campaign_summary(
        self, advert_id: str,
        date_from: str, date_to: str,
    ) -> dict:
        """拉活动汇总统计（fullstats 顶层字段）

        返回: {views, clicks, orders, atbs, sum, sum_price, cpc, ctr, cr}
        用于关键词级订单归因估算（按点击占比分摊活动总订单）。
        """
        try:
            url = f"{WB_ADVERT_API}/adv/v3/fullstats"
            result = await self._request(
                "GET", url,
                params={"ids": str(advert_id), "beginDate": date_from, "endDate": date_to},
            )
        except Exception as e:
            logger.warning(f"WB fullstats 失败 advert={advert_id}: {e}")
            return {}

        if not result:
            return {}

        # v3 返回 list，取第一个活动的顶层汇总
        if isinstance(result, list) and result:
            top = result[0]
        elif isinstance(result, dict):
            top = result
        else:
            return {}

        return {
            "views": int(top.get("views") or 0),
            "clicks": int(top.get("clicks") or 0),
            "orders": int(top.get("orders") or 0),
            "atbs": int(top.get("atbs") or 0),
            "sum": float(top.get("sum") or 0),
            "sum_price": float(top.get("sum_price") or 0),
            "cpc": float(top.get("cpc") or 0),
            "ctr": float(top.get("ctr") or 0),
            "cr": float(top.get("cr") or 0),
        }

    async def fetch_campaign_keywords(
        self, advert_id: str,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> list:
        """拉取 WB 广告活动的关键词统计

        API: GET /adv/v0/stats/keywords?advert_id=X&from=YYYY-MM-DD&to=YYYY-MM-DD

        注意：
        - WB 限制：from 和 to 的时间跨度不能超过 1 周（7 天）
        - WB 活动级别的数据，不按 nm_id 过滤（所有 SKU 共享同一套关键词）
        - auction/unified 类型活动没有"手动关键词"概念，但可以查系统为活动触发的实际搜索词

        Returns:
            [{keyword, views, clicks, ctr, sum(花费), currency}]
        """
        # WB 限制：跨度必须 ≤ 7 天（from-to 差值最多 6 天）
        today = datetime.now(tz=None).date()
        if not date_to:
            date_to = today.strftime("%Y-%m-%d")
        if not date_from:
            date_from = (today - timedelta(days=6)).strftime("%Y-%m-%d")

        try:
            url = f"{WB_ADVERT_API}/adv/v0/stats/keywords"
            resp = await self._request("GET", url, params={
                "advert_id": int(advert_id),
                "from": date_from,
                "to": date_to,
            })
        except Exception as e:
            logger.warning(
                f"WB 拉取关键词统计失败 advert={advert_id}: {e}"
            )
            return []

        if not isinstance(resp, dict):
            return []

        # 响应: {"keywords": [{"date": "YYYY-MM-DD", "stats": [{...关键词数据}]}]}
        # 按关键词聚合，每个关键词合并所有日期的 views/clicks/sum + 出现天数
        total_days = len(resp.get("keywords") or [])
        agg: dict = {}
        for day_group in resp.get("keywords") or []:
            day_date = day_group.get("date") or ""
            for stat in day_group.get("stats") or []:
                kw = stat.get("keyword") or ""
                if not kw:
                    continue
                if kw not in agg:
                    agg[kw] = {
                        "keyword": kw,
                        "views": 0, "clicks": 0,
                        "sum": 0.0, "currency": stat.get("currency", "RUB"),
                        "active_days": 0,
                        "first_seen": day_date,
                        "last_seen": day_date,
                    }
                agg[kw]["views"] += int(stat.get("views") or 0)
                agg[kw]["clicks"] += int(stat.get("clicks") or 0)
                agg[kw]["sum"] += float(stat.get("sum") or 0)
                agg[kw]["active_days"] += 1
                if day_date and day_date < agg[kw]["first_seen"]:
                    agg[kw]["first_seen"] = day_date
                if day_date and day_date > agg[kw]["last_seen"]:
                    agg[kw]["last_seen"] = day_date

        # 按 views 降序
        result = sorted(agg.values(), key=lambda x: x["views"], reverse=True)

        # 算 CTR + 推断活跃标签
        for r in result:
            r["ctr"] = (
                round(r["clicks"] / r["views"] * 100, 2) if r["views"] > 0 else 0
            )
            r["sum"] = round(r["sum"], 2)
            r["total_days"] = total_days
            # 活跃标签推断
            if r["clicks"] > 0:
                r["status"] = "active"       # 有点击=真正在工作
            elif r["active_days"] >= max(total_days - 1, 3):
                r["status"] = "stable"       # 多数天都出现，曝光稳定但没点击
            elif r["active_days"] <= 2:
                r["status"] = "occasional"   # 只出现 1-2 天
            else:
                r["status"] = "low_effect"   # 有曝光无点击

        logger.info(
            f"WB shop_id={self.shop_id} advert={advert_id} "
            f"关键词 {date_from}~{date_to} 共 {len(result)} 个"
        )
        return result

    async def fetch_campaign_products(self, advert_id: str) -> list:
        """拉取 WB 广告活动下的商品列表及出价

        通过 /api/advert/v2/adverts?ids={advert_id} 解析 nm_settings 数组。
        每个 nm 的出价按 placement 分（search / recommendations），单位戈比转卢布。

        Returns:
            [{sku, subject_name, bid_search, bid_recommendations}]
            sku 为 WB 的 nm_id（字符串形式，与 Ozon 字段名对齐）
        """
        try:
            url = f"{WB_ADVERT_API}/api/advert/v2/adverts"
            resp = await self._request("GET", url, params={"ids": str(advert_id)})
        except Exception as e:
            logger.error(
                f"WB 拉取活动商品失败 shop_id={self.shop_id} "
                f"advert_id={advert_id}: {e}"
            )
            return []

        if not isinstance(resp, dict):
            return []
        adverts = resp.get("adverts") or []
        if not adverts:
            return []

        nm_settings = (adverts[0] or {}).get("nm_settings") or []
        products = []
        for nm in nm_settings:
            if not isinstance(nm, dict):
                continue
            bids = nm.get("bids_kopecks") or {}
            subject = nm.get("subject") or {}
            products.append({
                "sku": str(nm.get("nm_id") or ""),
                "subject_name": subject.get("name") or "",
                # 戈比 → 卢布（1 ₽ = 100 копейки）
                "bid_search": round((bids.get("search") or 0) / 100, 2),
                "bid_recommendations": round((bids.get("recommendations") or 0) / 100, 2),
            })
        return products

    # ==================== 商品 ====================

    async def fetch_products(self, limit: int = 100) -> dict:
        """拉取商品列表 (使用内容API，自动 cursor 分页拉取全部)"""
        try:
            url = f"{WB_CONTENT_API}/content/v2/get/cards/list"
            all_cards = []
            cursor = {"limit": limit}
            for _ in range(100):  # 最多 100 页 = 10000 商品
                payload = {
                    "settings": {
                        "cursor": cursor,
                        "filter": {"withPhoto": -1},
                    }
                }
                result = await self._request("POST", url, json=payload)
                cards = (result or {}).get("cards", [])
                all_cards.extend(cards)
                resp_cursor = (result or {}).get("cursor", {})
                total = resp_cursor.get("total", 0)
                if len(cards) < limit or total <= len(cards):
                    break
                cursor = {
                    "limit": limit,
                    "updatedAt": resp_cursor.get("updatedAt", ""),
                    "nmID": resp_cursor.get("nmID", 0),
                }
                if not cursor["updatedAt"]:
                    break
            logger.info(f"WB 拉取商品完成 shop_id={self.shop_id} total={len(all_cards)}")
            return {"cards": all_cards}
        except Exception as e:
            logger.error(f"WB 拉取商品失败，shop_id={self.shop_id}: {e}")
            raise

    async def fetch_prices(self, limit: int = 1000) -> dict:
        """拉取全量商品价格/折扣（discounts-prices API）

        返回 {nm_id_int: {price, discountedPrice, discount}}
        - price: 原价（商家定价）
        - discountedPrice: 折后价（商家折后价，仍非到手价）
        - discount: 折扣百分比

        API: GET /api/v2/list/goods/filter?limit=1000&offset=0
        分页：limit/offset，自动翻页到末尾
        """
        try:
            url = f"{WB_PRICES_API}/api/v2/list/goods/filter"
            price_map = {}
            offset = 0
            for _ in range(100):  # 最多 100 页 × 1000 = 10 万
                result = await self._request(
                    "GET", url, params={"limit": limit, "offset": offset},
                )
                goods = (result or {}).get("data", {}).get("listGoods") or []
                if not goods:
                    break
                for g in goods:
                    nm_id = g.get("nmID")
                    if not nm_id:
                        continue
                    sizes = g.get("sizes") or []
                    if not sizes:
                        continue
                    s0 = sizes[0]
                    price_map[nm_id] = {
                        "price": s0.get("price"),
                        "discountedPrice": s0.get("discountedPrice"),
                        "discount": g.get("discount", 0),
                    }
                if len(goods) < limit:
                    break
                offset += limit
            logger.info(f"WB 拉取价格完成 shop_id={self.shop_id} total={len(price_map)}")
            return price_map
        except Exception as e:
            logger.error(f"WB 拉取价格失败，shop_id={self.shop_id}: {e}")
            return {}

    async def remove_campaign_product(self, advert_id: str, nm_id: int) -> dict:
        """从 WB 广告活动中移除指定商品

        主路径：POST /adv/v0/nm-to-advert/delete（对旧类型活动有效）
        Fallback：unified/auction 类型活动该接口返回 404，自动改调
                  update_campaign_cpm 把 CPM 降到最低出价（0.01 → WB min bid 自动兜底），
                  视觉等同于"停止该 SKU 竞价曝光"。
        """
        try:
            await self._request(
                "POST",
                f"{WB_ADVERT_API}/adv/v0/nm-to-advert/delete",
                json={"advertId": int(advert_id), "nms": [int(nm_id)]},
            )
            logger.info(f"WB 真删除成功 shop_id={self.shop_id} advert={advert_id} nm={nm_id}")
            return {"ok": True, "action": "deleted"}
        except Exception as e:
            err_str = str(e)
            logger.warning(
                f"WB 真删除失败 advert={advert_id} nm={nm_id}: {err_str}"
            )
            # 404 → unified/auction 类型不支持真删，fallback 降 CPM 到最低
            if "404" in err_str:
                logger.info(
                    f"WB /adv/v0/nm-to-advert/delete 对 advert={advert_id} 404，"
                    f"fallback 降最低 CPM 停投"
                )
                cpm_result = await self.update_campaign_cpm(
                    advert_id=str(advert_id),
                    nm_id=int(nm_id),
                    cpm_rub=0.01,
                )
                if cpm_result.get("ok"):
                    return {
                        "ok": True,
                        "action": "min_bid_fallback",
                        "actual_bid_rub": cpm_result.get("actual_bid_rub"),
                        "note": "WB 统一活动不支持 API 真删除，已降至类目最低出价停止竞价曝光。如需完全移除请在 WB 后台操作。",
                    }
                return {"ok": False, "error": cpm_result.get("error") or "fallback 失败"}
            return {"ok": False, "error": err_str}

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

    # ==================== 地区销售 ====================

    async def fetch_sales_returns_by_region(self, date_from: str, date_to: str) -> dict:
        """从 /supplier/sales 按地区聚合退货件数（saleID 以 "R" 开头的条）。

        WB 的 region-sale API 不返回退货字段，但 sales API 每条有 regionName +
        saleID（R 开头 = 退货）。按 regionName + date 聚合。

        Returns: {(region_name, date_str): returns_count}
        """
        try:
            url = f"{WB_STATISTICS_API}/api/v1/supplier/sales"
            params = {"dateFrom": date_from}
            result = await self._request("GET", url, params=params)
            if not isinstance(result, list):
                return {}
            from datetime import date as _date
            d_from = _date.fromisoformat(date_from)
            d_to = _date.fromisoformat(date_to)
            out: dict = {}
            for r in result:
                sale_id = str(r.get("saleID") or "")
                if not sale_id.startswith("R"):
                    continue
                d_str = (r.get("date") or "")[:10]
                if not d_str:
                    continue
                try:
                    d = _date.fromisoformat(d_str)
                except ValueError:
                    continue
                if d < d_from or d > d_to:
                    continue
                region = (r.get("regionName") or r.get("countryName") or "").strip()
                if not region:
                    continue
                key = (region, d_str)
                out[key] = out.get(key, 0) + 1
            logger.info(
                f"WB 退货按地区聚合 {date_from}~{date_to}: "
                f"共 {sum(out.values())} 条退货 / {len(out)} 个(地区,日期)组合"
            )
            return out
        except Exception as e:
            logger.error(f"WB 退货聚合失败 shop_id={self.shop_id}: {e}")
            return {}

    async def fetch_region_sales_by_sku(self, date_from: str, date_to: str,
                                        region_name: str = None) -> list:
        """按 region × nmID 双维度返回销售，用于"该地区 TOP SKU"决策。
        Returns: [{region_name, nm_id, sa (商家编码), orders, revenue}]
        """
        try:
            url = "https://seller-analytics-api.wildberries.ru/api/v1/analytics/region-sale"
            params = {"dateFrom": date_from, "dateTo": date_to}
            result = await self._request("GET", url, params=params)
            report = (result or {}).get("report") or []
            agg: dict = {}
            for item in report:
                region = item.get("regionName") or item.get("countryName") or "Unknown"
                if region_name and region != region_name:
                    continue
                nm_id = item.get("nmID")
                sa = item.get("sa") or ""
                if nm_id is None:
                    continue
                key = (region, int(nm_id))
                if key not in agg:
                    agg[key] = {"region_name": region, "nm_id": int(nm_id), "sa": sa,
                                "orders": 0, "revenue": 0}
                agg[key]["orders"] += int(item.get("saleItemInvoiceQty") or 0)
                agg[key]["revenue"] += float(item.get("saleInvoiceCostPrice") or 0)
            items = [v for v in agg.values() if v["orders"] > 0 or v["revenue"] > 0]
            for v in items:
                v["revenue"] = round(v["revenue"], 2)
            return items
        except Exception as e:
            logger.error(f"WB 按 SKU 拉地区销售失败: {e}")
            return []

    async def fetch_region_sales(self, date_from: str, date_to: str) -> list:
        """拉取地区销售数据

        API: GET https://seller-analytics-api.wildberries.ru/api/v1/analytics/region-sale
        单次最多 31 天。返回按 regionName + cityName + nmID 粒度。
        本方法按 regionName 聚合（去掉城市和商品粒度），返回每天每地区的汇总。

        Returns: [{region_name, date, orders, revenue}]
        """
        try:
            url = "https://seller-analytics-api.wildberries.ru/api/v1/analytics/region-sale"
            params = {"dateFrom": date_from, "dateTo": date_to}
            result = await self._request("GET", url, params=params)
            report = (result or {}).get("report") or []
            # 按 regionName 聚合（API 返回按 city+nmID 拆分，合并到 region 级）
            region_map = {}
            for item in report:
                region = item.get("regionName") or item.get("countryName") or "Unknown"
                orders = int(item.get("saleItemInvoiceQty") or 0)
                revenue = float(item.get("saleInvoiceCostPrice") or 0)
                key = region
                if key not in region_map:
                    region_map[key] = {"orders": 0, "revenue": 0}
                region_map[key]["orders"] += orders
                region_map[key]["revenue"] += revenue
            items = [
                {"region_name": k, "orders": v["orders"], "revenue": round(v["revenue"], 2)}
                for k, v in region_map.items() if v["orders"] > 0 or v["revenue"] > 0
            ]
            logger.info(f"WB 地区销售 {date_from}~{date_to}: {len(items)} 个地区，原始 {len(report)} 条")
            return items
        except Exception as e:
            logger.error(f"WB 地区销售拉取失败: {e}")
            return []

    # ==================== 关键词统计 ====================

    async def fetch_keyword_stats(self, advert_id: str, date_from: str, date_to: str) -> list:
        """拉取关键词统计数据

        API: GET /adv/v0/stats/keywords?advert_id=X&from=YYYY-MM-DD&to=YYYY-MM-DD
        单次最多 7 天，调用方需自行拆分。

        Returns: [{date, keyword, impressions, clicks, spend, ctr, cpc}]
        """
        try:
            url = f"{WB_ADVERT_API}/adv/v0/stats/keywords"
            params = {"advert_id": str(advert_id), "from": date_from, "to": date_to}
            result = await self._request("GET", url, params=params)
            items = []
            kw_data = (result or {}).get("keywords") or []
            for day_entry in kw_data:
                stat_date = day_entry.get("date", date_from)
                for s in day_entry.get("stats") or []:
                    kw = s.get("keyword", "")
                    if not kw:
                        continue
                    views = int(s.get("views") or 0)
                    clicks = int(s.get("clicks") or 0)
                    spend = float(s.get("sum") or 0)
                    ctr = float(s.get("ctr") or 0)
                    cpc = round(spend / clicks, 2) if clicks > 0 else 0
                    items.append({
                        "date": stat_date,
                        "keyword": kw,
                        "impressions": views,
                        "clicks": clicks,
                        "spend": spend,
                        "ctr": ctr,
                        "cpc": cpc,
                    })
            logger.info(f"WB 关键词统计 advert={advert_id} {date_from}~{date_to}: {len(items)} 条")
            return items
        except Exception as e:
            logger.error(f"WB 关键词统计拉取失败 advert={advert_id}: {e}")
            return []

    # ==================== 分类/属性（用于铺货映射） ====================

    async def fetch_commissions(self, locale: str = "ru") -> dict:
        """拉 WB 佣金表（按 subjectID 分类级），返回 {subject_id: kgvp_marketplace}。
        API: GET /api/v1/tariffs/commission?locale=ru（common-api）
        WB 佣金是按分类给，不是按 SKU；同一分类所有商品佣金相同。
        """
        try:
            url = f"{WB_COMMON_API}/api/v1/tariffs/commission"
            params = {"locale": locale}
            result = await self._request("GET", url, params=params)
            report = (result or {}).get("report") or []
            out: dict = {}
            for r in report:
                sid = r.get("subjectID") or r.get("subjectId")
                if sid is None:
                    continue
                # kgvpMarketplace = 卖家发货到仓储到客户的佣金率（最常用）
                rate = (
                    r.get("kgvpMarketplace")
                    or r.get("kgvpSupplier")
                    or r.get("paidStorageKgvp")
                )
                try:
                    if rate is not None:
                        out[int(sid)] = float(rate)
                except (TypeError, ValueError):
                    continue
            return out
        except Exception as e:
            logger.warning(f"WB 拉取佣金表失败 shop_id={self.shop_id}: {e}")
            return {}

    async def fetch_all_subjects(self, locale: str = "ru") -> list:
        """拉取 WB 全量分类列表（subjects）

        返回格式：[{subjectID, subjectName, parentID, parentName}, ...]
        API: GET /content/v2/object/all?locale=ru
        """
        try:
            url = f"{WB_CONTENT_API}/content/v2/object/all"
            params = {"locale": locale, "limit": 5000}
            result = await self._request("GET", url, params=params)
            return (result or {}).get("data") or []
        except Exception as e:
            logger.error(f"WB 拉取全量分类失败，shop_id={self.shop_id}: {e}")
            raise

    async def fetch_subject_charcs(self, subject_id: int, locale: str = "ru") -> list:
        """拉取 WB 指定分类的特性/属性定义

        返回格式：[{charcID, name, required, unitName, charcType, popular,
                   dictionary?: [{name, id}]}, ...]
        API: GET /content/v2/object/charcs/{subjectId}?locale=ru
        """
        try:
            url = f"{WB_CONTENT_API}/content/v2/object/charcs/{subject_id}"
            params = {"locale": locale}
            result = await self._request("GET", url, params=params)
            return (result or {}).get("data") or []
        except Exception as e:
            logger.error(f"WB 拉取分类属性失败 subject_id={subject_id}: {e}")
            raise

    async def close(self):
        """关闭HTTP客户端"""
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()


# 注册到工厂
PlatformClientFactory.register("wb", WBClient)
