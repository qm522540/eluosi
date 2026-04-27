"""SEO 商品描述生成器 — 基于全量缺词候选 + 商品信息 + 当前描述（如有），调 GLM 生成俄语商品描述。

与 title_generator 的差别：
- 描述不让用户勾选 N 个候选词，而是后端自取全量缺词（按 score desc 限 50 个）
- 描述要求长度 800-2000 字符（标题 80-180 字符）
- 描述允许段落分隔（\\n\\n），不强制全小写无标点
- 描述需要"卖点 + 使用场景 + 属性自然融入"，不是关键词堆叠
- 描述若已有 current_description_ru，走"渐进改写"模式：保留卖点融入新词

调用链路：
- API 层(`/seo/shop/{shop_id}/generate-description`) → 本 service.generate_description()
- 本 service → ai_router.execute(task_type='seo_generation', ...) → GLM 客户端
- 持久化到 seo_generated_contents 表 content_type='description'

规则合规：
- 规则 1 tenant_id：products / listing / candidates 三次查询都 WHERE tenant_id
- 规则 4 shop_id：所有查询按 shop_id 过滤（API 层 get_owned_shop 已守卫）
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.seo import SeoGeneratedContent
from app.services.ai import router as ai_router
from app.utils.errors import ErrorCode
from app.utils.logger import logger


# ==================== Prompt 模板 ====================

SYSTEM_PROMPT = """你是俄罗斯跨境电商（WB / Ozon / Yandex）商品描述（description）写作专家。
你的工作是基于商品信息和反哺关键词清单，写出一段既能吸引用户购买、又能被搜索引擎抓到关键词的俄语商品描述。

【核心目标】
描述与标题分工不同：
- 标题：用户搜索时第一眼看到的，关键词位置权重决定排名
- 描述：用户被标题吸引点开后，决定是否购买的临门一脚 — **转化率优先，SEO 顺带**

【写作约束】
1. 输出俄语描述，长度 800-2000 字符（包括空格和换行；WB 上限 5000 / Ozon 上限 6000，留出余量）
2. 用段落分隔（\\n\\n），不要写成单行长句
3. 推荐结构：开头一句钩子（核心卖点）→ 商品特征/材质/尺寸 → 使用场景 → 包装/配送/售后（如适用）
4. 关键词自然融入正文，**禁止罗列堆砌**（不要写 "Ключевые слова: ..."）
5. 同义词换着用避免重复（например "сережки / серьги / украшение для ушей"）
6. 保留商品的真实属性（颜色、材质、尺寸、重量），**不能编造原数据没有的属性**
7. 保留"必须保留的高价值词"列表里的词（已在原标题/原描述出现且带过订单/曝光的）
8. 全俄语，不要混用中文/英文（英文品牌名 / 国际通用词如 "happy birthday" 可保留）
9. 标点正常使用（描述不像标题那样无标点，正常的逗号句号必须有，让用户读得舒服）

【关键词融入数量参考】
传给你 30-50 个候选词，你不需要全部融入，**优先选高分（前 20-30 个）+ 与商品语义最契合**的融入。
低分长尾词如果生硬塞进描述会让用户读不下去，宁可不融入。

【平台差异】
- **WB (Wildberries)**：偏短句 + 卖点列表风格，正文紧凑，可以用 emoji（💎 ✨ 🎉 等节制使用）。建议 800-1200 字符。
- **Ozon**：可用更长结构化文本，分小节（"Описание", "Применение", "В комплекте"）适用，但本期统一段落即可。建议 1200-2000 字符。

【若已有原描述】
做"渐进改写"：保留原描述里已有的卖点和真实信息（材质 / 配送 / 套装件数等），只在保留基础上融入新关键词。**不要全部重写让原有人工沉淀的卖点丢失**。

【输出严格 JSON 格式】
{
  "new_description": "俄语描述全文，含段落分隔 \\n\\n",
  "reasoning": "中文一句话：选了哪些卖点 / 融入了哪些核心关键词 / 为什么这个结构",
  "included_keywords": ["实际自然融入的关键词（俄语原词，10-30 个）"],
  "structure": ["卖点1标题", "卖点2标题", ...]
}

