"""AI 辅助映射推荐

核心策略：
1. 拉平台全量分类/属性/枚举值（通过 platform client）
2. 让 AI 按语义相似度推荐 top-N 匹配项
3. 返回带置信度的候选，写入映射表但标记 ai_suggested=1 + is_confirmed=0
4. 用户在前端逐条人工确认或修改
"""

import asyncio
import json
from typing import Optional
from sqlalchemy.orm import Session

from app.config import get_settings
from app.services.ai.kimi import KimiClient
from app.services.category_mapping.service import (
    upsert_category_mapping, upsert_attribute_mapping,
    upsert_attribute_value_mapping,
)
from app.models.category import LocalCategory, AttributeMapping
from app.models.shop import Shop
from app.utils.logger import logger
from app.utils.errors import ErrorCode


async def _call_ai(prompt: str, max_tokens: int = 2000) -> Optional[list]:
    """调用 AI 返回 JSON 数组"""
    settings = get_settings()
    client = KimiClient(api_key=settings.KIMI_API_KEY)
    try:
        result = await client.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,  # 映射任务需要稳定输出
            max_tokens=max_tokens,
        )
        content = result.get("content", "").strip()
        # 去掉可能的 markdown 代码块包裹
        if content.startswith("```"):
            content = content.split("\n", 1)[1] if "\n" in content else content
            if content.endswith("```"):
                content = content.rsplit("```", 1)[0]
        if content.startswith("json"):
            content = content[4:].strip()
        return json.loads(content)
    except json.JSONDecodeError as e:
        logger.warning(f"AI 返回非合法 JSON: {e}, content={content[:200]}")
        return None
    except Exception as e:
        logger.error(f"AI 调用失败: {e}")
        return None


# ==================== 批量翻译 ====================

async def _translate_batch(texts: list, target: str = "zh") -> list:
    """批量翻译俄文→中文，返回等长数组（异常用原文兜底）

    一次最多 200 条，超出自动切片。
    """
    if not texts:
        return []
    # 去重后翻译，再按原顺序填回
    unique = list(dict.fromkeys(texts))  # 保持顺序去重
    chunk_size = 200
    translated_map = {}
    for i in range(0, len(unique), chunk_size):
        chunk = unique[i:i + chunk_size]
        numbered = "\n".join([f"{j+1}. {t}" for j, t in enumerate(chunk)])
        prompt = f"""把下列俄文翻译为{'中文' if target == 'zh' else target}，保持电商专业术语准确、简洁。
特别注意：
- 保留品牌名、型号等专有名词不翻译
- 分类名用最常用的中文电商术语（如 Ожерелья → 项链）
- 不要加"翻译："等前缀

输入（俄文，共 {len(chunk)} 条）：
{numbered}

返回 JSON 数组（不含其他文字），长度必须等于 {len(chunk)}：
["中文1", "中文2", ...]
"""
        result = await _call_ai(prompt, max_tokens=4000)
        if result and isinstance(result, list) and len(result) == len(chunk):
            for src, tgt in zip(chunk, result):
                translated_map[src] = tgt if isinstance(tgt, str) and tgt.strip() else src
        else:
            # 翻译失败兜底：用原文
            logger.warning(f"批量翻译失败，使用原文兜底（共 {len(chunk)} 条）")
            for src in chunk:
                translated_map.setdefault(src, src)
    return [translated_map.get(t, t) for t in texts]


# ==================== 品类映射推荐 ====================

