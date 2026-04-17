"""关键词俄文→中文翻译（带进程级内存缓存）"""

from app.services.category_mapping.ai_suggester import _translate_batch
from app.utils.logger import logger

# 进程级缓存（重启丢失，但同一进程内不重复翻译）
_cache: dict = {}


async def translate_keywords_cached(keywords: list) -> dict:
    """批量翻译关键词，返回 {keyword_ru: keyword_zh}

    已缓存的直接取，未缓存的调 Kimi 翻译后缓存。
    """
    result = {}
    to_translate = []
    for kw in keywords:
        if kw in _cache:
            result[kw] = _cache[kw]
        else:
            to_translate.append(kw)

    if to_translate:
        try:
            translated = await _translate_batch(to_translate)
            for src, tgt in zip(to_translate, translated):
                _cache[src] = tgt
                result[src] = tgt
        except Exception as e:
            logger.warning(f"关键词翻译失败: {e}")
            for kw in to_translate:
                result[kw] = kw  # 失败兜底用原文

    return result
