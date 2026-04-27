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


def _build_user_prompt(
    *,
    platform: Optional[str],
    name_zh: str,
    name_ru: Optional[str],
    brand: Optional[str],
    category_name: Optional[str],
    current_title_ru: Optional[str],
    current_description_ru: Optional[str],
    variant_attrs: Any,
    all_candidates: list[dict],
    preserve_keywords: Optional[list[str]] = None,
    brand_philosophy: Optional[str] = None,
) -> str:
    """拼用户侧 prompt。候选词按 score 降序传入，限 50 个。"""
    lines = []
    hint = PLATFORM_HINT.get((platform or "").lower())
    if hint:
        lines.append(hint)
        lines.append("")

    # 品牌理念优先放最前 — 让整段描述贯穿这个调性
    if brand_philosophy and brand_philosophy.strip():
        lines.append("【店铺品牌理念（请贯穿到描述风格里,但不要直接照抄整段)】")
        lines.append(brand_philosophy.strip())
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
    lines.append(f"当前俄语标题：{current_title_ru or '（空）'}")

    # 当前描述（如有）— 描述特有的"渐进改写"信号
    if current_description_ru:
        # 描述可能很长，截断 800 字符（比标题的 400 阈值更宽）
        cur_desc = current_description_ru
        if len(cur_desc) > 800:
            cur_desc = cur_desc[:800] + "...(截断)"
        lines.append("")
        lines.append("【当前俄语描述（已有，请保留卖点 + 渐进融入新词，不要全部重写）】")
        lines.append(cur_desc)
    else:
        lines.append("")
        lines.append("【当前俄语描述】（空，从零写）")

    # 商品属性 — 渲染成"俄语名 (中文): 值"列表, 比裸 JSON 省 token 也更易读
    # 同步代码现已存 [{id, name_ru, name_zh, value_ru}, ...] 结构 (Ozon /v4/info/attributes)
    # 过滤无用属性: 富文本/HTML 描述/视频/卖家编码 等占字符不带卖点信息的字段
    OZON_ATTR_BLACKLIST = {
        4191,   # 描述 (HTML, 跟 description_ru 重复)
        11254,  # rich_content_json (富文本楼层 JSON, 主要是图片 URL)
        21837,  # Ozon.Видео: 名称
        22968,  # Ozon.Видео: ссылка
        9024,   # Код продавца (内部 SKU 编号, 如 OZON-E0170)
        4180,   # Название товара (商品名, 跟 title 重复)
        10097,  # 颜色名称 (卖家常填成商品名, 不是真颜色)
    }
    if variant_attrs:
        attr_lines = []
        if isinstance(variant_attrs, list):
            title_norm = (current_title_ru or "").strip().lower()
            for a in variant_attrs:
                if not isinstance(a, dict):
                    continue
                attr_id = a.get("id")
                if attr_id in OZON_ATTR_BLACKLIST:
                    continue
                name_ru = (a.get("name_ru") or "").strip()
                name_zh = (a.get("name_zh") or "").strip()
                value_ru = (a.get("value_ru") or "").strip()
                if not value_ru:
                    continue
                # 兜底: 单个 value > 500 字符的多半是富文本/长 JSON, 跳过
                if len(value_ru) > 500:
                    continue
                # 去重: value 跟 title 一摸一样, 没有信息量
                if title_norm and value_ru.lower() == title_norm:
                    continue
                if name_ru and name_zh and name_ru != name_zh:
                    attr_lines.append(f"- {name_ru} ({name_zh}): {value_ru}")
                elif name_ru:
                    attr_lines.append(f"- {name_ru}: {value_ru}")
                else:
                    attr_lines.append(f"- 属性 #{attr_id or '?'}: {value_ru}")
            attrs_str = "\n".join(attr_lines)
        else:
            # 兜底: 老格式 dict / 字符串, 走原 JSON dump 路径
            attrs_str = json.dumps(variant_attrs, ensure_ascii=False) if isinstance(variant_attrs, dict) else str(variant_attrs)
        if len(attrs_str) > 2000:
            attrs_str = attrs_str[:2000] + "...(截断)"
        if attrs_str:
            lines.append("")
            lines.append(f"【商品属性（用于自然融入描述，不要罗列；务必基于这些真实属性写卖点，不要编造）】\n{attrs_str}")

    # 必须保留的高价值词
    if preserve_keywords:
        lines.append("")
        lines.append(f"【必须保留的高价值词（共 {len(preserve_keywords)} 个，已在原标题/原描述出现且带过真实订单/曝光，绝对不能丢）】")
        for kw in preserve_keywords:
            lines.append(f"- {kw}")

    # 全部候选词（按 score desc 限 50 个）
    lines.append("")
    lines.append(f"【可用反哺关键词（共 {len(all_candidates)} 个，按推荐系数降序，优先融入前 20-30 个高分词）】")
    for i, c in enumerate(all_candidates, 1):
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
        score_part = f"score={c['score']:.1f}" if c.get("score") else ""
        lines.append(f"{i}. {c['keyword']} {score_part} {metric}")

    lines.append("")
    lines.append("请按上述约束生成新俄语商品描述，返回 JSON。")
    return "\n".join(lines)


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
    max_candidates: int = 50,
    brand_philosophy: Optional[str] = None,
) -> dict:
    """为某商品生成 AI 商品描述（不让用户预选词，后端自取全量缺词 Top N）。

    Returns:
        成功：{"code": 0, "data": {new_description, reasoning, included_keywords,
                                    structure, ai_model, decision_id,
                                    generated_content_id, tokens, duration_ms,
                                    original_description, listing_id}}
        失败：{"code": ErrorCode.xxx, "msg": "..."}
    """
    shop_id = shop.id

    # ---------- 1. 查商品 + listing ----------
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

    # ---------- 2. 拉全部缺词候选（按 score desc 限 max_candidates 个）----------
    cand_rows = db.execute(text("""
        SELECT id, keyword, score,
               paid_roas, paid_orders, paid_spend, paid_revenue,
               organic_impressions, organic_orders
        FROM seo_keyword_candidates
        WHERE tenant_id = :tid
          AND shop_id = :sid
          AND product_id = :pid
          AND status = 'pending'
          AND in_title = 0
          AND in_attrs = 0
        ORDER BY score DESC
        LIMIT :lim
    """), {"tid": tenant_id, "sid": shop_id, "pid": product_id, "lim": max_candidates}).fetchall()

    if not cand_rows:
        return {"code": ErrorCode.SEO_CANDIDATE_NOT_FOUND,
                "msg": "该商品暂无可用候选词，请先在 SEO 优化建议页跑「刷新引擎」生成候选池"}

    all_candidates = [
        {
            "id": r.id,
            "keyword": r.keyword,
            "score": float(r.score or 0),
            "paid_roas": float(r.paid_roas) if r.paid_roas is not None else None,
            "paid_orders": int(r.paid_orders) if r.paid_orders is not None else None,
            "organic_impressions": int(r.organic_impressions) if r.organic_impressions is not None else None,
            "organic_orders": int(r.organic_orders) if r.organic_orders is not None else None,
        }
        for r in cand_rows
    ]

    # ---------- 3. 查"必须保留高价值词"（在原标题/描述里出现且带订单/曝光）----------
    # 注意 in_title=1 OR in_attrs=1 都算（描述里没有 in_description 字段，先不查描述里的词）
    preserve_rows = db.execute(text("""
        SELECT keyword
        FROM seo_keyword_candidates
        WHERE tenant_id = :tid
          AND shop_id = :sid
          AND product_id = :pid
          AND (in_title = 1 OR in_attrs = 1)
          AND (COALESCE(paid_orders, 0) > 0
               OR COALESCE(organic_orders, 0) > 0
               OR COALESCE(organic_impressions, 0) >= 20)
        ORDER BY (COALESCE(paid_orders,0) + COALESCE(organic_orders,0)) DESC,
                 score DESC
        LIMIT 15
    """), {"tid": tenant_id, "sid": shop_id, "pid": product_id}).fetchall()
    preserve_keywords = [r.keyword for r in preserve_rows]

    # ---------- 4. 处理品牌理念: 传入则保存到 shops 表(空字符串=清空), 不传则用现值 ----------
    # brand_philosophy=None 表示前端未触发更新, 用 shops 表当前值
    # brand_philosophy="" 表示用户清空了, 写 NULL
    # brand_philosophy="非空" 表示更新, 同时保存到 shops 表
    final_philosophy: Optional[str] = None
    if brand_philosophy is None:
        # 不传 → 用 shops 表现值
        final_philosophy = getattr(shop, "brand_philosophy", None)
    else:
        # 传了(空或非空)都执行 update
        new_val = (brand_philosophy or "").strip() or None
        db.execute(
            text("UPDATE shops SET brand_philosophy = :bp WHERE id = :sid AND tenant_id = :tid"),
            {"bp": new_val, "sid": shop_id, "tid": tenant_id},
        )
        db.commit()
        final_philosophy = new_val

    # ---------- 5. 拼 prompt & 调 GLM ----------
    user_prompt = _build_user_prompt(
        platform=getattr(shop, "platform", None),
        name_zh=prod_row.name_zh or "",
        name_ru=prod_row.name_ru,
        brand=prod_row.brand,
        category_name=prod_row.platform_category_name,
        current_title_ru=prod_row.title_ru,
        current_description_ru=prod_row.description_ru,
        variant_attrs=prod_row.variant_attrs,
        all_candidates=all_candidates,
        preserve_keywords=preserve_keywords,
        brand_philosophy=final_philosophy,
    )

    logger.info(
        f"SEO description generate: tenant={tenant_id} shop={shop_id} product={product_id} "
        f"candidates={len(all_candidates)} preserve={len(preserve_keywords)} "
        f"prompt_chars={len(user_prompt)} has_current_desc={bool(prod_row.description_ru)}"
    )
    logger.info(
        "SEO description SYSTEM_PROMPT >>>\n%s\n<<< SYSTEM_PROMPT END",
        SYSTEM_PROMPT,
    )
    logger.info(
        "SEO description USER_PROMPT (tenant=%s shop=%s product=%s) >>>\n%s\n<<< USER_PROMPT END",
        tenant_id, shop_id, product_id, user_prompt,
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

    # ---------- 5. 持久化到 seo_generated_contents（content_type='description'）----------
    gen = SeoGeneratedContent(
        tenant_id=tenant_id,
        listing_id=prod_row.listing_id,
        content_type="description",
        original_text=prod_row.description_ru or "",
        generated_text=parsed["new_description"],
        keywords_used={
            "candidate_ids": [c["id"] for c in all_candidates],
            "keywords": parsed["included_keywords"],
            "reasoning": parsed["reasoning"],
            "structure": parsed["structure"],
            "preserve_keywords": preserve_keywords,
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
            "original_description": prod_row.description_ru or "",
            "char_count": len(parsed["new_description"]),
            "listing_id": prod_row.listing_id,
            "brand_philosophy": final_philosophy or "",  # 返给前端,确保 modal 同步
        },
    }