async def suggest_category_mappings(
    db: Session, tenant_id: int,
    local_category_id: int, shop_id: int, platforms: list = None,
) -> dict:
    """AI 推荐本地分类 → 各平台分类的映射

    流程：
    1. 读取本地分类（name, name_ru）
    2. 通过 shop 凭证拉取平台全量分类列表
    3. 让 AI 按名称语义推荐 top-1 + 置信度
    4. 写入 category_platform_mappings，ai_suggested=1
    """
    platforms = platforms or ["wb", "ozon"]
    local_cat = db.query(LocalCategory).filter(
        LocalCategory.id == local_category_id,
        LocalCategory.tenant_id == tenant_id,
    ).first()
    if not local_cat:
        return {"code": ErrorCode.PARAM_ERROR, "msg": "本地分类不存在"}

    shop = db.query(Shop).filter(
        Shop.id == shop_id, Shop.tenant_id == tenant_id,
    ).first()
    if not shop:
        return {"code": ErrorCode.SHOP_NOT_FOUND, "msg": "店铺不存在"}

    results = []
    for platform in platforms:
        try:
            platform_cats = await _fetch_platform_categories(shop, platform)
            if not platform_cats:
                results.append({"platform": platform, "error": "拉取平台分类失败"})
                continue
            suggestion = await _ai_match_category(local_cat, platform, platform_cats)
            if suggestion:
                upsert_category_mapping(db, tenant_id, {
                    "local_category_id": local_category_id,
                    "platform": platform,
                    "platform_category_id": str(suggestion["id"]),
                    "platform_category_extra_id": str(suggestion["extra_id"]) if suggestion.get("extra_id") else None,
                    "platform_category_name": suggestion["name"],
                    "platform_parent_path": suggestion.get("path"),
                    "ai_suggested": 1,
                    "ai_confidence": suggestion["confidence"],
                })
                results.append({"platform": platform, **suggestion})
            else:
                results.append({"platform": platform, "error": "AI 未给出推荐"})
        except Exception as e:
            logger.error(f"AI 推荐 {platform} 品类映射失败: {e}")
            results.append({"platform": platform, "error": str(e)})
    return {"code": 0, "data": {"suggestions": results}}


async def _fetch_platform_categories(shop: Shop, platform: str) -> list:
    """拉取平台分类列表，返回 [{id, name, path}, ...]"""
    if platform == "wb":
        from app.services.platform.wb import WBClient
        client = WBClient(shop_id=shop.id, api_key=shop.api_key)
        try:
            subjects = await client.fetch_all_subjects()
            # WB: [{subjectID, subjectName, parentID, parentName}]
            return [{
                "id": s.get("subjectID"),
                "name": s.get("subjectName", ""),
                "path": f"{s.get('parentName', '')} > {s.get('subjectName', '')}".strip(" >"),
            } for s in subjects if s.get("subjectID")]
        finally:
            await client.close()
    elif platform == "ozon":
        from app.services.platform.ozon import OzonClient
        client = OzonClient(
            shop_id=shop.id, api_key=shop.api_key, client_id=shop.client_id,
            perf_client_id=shop.perf_client_id or "",
            perf_client_secret=shop.perf_client_secret or "",
        )
        try:
            tree = await client.fetch_category_tree()
            # 展平叶子节点（只有 type_id 的才是可发布目标）
            flat = []
            _flatten_ozon_tree(tree, [], flat)
            return flat
        finally:
            await client.close()
    return []


def _flatten_ozon_tree(nodes: list, path: list, flat: list, parent_cat_id: int = None):
    """递归展平 Ozon 分类树，只收集叶子（有 type_id 的节点）

    Ozon 发布需要 description_category_id + type_id 两个值。
    展平时：
    - id 存 description_category_id（祖先节点中最近的 category_id）
    - extra_id 存 type_id
    """
    for node in nodes or []:
        name = node.get("category_name") or node.get("type_name") or ""
        cur_path = path + [name]
        cur_cat_id = node.get("description_category_id") or parent_cat_id
        type_id = node.get("type_id")
        children = node.get("children") or []
        if type_id and not children:
            flat.append({
                "id": cur_cat_id,
                "extra_id": type_id,
                "name": name,
                "path": " > ".join(cur_path),
            })
        elif children:
            _flatten_ozon_tree(children, cur_path, flat, parent_cat_id=cur_cat_id)


