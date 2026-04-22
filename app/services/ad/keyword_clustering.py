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


_PROPOSE_REPS_PROMPT = """你是俄语电商关键词聚类专家。任务：从给定的搜索词列表中提取多个候选"集群代表词"。

规则：
1. 候选代表词应是**短、通用、不带修饰**的核心短语（2-4 个实词）
   - 好例子: "серьги детские медицинский сплав" / "серьги для девочек" / "серьги сердечки"
   - 坏例子: "серьги детские маленькие для девочки 10 лет" (太具体/加了修饰)
2. 覆盖性原则：候选应尽量覆盖输入词里的**所有核心主题**（儿童/成人/材质/形状/场景）
3. 去重原则：同义候选只留一个（серьги 和 серёжки 的代表词二选一）
4. 目标 **8-15 个候选**，宁可多不可少（由外部 WB 规则进一步筛选）
5. 每个候选词须是**输入列表中真实存在的原词**（不要生造），或者在输入中有明显同义变体

输出严格 JSON（不要 markdown）：
{"candidates": ["代表词1", "代表词2", ...]}
"""


_ASSIGN_PROMPT = """你是俄语电商关键词聚类专家。任务：把关键词列表分配到已给定的固定集群里。

**最重要规则 — 多属性优先**：
如果一个关键词能匹配多个集群，**选最具体的那个**（包含最多核心属性 token 的集群）。
- 例：关键词 "серьги детские медицинский сплав"（4 个核心词: серьги+детские+медицинский+сплав）
  - 候选簇有 "серьги медицинские детские"(3 个: серьги+медицинский+детские) 和
    "серьги детские медицинский сплав"(4 个: серьги+детские+медицинский+сплав)
  - **必须选后者**（完全匹配 > 部分匹配）
- 例：关键词 "серьги детские из медицинского сплава"（含"медицинский сплав"）
  - 必须归 "серьги детские медицинский сплав"，不可归 "серьги для детей"

一般规则：
1. 每个关键词**恰好**分到一个集群
2. 所有集群都不搭 → "_other"
3. 同义合并：серьги↔серёжки↔сережки、детские↔для детей↔детям↔для ребёнка 同
4. 修饰词不影响归属：большие/маленькие/цветные/10 лет/под золото 等不改变主簇

集群选择决策树（按顺序检查）：
- 词里含 "медицинск" 且含 "сплав"？→ 归 "серьги детские медицинский сплав"（最具体）
- 词里含 "сердеч"/"сердц" ？→ 归 "серьги сердечки"
- 词里含 "медицинск" 但不含 "сплав"？→ 归 "серьги медицинские детские"
- 词里含 "для девочек"/"для девочки"/"девчонок"？→ 归 "серьги для девочек"
- 词里含 "детск"/"для детей"/"для ребёнка"/"малыш"？→ 归 "серьги для детей"
- 都不搭 → "_other"

（如果上述关键词集群名不在候选集群里，跳过该条规则，选下一个匹配）

输出严格 JSON（不要 markdown）：
{"assignments": {"集群名1": ["关键词1", ...], "_other": [...]}}
每个输入必须在某个桶里。"""


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


_VALID_CACHE_TTL = 86400  # WB 集群定义变化慢，缓存 24h
_KNOWN_REPS_TTL = 86400 * 30  # 已知 WB 代表词持久化 30 天


def _known_reps_key(advert_id, nm_id) -> str:
    return f"wb:known_reps:{advert_id}:{nm_id}"


def add_known_rep(advert_id, nm_id, rep: str):
    """把经 WB 确认的集群代表词加入 known set，30 天 TTL"""
    try:
        import redis as redis_lib
        r = redis_lib.Redis.from_url(settings.REDIS_URL, decode_responses=True)
        key = _known_reps_key(advert_id, nm_id)
        r.sadd(key, rep)
        r.expire(key, _KNOWN_REPS_TTL)
    except Exception:
        pass


def get_known_reps(advert_id, nm_id) -> List[str]:
    """拿该 SKU 历史已知的所有 WB 代表词（用户解除屏蔽后也保留）"""
    try:
        import redis as redis_lib
        r = redis_lib.Redis.from_url(settings.REDIS_URL, decode_responses=True)
        return list(r.smembers(_known_reps_key(advert_id, nm_id)) or [])
    except Exception:
        return []


def _valid_cache_key(advert_id, nm_id, cluster_names: List[str]) -> str:
    name_str = "|".join(sorted(cluster_names))
    h = hashlib.md5(name_str.encode("utf-8")).hexdigest()[:12]
    return f"wb:cluster_valid:{advert_id}:{nm_id}:{h}"


