"""SEO AI 生成标题历史 — 查询 seo_generated_contents 表。

老林早建的 SeoGeneratedContent 表（see app/models/seo.py）现在被 title_generator
每次 AI 调用时写入 —— 这个 service 负责读取、分页、按商品 JOIN 展示。

为二期模块 4（Before/After ROI 对比）打底：一期只展示历史，二期用
approval_status='applied' + applied_at 字段记录"已采用"时点，做效果对比。

规则 1 tenant_id / 规则 4 listing JOIN products 过滤 shop_id。
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.utils.errors import ErrorCode


def list_generated_titles(
    db: Session,
    tenant_id: int,
    shop,  # Shop ORM（API 层已 get_owned_shop 守卫）
    keyword: str = "",
    approval_status: str = "all",
    page: int = 1,
    size: int = 20,
) -> dict:
    """分页拉当前店铺的 AI 生成标题历史。

    只返 content_type='title' 记录（description / bullets 其他类型暂不做）。
    通过 listing_id JOIN platform_listings → products 过滤到当前 shop。

    Returns:
        {"code": 0, "data": {total, items, page, size}}
    """
    page = max(1, int(page))
    size = min(max(1, int(size)), 100)
    offset = (page - 1) * size

    shop_id = shop.id

    where_parts = [
        "g.tenant_id = :tid",
        "g.content_type = 'title'",
        "pl.shop_id = :sid",
        "pl.tenant_id = :tid",
    ]
    params = {"tid": tenant_id, "sid": shop_id}

    if approval_status and approval_status != "all":
        where_parts.append("g.approval_status = :appst")
        params["appst"] = approval_status

    if keyword and keyword.strip():
        where_parts.append("(g.original_text LIKE :kw_like OR g.generated_text LIKE :kw_like)")
        params["kw_like"] = f"%{keyword.strip()}%"

    where_sql = " AND ".join(where_parts)

    # Totals
    total_sql = text(f"""
        SELECT COUNT(DISTINCT g.id) AS total
        FROM seo_generated_contents g
        JOIN platform_listings pl ON pl.id = g.listing_id
        WHERE {where_sql}
    """)
    total = int(db.execute(total_sql, params).scalar() or 0)

    # Items — JOIN listings + products 取商品信息
    items_sql = text(f"""
        SELECT
            g.id,
            g.listing_id,
            g.original_text,
            g.generated_text,
            g.keywords_used,
            g.ai_model,
            g.ai_decision_id,
            g.approval_status,
            g.approved_by,
            g.applied_at,
            g.created_at,
            ANY_VALUE(pl.product_id) AS product_id,
            ANY_VALUE(pl.title_ru) AS current_title,
            ANY_VALUE(p.name_zh) AS product_name,
            ANY_VALUE(p.image_url) AS image_url,
            ANY_VALUE(pl.platform) AS platform
        FROM seo_generated_contents g
        JOIN platform_listings pl ON pl.id = g.listing_id
        LEFT JOIN products p ON p.id = pl.product_id
                             AND p.tenant_id = pl.tenant_id
        WHERE {where_sql}
        GROUP BY g.id
        ORDER BY g.created_at DESC
        LIMIT :offset, :size
    """)
    rows = db.execute(items_sql, dict(params, offset=offset, size=size)).fetchall()

    items = []
    for r in rows:
        ku = r.keywords_used
        if isinstance(ku, str):
            import json
            try:
                ku = json.loads(ku)
            except Exception:
                ku = {}
        items.append({
            "id": int(r.id),
            "listing_id": int(r.listing_id),
            "product_id": int(r.product_id) if r.product_id else None,
            "product_name": r.product_name,
            "image_url": r.image_url,
            "platform": r.platform,
            "original_title": r.original_text or "",
            "current_title": r.current_title or "",
            "generated_title": r.generated_text or "",
            "keywords_used": (ku or {}).get("keywords", []),
            "reasoning": (ku or {}).get("reasoning", ""),
            "ai_model": r.ai_model,
            "ai_decision_id": int(r.ai_decision_id) if r.ai_decision_id else None,
            "approval_status": r.approval_status,
            "approved_by": int(r.approved_by) if r.approved_by else None,
            "applied_at": r.applied_at.isoformat() if r.applied_at else None,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        })

    return {
        "code": ErrorCode.SUCCESS,
        "data": {
            "total": total,
            "items": items,
            "page": page,
            "size": size,
        },
    }


def mark_title_applied(
    db: Session,
    tenant_id: int,
    shop,
    generated_id: int,
    user_id: Optional[int] = None,
) -> dict:
    """标记"已复制并应用到商品"——用户手动确认已改，建立后续 ROI 对比基线。

    一期只改 approval_status = 'applied' + 写 applied_at + approved_by。
    不碰 platform_listings.title_ru（三期才做真正的平台 API 写回）。
    """
    from datetime import datetime, timezone

    row = db.execute(text("""
        SELECT g.id, g.approval_status
        FROM seo_generated_contents g
        JOIN platform_listings pl ON pl.id = g.listing_id
        WHERE g.id = :gid
          AND g.tenant_id = :tid
          AND pl.shop_id = :sid
          AND pl.tenant_id = :tid
    """), {"gid": generated_id, "tid": tenant_id, "sid": shop.id}).fetchone()

    if not row:
        return {"code": ErrorCode.NOT_FOUND,
                "msg": "生成记录不存在或不属于当前店铺"}

    if row.approval_status == "applied":
        return {"code": ErrorCode.SUCCESS,
                "data": {"id": generated_id, "approval_status": "applied",
                         "msg": "已是 applied 状态，无变更"}}

    now_utc = datetime.now(timezone.utc)
    db.execute(text("""
        UPDATE seo_generated_contents
        SET approval_status = 'applied',
            approved_by = :uid,
            applied_at = :now
        WHERE id = :gid AND tenant_id = :tid
    """), {"gid": generated_id, "tid": tenant_id, "uid": user_id, "now": now_utc})
    db.commit()

    return {"code": ErrorCode.SUCCESS,
            "data": {"id": generated_id, "approval_status": "applied",
                     "applied_at": now_utc.isoformat()}}