async def _ai_match_category(local_cat: LocalCategory, platform: str, platform_cats: list) -> Optional[dict]:
    """让 AI 从 platform_cats 里挑最匹配本地分类的一条"""
    candidates = platform_cats[:500]
    # Ozon 候选展示 id+extra_id，WB 只有 id
    cand_lines = "\n".join([
        f"{i+1}. idx={i} name={c['name']} path={c.get('path','')}"
        for i, c in enumerate(candidates)
    ])
    prompt = f"""你是跨境电商分类映射专家。我有一个本地分类，需要在{platform.upper()}平台找到最匹配的分类。

本地分类：
- 中文名：{local_cat.name}
- 俄文名：{local_cat.name_ru or '无'}

{platform.upper()}候选分类列表（共{len(candidates)}条，按序号 idx 标识）：
{cand_lines}

请返回 JSON 格式（不要任何其他文字）：
{{
  "idx": 最匹配候选的序号（上面的 idx 数字）,
  "confidence": 置信度0-100,
  "reason": "为什么选这个，一句话"
}}

要求：
- confidence >= 80 表示高度自信，60-79 表示可能对但需人工确认，< 60 表示不确定
- 完全找不到合适的返回 {{"idx": -1, "confidence": 0, "reason": "找不到匹配"}}
"""
    result = await _call_ai(prompt, max_tokens=300)
    if not result or not isinstance(result, dict):
        return None
    idx = result.get("idx")
    if idx is None or idx < 0 or idx >= len(candidates):
        return None
    picked = candidates[idx]
    return {
        "id": picked["id"],
        "extra_id": picked.get("extra_id"),
        "name": picked.get("name", ""),
        "path": picked.get("path", ""),
        "confidence": int(result.get("confidence", 0)),
        "reason": result.get("reason", ""),
    }


# ==================== 属性映射推荐 ====================

async def suggest_attribute_mappings(
    db: Session, tenant_id: int,
    local_category_id: int, shop_id: int, platform: str,
) -> dict:
    """AI 推荐该本地分类下的属性映射

    流程：
    1. 查本地分类已确认的品类映射，拿到 platform_category_id
    2. 拉平台该分类的必填/可选属性列表
    3. 让 AI 把每个平台属性推荐本地属性名（用户可能已有本地属性也可能是首次建）
    4. 批量写入 attribute_mappings
    """
    from app.models.category import CategoryPlatformMapping
    cat_mapping = db.query(CategoryPlatformMapping).filter(
        CategoryPlatformMapping.tenant_id == tenant_id,
        CategoryPlatformMapping.local_category_id == local_category_id,
        CategoryPlatformMapping.platform == platform,
    ).first()
    if not cat_mapping:
        return {"code": ErrorCode.PARAM_ERROR, "msg": "请先完成品类映射"}

    shop = db.query(Shop).filter(
        Shop.id == shop_id, Shop.tenant_id == tenant_id,
    ).first()
    if not shop:
        return {"code": ErrorCode.SHOP_NOT_FOUND, "msg": "店铺不存在"}

    platform_attrs = await _fetch_platform_attributes(
        shop, platform, cat_mapping.platform_category_id,
        extra_id=cat_mapping.platform_category_extra_id,
    )
    if not platform_attrs:
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "拉取平台属性失败"}

    suggestions = await _ai_suggest_attr_names(platform, platform_attrs)
    if not suggestions:
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "AI 未能推荐属性"}

    # 批量写入
    created = 0
    for attr, suggestion in zip(platform_attrs, suggestions):
        upsert_attribute_mapping(db, tenant_id, {
            "local_category_id": local_category_id,
            "local_attr_name": suggestion.get("local_name", attr["name"]),
            "local_attr_name_ru": attr["name"],
            "platform": platform,
            "platform_attr_id": str(attr.get("id", "")),
            "platform_attr_name": attr["name"],
            "is_required": 1 if attr.get("is_required") else 0,
            "value_type": attr.get("value_type", "string"),
            "platform_dict_id": str(attr.get("dict_id")) if attr.get("dict_id") else None,
            "ai_suggested": 1,
            "ai_confidence": suggestion.get("confidence", 70),
        })
        created += 1
    return {"code": 0, "data": {"count": created}}


