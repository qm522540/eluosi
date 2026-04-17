"""全局映射建议服务

写入：租户确认映射时被动贡献到全局 hints
读取：AI 推荐 / init-from-* 时优先查 hints，命中可跳过 AI

三张表（都无 tenant_id）：
- global_category_hints        单平台分类建议
- global_cross_platform_category_hints  跨平台分类共现
- global_attribute_hints       单平台属性建议
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy import and_, or_

from app.models.global_hints import (
    GlobalCategoryHint,
    GlobalCrossPlatformCategoryHint,
    GlobalAttributeHint,
)
from app.models.category import (
    CategoryPlatformMapping,
    AttributeMapping,
    LocalCategory,
)

logger = logging.getLogger(__name__)


# ==================== 写入（确认触发） ====================

def record_category_confirmation(
    db: Session, tenant_id: int, mapping: CategoryPlatformMapping,
):
    """租户确认一条品类映射时调用

    - 更新 global_category_hints 的计票
    - 同本地分类下已确认的其他平台映射 → 两两记录跨平台共现
    """
    try:
        local_cat = db.query(LocalCategory).filter(
            LocalCategory.id == mapping.local_category_id,
            LocalCategory.tenant_id == tenant_id,
        ).first()
        local_name_zh = local_cat.name if local_cat else None

        # 1. 更新单平台 hint
        _upsert_category_hint(
            db,
            platform=mapping.platform,
            platform_category_id=str(mapping.platform_category_id),
            platform_category_name_ru=mapping.platform_category_name,
            suggested_local_name_zh=local_name_zh,
        )

        # 2. 找出同本地分类下其他已确认的平台映射，记录共现
        # 注：每一对配对的两次 confirm 都会各 +1（A 先确认的话 A 函数里 siblings=[]，
        # B 后确认时 siblings=[A] 得 +1；反过来也是类似）。净效果：每对贡献 1 次。
        # 但回填时两头都已 confirmed，两次循环都会 +1 → 贡献 2（已知小瑕疵，不影响排序用途）。
        siblings = db.query(CategoryPlatformMapping).filter(
            CategoryPlatformMapping.tenant_id == tenant_id,
            CategoryPlatformMapping.local_category_id == mapping.local_category_id,
            CategoryPlatformMapping.is_confirmed == 1,
            CategoryPlatformMapping.id != mapping.id,
        ).all()
        for sib in siblings:
            if sib.platform == mapping.platform:
                continue
            _upsert_cross_hint(
                db,
                mapping.platform, str(mapping.platform_category_id),
                sib.platform, str(sib.platform_category_id),
            )

        db.commit()
    except Exception as e:
        db.rollback()
        logger.warning(f"全局品类 hint 写入失败（非致命）: {e}")


def record_attribute_confirmation(
    db: Session, tenant_id: int, mapping: AttributeMapping,
):
    """租户确认一条属性映射时调用 → 更新 global_attribute_hints"""
    try:
        _upsert_attribute_hint(
            db,
            platform=mapping.platform,
            platform_attr_id=str(mapping.platform_attr_id),
            platform_attr_name_ru=mapping.platform_attr_name,
            suggested_local_name_zh=mapping.local_attr_name,
        )
        db.commit()
    except Exception as e:
        db.rollback()
        logger.warning(f"全局属性 hint 写入失败（非致命）: {e}")


# ==================== 读取（推荐时使用） ====================

def get_category_hint(
    db: Session, platform: str, platform_category_id: str,
) -> Optional[dict]:
    """查单平台分类建议，没有返回 None"""
    row = db.query(GlobalCategoryHint).filter(
        GlobalCategoryHint.platform == platform,
        GlobalCategoryHint.platform_category_id == str(platform_category_id),
    ).first()
    if not row:
        return None
    return {
        "suggested_local_name_zh": row.suggested_local_name_zh,
        "top_name_count": row.top_name_count,
        "total_confirmed_count": row.total_confirmed_count,
    }


def get_category_hints_bulk(
    db: Session, platform: str, platform_category_ids: list,
) -> dict:
    """批量查，返回 {platform_category_id: hint_dict}"""
    if not platform_category_ids:
        return {}
    ids = [str(x) for x in platform_category_ids]
    rows = db.query(GlobalCategoryHint).filter(
        GlobalCategoryHint.platform == platform,
        GlobalCategoryHint.platform_category_id.in_(ids),
    ).all()
    return {
        r.platform_category_id: {
            "suggested_local_name_zh": r.suggested_local_name_zh,
            "top_name_count": r.top_name_count,
            "total_confirmed_count": r.total_confirmed_count,
        }
        for r in rows
    }


def get_cross_platform_hint(
    db: Session, source_platform: str, source_category_id: str,
    target_platform: str,
) -> Optional[dict]:
    """找源分类对应的目标平台分类（top1 by co_confirmed_count）"""
    src = str(source_category_id)
    # 表里 a/b 是按字典序排的，查询两向都试
    row = db.query(GlobalCrossPlatformCategoryHint).filter(
        or_(
            and_(
                GlobalCrossPlatformCategoryHint.platform_a == source_platform,
                GlobalCrossPlatformCategoryHint.category_a_id == src,
                GlobalCrossPlatformCategoryHint.platform_b == target_platform,
            ),
            and_(
                GlobalCrossPlatformCategoryHint.platform_b == source_platform,
                GlobalCrossPlatformCategoryHint.category_b_id == src,
                GlobalCrossPlatformCategoryHint.platform_a == target_platform,
            ),
        ),
    ).order_by(GlobalCrossPlatformCategoryHint.co_confirmed_count.desc()).first()
    if not row:
        return None
    # 返回目标平台那一侧的 category_id
    if row.platform_a == source_platform and row.category_a_id == src:
        target_id = row.category_b_id
    else:
        target_id = row.category_a_id
    return {
        "target_category_id": target_id,
        "co_confirmed_count": row.co_confirmed_count,
    }


def get_cross_platform_suggestions(
    db: Session, tenant_id: int, local_category_id: int,
    supported_platforms: tuple = ("wb", "ozon"),
) -> list:
    """对某本地分类，找出"其他租户绑了但当前租户还没绑"的平台建议

    算法：
    1. 查该 local_cat 当前已有的平台映射（不必 is_confirmed，已是本租户意图）
    2. 对每个 supported_platforms 里"未覆盖"的目标平台 T：
       - 对每个已覆盖的源平台 S 的 mapping，查 S→T 的 cross hint
       - 取 co_confirmed_count 最大的那一条作为 T 的 top1 建议
    3. name 补全：GlobalCategoryHint 查 target 平台+id 的俄文名/中文建议名
    """
    existing = db.query(CategoryPlatformMapping).filter(
        CategoryPlatformMapping.tenant_id == tenant_id,
        CategoryPlatformMapping.local_category_id == local_category_id,
    ).all()
    if not existing:
        return []

    covered = {m.platform for m in existing}
    suggestions = []
    for target in supported_platforms:
        if target in covered:
            continue
        best = None  # (co_count, source_mapping, target_id)
        for src in existing:
            hint = get_cross_platform_hint(
                db, src.platform, str(src.platform_category_id), target,
            )
            if not hint:
                continue
            if best is None or hint["co_confirmed_count"] > best[0]:
                best = (hint["co_confirmed_count"], src, hint["target_category_id"])
        if best is None:
            continue
        count, src_mapping, target_id = best
        target_name_row = db.query(GlobalCategoryHint).filter(
            GlobalCategoryHint.platform == target,
            GlobalCategoryHint.platform_category_id == str(target_id),
        ).first()
        suggestions.append({
            "target_platform": target,
            "target_platform_category_id": target_id,
            "target_platform_category_name_ru": (
                target_name_row.platform_category_name_ru if target_name_row else None
            ),
            "target_suggested_local_name_zh": (
                target_name_row.suggested_local_name_zh if target_name_row else None
            ),
            "co_confirmed_count": count,
            "source_platform": src_mapping.platform,
            "source_platform_category_id": src_mapping.platform_category_id,
            "source_platform_category_name": src_mapping.platform_category_name,
        })
    return suggestions


def get_attribute_hint(
    db: Session, platform: str, platform_attr_id: str,
) -> Optional[dict]:
    """查单平台属性建议"""
    row = db.query(GlobalAttributeHint).filter(
        GlobalAttributeHint.platform == platform,
        GlobalAttributeHint.platform_attr_id == str(platform_attr_id),
    ).first()
    if not row:
        return None
    return {
        "suggested_local_name_zh": row.suggested_local_name_zh,
        "top_name_count": row.top_name_count,
        "total_confirmed_count": row.total_confirmed_count,
    }


def get_attribute_hints_bulk(
    db: Session, platform: str, attr_ids: list,
) -> dict:
    if not attr_ids:
        return {}
    ids = [str(x) for x in attr_ids]
    rows = db.query(GlobalAttributeHint).filter(
        GlobalAttributeHint.platform == platform,
        GlobalAttributeHint.platform_attr_id.in_(ids),
    ).all()
    return {
        r.platform_attr_id: {
            "suggested_local_name_zh": r.suggested_local_name_zh,
            "top_name_count": r.top_name_count,
            "total_confirmed_count": r.total_confirmed_count,
        }
        for r in rows
    }


# ==================== 内部 upsert（不 commit，由外层统一 commit） ====================

def _upsert_category_hint(
    db: Session, platform: str, platform_category_id: str,
    platform_category_name_ru: Optional[str],
    suggested_local_name_zh: Optional[str],
):
    row = db.query(GlobalCategoryHint).filter(
        GlobalCategoryHint.platform == platform,
        GlobalCategoryHint.platform_category_id == platform_category_id,
    ).first()
    if not row:
        row = GlobalCategoryHint(
            platform=platform,
            platform_category_id=platform_category_id,
            platform_category_name_ru=platform_category_name_ru,
            suggested_local_name_zh=suggested_local_name_zh,
            top_name_count=1 if suggested_local_name_zh else 0,
            total_confirmed_count=1,
        )
        db.add(row)
        return
    row.total_confirmed_count += 1
    if platform_category_name_ru and not row.platform_category_name_ru:
        row.platform_category_name_ru = platform_category_name_ru
    if suggested_local_name_zh:
        if row.suggested_local_name_zh == suggested_local_name_zh:
            row.top_name_count += 1
        elif row.top_name_count <= 1:
            # 原 top 只有 1 票，被新名替掉
            row.suggested_local_name_zh = suggested_local_name_zh
            row.top_name_count = 1
        # 否则保留原 top（lossy）


def _upsert_attribute_hint(
    db: Session, platform: str, platform_attr_id: str,
    platform_attr_name_ru: Optional[str],
    suggested_local_name_zh: Optional[str],
):
    row = db.query(GlobalAttributeHint).filter(
        GlobalAttributeHint.platform == platform,
        GlobalAttributeHint.platform_attr_id == platform_attr_id,
    ).first()
    if not row:
        row = GlobalAttributeHint(
            platform=platform,
            platform_attr_id=platform_attr_id,
            platform_attr_name_ru=platform_attr_name_ru,
            suggested_local_name_zh=suggested_local_name_zh,
            top_name_count=1 if suggested_local_name_zh else 0,
            total_confirmed_count=1,
        )
        db.add(row)
        return
    row.total_confirmed_count += 1
    if platform_attr_name_ru and not row.platform_attr_name_ru:
        row.platform_attr_name_ru = platform_attr_name_ru
    if suggested_local_name_zh:
        if row.suggested_local_name_zh == suggested_local_name_zh:
            row.top_name_count += 1
        elif row.top_name_count <= 1:
            row.suggested_local_name_zh = suggested_local_name_zh
            row.top_name_count = 1


def _upsert_cross_hint(
    db: Session,
    platform_a: str, category_a_id: str,
    platform_b: str, category_b_id: str,
):
    # 规范化：按字典序把小的放 a，大的放 b，避免 (wb,x,ozon,y) 和 (ozon,y,wb,x) 重复
    if (platform_a, category_a_id) > (platform_b, category_b_id):
        platform_a, category_a_id, platform_b, category_b_id = (
            platform_b, category_b_id, platform_a, category_a_id,
        )
    row = db.query(GlobalCrossPlatformCategoryHint).filter(
        GlobalCrossPlatformCategoryHint.platform_a == platform_a,
        GlobalCrossPlatformCategoryHint.category_a_id == category_a_id,
        GlobalCrossPlatformCategoryHint.platform_b == platform_b,
        GlobalCrossPlatformCategoryHint.category_b_id == category_b_id,
    ).first()
    if not row:
        row = GlobalCrossPlatformCategoryHint(
            platform_a=platform_a, category_a_id=category_a_id,
            platform_b=platform_b, category_b_id=category_b_id,
            co_confirmed_count=1,
        )
        db.add(row)
    else:
        row.co_confirmed_count += 1
