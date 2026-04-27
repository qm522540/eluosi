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


async def mark_title_applied(
    db: Session,
    tenant_id: int,
    shop,
    generated_id: int,
    user_id: Optional[int] = None,
) -> dict:
    """启用新标题: 改本地 DB title_ru + 调平台 API 写回 + 标 applied 建 ROI 基线。

    流程:
      1. 拉 generated 记录 + 对应 listing 的 platform_product_id, offer_id, content_type
      2. 改本地 platform_listings.title_ru (description 走 description_ru)
      3. 标 seo_generated_contents.approval_status='applied' + applied_at
      4. 调平台 API 写回:
         - Ozon: /v1/product/import 异步任务, 返 task_id, 1-5 分钟生效
         - WB: 暂不支持 (下一步加, 用户暂时手动到平台改)
      5. 平台 API 失败不回滚本地 (本地已应用, 用户可看到; 失败信息回传前端提示)
    """
    from datetime import datetime, timezone

    row = db.execute(text("""
        SELECT g.id, g.approval_status, g.content_type, g.generated_text,
               pl.id AS listing_id, pl.platform, pl.platform_product_id,
               pl.title_ru AS old_title, pl.description_ru AS old_desc
        FROM seo_generated_contents g
        JOIN platform_listings pl ON pl.id = g.listing_id
        LEFT JOIN platform_listings pl2 ON pl2.id = g.listing_id
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
                         "msg": "已是 applied 状态,无变更"}}

    new_text = row.generated_text or ""
    if not new_text:
        return {"code": ErrorCode.SUCCESS,
                "data": {"id": generated_id, "msg": "生成内容为空,跳过"}}

    # 取 offer_id (Ozon 改商品需要 offer_id 而非 product_id)
    offer_row = db.execute(text("""
        SELECT p.sku FROM platform_listings pl
        JOIN products p ON p.id = pl.product_id
        WHERE pl.id = :lid LIMIT 1
    """), {"lid": row.listing_id}).first()
    offer_id = (offer_row.sku if offer_row else None) or row.platform_product_id

    now_utc = datetime.now(timezone.utc)

    # 1. 改本地 listing 字段 (title 或 description)
    if row.content_type == "title":
        db.execute(text("""
            UPDATE platform_listings SET title_ru = :v, updated_at = :now
            WHERE id = :lid AND tenant_id = :tid
        """), {"v": new_text[:500], "now": now_utc, "lid": row.listing_id, "tid": tenant_id})
    elif row.content_type == "description":
        db.execute(text("""
            UPDATE platform_listings SET description_ru = :v, updated_at = :now
            WHERE id = :lid AND tenant_id = :tid
        """), {"v": new_text, "now": now_utc, "lid": row.listing_id, "tid": tenant_id})

    # 2. 标 applied
    db.execute(text("""
        UPDATE seo_generated_contents
        SET approval_status = 'applied',
            approved_by = :uid,
            applied_at = :now
        WHERE id = :gid AND tenant_id = :tid
    """), {"gid": generated_id, "tid": tenant_id, "uid": user_id, "now": now_utc})
    db.commit()

    # 3. 调平台 API 写回 (失败不回滚本地)
    platform_result: dict = {"status": "skipped", "msg": "未知平台/未支持的内容类型"}
    if row.platform == "ozon" and offer_id and row.content_type in ("title", "description"):
        try:
            from app.services.platform.ozon import OzonClient
            client = OzonClient(
                shop_id=shop.id, api_key=shop.api_key, client_id=shop.client_id,
                perf_client_id=getattr(shop, "perf_client_id", None) or "",
                perf_client_secret=getattr(shop, "perf_client_secret", None) or "",
            )
            try:
                if row.content_type == "title":
                    api_res = await client.update_product_name(offer_id, new_text)
                else:
                    api_res = await client.update_product_description(offer_id, new_text)
            finally:
                await client.close()
            if api_res.get("task_id"):
                platform_result = {
                    "status": "submitted",
                    "task_id": api_res["task_id"],
                    "msg": f"已提交 Ozon, task_id={api_res['task_id']}, 1-5 分钟生效",
                }
            else:
                platform_result = {
                    "status": "failed",
                    "msg": api_res.get("error", "未知错误"),
                }
        except Exception as e:
            logger.error(f"启用 {row.content_type} 平台写回失败 generated_id={generated_id}: {e}")
            platform_result = {"status": "failed", "msg": f"{type(e).__name__}: {str(e)[:120]}"}
    elif row.platform == "wb":
        platform_result = {
            "status": "skipped",
            "msg": f"WB 平台 API 写回{row.content_type}暂未实现, 请手动到 WB 后台粘贴",
        }

    return {"code": ErrorCode.SUCCESS,
            "data": {
                "id": generated_id,
                "approval_status": "applied",
                "applied_at": now_utc.isoformat(),
                "local_updated": True,
                "platform_writeback": platform_result,
            }}