async def _fetch_platform_attributes(
    shop: Shop, platform: str, platform_category_id: str,
    extra_id: Optional[str] = None,
) -> list:
    """拉取平台分类下的属性列表，返回 [{id, name, is_required, value_type, dict_id}]

    - WB: platform_category_id = subjectID
    - Ozon: platform_category_id = description_category_id, extra_id = type_id
    """
    if platform == "wb":
        from app.services.platform.wb import WBClient
        client = WBClient(shop_id=shop.id, api_key=shop.api_key)
        try:
            charcs = await client.fetch_subject_charcs(int(platform_category_id))
            # WB charcs 返回的枚举值在 dictionary 字段里（直接嵌入）
            return [{
                "id": c.get("charcID"),
                "name": c.get("name", ""),
                "is_required": c.get("required", False),
                "value_type": "enum" if c.get("dictionary") else (c.get("charcType") or "string"),
                "dict_id": str(c.get("charcID")) if c.get("dictionary") else None,
                "dictionary": c.get("dictionary") or [],  # WB 直接返回枚举值列表
            } for c in charcs]
        finally:
            await client.close()
    elif platform == "ozon":
        if not extra_id:
            logger.warning(
                f"Ozon 属性拉取缺少 type_id（extra_id），shop={shop.id} "
                f"cat={platform_category_id}"
            )
            return []
        from app.services.platform.ozon import OzonClient
        client = OzonClient(
            shop_id=shop.id, api_key=shop.api_key, client_id=shop.client_id,
            perf_client_id=shop.perf_client_id or "",
            perf_client_secret=shop.perf_client_secret or "",
        )
        try:
            attrs = await client.fetch_category_attributes(
                int(platform_category_id), int(extra_id),
            )
            # Ozon: type=Enum 或 dictionary_id != 0 表示枚举类型，需要另拉字典值
            def _ozon_value_type(a: dict) -> str:
                t = (a.get("type") or "").lower()
                if t in ("string", "multiline"):
                    return "string"
                if t in ("integer", "decimal"):
                    return "number"
                if t == "boolean":
                    return "boolean"
                if a.get("dictionary_id", 0):
                    return "enum"
                return "string"
            return [{
                "id": a.get("id"),
                "name": a.get("name", ""),
                "is_required": a.get("is_required", False),
                "value_type": _ozon_value_type(a),
                "dict_id": str(a.get("dictionary_id")) if a.get("dictionary_id") else None,
                "dictionary": [],  # Ozon 字典值要另拉
            } for a in attrs]
        finally:
            await client.close()
    return []


async def _ai_suggest_attr_names(platform: str, platform_attrs: list) -> list:
    """让 AI 为每个平台属性推荐本地属性名（中文）"""
    attr_lines = "\n".join([
        f"{i+1}. {a['name']}{' [必填]' if a.get('is_required') else ''}"
        for i, a in enumerate(platform_attrs)
    ])
    prompt = f"""你是跨境电商属性映射专家。下面是{platform.upper()}平台某分类下的属性列表（俄文），请为每个属性推荐一个中文本地属性名。

平台属性列表：
{attr_lines}

请按**相同顺序**返回 JSON 数组（不要任何其他文字），每项一个对象：
[
  {{"local_name": "中文属性名", "confidence": 置信度0-100}},
  ...
]

要求：
- 数组长度必须等于输入属性数
- local_name 用最通用的中文电商术语（如"材质"、"颜色"、"尺寸"、"品牌"）
- 置信度 confidence: 80+ 表示高度确定，50-79 需人工确认，<50 不确定
"""
    result = await _call_ai(prompt, max_tokens=3000)
    if not result or not isinstance(result, list):
        return []
    return result


# ==================== 属性值映射推荐 ====================

