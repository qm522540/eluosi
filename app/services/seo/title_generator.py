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

约束：
1. 输出俄语标题，总长度不超过 180 字符（保留余量，Ozon/WB 上限 200）
2. 保留原标题的核心商品信息（商品类型、品牌、关键属性如颜色/材质）
3. 融合关键词要"语法通顺"，不是简单罗列（但电商标题允许空格分隔的短语堆叠）
4. 搜索量/订单数高的词放前面
5. 全部小写，不用标点符号（电商平台 SEO 惯例），短语之间用单个空格分隔
6. 不编造原标题没有的属性（比如原品没说"防水"，不要加"водостойкий"）

输出严格 JSON 格式：
{
  "new_title": "融合后的俄语新标题",
  "reasoning": "为什么这样组合（中文一句话，便于用户理解决策）",
  "included_keywords": ["实际用到的候选词（用原词）"]
}

不要输出 markdown 代码块标记，不要输出 JSON 之外的其他内容。"""


def _build_user_prompt(
    *,
    name_zh: str,
    name_ru: Optional[str],
    brand: Optional[str],
    category_name: Optional[str],
    current_title_ru: Optional[str],
    variant_attrs: Any,
    candidates: list[dict],
) -> str:
    """拼用户侧 prompt。候选词按 score 降序传入。"""
    lines = [
        "【当前商品信息】",
        f"中文名：{name_zh}",
    ]
    if name_ru:
        lines.append(f"俄语名：{name_ru}")
    if brand:
        lines.append(f"品牌：{brand}")
    if category_name:
        lines.append(f"类目：{category_name}")
    lines.append(f"当前俄语标题：{current_title_ru or '（空）'}")
    if variant_attrs:
        attrs_str = json.dumps(variant_attrs, ensure_ascii=False) if isinstance(variant_attrs, (dict, list)) else str(variant_attrs)
        # 属性可能很长，截断 400 字符避免烧 token
        if len(attrs_str) > 400:
            attrs_str = attrs_str[:400] + "...(截断)"
        lines.append(f"属性：{attrs_str}")

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

    lines.append("")
    lines.append("请按上述约束生成新俄语标题，返回 JSON。")
    return "\n".join(lines)


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
    if not candidate_ids:
        return {"code": ErrorCode.SEO_CANDIDATE_NOT_FOUND,
                "msg": "candidate_ids 不能为空"}

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

    if not cand_rows:
        return {"code": ErrorCode.SEO_CANDIDATE_NOT_FOUND,
                "msg": "选中的候选词在该商品下不存在（可能被其他人处理过或 id 非法）"}

    candidates = [
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

    # ---------- 3. 拼 prompt & 调 AI（GLM）----------
    user_prompt = _build_user_prompt(
        name_zh=prod_row.name_zh or "",
        name_ru=prod_row.name_ru,
        brand=prod_row.brand,
        category_name=prod_row.platform_category_name,
        current_title_ru=prod_row.title_ru,
        variant_attrs=prod_row.variant_attrs,
        candidates=candidates,
    )

    logger.info(
        f"SEO title generate: tenant={tenant_id} shop={shop_id} product={product_id} "
        f"candidates={len(candidates)} prompt_chars={len(user_prompt)}"
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

    return {
        "code": ErrorCode.SUCCESS,
        "data": {
            "new_title": parsed["new_title"],
            "reasoning": parsed["reasoning"],
            "included_keywords": parsed["included_keywords"] or [c["keyword"] for c in candidates],
            "ai_model": ai_result["model"],
            "decision_id": ai_result["decision_id"],
            "generated_content_id": gen.id,
            "tokens": ai_result["tokens"],
            "duration_ms": ai_result["duration_ms"],
            "original_title": prod_row.title_ru or "",
            "listing_id": prod_row.listing_id,
        },
    }
