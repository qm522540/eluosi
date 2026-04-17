"""俄→中翻译服务（带 DB 缓存）

用法：
    from app.services.translation.ru_zh import translate_batch
    mapping = await translate_batch(db, ["Цвет", "Материал"], field_type="attr_name")
    # mapping = {"Цвет": "颜色", "Материал": "材料"}

首次调用查 ru_zh_dict 表，未命中的扔给 Kimi 批量翻译后回写。
字典全局共享，不带 tenant_id。
"""

import hashlib
import json
import logging
import re
from sqlalchemy.orm import Session
from sqlalchemy import tuple_
from sqlalchemy.exc import IntegrityError

from app.models.translation import RuZhDict
from app.services.ai.kimi import KimiClient
from app.config import get_settings

logger = logging.getLogger(__name__)

MAX_TEXT_LEN = 500  # 超过不缓存，走原文兜底
CHUNK_SIZE = 100    # 单次 Kimi 翻译条数上限


def _hash(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def _looks_russian(text: str) -> bool:
    """粗略判断是否含俄文字符；纯数字/英文/中文不翻"""
    if not text or not isinstance(text, str):
        return False
    return bool(re.search(r"[\u0400-\u04FF]", text))


async def translate_batch(
    db: Session,
    texts: list,
    field_type: str = "attr_value",
) -> dict:
    """批量俄→中翻译，返回 {俄文: 中文} 映射。

    texts 不含俄文字符或为空时原文返回。
    对超长文本（>500 字）也原文返回不缓存。
    """
    if not texts:
        return {}
    # 去重 + 基本过滤
    unique = []
    seen = set()
    for t in texts:
        if not t or not isinstance(t, str):
            continue
        t = t.strip()
        if not t or t in seen:
            continue
        seen.add(t)
        if _looks_russian(t) and len(t) <= MAX_TEXT_LEN:
            unique.append(t)

    if not unique:
        return {t: t for t in texts if t}

    # 1. 查 DB 缓存
    hash_pairs = [(_hash(t), field_type) for t in unique]
    hits = db.query(RuZhDict.text_ru, RuZhDict.text_zh).filter(
        tuple_(RuZhDict.text_ru_hash, RuZhDict.field_type).in_(hash_pairs),
    ).all()
    cached = {r.text_ru: r.text_zh for r in hits}

    # 2. 未命中的去 Kimi
    missing = [t for t in unique if t not in cached]
    new_translations = {}
    if missing:
        new_translations = await _call_kimi(missing, field_type)
        # 3. 回写 DB
        if new_translations:
            _persist(db, new_translations, field_type)

    # 4. 合并：原文兜底所有未翻译的（非俄文/超长/翻译失败）
    out = {}
    for t in texts:
        if not t or not isinstance(t, str):
            continue
        t_stripped = t.strip()
        if t_stripped in cached:
            out[t] = cached[t_stripped]
        elif t_stripped in new_translations:
            out[t] = new_translations[t_stripped]
        else:
            out[t] = t  # 原文兜底
    return out


async def _call_kimi(texts: list, field_type: str) -> dict:
    """调用 Kimi 批量翻译，返回 {俄文: 中文}。失败返回 {}"""
    settings = get_settings()
    if not settings.KIMI_API_KEY:
        logger.warning("KIMI_API_KEY 未配置，跳过翻译")
        return {}

    client = KimiClient(api_key=settings.KIMI_API_KEY)
    out = {}
    try:
        for i in range(0, len(texts), CHUNK_SIZE):
            chunk = texts[i:i + CHUNK_SIZE]
            numbered = "\n".join(f"{j+1}. {t}" for j, t in enumerate(chunk))
            hint = {
                "attr_name": "这些是电商平台的商品属性名（如 Цвет/Материал），用最常用的中文电商术语",
                "attr_value": "这些是商品属性值（如 Красный/Хлопок），用最常用的中文",
            }.get(field_type, "这些是电商商品数据")
            prompt = (
                f"把下列俄文翻译为中文。{hint}。\n"
                "规则：\n"
                "- 保留品牌名/型号等专有名词不翻译\n"
                "- 数字、单位原样保留（如 100 г → 100克）\n"
                "- 不要加 \"翻译：\" 等前缀\n\n"
                f"输入（俄文，共 {len(chunk)} 条）：\n{numbered}\n\n"
                f"返回 JSON 数组（不含其他文字），长度必须等于 {len(chunk)}：\n"
                "[\"中文1\", \"中文2\", ...]"
            )
            try:
                res = await client.chat(
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.1, max_tokens=4000,
                )
                content = (res.get("content") or "").strip()
                # 兼容围栏代码块
                if content.startswith("```"):
                    content = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", content).strip()
                arr = json.loads(content)
                if isinstance(arr, list) and len(arr) == len(chunk):
                    for src, tgt in zip(chunk, arr):
                        if isinstance(tgt, str) and tgt.strip():
                            out[src] = tgt.strip()
                else:
                    logger.warning(
                        f"Kimi 翻译返回长度不匹配: expected={len(chunk)} got={len(arr) if isinstance(arr, list) else 'N/A'}"
                    )
            except Exception as e:
                logger.warning(f"Kimi 翻译分片失败（{len(chunk)} 条）: {e}")
    finally:
        await client.close()
    return out


def _persist(db: Session, translations: dict, field_type: str):
    """把翻译结果写入 ru_zh_dict。UNIQUE 冲突忽略（并发两条一样的情况）"""
    for ru, zh in translations.items():
        if len(ru) > MAX_TEXT_LEN or len(zh) > MAX_TEXT_LEN:
            continue
        row = RuZhDict(
            text_ru_hash=_hash(ru),
            text_ru=ru,
            text_zh=zh,
            field_type=field_type,
            source="kimi",
        )
        db.add(row)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
    try:
        db.commit()
    except Exception as e:
        logger.warning(f"ru_zh_dict 批量回写失败: {e}")
        db.rollback()