async def suggest_attribute_value_mappings(
    db: Session, tenant_id: int, attribute_mapping_id: int,
    local_values: list, shop_id: int,
) -> dict:
    """AI 推荐本地属性值 → 平台枚举值的映射

    流程:
    1. 查属性映射 → 拿到 platform + platform_attr_id + value_type
    2. 查同分类同平台的品类映射 → 拿到 platform_category_id + extra_id
    3. 拉平台该属性的枚举值字典
    4. 让 AI 为每个本地值匹配最接近的平台枚举值
    5. 批量 upsert attribute_value_mappings
    """
    from app.models.category import CategoryPlatformMapping

    attr_mapping = db.query(AttributeMapping).filter(
        AttributeMapping.id == attribute_mapping_id,
        AttributeMapping.tenant_id == tenant_id,
    ).first()
    if not attr_mapping:
        return {"code": ErrorCode.PARAM_ERROR, "msg": "属性映射不存在"}
    if attr_mapping.value_type != "enum":
        return {"code": ErrorCode.PARAM_ERROR, "msg": "仅枚举类型属性支持属性值映射"}
    if not local_values:
        return {"code": ErrorCode.PARAM_ERROR, "msg": "请提供本地属性值列表"}

    cat_mapping = db.query(CategoryPlatformMapping).filter(
        CategoryPlatformMapping.tenant_id == tenant_id,
        CategoryPlatformMapping.local_category_id == attr_mapping.local_category_id,
        CategoryPlatformMapping.platform == attr_mapping.platform,
    ).first()
    if not cat_mapping:
        return {"code": ErrorCode.PARAM_ERROR, "msg": "请先完成品类映射"}

    shop = db.query(Shop).filter(
        Shop.id == shop_id, Shop.tenant_id == tenant_id,
    ).first()
    if not shop:
        return {"code": ErrorCode.SHOP_NOT_FOUND, "msg": "店铺不存在"}

    # 拉平台枚举值
    enum_values = await _fetch_platform_enum_values(
        shop, attr_mapping.platform, attr_mapping.platform_attr_id,
        cat_mapping.platform_category_id, cat_mapping.platform_category_extra_id,
    )
    if not enum_values:
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "拉取平台枚举值失败或该属性不是字典类型"}

    # AI 批量匹配
    suggestions = await _ai_match_values(
        attr_mapping.local_attr_name, local_values, enum_values,
    )
    if not suggestions:
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "AI 未能推荐"}

    # 写入
    created = 0
    for local_val, sug in zip(local_values, suggestions):
        if not sug or sug.get("idx") is None or sug["idx"] < 0 or sug["idx"] >= len(enum_values):
            continue
        picked = enum_values[sug["idx"]]
        upsert_attribute_value_mapping(db, tenant_id, {
            "attribute_mapping_id": attribute_mapping_id,
            "local_value": local_val,
            "platform_value": picked["value"],
            "platform_value_id": str(picked.get("id")) if picked.get("id") else None,
            "ai_suggested": 1,
            "ai_confidence": int(sug.get("confidence", 0)),
        })
        created += 1
    return {"code": 0, "data": {"count": created, "total": len(local_values)}}


async def _fetch_platform_enum_values(
    shop: Shop, platform: str, platform_attr_id: str,
    platform_category_id: str, extra_id: Optional[str],
) -> list:
    """拉取平台枚举值字典，返回 [{id, value}, ...]"""
    if platform == "wb":
        from app.services.platform.wb import WBClient
        client = WBClient(shop_id=shop.id, api_key=shop.api_key)
        try:
            charcs = await client.fetch_subject_charcs(int(platform_category_id))
            # 找到目标 charcID 的 dictionary
            for c in charcs:
                if str(c.get("charcID")) == str(platform_attr_id):
                    dict_items = c.get("dictionary") or []
                    # WB dictionary 项格式：{name: "...", id: 0}（部分属性只有 name）
                    return [{
                        "id": d.get("id"),
                        "value": d.get("name", ""),
                    } for d in dict_items if d.get("name")]
            return []
        finally:
            await client.close()
    elif platform == "ozon":
        if not extra_id:
            return []
        from app.services.platform.ozon import OzonClient
        client = OzonClient(
            shop_id=shop.id, api_key=shop.api_key, client_id=shop.client_id,
            perf_client_id=shop.perf_client_id or "",
            perf_client_secret=shop.perf_client_secret or "",
        )
        try:
            values = await client.fetch_attribute_values(
                int(platform_category_id), int(extra_id), int(platform_attr_id),
            )
            return [{
                "id": v.get("id"),
                "value": v.get("value", ""),
            } for v in values if v.get("value")]
        finally:
            await client.close()
    return []


