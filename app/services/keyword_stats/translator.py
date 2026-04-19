"""关键词俄文→中文翻译（双层缓存：进程内存 + ru_zh_dict 表）

复用现有 ru_zh_dict 表（原本给商品属性值翻译用），永久缓存重启不丢。
field_type='keyword' 区分关键词翻译和属性值翻译。
"""

import hashlib
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.category_mapping.ai_suggester import _translate_batch
from app.utils.logger import logger

# 进程级缓存（仍保留作 L1，避免反复查 DB）
_cache: dict = {}

_FIELD_TYPE = "keyword"


def _ru_hash(text_ru: str) -> str:
    return hashlib.md5(text_ru.encode("utf-8")).hexdigest()


def _load_db_cache(db: Session, keywords: list) -> dict:
    """从 ru_zh_dict 表批量查已翻译的关键词"""
    if not keywords or db is None:
        return {}
    hashes = [_ru_hash(k) for k in keywords]
    # 用 expanding bindparam 处理 IN 列表
    from sqlalchemy import bindparam
    sql = text("""
        SELECT text_ru, text_zh FROM ru_zh_dict
        WHERE field_type = :ft AND text_ru_hash IN :hashes
    """).bindparams(bindparam("hashes", expanding=True))
    rows = db.execute(sql, {"ft": _FIELD_TYPE, "hashes": hashes}).fetchall()
    return {r.text_ru: r.text_zh for r in rows}


def _save_db_cache(db: Session, translations: dict):
    """批量写 ru_zh_dict（INSERT ... ON DUPLICATE KEY UPDATE）"""
    if not translations or db is None:
        return
    sql = text("""
        INSERT INTO ru_zh_dict (text_ru_hash, text_ru, text_zh, field_type, source, created_at, updated_at)
        VALUES (:h, :ru, :zh, :ft, 'kimi', NOW(), NOW())
        ON DUPLICATE KEY UPDATE
            text_zh = VALUES(text_zh),
            updated_at = NOW()
    """)
    try:
        for ru, zh in translations.items():
            db.execute(sql, {
                "h": _ru_hash(ru), "ru": ru[:500], "zh": (zh or "")[:500],
                "ft": _FIELD_TYPE,
            })
        db.commit()
    except Exception as e:
        logger.warning(f"翻译入库失败: {e}")
        db.rollback()


async def translate_keywords_cached(keywords: list, db: Optional[Session] = None) -> dict:
    """批量翻译关键词，返回 {keyword_ru: keyword_zh}

    三层查找：
    1. L1 进程内存（_cache）
    2. L2 DB ru_zh_dict 持久化
    3. L3 Kimi AI 真翻
    新翻译同时回写 L1 + L2。
    """
    if not keywords:
        return {}
    result = {}
    miss_l1 = []

    # L1
    for kw in keywords:
        if kw in _cache:
            result[kw] = _cache[kw]
        else:
            miss_l1.append(kw)

    # L2: DB
    if miss_l1 and db is not None:
        db_hits = _load_db_cache(db, miss_l1)
        for kw, zh in db_hits.items():
            _cache[kw] = zh  # 同步填 L1
            result[kw] = zh
        miss_l2 = [kw for kw in miss_l1 if kw not in db_hits]
    else:
        miss_l2 = miss_l1

    # L3: Kimi
    if miss_l2:
        try:
            translated = await _translate_batch(miss_l2)
            new_translations = {}
            for src, tgt in zip(miss_l2, translated):
                _cache[src] = tgt
                result[src] = tgt
                if tgt and tgt != src:
                    new_translations[src] = tgt
            # 回写 DB
            if new_translations and db is not None:
                _save_db_cache(db, new_translations)
                logger.info(f"翻译入库 {len(new_translations)} 条")
        except Exception as e:
            logger.warning(f"关键词翻译失败: {e}")
            for kw in miss_l2:
                result[kw] = kw

    return result