不要输出 markdown 代码块标记（```json），不要输出 JSON 之外的其他内容。"""


PLATFORM_HINT = {
    "wb":   "【当前平台】Wildberries —— 偏短句 + 卖点列表风格，描述紧凑，可节制使用 emoji，建议 800-1200 字符。",
    "ozon": "【当前平台】Ozon —— 可用更长结构化文本，建议 1200-2000 字符；标点完整可让用户读得舒服。",
    "yandex": "【当前平台】Yandex Market —— 参考通用规则，建议 1000-1500 字符。",
}


# Ozon 属性黑名单 (默认 _collect 时就过滤掉, 不在 preview / prompt 里出现)
# 这些字段对 AI 写描述没用, 还会撑爆 prompt
OZON_ATTR_BLACKLIST = {
    4191,   # 描述 (HTML, 跟 description_ru 重复)
    11254,  # rich_content_json (富文本楼层 JSON, 主要是图片 URL)
    21837,  # Ozon.Видео: 名称
    22968,  # Ozon.Видео: ссылка
    9024,   # Код продавца (内部 SKU 编号, 如 OZON-E0170)
    4180,   # Название товара (商品名, 跟 title 重复)
    10097,  # 颜色名称 (卖家常填成商品名, 不是真颜色)
}

# 上下文字段顺序 (preview 和 prompt 都按这个顺序展示)
CONTEXT_FIELD_KEYS = [
    "brand_philosophy",
    "name_ru",
    "brand",
    "category",
    "title_ru",
    "description_ru",
]

CONTEXT_FIELD_LABELS = {
    "brand_philosophy": "店铺品牌理念",
    "name_ru": "俄语名",
    "brand": "品牌",
    "category": "类目",
    "title_ru": "当前俄语标题",
    "description_ru": "当前俄语描述",
}


def _build_user_prompt(
    *,
    platform: Optional[str],
    context_fields: list[dict],
    attrs: list[dict],
    category_top_keywords: list[dict],
    product_top_keywords: list[dict],
) -> str:
    """拼 user prompt。所有 4 段已是过滤后的最终数据 (excluded 在外面应用过)。

    context_fields: [{key, label, value}, ...] (value 已 strip, 空值已剔除)
    attrs: [{id, name_ru, name_zh, value_ru}, ...]
    category_top_keywords: [{keyword, total_orders, total_impressions, max_score, product_count}]
    product_top_keywords: [{keyword, score, organic_impressions, organic_orders, paid_orders}]
    """
    lines = []
    hint = PLATFORM_HINT.get((platform or "").lower())
    if hint:
        lines.append(hint)
        lines.append("")

    # 上下文字段 (品牌理念排最前以便贯穿描述风格)
    bp = next((f for f in context_fields if f["key"] == "brand_philosophy"), None)
    if bp:
        lines.append("【店铺品牌理念（请贯穿到描述风格里,但不要直接照抄整段)】")
        lines.append(bp["value"])
        lines.append("")

    info_lines = []
    for key in ["name_zh", "name_ru", "brand", "category", "title_ru"]:
        f = next((f for f in context_fields if f["key"] == key), None)
        if f:
            info_lines.append(f"{f['label']}：{f['value']}")
    if info_lines:
        lines.append("【当前商品信息】")
        lines.extend(info_lines)

    # 当前描述 (描述特有的"渐进改写"信号)
    desc = next((f for f in context_fields if f["key"] == "description_ru"), None)
    if desc:
        cur_desc = desc["value"]
        if len(cur_desc) > 800:
            cur_desc = cur_desc[:800] + "...(截断)"
        lines.append("")
        lines.append("【当前俄语描述（已有，请保留卖点 + 渐进融入新词，不要全部重写）】")
        lines.append(cur_desc)
    else:
        lines.append("")
        lines.append("【当前俄语描述】（空，从零写）")

    # 商品属性 — 渲染成"俄语名 (中文): 值"列表, 比裸 JSON 省 token
    if attrs:
        attr_lines = []
        for a in attrs:
            name_ru = (a.get("name_ru") or "").strip()
            name_zh = (a.get("name_zh") or "").strip()
            value_ru = (a.get("value_ru") or "").strip()
            if not value_ru:
                continue
            if name_ru and name_zh and name_ru != name_zh:
                attr_lines.append(f"- {name_ru} ({name_zh}): {value_ru}")
            elif name_ru:
                attr_lines.append(f"- {name_ru}: {value_ru}")
            else:
                attr_lines.append(f"- 属性 #{a.get('id', '?')}: {value_ru}")
        if attr_lines:
            lines.append("")
            lines.append(f"【商品属性（用于自然融入描述，不要罗列；务必基于这些真实属性写卖点，不要编造）】")
            lines.extend(attr_lines)

    # 该类目热门关键词 (跨商品聚合, Top 30)
    if category_top_keywords:
        lines.append("")
        lines.append(f"【同类目热门关键词（共 {len(category_top_keywords)} 个，按订单+曝光降序，跨商品聚合 — 优先融入这些）】")
        for i, k in enumerate(category_top_keywords, 1):
            metric_parts = []
            if k.get("total_orders"):
                metric_parts.append(f"总订单 {int(k['total_orders'])}")
            if k.get("total_impressions"):
                metric_parts.append(f"总曝光 {int(k['total_impressions'])}")
            if k.get("product_count"):
                metric_parts.append(f"覆盖 {int(k['product_count'])} 个商品")
            metric = f"（{' / '.join(metric_parts)}）" if metric_parts else ""
            lines.append(f"{i}. {k['keyword']} {metric}")

    # 本商品热门关键词 (单 product, Top 10)
    if product_top_keywords:
        lines.append("")
        lines.append(f"【本商品热门关键词（共 {len(product_top_keywords)} 个，按本商品订单+曝光降序）】")
        for i, k in enumerate(product_top_keywords, 1):
            metric_parts = []
            if k.get("paid_orders"):
                metric_parts.append(f"付费订单 {int(k['paid_orders'])}")
            if k.get("organic_orders"):
                metric_parts.append(f"自然订单 {int(k['organic_orders'])}")
            if k.get("organic_impressions"):
                metric_parts.append(f"自然曝光 {int(k['organic_impressions'])}")
            metric = f"（{' / '.join(metric_parts)}）" if metric_parts else ""
            score_part = f"score={float(k['score']):.1f}" if k.get("score") is not None else ""
            lines.append(f"{i}. {k['keyword']} {score_part} {metric}")

    lines.append("")
    lines.append("请按上述约束生成新俄语商品描述，返回 JSON。")
    return "\n".join(lines)


# ==================== 数据收集 (preview + generate 共用) ====================

def _collect_inputs(
    db: Session, tenant_id: int, shop, product_id: int,
    *,
    brand_philosophy_override: Any = None,
) -> dict:
    """收集所有要喂给 AI 的字段 (全集, 未应用 excluded)。

    preview API 直接返回这个; generate 主入口在此基础上应用 excluded 过滤。
    brand_philosophy_override: None=用 shops 表现值; 其它(包括 "")=用此值

    Returns: {
        "ok": bool, "code"/"msg" (失败时),
        "platform_listing_id": ..., "platform": "ozon"/"wb",
        "context_fields": [{key, label, value}],
        "attrs": [{id, name_ru, name_zh, value_ru}],
        "category_top_keywords": [...30],
        "product_top_keywords": [...10],
    }
    """
    shop_id = shop.id

    prod_row = db.execute(text("""
        SELECT
            p.id AS pid,
            p.name_zh, p.name_ru, p.brand, p.local_category_id,
            lc.name AS local_category_name,
            pl.id AS listing_id, pl.title_ru, pl.description_ru,
            pl.variant_attrs, pl.platform_category_name,
            pl.platform_category_id, pl.platform_category_extra_id
        FROM products p
        LEFT JOIN platform_listings pl
            ON pl.product_id = p.id AND pl.tenant_id = p.tenant_id
            AND pl.shop_id = p.shop_id AND pl.status NOT IN ('deleted', 'archived')
        LEFT JOIN local_categories lc
            ON lc.id = p.local_category_id AND lc.tenant_id = p.tenant_id
        WHERE p.id = :pid AND p.tenant_id = :tid AND p.shop_id = :sid
        ORDER BY pl.id ASC LIMIT 1
    """), {"pid": product_id, "tid": tenant_id, "sid": shop_id}).first()

    if not prod_row or not prod_row.listing_id:
        return {"ok": False, "code": ErrorCode.SEO_PRODUCT_NOT_FOUND,
                "msg": "该商品在当前店铺找不到 listing"}

    # 1. 上下文字段 — 全集
    if brand_philosophy_override is None:
        philosophy = getattr(shop, "brand_philosophy", None)
    else:
        philosophy = (brand_philosophy_override or "").strip() or None

    # 类目: 中文 + 俄文 全路径, 让 AI 同时知道本地行业语言 + 平台类目
    cat_parts = []
    if prod_row.local_category_name:
        cat_parts.append(prod_row.local_category_name)
    if prod_row.platform_category_name:
        cat_parts.append(prod_row.platform_category_name)
    category_value = " — ".join(cat_parts) if cat_parts else None

    context_fields = []
    raw_ctx = {
        "brand_philosophy": philosophy,
        "name_ru": prod_row.name_ru,
        "brand": prod_row.brand,
        "category": category_value,
        "title_ru": prod_row.title_ru,
        "description_ru": prod_row.description_ru,
    }
    for key in CONTEXT_FIELD_KEYS:
        v = raw_ctx.get(key)
        if v is None or (isinstance(v, str) and not v.strip()):
            continue
        context_fields.append({
            "key": key,
            "label": CONTEXT_FIELD_LABELS[key],
            "value": v.strip() if isinstance(v, str) else str(v),
        })

    # 2. 属性 — 全集 (已过黑名单 + 长字段 + title 重复)
    title_norm = (prod_row.title_ru or "").strip().lower()
    attrs_raw = prod_row.variant_attrs or []
    if isinstance(attrs_raw, str):
        try:
            attrs_raw = json.loads(attrs_raw)
        except (json.JSONDecodeError, TypeError):
            attrs_raw = []
    attrs = []
    for a in (attrs_raw or []):
        if not isinstance(a, dict):
            continue
        attr_id = a.get("id")
        if attr_id in OZON_ATTR_BLACKLIST:
            continue
        value_ru = (a.get("value_ru") or "").strip()
        if not value_ru or len(value_ru) > 500:
            continue
        if title_norm and value_ru.lower() == title_norm:
            continue
        attrs.append({
            "id": attr_id,
            "name_ru": (a.get("name_ru") or "").strip(),
            "name_zh": (a.get("name_zh") or "").strip(),
            "value_ru": value_ru,
        })

    # 3. 类目热门关键词 — 跨商品聚合 Top 20
    # 优先按平台子类目 (Ozon type_id) 聚合, 同子类目商品才有真正可比关键词
    # 本地类目通常太宽 (例如全店 356 饰品都归 "时尚饰品" id=4, 但其中混了 270 耳环 + 23 项链 + 26 戒指)
    # 没有 type_id (WB 商品) 时回退到 platform_category_id, 再回退到 local_category_id
    category_top_keywords = _fetch_category_top_keywords(
        db, tenant_id,
        platform_category_extra_id=prod_row.platform_category_extra_id,
        platform_category_id=prod_row.platform_category_id,
        local_category_id=prod_row.local_category_id,
        limit=20,
    )

    # 4. 本商品热门关键词 — Top 10
    product_top_keywords = _fetch_product_top_keywords(
        db, tenant_id, shop_id, product_id, limit=10,
    )

    return {
        "ok": True,
        "platform_listing_id": prod_row.listing_id,
        "platform": getattr(shop, "platform", None),
        "context_fields": context_fields,
        "attrs": attrs,
        "category_top_keywords": category_top_keywords,
        "product_top_keywords": product_top_keywords,
        # 给 generate_description 持久化用的原始字段 (不受 excluded 影响)
        "_raw_description_ru": prod_row.description_ru or "",
    }


def _fetch_category_top_keywords(
    db: Session, tenant_id: int,
    *,
    platform_category_extra_id: Optional[str] = None,
    platform_category_id: Optional[str] = None,
    local_category_id: Optional[int] = None,
    limit: int = 20,
) -> list[dict]:
    """同子类目所有商品聚合关键词, 按订单+曝光降序 Top N。

    优先级:
    1. platform_category_extra_id (Ozon type_id, 三级最细) — 真正同款类目商品
    2. platform_category_id (二级 description_category_id) — 略宽
    3. local_category_id — 兜底, 通常太宽 (本地类目可能整个饰品都一类)

    口径: 跨店铺跨商品 (本租户内)。
    过滤: 总订单>0 OR 总曝光>=10 — 把噪声过掉。
    """
    # 选最精确的可用维度
    if platform_category_extra_id:
        join_cond = "pl.platform_category_extra_id = :cat"
        cat_val: Any = str(platform_category_extra_id)
    elif platform_category_id:
        join_cond = "pl.platform_category_id = :cat"
        cat_val = str(platform_category_id)
    elif local_category_id:
        # 本地类目兜底 — 走 products 表
        rows = db.execute(text("""
            SELECT
                c.keyword,
                SUM(COALESCE(c.organic_orders, 0) + COALESCE(c.paid_orders, 0)) AS total_orders,
                SUM(COALESCE(c.organic_impressions, 0)) AS total_impressions,
                MAX(c.score) AS max_score,
                COUNT(DISTINCT c.product_id) AS product_count
            FROM seo_keyword_candidates c
            INNER JOIN products p ON p.id = c.product_id AND p.tenant_id = c.tenant_id
            WHERE c.tenant_id = :tid AND p.local_category_id = :cat AND c.status = 'pending'
            GROUP BY c.keyword
            HAVING total_orders > 0 OR total_impressions >= 10
            ORDER BY total_orders DESC, total_impressions DESC, max_score DESC
            LIMIT :lim
        """), {"tid": tenant_id, "cat": local_category_id, "lim": limit}).fetchall()
        return _format_kw_rows(rows)
    else:
        return []

    # 走 platform_listings 表 (按 type_id 或 desc_cat_id 聚合)
    rows = db.execute(text(f"""
        SELECT
            c.keyword,
            SUM(COALESCE(c.organic_orders, 0) + COALESCE(c.paid_orders, 0)) AS total_orders,
            SUM(COALESCE(c.organic_impressions, 0)) AS total_impressions,
            MAX(c.score) AS max_score,
            COUNT(DISTINCT c.product_id) AS product_count
        FROM seo_keyword_candidates c
        INNER JOIN platform_listings pl
            ON pl.product_id = c.product_id
            AND pl.tenant_id = c.tenant_id
            AND pl.shop_id = c.shop_id
            AND pl.status NOT IN ('deleted', 'archived')
        WHERE c.tenant_id = :tid AND {join_cond} AND c.status = 'pending'
        GROUP BY c.keyword
        HAVING total_orders > 0 OR total_impressions >= 10
        ORDER BY total_orders DESC, total_impressions DESC, max_score DESC
        LIMIT :lim
    """), {"tid": tenant_id, "cat": cat_val, "lim": limit}).fetchall()
    return _format_kw_rows(rows)


def _format_kw_rows(rows) -> list[dict]:
    return [
        {
            "keyword": r.keyword,
            "total_orders": int(r.total_orders or 0),
            "total_impressions": int(r.total_impressions or 0),
            "max_score": float(r.max_score or 0),
            "product_count": int(r.product_count or 0),
        }
        for r in rows
    ]


def _fetch_product_top_keywords(
    db: Session, tenant_id: int, shop_id: int, product_id: int, limit: int = 10,
) -> list[dict]:
    """本商品热门关键词 — 仅看本 product_id, 按订单优先+曝光次之降序 Top N。"""
    rows = db.execute(text("""
        SELECT keyword, score, organic_impressions, organic_orders, paid_orders
        FROM seo_keyword_candidates
        WHERE tenant_id = :tid AND shop_id = :sid AND product_id = :pid AND status = 'pending'
        ORDER BY (
            COALESCE(organic_orders, 0) * 5 +
            COALESCE(paid_orders, 0) * 5 +
            COALESCE(organic_impressions, 0) * 1
        ) DESC, score DESC
        LIMIT :lim
    """), {"tid": tenant_id, "sid": shop_id, "pid": product_id, "lim": limit}).fetchall()
    return [
        {
            "keyword": r.keyword,
            "score": float(r.score or 0),
            "organic_impressions": int(r.organic_impressions or 0),
            "organic_orders": int(r.organic_orders or 0),
            "paid_orders": int(r.paid_orders or 0),
        }
        for r in rows
    ]


async def preview_description_inputs(
    db: Session, tenant_id: int, shop, product_id: int,
) -> dict:
    """前端 AiDescriptionModal 打开时调, 返回 4 个分组的全集数据让用户勾选。

    关键词附带 keyword_zh (走 ru_zh_dict 缓存优先, 缺失再调 Kimi)。
    """
    inputs = _collect_inputs(db, tenant_id, shop, product_id)
    if not inputs.get("ok"):
        return {"code": inputs.get("code"), "msg": inputs.get("msg")}

    # 给类目+本商品热门词批量翻译 (L1 process / L2 ru_zh_dict / L3 Kimi)
    cat_kws = inputs["category_top_keywords"]
    prod_kws = inputs["product_top_keywords"]
    all_keywords = list({k["keyword"] for k in cat_kws + prod_kws if k.get("keyword")})
    translations: dict = {}
    if all_keywords:
        try:
            from app.services.translation.ru_zh import translate_batch
            translations = await translate_batch(db, all_keywords, field_type="keyword")
        except Exception as e:
            logger.warning(f"SEO preview 翻译批量失败 product={product_id}: {e}")

    for k in cat_kws:
        k["keyword_zh"] = translations.get(k["keyword"], "")
    for k in prod_kws:
        k["keyword_zh"] = translations.get(k["keyword"], "")

    return {
        "code": 0,
        "data": {
            "platform": inputs["platform"],
            "context_fields": inputs["context_fields"],
            "attrs": inputs["attrs"],
            "category_top_keywords": cat_kws,
            "product_top_keywords": prod_kws,
        },
    }


# ==================== AI 返回解析 ====================

def _parse_ai_output(raw: str) -> dict:
    """解析 GLM 返回。优先严格 JSON；失败时启发式提取整段当 description。"""
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)

    try:
        obj = json.loads(raw)
        if isinstance(obj, dict) and obj.get("new_description"):
            return {
                "new_description": str(obj["new_description"]).strip(),
                "reasoning": str(obj.get("reasoning", "")).strip(),
                "included_keywords": [str(x) for x in (obj.get("included_keywords") or [])],
                "structure": [str(x) for x in (obj.get("structure") or [])],
            }
    except (json.JSONDecodeError, TypeError, ValueError):
        pass

    # Fallback：整段文本当描述（去掉首行可能的 "新描述：" 类前缀）
    cleaned = re.sub(r"^[【\[]?新描述[】\]]?[:：]\s*", "", raw)
    return {
        "new_description": cleaned,
        "reasoning": "（AI 未返回标准 JSON，已启发式提取全文作为描述）",
        "included_keywords": [],
        "structure": [],
    }


# ==================== 主入口 ====================

async def generate_description(
    db: Session,
    tenant_id: int,
    shop,
    product_id: int,
    user_id: Optional[int] = None,
    brand_philosophy: Optional[str] = None,
    excluded_context_keys: Optional[list[str]] = None,
    excluded_attr_ids: Optional[list[int]] = None,
    excluded_keywords: Optional[list[str]] = None,
) -> dict:
    """为某商品生成 AI 商品描述。前端勾选哪些喂 AI, excluded_* 传被勾掉的项。

    Returns:
        成功：{"code": 0, "data": {new_description, reasoning, included_keywords,
                                    structure, ai_model, decision_id, ...}}
        失败：{"code": ErrorCode.xxx, "msg": "..."}
    """
    shop_id = shop.id

    # 1. 处理品牌理念 (传入则保存到 shops 表)
    if brand_philosophy is not None:
        new_val = (brand_philosophy or "").strip() or None
        db.execute(
            text("UPDATE shops SET brand_philosophy = :bp WHERE id = :sid AND tenant_id = :tid"),
            {"bp": new_val, "sid": shop_id, "tid": tenant_id},
        )
        db.commit()
        # 同步到内存对象, 让 _collect 能拿到最新值
        try:
            shop.brand_philosophy = new_val
        except Exception:
            pass
        final_philosophy = new_val
    else:
        final_philosophy = getattr(shop, "brand_philosophy", None)

    # 2. 收集全集 (内部已应用黑名单 + 长字段过滤 + title 重复去重)
    inputs = _collect_inputs(db, tenant_id, shop, product_id)
    if not inputs.get("ok"):
        return {"code": inputs.get("code"), "msg": inputs.get("msg")}

    # 3. 应用前端 excluded 过滤
    excl_keys = set(excluded_context_keys or [])
    excl_attr = set(int(x) for x in (excluded_attr_ids or []))
    excl_kw = set((excluded_keywords or []))

    context_fields = [f for f in inputs["context_fields"] if f["key"] not in excl_keys]
    attrs = [a for a in inputs["attrs"] if a.get("id") not in excl_attr]
    cat_kws = [k for k in inputs["category_top_keywords"] if k["keyword"] not in excl_kw]
    prod_kws = [k for k in inputs["product_top_keywords"] if k["keyword"] not in excl_kw]

    # product_top_keywords 是本商品已有订单/曝光的高价值词, 视为"必须保留"清单
    preserve_keywords = [k["keyword"] for k in prod_kws if (
        (k.get("paid_orders") or 0) > 0
        or (k.get("organic_orders") or 0) > 0
        or (k.get("organic_impressions") or 0) >= 20
    )]

    # 4. 拼 prompt
    user_prompt = _build_user_prompt(
        platform=inputs["platform"],
        context_fields=context_fields,
        attrs=attrs,
        category_top_keywords=cat_kws,
        product_top_keywords=prod_kws,
    )

    logger.info(
        f"SEO description generate: tenant={tenant_id} shop={shop_id} product={product_id} "
        f"ctx={len(context_fields)}/{len(inputs['context_fields'])} "
        f"attrs={len(attrs)}/{len(inputs['attrs'])} "
        f"cat_kw={len(cat_kws)}/{len(inputs['category_top_keywords'])} "
        f"prod_kw={len(prod_kws)}/{len(inputs['product_top_keywords'])} "
        f"prompt_chars={len(user_prompt)}"
    )

    try:
        ai_result = await ai_router.execute(
            task_type="seo_generation",
            input_data={"prompt": user_prompt},
            tenant_id=tenant_id,
            db=db,
            user_id=user_id,
            triggered_by="manual",
            system_prompt=SYSTEM_PROMPT,
            temperature=0.6,   # 描述比标题需要稍微更有变化（场景、卖点表达）
            max_tokens=2500,   # 描述长，留充足空间避免截断
        )
    except Exception as e:
        logger.error(f"SEO description AI 调用失败: {e}")
        return {"code": ErrorCode.SEO_TITLE_GENERATE_FAILED,
                "msg": f"AI 调用失败：{type(e).__name__}: {str(e)[:120]}"}

    parsed = _parse_ai_output(ai_result["content"])
    if not parsed["new_description"]:
        return {"code": ErrorCode.SEO_TITLE_GENERATE_FAILED,
                "msg": "AI 返回为空或解析失败"}

    # 5. 持久化到 seo_generated_contents
    gen = SeoGeneratedContent(
        tenant_id=tenant_id,
        listing_id=inputs["platform_listing_id"],
        content_type="description",
        original_text=inputs["_raw_description_ru"],
        generated_text=parsed["new_description"],
        keywords_used={
            "category_top_keywords": [k["keyword"] for k in cat_kws],
            "product_top_keywords": [k["keyword"] for k in prod_kws],
            "ai_included_keywords": parsed["included_keywords"],
            "reasoning": parsed["reasoning"],
            "structure": parsed["structure"],
            "preserve_keywords": preserve_keywords,
            "excluded": {
                "context_keys": list(excl_keys),
                "attr_ids": list(excl_attr),
                "keywords": list(excl_kw),
            },
        },
        ai_model=ai_result["model"],
        ai_decision_id=ai_result["decision_id"],
        approval_status="pending",
    )
    db.add(gen)
    db.commit()
    db.refresh(gen)

    # 检查 AI 是否守约保留高价值词
    new_desc_lower = (parsed["new_description"] or "").lower()
    dropped_preserve = [kw for kw in preserve_keywords if kw.lower() not in new_desc_lower]
    if dropped_preserve:
        logger.warning(
            f"SEO description: AI dropped preserve keywords product={product_id}: "
            f"{dropped_preserve}"
        )

    return {
        "code": ErrorCode.SUCCESS,
        "data": {
            "new_description": parsed["new_description"],
            "reasoning": parsed["reasoning"],
            "included_keywords": parsed["included_keywords"],
            "structure": parsed["structure"],
            "preserved_keywords": preserve_keywords,
            "dropped_preserve": dropped_preserve,
            "ai_model": ai_result["model"],
            "decision_id": ai_result["decision_id"],
            "generated_content_id": gen.id,
            "tokens": ai_result["tokens"],
            "duration_ms": ai_result["duration_ms"],
            "original_description": inputs["_raw_description_ru"],
            "char_count": len(parsed["new_description"]),
            "listing_id": inputs["platform_listing_id"],
            "brand_philosophy": final_philosophy or "",  # 返给前端,确保 modal 同步
        },
    }