async def _ai_match_values(attr_name: str, local_values: list, enum_values: list) -> list:
    """为每个本地值匹配最接近的平台枚举值，返回等长数组"""
    # 候选太多时截断，避免 token 超限
    candidates = enum_values[:300]
    cand_lines = "\n".join([
        f"{i}. {c['value']}"
        for i, c in enumerate(candidates)
    ])
    local_lines = "\n".join([f"- {v}" for v in local_values])
    prompt = f"""你是跨境电商属性值映射专家。现在需要把一组本地属性值匹配到平台字典的枚举值。

属性名：{attr_name}

本地值（共 {len(local_values)} 个）：
{local_lines}

平台枚举候选（按 idx 标识，共 {len(candidates)} 个）：
{cand_lines}

请按**本地值的顺序**返回 JSON 数组（不要任何其他文字）：
[
  {{"idx": 候选序号, "confidence": 置信度0-100}},
  ...
]

要求：
- 数组长度必须等于本地值数量（{len(local_values)}）
- 找不到匹配时返回 {{"idx": -1, "confidence": 0}}
- confidence >= 80 高度自信，60-79 可能需人工核对
"""
    result = await _call_ai(prompt, max_tokens=2000)
    if not result or not isinstance(result, list):
        return []
    return result


# ==================== 从 WB 初始化本地分类 ====================

