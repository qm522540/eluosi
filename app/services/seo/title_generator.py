"""SEO 标题生成器 — 基于候选词池 + 商品当前标题/属性，调 GLM 生成融合新标题。

调用链路：
- API 层(`/seo/shop/{shop_id}/generate-title`) → 本 service.generate_title()
- 本 service → `app.services.ai.router.execute(task_type='seo_generation', ...)` → GLM 客户端

核心决策：
- 走 GLM（俄语文案 + SEO，见 router.TASK_MODEL_MAP），不走 Kimi（长文档）。
- 返回严格 JSON（new_title / reasoning / included_keywords），失败 fallback 到纯文本。
- 持久化到 seo_generated_contents 表（老林早就搭好的 SEO 基础表）供后续审批/回溯。
- 不直接改 platform_listings.title_ru — 三期再做"一键写回"，本期仅展示供人工复制。

规则合规：
- 规则 1 tenant_id：product / listing / candidates 三次查询都 WHERE tenant_id
- 规则 4 shop_id：所有查询按 shop_id 过滤（调用方 API 层已 get_owned_shop 守卫）
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.models.seo import SeoGeneratedContent
from app.services.ai import router as ai_router
from app.utils.errors import ErrorCode
from app.utils.logger import logger


# ==================== Prompt 模板 ====================

SYSTEM_PROMPT = """你是俄罗斯跨境电商（WB / Ozon / Yandex）SEO 标题专家。
你的工作是帮商家把用户选中的"反哺关键词"自然地融合到商品俄语标题里，帮商品吃到更多自然搜索流量。

通用约束：
1. 输出俄语标题，总长度不超过 180 字符（保留余量，Ozon/WB 上限 200）
2. 保留原标题的核心商品信息（商品类型、品牌、关键属性如颜色/材质）
3. 融合关键词要"语法通顺"，不是简单罗列（但电商标题允许空格分隔的短语堆叠）
4. 全部小写，不用标点符号（电商平台 SEO 惯例），短语之间用单个空格分隔
5. 不编造原标题没有的属性（比如原品没说"防水"，不要加"водостойкий"）
6. **绝对不能丢失**"必须保留的高价值词"列表里的词（这些词已在原标题出现且带来过真实订单/曝光，丢了会直接降流量）
7. **绝对不能输出中文 / 拼音 / 日文 / 韩文 等非俄/英字符**。即使输入的属性 value 里带中文（可能是卖家在平台后台填错了型号名 / 颜色等），也要**忽略**那段中文，不要原样塞进标题。例如属性"型号: 环形"或"颜色: 米色"——禁止把"环形""米色"这类汉字写进 new_title。

【位置规则 —— 决定搜索权重】
平台搜索权重从标题开头向后递减，按"权重梯度"排词：

① **首位（前 1-3 词）**：商品品类类型词（如 `серьги` 耳环 / `шары` 气球 / `кольцо` 戒指 / `платье` 连衣裙）必须在最前面。让平台 0.1 秒内分好类目，**这是重中之重，不能被别的词挤掉**。
② **前段（第 2-5 词）**：实证表现最强的搜索词（订单/曝光最高的候选词），紧跟类型词。
③ **中段**：次要搜索词 + 属性修饰词（颜色 / 材质 / 尺寸 / 用途场景）。
④ **末段**：品牌名 / 型号 / SKU（末尾放品牌依然能被精确搜索，但不占搜索主位）。

【平台差异 —— 用户 prompt 里会告诉你具体是哪个平台】
- **WB (Wildberries)**：前 30-40 字符是搜索主战场，风格紧凑；品牌可弱化（WB 卖家多白牌）；标题长度建议 80-120 字符即可。
- **Ozon**：前 60-80 字符是搜索主战场，可以放更多搜索词；品牌是独立属性但放末尾依然有辅助加权；标题长度建议 120-180 字符。

输出严格 JSON 格式：
{
  "new_title": "融合后的俄语新标题",
  "reasoning": "为什么这样组合（中文一句话，便于用户理解决策，说明首位放了什么、品牌放在哪）",
  "included_keywords": ["实际用到的候选词（用原词）"]
}

