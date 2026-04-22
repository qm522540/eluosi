"""关键词 AI 语义聚类

对 WB 广告活动的用户搜索词做语义聚类，对齐 WB 后台「顶级搜索集群」粒度。

背景：
- WB 后台的 SKU 级集群视图是 AI 做的语义分组（серьги ↔ серёжки 合并、
  детские ↔ для детей 合并、修饰词忽略等）
- 本地字符串规则（前缀/bag-of-words）无法复现，需调 DeepSeek 做语义理解
- 缓存 30 分钟：同活动+SKU+关键词集合不变时命中缓存，不反复调 AI
"""

import hashlib
import json
from typing import List, Dict, Optional

from sqlalchemy.orm import Session

from app.config import get_settings
from app.services.ai.router import execute as ai_execute
from app.utils.logger import logger

settings = get_settings()


_CLUSTER_CACHE_TTL = 1800  # 30 分钟


_SYSTEM_PROMPT = """你是俄语电商关键词聚类专家。对 WB 广告活动的用户搜索词按"购买意图"语义聚类，对齐 WB 后台「顶级搜索集群」粒度。

规则：
1. 同义词合并：серьги / серёжки / сережки 都是"耳环"，视为同一主词
2. 形态变化合并：детский / детские / для детей / детям 都是"儿童"，视为同一限定
3. 修饰词不分家：加了 большие / маленькие / красивые / с разными лицами 等形容不应让变体分簇
4. 核心属性分簇：是否含"медицинский сплав"(医用合金) / "сердечки"(心形) / "для девочек"(女孩) 等是分簇依据
5. 簇代表词：从簇内挑一个最具代表性的原词（通常是最短且最抽象的）
6. 目标 2-8 个簇（根据多样性）；所有输入词必须出现在某个簇的 members 里，不能漏

输出严格 JSON（不要 markdown 代码块包裹）：
{"clusters": [{"name": "代表词", "members": ["原词1", "原词2", ...]}]}
"""


def _cache_key(advert_id, nm_id, keywords: List[str]) -> str:
    """Redis key：活动+SKU+关键词集合哈希（关键词变化就自动换 key）"""
    kw_str = "|".join(sorted(keywords))
    kw_hash = hashlib.md5(kw_str.encode("utf-8")).hexdigest()[:12]
    return f"wb:kw_clusters:{advert_id}:{nm_id}:{kw_hash}"


def _get_cached(key: str) -> Optional[list]:
    try:
        import redis as redis_lib
        r = redis_lib.Redis.from_url(settings.REDIS_URL, decode_responses=True)
        raw = r.get(key)
        return json.loads(raw) if raw else None
    except Exception:
        return None


def _set_cached(key: str, clusters: list):
    try:
        import redis as redis_lib
        r = redis_lib.Redis.from_url(settings.REDIS_URL, decode_responses=True)
        r.setex(key, _CLUSTER_CACHE_TTL, json.dumps(clusters, ensure_ascii=False))
    except Exception:
        pass


def _parse_ai_response(content: str) -> List[Dict]:
    """解析 DeepSeek 返回：应为 JSON，可能带 markdown 包裹"""
    text = content.strip()
    if text.startswith("```"):
        # 去掉 ```json ... ``` 包裹
        first = text.find("\n")
        last = text.rfind("```")
        if first > 0 and last > first:
            text = text[first + 1:last].strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        logger.warning(f"kw_clustering AI 返回非 JSON: {e} content={content[:200]}")
        return []
    clusters = parsed.get("clusters") if isinstance(parsed, dict) else None
    if not isinstance(clusters, list):
        return []
    # 校验结构
    out = []
    for c in clusters:
        if not isinstance(c, dict):
            continue
        name = c.get("name") or ""
        members = c.get("members") or []
        if not name or not isinstance(members, list):
            continue
        out.append({
            "name": str(name),
            "members": [str(m) for m in members if m],
        })
    return out


async def cluster_keywords_ai(
    db: Session,
    tenant_id: int,
    advert_id,
    nm_id,
    keywords: List[str],
) -> List[Dict]:
    """用 DeepSeek 对关键词做语义聚类

    Args:
        db: DB session (ai_execute 写日志需要)
        tenant_id: 租户 ID
        advert_id: WB 活动 ID (缓存 key 一部分)
        nm_id: WB 商品 nm_id (缓存 key 一部分)
        keywords: 活跃关键词列表

    Returns:
        [{"name": str, "members": [str]}] 或 [] (失败 / 空输入)
    """
    if not keywords:
        return []

    key = _cache_key(advert_id, nm_id, keywords)
    cached = _get_cached(key)
    if cached is not None:
        logger.info(f"kw_clustering 缓存命中 advert={advert_id} nm={nm_id} n={len(keywords)}")
        return cached

    # 限制输入量：太多词 token 会爆，截断到前 60（按曝光排序的话是前 60 个高曝光词）
    if len(keywords) > 60:
        keywords = keywords[:60]

    prompt_lines = ["请聚类下列关键词（共 {} 条）：".format(len(keywords))]
    for i, kw in enumerate(keywords, 1):
        prompt_lines.append(f"{i}. {kw}")
    prompt = "\n".join(prompt_lines)

    try:
        result = await ai_execute(
            task_type="ad_optimization",
            input_data={"prompt": prompt},
            tenant_id=tenant_id,
            db=db,
            triggered_by="manual",
            system_prompt=_SYSTEM_PROMPT,
            temperature=0.2,  # 低温度求稳定
            max_tokens=3000,
        )
    except Exception as e:
        logger.warning(f"kw_clustering AI 调用失败 advert={advert_id} nm={nm_id}: {e}")
        return []

    clusters = _parse_ai_response(result.get("content", ""))
    if not clusters:
        return []

    # 保证所有输入词都出现在某个 cluster.members 里，否则补一个"其他"簇
    all_members = set()
    for c in clusters:
        for m in c["members"]:
            all_members.add(m.strip().lower())
    missing = [kw for kw in keywords if kw.strip().lower() not in all_members]
    if missing:
        clusters.append({"name": "其他", "members": missing})

    _set_cached(key, clusters)
    logger.info(
        f"kw_clustering AI 聚类成功 advert={advert_id} nm={nm_id} "
        f"input={len(keywords)} → {len(clusters)} 簇"
    )
    return clusters