async def init_mapping_from_wb(
    db: Session, tenant_id: int, shop_id: int,
    include_enum_values: bool = True,
) -> dict:
    """从 WB 店铺已用分类初始化本地分类 + 属性 + 枚举值

    流程：
      1. 查店铺 platform_listings 里已出现的 subjectID 集合
      2. 调 fetch_all_subjects 拉 WB 全量分类字典
      3. 筛选出店铺实际用到的，批量翻译为中文
      4. 建 local_category + WB 品类映射 (is_confirmed=1)
      5. 对每个分类拉 charcs 属性，批量翻译，建 WB 属性映射
      6. 如 include_enum_values=True，dictionary 字段内枚举值也批量翻译
         写入 attribute_value_mappings（本地=中文，平台=俄文）

    返回：{categories: N, attributes: M, values: K, skipped: [...]}
    """
    from app.models.product import PlatformListing
    from app.models.category import LocalCategory, CategoryPlatformMapping, AttributeMapping
    from app.services.platform.wb import WBClient
    from sqlalchemy import distinct

    shop = db.query(Shop).filter(
        Shop.id == shop_id, Shop.tenant_id == tenant_id,
    ).first()
    if not shop:
        return {"code": ErrorCode.SHOP_NOT_FOUND, "msg": "店铺不存在"}
    if shop.platform != "wb":
        return {"code": ErrorCode.PARAM_ERROR, "msg": "初始化只支持 WB 店铺"}

    # 1. 店铺已用 subject_id
    used_ids = [
        row[0] for row in db.query(distinct(PlatformListing.platform_category_id)).filter(
            PlatformListing.tenant_id == tenant_id,
            PlatformListing.shop_id == shop_id,
            PlatformListing.platform == "wb",
            PlatformListing.platform_category_id.isnot(None),
        ).all() if row[0]
    ]
    if not used_ids:
        return {"code": ErrorCode.PARAM_ERROR, "msg": "店铺暂无商品分类数据，请先同步商品"}

    # 2. 拉全量分类建字典
    client = WBClient(shop_id=shop_id, api_key=shop.api_key)
    try:
        subjects = await client.fetch_all_subjects()
    finally:
        await client.close()
    subject_map = {str(s.get("subjectID")): s for s in subjects if s.get("subjectID")}

    # 3. 筛选店铺已用分类并收集俄文名做批量翻译
    target_subjects = []
    for sid in used_ids:
        s = subject_map.get(str(sid))
        if s:
            target_subjects.append(s)
    if not target_subjects:
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "WB 分类字典未命中店铺数据"}

    ru_names = [s.get("subjectName", "") for s in target_subjects]
    zh_names = await _translate_batch(ru_names)

    # 4. 建本地分类 + WB 映射
    stats = {"categories": 0, "attributes": 0, "values": 0, "skipped": []}
    local_cat_map = {}  # subjectID → local_category_id
    for s, zh in zip(target_subjects, zh_names):
        subj_id = str(s["subjectID"])
        subj_name_ru = s.get("subjectName", "")

        # 检查是否已存在（按俄文名 + 租户唯一）
        existing = db.query(LocalCategory).filter(
            LocalCategory.tenant_id == tenant_id,
            LocalCategory.name_ru == subj_name_ru,
            LocalCategory.status == "active",
        ).first()
        if existing:
            local_cat_map[subj_id] = existing.id
            stats["skipped"].append(f"本地分类已存在: {subj_name_ru}")
            continue

        cat = LocalCategory(
            tenant_id=tenant_id,
            parent_id=None,
            name=zh or subj_name_ru,
            name_ru=subj_name_ru,
            level=1,
        )
        db.add(cat)
        db.flush()
        local_cat_map[subj_id] = cat.id
        stats["categories"] += 1

        # 同时建 WB 品类映射（1:1 直接确认）
        upsert_category_mapping(db, tenant_id, {
            "local_category_id": cat.id,
            "platform": "wb",
            "platform_category_id": subj_id,
            "platform_category_name": subj_name_ru,
            "platform_parent_path": f"{s.get('parentName','')} > {subj_name_ru}".strip(" >"),
            "ai_suggested": 0,  # 初始化来的不是 AI 推荐，是 1:1 直接关联
            "ai_confidence": 100,
        })
        # 再标记为已确认
        mp = db.query(CategoryPlatformMapping).filter(
            CategoryPlatformMapping.tenant_id == tenant_id,
            CategoryPlatformMapping.local_category_id == cat.id,
            CategoryPlatformMapping.platform == "wb",
        ).first()
        if mp:
            mp.is_confirmed = 1
            from datetime import datetime, timezone
            mp.confirmed_at = datetime.now(timezone.utc)
    db.commit()

    # 5. 对每个分类拉 charcs，建属性映射
    client = WBClient(shop_id=shop_id, api_key=shop.api_key)
    try:
        for subj_id, local_cat_id in local_cat_map.items():
            try:
                charcs = await client.fetch_subject_charcs(int(subj_id))
            except Exception as e:
                logger.warning(f"拉取 subject_id={subj_id} charcs 失败: {e}")
                stats["skipped"].append(f"charcs 拉取失败: {subj_id}")
                continue
            if not charcs:
                continue

            attr_ru_names = [c.get("name", "") for c in charcs]
            attr_zh_names = await _translate_batch(attr_ru_names)

            for c, attr_zh in zip(charcs, attr_zh_names):
                attr_name_ru = c.get("name", "")
                if not attr_name_ru:
                    continue
                has_dict = bool(c.get("dictionary"))
                value_type = "enum" if has_dict else (c.get("charcType") or "string")

                res = upsert_attribute_mapping(db, tenant_id, {
                    "local_category_id": local_cat_id,
                    "local_attr_name": attr_zh or attr_name_ru,
                    "local_attr_name_ru": attr_name_ru,
                    "platform": "wb",
                    "platform_attr_id": str(c.get("charcID", "")),
                    "platform_attr_name": attr_name_ru,
                    "is_required": 1 if c.get("required") else 0,
                    "value_type": value_type,
                    "platform_dict_id": str(c.get("charcID")) if has_dict else None,
                    "ai_suggested": 0,
                    "ai_confidence": 100,
                })
                if res["code"] != 0:
                    continue
                attr_id = res["data"]["id"]
                # 初始化来的直接确认
                attr_mp = db.query(AttributeMapping).filter(
                    AttributeMapping.id == attr_id,
                    AttributeMapping.tenant_id == tenant_id,
                ).first()
                if attr_mp:
                    attr_mp.is_confirmed = 1
                    from datetime import datetime, timezone
                    attr_mp.confirmed_at = datetime.now(timezone.utc)
                stats["attributes"] += 1

                # 6. 枚举值写入
                if include_enum_values and has_dict:
                    dict_items = c.get("dictionary") or []
                    if not dict_items:
                        continue
                    enum_ru = [d.get("name", "") for d in dict_items if d.get("name")]
                    if not enum_ru:
                        continue
                    enum_zh = await _translate_batch(enum_ru)
                    for d, zh_val in zip(dict_items, enum_zh):
                        val_ru = d.get("name", "")
                        if not val_ru:
                            continue
                        upsert_attribute_value_mapping(db, tenant_id, {
                            "attribute_mapping_id": attr_id,
                            "local_value": zh_val or val_ru,
                            "local_value_ru": val_ru,
                            "platform_value": val_ru,
                            "platform_value_id": str(d.get("id")) if d.get("id") else None,
                            "ai_suggested": 0,
                            "ai_confidence": 100,
                        })
                        stats["values"] += 1
            db.commit()
    finally:
        await client.close()

    return {"code": 0, "data": stats}