不要输出 markdown 代码块标记，不要输出 JSON 之外的其他内容。"""


PLATFORM_HINT = {
    "wb": "【当前平台】Wildberries（WB）—— 前 30-40 字符是搜索主战场，风格紧凑；品牌弱化或放末尾；标题 80-120 字符即可。",
    "ozon": "【当前平台】Ozon —— 前 60-80 字符是搜索主战场，可多放相关词；品牌建议放末尾（是独立属性）；标题 120-180 字符。",
    "yandex": "【当前平台】Yandex Market —— 参考通用规则，标题偏紧凑，品牌放末尾。",
}


# 检测字符串是否含中文字符 (CJK 统一汉字 + 兼容汉字)
_CJK_RE = re.compile(r"[一-鿿㐀-䶿]")

def _has_cjk(s: str) -> bool:
    return bool(_CJK_RE.search(s or ""))


def _strip_cjk(s: str) -> str:
    """把中文字符全去掉 + 清理多余空格。"""
    if not s:
        return s
    cleaned = _CJK_RE.sub("", s)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    return cleaned


# 首饰常见子类目主词词根 (匹配用 startswith 兼容俄语变格)
# 用于检测"跨品类"热门词:本类目=耳环,热门词出现 кольцо/колье 等其他类目主词
CATEGORY_PRIMARY_ROOTS = {
    "серьги":   ["серьг", "сереж", "серг", "клипс", "моносерьг", "конго"],
    "кольцо":   ["кольц", "ring"],
    "колье":    ["колье", "кулон", "подвеск", "ожерель", "цепочк", "чокер"],
    "брошь":    ["брошь", "брош", "брошк"],
    "браслет":  ["браслет"],
    "заколка":  ["заколк", "ободок", "резинк"],
    "шарик":    ["шар", "шарик", "воздушн"],
}


def _detect_category_key(category_name: Optional[str]) -> Optional[str]:
    """从 platform_category_name (如 "Галантерея / Бижутерные / Серьги") 末段
    推出本类目 key (如 "серьги"), 用于跨品类判断。
    """
    if not category_name:
        return None
    leaf = category_name.split("/")[-1].strip().lower()
    for key in CATEGORY_PRIMARY_ROOTS.keys():
        if key in leaf:
            return key
    return None


def _is_cross_category(keyword: str, current_cat_key: Optional[str]) -> bool:
    """判断关键词是否含其他类目主词 → 默认不打勾让用户决定。

    规则: 只要词里含任何"非本类目"的主词, 就标记跨品类。
    例如本类目=耳环时, "серьги кольца медицинский сплав" 含 кольц(戒指) → 跨
    "серьги жемчуг" 不含其他类目主词 → 不跨
    本类目无法识别 → 不判断 (返 False)
    """
    if not current_cat_key or not keyword:
        return False
    kw_low = keyword.lower()
    for other_key, other_roots in CATEGORY_PRIMARY_ROOTS.items():
        if other_key == current_cat_key:
            continue
        if any(r in kw_low for r in other_roots):
            return True
    return False


def _build_user_prompt(
    *,
    platform: Optional[str],
    name_zh: str,
    name_ru: Optional[str],
    brand: Optional[str],
    category_name: Optional[str],
    current_title_ru: Optional[str],
    variant_attrs: Any,
    candidates: list[dict],
    preserve_keywords: Optional[list[str]] = None,
    category_top_keywords: Optional[list[dict]] = None,
    include_current_title: bool = True,
    manual_keywords: Optional[list[str]] = None,
) -> str:
    """拼用户侧 prompt。

    candidates: 用户在表格里勾选的反哺词
    category_top_keywords: 跨店本类目热门词
    include_current_title: False=不喂当前标题给 AI (从零拼新标题)
    manual_keywords: 用户手动输入的关键词 (例如看到竞品热门词在系统里没有)
    """
    lines = []
    hint = PLATFORM_HINT.get((platform or "").lower())
    if hint:
        lines.append(hint)
        lines.append("")
    lines.extend([
        "【当前商品信息】",
        f"中文名：{name_zh}",
    ])
    if name_ru:
        lines.append(f"俄语名：{name_ru}")
    if brand:
        lines.append(f"品牌：{brand}")
    if category_name:
        lines.append(f"类目：{category_name}")
    if include_current_title:
        lines.append(f"当前俄语标题：{current_title_ru or '（空）'}")
    # 属性: 按字段渲染并过滤含中文 value 的属性 (例如卖家在 Ozon 后台填了中文型号名 "环形",
    # 直接 dump 给 AI 会让 AI 把中文塞进俄语标题)
    if variant_attrs:
        attr_lines = []
        if isinstance(variant_attrs, list):
            for a in variant_attrs:
                if not isinstance(a, dict):
                    continue
                value_ru = (a.get("value_ru") or "").strip()
                name_ru = (a.get("name_ru") or "").strip()
                # 过滤: value 含中文/含拼音(英文连字+全小写也疑似)→ skip
                if not value_ru or _has_cjk(value_ru):
                    continue
                # 长字段不喂 (富文本等)
                if len(value_ru) > 200:
                    continue
                if name_ru:
                    attr_lines.append(f"- {name_ru}: {value_ru}")
                else:
                    attr_lines.append(f"- 属性 #{a.get('id', '?')}: {value_ru}")
            attrs_str = "\n".join(attr_lines)
        else:
            # 兜底: 旧 dict / str 格式直接 dump (强行不 wb 平台进来)
            attrs_str = json.dumps(variant_attrs, ensure_ascii=False) if isinstance(variant_attrs, dict) else str(variant_attrs)
        if len(attrs_str) > 800:
            attrs_str = attrs_str[:800] + "...(截断)"
        if attrs_str:
            lines.append("【商品属性(只展示俄语 value, 中文已过滤)】")
            lines.append(attrs_str)

    if preserve_keywords:
        lines.append("")
        lines.append(f"【必须保留的高价值词（共 {len(preserve_keywords)} 个，已在当前标题出现且带过真实订单/曝光，绝对不能丢）】")
        for kw in preserve_keywords:
            lines.append(f"- {kw}")

    if candidates:
        lines.append("")
        lines.append(f"【用户选中要融合的反哺关键词（共 {len(candidates)} 个，按重要性排序）】")
        for i, c in enumerate(candidates, 1):
            metric_parts = []
            if c.get("paid_orders"):
                metric_parts.append(f"付费订单 {c['paid_orders']}")
            if c.get("paid_roas"):
                metric_parts.append(f"ROAS {float(c['paid_roas']):.2f}")
            if c.get("organic_impressions"):
                metric_parts.append(f"自然曝光 {c['organic_impressions']}")
            if c.get("organic_orders"):
                metric_parts.append(f"自然订单 {c['organic_orders']}")
            metric = f"（{' / '.join(metric_parts)}）" if metric_parts else ""
            lines.append(f"{i}. {c['keyword']} {metric}")

    if category_top_keywords:
        lines.append("")
        lines.append(f"【跨店铺本类目热门关键词（共 {len(category_top_keywords)} 个，跨商品聚合按订单+曝光降序，可参考融入但优先级低于上面用户选中词）】")
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

    if manual_keywords:
        # 去重已经在前端做了, 这里也做一道 (空、纯空格)
        manual_clean = [k.strip() for k in manual_keywords if k and k.strip()]
        if manual_clean:
            lines.append("")
            lines.append(f"【用户手动输入关键词（共 {len(manual_clean)} 个，最高优先级 — 这是用户根据竞品/经验手填的词，请尽量融入）】")
            for i, k in enumerate(manual_clean, 1):
                lines.append(f"{i}. {k}")

    lines.append("")
    lines.append("请按上述约束生成新俄语标题，返回 JSON。")
    return "\n".join(lines)


# ==================== Preview API (前端弹窗打开时拉) ====================

async def preview_title_inputs(
    db: Session, tenant_id: int, shop, product_id: int,
    candidate_ids: list[int],
) -> dict:
    """前端 AiTitleModal 打开时调,返回:
    - candidates: 用户传过来的 ids 对应的反哺词全集 (含 keyword_zh 翻译)
    - category_top_keywords: 跨店本类目热门 Top 5 (含 keyword_zh 翻译)
    """
    from app.services.seo.description_generator import _fetch_category_top_keywords
    from app.services.translation.ru_zh import translate_batch

    shop_id = shop.id

    # 1. 商品基础 (要 platform_category_extra_id 才能聚合同 type_id; 要 platform_category_name 推本类目 key)
    prod_row = db.execute(text("""
        SELECT pl.platform_category_extra_id, pl.platform_category_id,
               pl.platform_category_name,
               p.local_category_id
        FROM products p
        LEFT JOIN platform_listings pl
            ON pl.product_id = p.id AND pl.tenant_id = p.tenant_id
            AND pl.shop_id = p.shop_id AND pl.status NOT IN ('deleted', 'archived')
        WHERE p.id = :pid AND p.tenant_id = :tid AND p.shop_id = :sid
        ORDER BY pl.id ASC LIMIT 1
    """), {"pid": product_id, "tid": tenant_id, "sid": shop_id}).first()

    if not prod_row:
        return {"code": ErrorCode.SEO_PRODUCT_NOT_FOUND, "msg": "商品不在当前店铺"}

    # 2. 反哺词全量(用户勾选的)
    cand_rows = []
    if candidate_ids:
        cand_stmt = text("""
            SELECT id, keyword, score, paid_roas, paid_orders,
                   organic_impressions, organic_orders
            FROM seo_keyword_candidates
            WHERE tenant_id = :tid AND shop_id = :sid AND product_id = :pid
              AND id IN :ids
            ORDER BY score DESC
        """).bindparams(bindparam("ids", expanding=True))
        cand_rows = db.execute(cand_stmt, {
            "tid": tenant_id, "sid": shop_id, "pid": product_id,
            "ids": list(candidate_ids),
        }).fetchall()

    candidates = [
        {
            "id": r.id, "keyword": r.keyword,
            "score": float(r.score or 0),
            "paid_orders": int(r.paid_orders or 0) if r.paid_orders is not None else 0,
            "paid_roas": float(r.paid_roas) if r.paid_roas is not None else None,
            "organic_impressions": int(r.organic_impressions or 0),
            "organic_orders": int(r.organic_orders or 0),
        }
        for r in cand_rows
    ]

    # 3. 跨店本类目热门 Top 5
    category_top_keywords = _fetch_category_top_keywords(
        db, tenant_id,
        platform_category_extra_id=prod_row.platform_category_extra_id,
        platform_category_id=prod_row.platform_category_id,
        local_category_id=prod_row.local_category_id,
        limit=5,
    )

    # 跨品类标记: 例如本类目=耳环 (Серьги), 热门词里有 кольцо/колье/брошь 等 → 标 looks_cross_category
    cat_key = _detect_category_key(prod_row.platform_category_name)
    for k in category_top_keywords:
        k["looks_cross_category"] = _is_cross_category(k.get("keyword", ""), cat_key)

    # 4. 批量翻译
    all_keywords = list({k["keyword"] for k in candidates + category_top_keywords if k.get("keyword")})
    translations: dict = {}
    if all_keywords:
        try:
            translations = await translate_batch(db, all_keywords, field_type="keyword")
        except Exception as e:
            logger.warning(f"SEO title preview 翻译失败 product={product_id}: {e}")

    for k in candidates:
        k["keyword_zh"] = translations.get(k["keyword"], "")
    for k in category_top_keywords:
        k["keyword_zh"] = translations.get(k["keyword"], "")

    return {
        "code": 0,
        "data": {
            "candidates": candidates,
            "category_top_keywords": category_top_keywords,
        },
    }


# ==================== AI 返回解析 ====================

def _parse_ai_output(raw: str) -> dict:
    """解析 GLM 返回。优先严格 JSON；失败时启发式提取 new_title。"""
    raw = (raw or "").strip()
    # 去除 markdown 代码块包裹（AI 偶尔不听话）
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)

    try:
        obj = json.loads(raw)
        if isinstance(obj, dict) and obj.get("new_title"):
            return {
                "new_title": str(obj["new_title"]).strip(),
                "reasoning": str(obj.get("reasoning", "")).strip(),
                "included_keywords": [str(x) for x in (obj.get("included_keywords") or [])],
            }
    except (json.JSONDecodeError, TypeError, ValueError):
        pass

    # Fallback：首行当标题，其余都丢到 reasoning
    first_line = raw.split("\n", 1)[0].strip()
    return {
        "new_title": first_line,
        "reasoning": "（AI 未返回标准 JSON，已启发式提取首行作为标题）",
        "included_keywords": [],
    }


# ==================== 主入口 ====================

async def generate_title(
    db: Session,
    tenant_id: int,
    shop,  # Shop 对象（API 层 get_owned_shop 已守卫）
    product_id: int,
    candidate_ids: list[int],
    user_id: Optional[int] = None,
    extra_category_keywords: Optional[list[str]] = None,
    include_current_title: bool = True,
    manual_keywords: Optional[list[str]] = None,
) -> dict:
    """为某商品基于候选词生成 AI 融合新标题。

    Returns:
        成功：{"code": 0, "data": {new_title, reasoning, included_keywords,
                                    ai_model, decision_id, generated_content_id,
                                    tokens, duration_ms, original_title, listing_id}}
        失败：{"code": ErrorCode.xxx, "msg": "..."}
    """
    shop_id = shop.id

    # ---------- 1. 查商品 + listing（规则 1 + 规则 4 严格过滤）----------
    prod_row = db.execute(text("""
        SELECT
            p.id AS pid,
            p.name_zh, p.name_ru, p.brand, p.local_category_id,
            pl.id AS listing_id,
            pl.title_ru,
            pl.description_ru,
            pl.variant_attrs,
            pl.platform_category_name
        FROM products p
        LEFT JOIN platform_listings pl
            ON pl.product_id = p.id
            AND pl.tenant_id = p.tenant_id
            AND pl.shop_id = p.shop_id
            AND pl.status NOT IN ('deleted', 'archived')
        WHERE p.id = :pid
          AND p.tenant_id = :tid
          AND p.shop_id = :sid
        ORDER BY pl.id ASC
        LIMIT 1
    """), {"pid": product_id, "tid": tenant_id, "sid": shop_id}).first()

    if not prod_row or not prod_row.listing_id:
        return {"code": ErrorCode.SEO_PRODUCT_NOT_FOUND,
                "msg": "该商品在当前店铺找不到 listing，请先同步商品或确认店铺归属"}

    # ---------- 2. 查选中的候选词（tenant + shop + product 三重约束，防越权）----------
    # candidate_ids 可空 (用户可能只用跨店类目词 / 手动输入词)
    candidates: list[dict] = []
    if candidate_ids:
        cand_stmt = text("""
            SELECT id, keyword, score,
                   paid_roas, paid_orders, paid_spend, paid_revenue,
                   organic_impressions, organic_orders
            FROM seo_keyword_candidates
            WHERE tenant_id = :tid
              AND shop_id = :sid
              AND product_id = :pid
              AND id IN :ids
            ORDER BY score DESC
        """).bindparams(bindparam("ids", expanding=True))
        cand_rows = db.execute(cand_stmt, {
            "tid": tenant_id, "sid": shop_id, "pid": product_id,
            "ids": list(candidate_ids),
        }).fetchall()
        candidates = [
            {
                "id": r.id, "keyword": r.keyword,
                "score": float(r.score or 0),
                "paid_roas": float(r.paid_roas) if r.paid_roas is not None else None,
                "paid_orders": int(r.paid_orders) if r.paid_orders is not None else None,
                "organic_impressions": int(r.organic_impressions) if r.organic_impressions is not None else None,
                "organic_orders": int(r.organic_orders) if r.organic_orders is not None else None,
            }
            for r in cand_rows
        ]

    # 至少要有一个 keyword 来源 (反哺 / 类目 / 手动) 才能生成
    has_extra = bool(extra_category_keywords) or bool(manual_keywords and any(
        k and k.strip() for k in manual_keywords
    ))
    if not candidates and not has_extra:
        return {"code": ErrorCode.SEO_CANDIDATE_NOT_FOUND,
                "msg": "至少要选一个反哺词 / 跨店类目词 / 手动输入词才能生成"}

    # ---------- 2.5 查已在当前标题里的"高价值保留词"（防止 AI 换新词时丢失已验证的高转化词）----------
    preserve_rows = db.execute(text("""
        SELECT keyword
        FROM seo_keyword_candidates
        WHERE tenant_id = :tid
          AND shop_id = :sid
          AND product_id = :pid
          AND in_title = 1
          AND (COALESCE(paid_orders, 0) > 0
               OR COALESCE(organic_orders, 0) > 0
               OR COALESCE(organic_impressions, 0) >= 20)
        ORDER BY (COALESCE(paid_orders,0) + COALESCE(organic_orders,0)) DESC,
                 score DESC
        LIMIT 10
    """), {"tid": tenant_id, "sid": shop_id, "pid": product_id}).fetchall()
    preserve_keywords = [r.keyword for r in preserve_rows]

    # ---------- 2.6 跨店本类目热门词 (用户勾选过的, 按 keyword 字符串过滤) ----------
    category_top_keywords: list = []
    if extra_category_keywords:
        from app.services.seo.description_generator import _fetch_category_top_keywords
        # 拉商品的 platform_category_extra_id (type_id) 用于聚合
        cat_row = db.execute(text("""
            SELECT pl.platform_category_extra_id, pl.platform_category_id
            FROM platform_listings pl
            WHERE pl.tenant_id=:tid AND pl.shop_id=:sid AND pl.product_id=:pid
              AND pl.status NOT IN ('deleted', 'archived')
            ORDER BY pl.id ASC LIMIT 1
        """), {"tid": tenant_id, "sid": shop_id, "pid": product_id}).first()
        if cat_row:
            all_cat_kws = _fetch_category_top_keywords(
                db, tenant_id,
                platform_category_extra_id=cat_row.platform_category_extra_id,
                platform_category_id=cat_row.platform_category_id,
                local_category_id=prod_row.local_category_id,
                limit=20,  # 取多一点防 preview 时是 5 现在改 10 等差异
            )
            wanted = set(extra_category_keywords)
            category_top_keywords = [k for k in all_cat_kws if k["keyword"] in wanted]

    # ---------- 3. 拼 prompt & 调 AI（GLM）----------
    user_prompt = _build_user_prompt(
        platform=getattr(shop, "platform", None),
        name_zh=prod_row.name_zh or "",
        name_ru=prod_row.name_ru,
        brand=prod_row.brand,
        category_name=prod_row.platform_category_name,
        current_title_ru=prod_row.title_ru,
        variant_attrs=prod_row.variant_attrs,
        candidates=candidates,
        preserve_keywords=preserve_keywords,
        category_top_keywords=category_top_keywords,
        include_current_title=include_current_title,
        manual_keywords=manual_keywords,
    )

    logger.info(
        f"SEO title generate: tenant={tenant_id} shop={shop_id} product={product_id} "
        f"candidates={len(candidates)} preserve={len(preserve_keywords)} "
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
            temperature=0.5,   # 电商标题偏确定性，低温
            max_tokens=800,
        )
    except Exception as e:
        logger.error(f"SEO title AI 调用失败: {e}")
        return {"code": ErrorCode.SEO_TITLE_GENERATE_FAILED,
                "msg": f"AI 调用失败：{type(e).__name__}: {str(e)[:120]}"}

    parsed = _parse_ai_output(ai_result["content"])
    if not parsed["new_title"]:
        return {"code": ErrorCode.SEO_TITLE_GENERATE_FAILED,
                "msg": "AI 返回为空或解析失败"}

    # post-check: AI 输出含中文字符 → 自动剥离 (兜底防御, system_prompt 已禁但偶尔不听)
    if _has_cjk(parsed["new_title"]):
        original_with_cjk = parsed["new_title"]
        parsed["new_title"] = _strip_cjk(parsed["new_title"])
        logger.warning(
            f"SEO title 输出含中文已自动剥离 product={product_id} "
            f"原: {original_with_cjk!r} → 净: {parsed['new_title']!r}"
        )

    # ---------- 4. 持久化到 seo_generated_contents ----------
    gen = SeoGeneratedContent(
        tenant_id=tenant_id,
        listing_id=prod_row.listing_id,
        content_type="title",
        original_text=prod_row.title_ru or "",
        generated_text=parsed["new_title"],
        keywords_used={
            "candidate_ids": [c["id"] for c in candidates],
            "keywords": parsed["included_keywords"] or [c["keyword"] for c in candidates],
            "reasoning": parsed["reasoning"],
        },
        ai_model=ai_result["model"],
        ai_decision_id=ai_result["decision_id"],
        approval_status="pending",
    )
    db.add(gen)
    db.commit()
    db.refresh(gen)

    # 检查 AI 是否真的保留了所有高价值词（不强制拦截，仅 log + 回传让前端透明）
    new_title_lower = (parsed["new_title"] or "").lower()
    dropped_preserve = [kw for kw in preserve_keywords if kw.lower() not in new_title_lower]
    if dropped_preserve:
        logger.warning(
            f"SEO title generate: AI dropped preserve keywords product={product_id}: "
            f"{dropped_preserve}"
        )

    return {
        "code": ErrorCode.SUCCESS,
        "data": {
            "new_title": parsed["new_title"],
            "reasoning": parsed["reasoning"],
            "included_keywords": parsed["included_keywords"] or [c["keyword"] for c in candidates],
            "preserved_keywords": preserve_keywords,
            "dropped_preserve": dropped_preserve,
            "ai_model": ai_result["model"],
            "decision_id": ai_result["decision_id"],
            "generated_content_id": gen.id,
            "tokens": ai_result["tokens"],
            "duration_ms": ai_result["duration_ms"],
            "original_title": prod_row.title_ru or "",
            "listing_id": prod_row.listing_id,
        },
    }