def _get_valid_cached(key: str) -> Optional[dict]:
    try:
        import redis as redis_lib
        r = redis_lib.Redis.from_url(settings.REDIS_URL, decode_responses=True)
        raw = r.get(key)
        return json.loads(raw) if raw else None
    except Exception:
        return None


def _set_valid_cached(key: str, valid_map: dict):
    try:
        import redis as redis_lib
        r = redis_lib.Redis.from_url(settings.REDIS_URL, decode_responses=True)
        r.setex(key, _VALID_CACHE_TTL, json.dumps(valid_map, ensure_ascii=False))
    except Exception:
        pass


async def propose_cluster_reps_ai(
    db: Session, tenant_id: int, advert_id, nm_id, keywords: List[str],
) -> List[str]:
    """让 AI 只提候选代表词列表（不做分配）"""
    if not keywords:
        return []
    key = f"wb:kw_cand:{advert_id}:{nm_id}:{hashlib.md5('|'.join(sorted(keywords)).encode()).hexdigest()[:12]}"
    cached = _get_cached(key)
    if cached is not None:
        return cached

    if len(keywords) > 80:
        keywords = keywords[:80]
    prompt_lines = ["请从以下关键词列表中提取候选集群代表词（共 {} 条）：".format(len(keywords))]
    for i, kw in enumerate(keywords, 1):
        prompt_lines.append(f"{i}. {kw}")
    prompt = "\n".join(prompt_lines)

    try:
        result = await ai_execute(
            task_type="ad_optimization",
            input_data={"prompt": prompt},
            tenant_id=tenant_id, db=db, triggered_by="manual",
            system_prompt=_PROPOSE_REPS_PROMPT,
            temperature=0.3, max_tokens=1000,
        )
    except Exception as e:
        logger.warning(f"propose_reps AI 失败: {e}")
        return []

    content = result.get("content", "").strip()
    if content.startswith("```"):
        first = content.find("\n")
        last = content.rfind("```")
        if first > 0 and last > first:
            content = content[first + 1:last].strip()
    try:
        parsed = json.loads(content)
        candidates = parsed.get("candidates", []) if isinstance(parsed, dict) else []
        candidates = [str(c).strip() for c in candidates if c and str(c).strip()]
    except Exception:
        candidates = []

    _set_cached(key, candidates)
    logger.info(f"propose_reps advert={advert_id} nm={nm_id} 产出 {len(candidates)} 候选")
    return candidates


async def assign_keywords_to_clusters_ai(
    db: Session, tenant_id: int, advert_id, nm_id,
    keywords: List[str], cluster_names: List[str],
) -> dict:
    """让 AI 把 keywords 分配到 cluster_names 指定的簇里

    Returns:
        {cluster_name: [keyword, ...], "_other": [...]}
    """
    if not keywords or not cluster_names:
        return {}

    # 缓存 key：关键词集 + 簇名集
    kw_hash = hashlib.md5(("|".join(sorted(keywords))).encode()).hexdigest()[:10]
    cn_hash = hashlib.md5(("|".join(sorted(cluster_names))).encode()).hexdigest()[:10]
    key = f"wb:kw_assign:{advert_id}:{nm_id}:{kw_hash}:{cn_hash}"
    cached = _get_cached(key)
    if cached is not None:
        return cached

    lines = [
        "集群列表（固定，不能新增）：",
    ]
    for i, cn in enumerate(cluster_names, 1):
        lines.append(f"  [{i}] {cn}")
    lines.append("")
    lines.append(f"待分配关键词（共 {len(keywords)} 条）：")
    for i, kw in enumerate(keywords, 1):
        lines.append(f"{i}. {kw}")
    prompt = "\n".join(lines)

    try:
        result = await ai_execute(
            task_type="ad_optimization",
            input_data={"prompt": prompt},
            tenant_id=tenant_id, db=db, triggered_by="manual",
            system_prompt=_ASSIGN_PROMPT,
            temperature=0.1, max_tokens=4000,
        )
    except Exception as e:
        logger.warning(f"assign_keywords AI 失败: {e}")
        return {}

    content = result.get("content", "").strip()
    if content.startswith("```"):
        first = content.find("\n")
        last = content.rfind("```")
        if first > 0 and last > first:
            content = content[first + 1:last].strip()
    try:
        parsed = json.loads(content)
        assignments = parsed.get("assignments", {}) if isinstance(parsed, dict) else {}
    except Exception:
        assignments = {}

    # 去重：AI 可能把同一个词分到多个簇，只保留首次出现
    seen = set()
    cleaned = {}
    for bucket_name, bucket_words in assignments.items():
        if not isinstance(bucket_words, list):
            continue
        cleaned[bucket_name] = []
        for w in bucket_words:
            key_lc = str(w).strip().lower()
            if key_lc and key_lc not in seen:
                seen.add(key_lc)
                cleaned[bucket_name].append(str(w).strip())
    assignments = cleaned

    # 保证所有输入词都分到了桶里
    missing = [kw for kw in keywords if kw.strip().lower() not in seen]
    if missing:
        if "_other" not in assignments:
            assignments["_other"] = []
        assignments["_other"].extend(missing)

    _set_cached(key, assignments)
    logger.info(
        f"assign_keywords advert={advert_id} nm={nm_id} 分 {len(keywords)} 词 到 "
        f"{len(cluster_names)} 簇 + _other({len(assignments.get('_other', []))})"
    )
    return assignments