# ==================== 从本地批量匹配 Ozon ====================

async def match_ozon_from_local(
    db: Session, tenant_id: int, shop_id: int,
) -> dict:
    """遍历已有本地分类，AI 批量匹配 Ozon 平台的分类 + 属性映射

    流程:
    1. 查所有本地分类
    2. 对每个本地分类调现有 suggest_category_mappings(ozon)
    3. 对每个已映射分类调 suggest_attribute_mappings(ozon)
    4. 全部 is_confirmed=0（待人工确认）

    返回：{categories: {matched, failed}, attributes: {matched, failed}}
    """
    shop = db.query(Shop).filter(
        Shop.id == shop_id, Shop.tenant_id == tenant_id,
    ).first()
    if not shop:
        return {"code": ErrorCode.SHOP_NOT_FOUND, "msg": "店铺不存在"}
    if shop.platform != "ozon":
        return {"code": ErrorCode.PARAM_ERROR, "msg": "Ozon 匹配只支持 Ozon 店铺"}

    local_cats = db.query(LocalCategory).filter(
        LocalCategory.tenant_id == tenant_id,
        LocalCategory.status == "active",
    ).all()
    if not local_cats:
        return {"code": ErrorCode.PARAM_ERROR, "msg": "本地暂无分类，请先从 WB 初始化"}

    cat_stats = {"matched": 0, "failed": 0}
    attr_stats = {"matched": 0, "failed": 0}

    for lc in local_cats:
        # 品类映射
        try:
            res = await suggest_category_mappings(
                db, tenant_id, lc.id, shop_id, ["ozon"],
            )
            sugs = (res.get("data") or {}).get("suggestions") or []
            if sugs and sugs[0].get("id"):
                cat_stats["matched"] += 1
            else:
                cat_stats["failed"] += 1
                continue
        except Exception as e:
            logger.warning(f"本地分类 {lc.id} 匹配 Ozon 失败: {e}")
            cat_stats["failed"] += 1
            continue

        # 属性映射（基于上面成功的品类映射）
        try:
            res = await suggest_attribute_mappings(
                db, tenant_id, lc.id, shop_id, "ozon",
            )
            if res["code"] == 0:
                attr_stats["matched"] += (res.get("data") or {}).get("count", 0)
            else:
                attr_stats["failed"] += 1
        except Exception as e:
            logger.warning(f"本地分类 {lc.id} 属性映射 Ozon 失败: {e}")
            attr_stats["failed"] += 1

    return {"code": 0, "data": {"categories": cat_stats, "attributes": attr_stats}}
