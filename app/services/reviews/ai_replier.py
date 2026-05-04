"""评价 AI 调用封装

3 个核心函数:
- translate_to_zh: 俄→中翻译 (复用 ru_zh_dict 缓存, field_type='review_content')
- detect_sentiment: 情感分析 — 用 rating + 关键词规则, 不调 AI 省成本
- generate_reply_draft: 生成俄语回复草稿 + 翻译给老板看 (调 DeepSeek)

设计:
- DeepSeek 默认 task_type='ad_optimization' (router map 到 deepseek)
  本期评价回复生成跟广告分析共用 deepseek, 后续如需可加新 task_type
- 翻译走 Kimi (router map: report_generation 是 Kimi, 但 translate_batch 直调
  KimiClient 更直接, 跟 keyword_stats translator 保持一致)
"""

import re
from typing import Optional

from sqlalchemy.orm import Session

from app.services.translation.ru_zh import translate_batch
from app.services.reviews.prompts import build_reply_prompt
from app.utils.logger import setup_logger

logger = setup_logger("reviews.ai_replier")

# 差评关键词 (用于矫正 rating 模糊场景, 例如 rating=4 但内容含抱怨)
NEGATIVE_KEYWORDS = [
    "плох", "брак", "недоволен", "недовольна", "ужасн", "разочаров",
    "не пришёл", "не пришел", "не получил", "сломан", "повреждён", "повреждена",
    "обман", "не работает", "ужас", "кошмар",
]
# 好评关键词
POSITIVE_KEYWORDS = [
    "отличн", "прекрасн", "великолепн", "супер", "идеальн",
    "восторг", "рекомендую", "класс", "огромное спасибо",
]


async def translate_to_zh(db: Session, text_ru: str) -> Optional[str]:
    """单条俄语→中文 (走 translate_batch 复用 ru_zh_dict 缓存)

    Returns:
        中文翻译 / None (空文本 / 翻译失败)
    """
    if not text_ru or not text_ru.strip():
        return None
    try:
        mapping = await translate_batch(db, [text_ru], field_type="review_content")
        zh = mapping.get(text_ru)
        # translate_batch 翻译失败时会返原文兜底, 用 == 判断是否真翻译了
        if zh and zh != text_ru:
            return zh
        return None
    except Exception as e:
        logger.warning(f"评价翻译失败 len={len(text_ru)}: {e}")
        return None


def detect_sentiment(content_ru: str, rating: int) -> str:
    """情感分析 — rating + 关键词规则 (不调 AI 省成本)

    判定规则:
    - 4-5 星: 默认 positive (除非内容含明显差评关键词 → neutral 矫正)
    - 3 星: 默认 neutral (含好评词 → positive, 含差评词 → negative)
    - 1-2 星: 默认 negative (除非内容很短或只是误评 → neutral)
    - rating=0 或缺失: unknown

    Returns:
        'positive' / 'neutral' / 'negative' / 'unknown'
    """
    if not rating or rating < 1 or rating > 5:
        return "unknown"

    text_low = (content_ru or "").lower()
    has_neg = any(kw in text_low for kw in NEGATIVE_KEYWORDS)
    has_pos = any(kw in text_low for kw in POSITIVE_KEYWORDS)

    if rating >= 4:
        return "neutral" if has_neg and not has_pos else "positive"
    if rating == 3:
        if has_pos and not has_neg:
            return "positive"
        if has_neg and not has_pos:
            return "negative"
        return "neutral"
    # rating 1-2
    return "neutral" if has_pos and not has_neg else "negative"


async def generate_reply_draft(
    db: Session,
    *,
    tenant_id: int,
    review_text_ru: str,
    rating: int,
    customer_name: str = "",
    product_name: str = "",
    custom_hint: str = "",
    brand_signature: str = "",
    reply_tone: str = "friendly",
    custom_prompt_extra: str = "",
) -> dict:
    """调 DeepSeek 生成俄语回复 + 翻译中文给老板看

    新增 (2026-05-04 修 BUG A):
      reply_tone / custom_prompt_extra 从 shop_review_settings 透传, 让 SettingsModal
      改的语气和品牌 prompt 真正生效, 之前是装饰品.

    Returns:
        {
          "ok": bool,
          "draft_ru": str,    # 俄语回复
          "draft_zh": str,    # 中文翻译 (失败时为空)
          "ai_model": str,    # 实际用的模型 (router 决定)
          "msg": str,         # 失败时含错误原因
        }
    """
    from app.services.ai.router import execute as ai_execute

    prompt = build_reply_prompt(
        review_text_ru=review_text_ru,
        rating=rating,
        customer_name=customer_name,
        product_name=product_name,
        custom_hint=custom_hint,
        brand_signature=brand_signature,
        reply_tone=reply_tone,
        custom_prompt_extra=custom_prompt_extra,
    )

    try:
        # task_type='ad_optimization' router 映到 deepseek (跟 AI 调价同款)
        # 本期不为 review 单独建 task_type, 等量大后再加 'review_reply'
        result = await ai_execute(
            task_type="ad_optimization",
            input_data={"prompt": prompt},
            tenant_id=tenant_id,
            db=db,
            triggered_by="manual",
            temperature=0.7,
            max_tokens=400,    # 30-80 个俄语单词约 200-400 字符, 留 buffer
        )
        draft_ru = (result.get("content") or "").strip()
        if not draft_ru:
            return {"ok": False, "draft_ru": "", "draft_zh": "",
                    "ai_model": result.get("model", ""),
                    "msg": "AI 返空内容"}
        # 去掉常见误格式: 引号包裹 / "回复:" 前缀 / 末尾解释
        draft_ru = re.sub(r'^["«""]+|["»""]+$', '', draft_ru).strip()
        draft_ru = re.sub(r'^(回复|Reply|Ответ)[:：]\s*', '', draft_ru).strip()

        # 翻译给老板看
        draft_zh = await translate_to_zh(db, draft_ru) or ""

        return {
            "ok": True,
            "draft_ru": draft_ru,
            "draft_zh": draft_zh,
            "ai_model": result.get("model", "deepseek"),
            "msg": "",
        }
    except Exception as e:
        logger.error(f"生成回复草稿失败 tenant={tenant_id} rating={rating}: {e}",
                     exc_info=True)
        return {
            "ok": False, "draft_ru": "", "draft_zh": "",
            "ai_model": "", "msg": str(e)[:300],
        }
