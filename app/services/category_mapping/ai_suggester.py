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

    前置条件：属性是枚举类型（value_type=enum 且 platform_dict_id 存在）
    """
    attr_mapping = db.query(AttributeMapping).filter(
        AttributeMapping.id == attribute_mapping_id,
        AttributeMapping.tenant_id == tenant_id,
    ).first()
    if not attr_mapping:
        return {"code": ErrorCode.PARAM_ERROR, "msg": "属性映射不存在"}
    if attr_mapping.value_type != "enum":
        return {"code": ErrorCode.PARAM_ERROR, "msg": "仅枚举类型属性支持属性值映射"}

    # TODO: 拉取平台枚举值（需 WB charcs 里的 dictionary 或 Ozon attribute/values）
    # 这里先实现框架，具体拉取逻辑与平台强相关，放到后续迭代
    return {"code": 0, "data": {"msg": "属性值推荐功能框架已就绪，等后续接入平台枚举值拉取"}}