async def validate_cluster_reps_with_wb(
    client, advert_id, nm_id, cluster_names: List[str],
) -> dict:
    """用 WB set-minus 作为 oracle 判断哪些词是 WB 认定的"顶级搜索集群代表词"

    原理：
      - 拉 existing minus list（会被保留）
      - 一次 set-minus(existing + candidates)
      - WB 返回 dropped_invalid 里的就不是 WB 集群代表词
      - 立刻 set-minus(existing) 回滚到原始状态

    Returns:
        {cluster_name: True/False} WB 是否认可该词为集群代表
    """
    if not cluster_names:
        return {}

    key = _valid_cache_key(advert_id, nm_id, cluster_names)
    cached = _get_valid_cached(key)
    if cached is not None:
        logger.info(f"cluster_valid 缓存命中 advert={advert_id} nm={nm_id}")
        return cached

    # 拉 existing
    try:
        excl_map = await client.fetch_excluded_keywords(
            advert_id=advert_id, nm_ids=[int(nm_id)],
        )
        existing = excl_map.get(int(nm_id), [])
    except Exception as e:
        logger.warning(f"cluster_valid 拉 existing 失败 advert={advert_id} nm={nm_id}: {e}")
        return {}

    existing_set = {w.lower().strip() for w in existing}
    # 只测试不在 existing 里的候选（已在里面的肯定是有效的）
    new_candidates = [c for c in cluster_names if c.lower().strip() not in existing_set]

    result_map = {}
    # existing 里的 = 必然有效
    for c in cluster_names:
        if c.lower().strip() in existing_set:
            result_map[c] = True

    if not new_candidates:
        _set_valid_cached(key, result_map)
        return result_map

    # 一次性发 existing + 所有新候选
    merged = list(existing) + new_candidates
    try:
        r = await client.set_excluded_keywords(
            advert_id=advert_id, nm_id=int(nm_id), words=merged,
        )
        dropped = {w.lower().strip() for w in (r.get("dropped_invalid") or [])}
    except Exception as e:
        logger.warning(f"cluster_valid set-minus 测试失败: {e}")
        return result_map

    # 标记：被 WB 拒绝 = 不是集群代表词
    for c in new_candidates:
        is_valid = c.lower().strip() not in dropped
        result_map[c] = is_valid
        if is_valid:
            # 持久化到 Redis known-reps set（30 天），下次自动作种子
            add_known_rep(advert_id, nm_id, c)

    # 立即回滚 —— 把新增的词从 minus 列表移除（只保留 existing）
    # 注意：WB 可能在测试时把 new_candidates 中被接受的那些加进了 minus，必须回滚
    try:
        await client.set_excluded_keywords(
            advert_id=advert_id, nm_id=int(nm_id), words=list(existing),
        )
        logger.info(
            f"cluster_valid advert={advert_id} nm={nm_id} "
            f"input={len(cluster_names)} valid={sum(1 for v in result_map.values() if v)}"
        )
    except Exception as e:
        # 回滚失败是严重问题，打 error log 但不抛（避免影响用户主流程）
        logger.error(
            f"cluster_valid 回滚失败 advert={advert_id} nm={nm_id}: {e} "
            f"WB minus list 可能多了 {len([c for c in new_candidates if result_map.get(c)])} 个未预期的屏蔽词，请人工检查"
        )

    _set_valid_cached(key, result_map)
    return result_map
