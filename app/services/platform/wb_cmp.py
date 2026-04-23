"""WB seller-panel 内部 API 客户端 (cmp.wildberries.ru)

用于自动同步「顶级搜索集群」数据，避免用户每周手动上传 xlsx。

认证：authorizev3 JWT + x-supplierid UUID（用户从浏览器 F12 拷贝，约 7-30 天过期）。
用户在店铺设置填这两个值 → 本 client 读 shop 字段调 API。

端点（HAR 分析）：
- GET /api/v1/advert/{advert_id}/preset-info?nm_id=X&from=Y-m-d&to=Y-m-d&...
  → 6 个 WB 官方簇汇总：{items: [{name, views, clicks, baskets, orders, is_excluded, ...}]}
- GET /api/v1/advert/{advert_id}/preset/words?nm_id=X&norm_query=簇名&from=Y-m-d&to=Y-m-d
  → 该簇全部关键词：{raw_queries: [str, ...]}

遍历策略：先 preset-info 拿 6 簇，再对每簇调一次 preset/words，拼出完整 kw→cluster 映射。
"""

from __future__ import annotations

import base64
import json
from datetime import datetime, date, timezone, timedelta
from typing import List, Dict, Optional

import httpx

from app.utils.moscow_time import moscow_today

from app.utils.logger import logger


BASE_URL = "https://cmp.wildberries.ru"


class CmpAuthExpired(Exception):
    """JWT token 过期或无效（401/403），需要用户重新 F12 拷贝"""


class WBCmpClient:
    """不继承 BasePlatformClient —— 认证完全不同（JWT 而非 API Key）"""

    def __init__(self, authorizev3: str, supplierid: str, timeout: float = 30.0):
        if not authorizev3 or not supplierid:
            raise ValueError("WBCmpClient 需要 authorizev3 和 supplierid")
        self._client = httpx.AsyncClient(
            base_url=BASE_URL,
            timeout=timeout,
            headers={
                "authorizev3": authorizev3,
                "x-supplierid": supplierid,
                "accept": "application/json, text/plain, */*",
                "accept-language": "zh-CN,zh;q=0.9,ru;q=0.8,en;q=0.7",
                "origin": BASE_URL,
                "referer": BASE_URL + "/",
                "user-agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"
                ),
            },
        )

    async def close(self):
        await self._client.aclose()

    @staticmethod
    def parse_jwt_exp(token: str) -> Optional[datetime]:
        """从 JWT payload 解出 exp 字段（UTC naive datetime）。失败返 None。"""
        try:
            parts = token.split(".")
            if len(parts) < 2:
                return None
            payload_b64 = parts[1]
            # base64url padding
            pad = "=" * (-len(payload_b64) % 4)
            payload = json.loads(base64.urlsafe_b64decode(payload_b64 + pad))
            exp = payload.get("exp")
            if not exp:
                return None
            return datetime.fromtimestamp(int(exp), tz=timezone.utc).replace(tzinfo=None)
        except Exception as e:
            logger.warning(f"JWT exp 解析失败: {e}")
            return None

    async def _get(self, path: str, params: Dict) -> Dict:
        r = await self._client.get(path, params=params)
        if r.status_code in (401, 403):
            raise CmpAuthExpired(f"{path} 返回 {r.status_code}，JWT 可能过期")
        r.raise_for_status()
        return r.json()

    async def fetch_preset_info(
        self, advert_id: int, nm_id: int,
        date_from: date, date_to: date, page_size: int = 50,
    ) -> List[Dict]:
        """拉该 (activity, nm_id) 的全部 WB 官方集群汇总。

        返回 items 列表，每项含 name/views/clicks/baskets/orders/ctr/cpc/cpm/avg_pos/is_excluded/spend
        """
        data = await self._get(
            f"/api/v1/advert/{advert_id}/preset-info",
            {
                "page_size":      page_size,
                "page_number":    1,
                "filter_query":   "",
                "from":           date_from.strftime("%Y-%m-%d"),
                "to":             date_to.strftime("%Y-%m-%d"),
                "sort_direction": "descend",
                "nm_id":          nm_id,
                "calc_pages":     "true",
                "calc_total":     "true",
            },
        )
        return data.get("items") or []

    async def fetch_cluster_words(
        self, advert_id: int, nm_id: int, cluster_name: str,
        date_from: date, date_to: date,
    ) -> List[str]:
        """拉该簇下全部用户搜索词"""
        data = await self._get(
            f"/api/v1/advert/{advert_id}/preset/words",
            {
                "nm_id":      nm_id,
                "norm_query": cluster_name,
                "from":       date_from.strftime("%Y-%m-%d"),
                "to":         date_to.strftime("%Y-%m-%d"),
            },
        )
        return [str(q).strip() for q in (data.get("raw_queries") or []) if q]

    async def fetch_cluster_oracle_full(
        self, advert_id: int, nm_id: int,
        date_from: Optional[date] = None, date_to: Optional[date] = None,
    ) -> Dict:
        """一次拉完整 oracle：6 簇汇总 + 每簇全部词。

        返回：
          {
            "summary": [...preset-info items...],
            "mapping": [{"cluster_name": str, "keyword": str}, ...]
          }
        """
        if date_to is None:
            date_to = moscow_today() - timedelta(days=1)
        if date_from is None:
            date_from = date_to - timedelta(days=6)  # 默认 7 天窗口，对齐 WB 后台

        summary = await self.fetch_preset_info(
            advert_id=advert_id, nm_id=nm_id,
            date_from=date_from, date_to=date_to,
        )

        mapping: List[Dict] = []
        for s in summary:
            cname = s.get("name")
            if not cname:
                continue
            words = await self.fetch_cluster_words(
                advert_id=advert_id, nm_id=nm_id, cluster_name=cname,
                date_from=date_from, date_to=date_to,
            )
            for w in words:
                mapping.append({"cluster_name": cname, "keyword": w})

        logger.info(
            f"[WBCmp] advert={advert_id} nm={nm_id} "
            f"{date_from}~{date_to}: {len(summary)} 簇 / {len(mapping)} 词"
        )
        return {
            "summary": summary,
            "mapping": mapping,
            "date_from": date_from,
            "date_to": date_to,
        }
