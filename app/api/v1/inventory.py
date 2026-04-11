"""库存联动 API 路由

路径前缀: /api/v1/inventory

- GET  /linkage-rule/{shop_id}   获取店铺库存联动规则
- PUT  /linkage-rule/{shop_id}   更新店铺库存联动规则
- GET  /stocks/{shop_id}          查询店铺SKU库存列表
- POST /linkage-check/{shop_id}   手动触发库存同步+联动检查
"""

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_current_user, get_tenant_id
from app.utils.logger import setup_logger
from app.utils.response import success, error

logger = setup_logger("api.inventory")
router = APIRouter()


class LinkageRuleUpdate(BaseModel):
    is_active: bool = Field(..., description="是否开启库存联动")
    pause_threshold: int = Field(10, ge=1, description="暂停阈值")
    resume_threshold: int = Field(20, ge=1, description="恢复阈值")


# ==================== 规则配置 ====================

@router.get("/linkage-rule/{shop_id}")
def get_linkage_rule(
    shop_id: int,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """获取店铺库存联动规则配置"""
    row = db.execute(text("""
        SELECT id, tenant_id, shop_id, is_active,
               pause_threshold, resume_threshold,
               created_at, updated_at
        FROM inventory_linkage_rules
        WHERE shop_id = :shop_id
        LIMIT 1
    """), {"shop_id": shop_id}).fetchone()

    if not row:
        # 店铺尚未配置时返回默认值
        return success({
            "shop_id": shop_id,
            "is_active": False,
            "pause_threshold": 10,
            "resume_threshold": 20,
        })

    return success({
        "id": row.id,
        "tenant_id": row.tenant_id,
        "shop_id": row.shop_id,
        "is_active": bool(row.is_active),
        "pause_threshold": row.pause_threshold,
        "resume_threshold": row.resume_threshold,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    })


@router.put("/linkage-rule/{shop_id}")
def update_linkage_rule(
    shop_id: int,
    req: LinkageRuleUpdate,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """更新店铺库存联动规则（开关+阈值）"""
    if req.pause_threshold >= req.resume_threshold:
        return error(40001, "恢复阈值必须大于暂停阈值")

    db.execute(text("""
        INSERT INTO inventory_linkage_rules
            (tenant_id, shop_id, is_active,
             pause_threshold, resume_threshold)
        VALUES
            (:tenant_id, :shop_id, :is_active,
             :pause_threshold, :resume_threshold)
        ON DUPLICATE KEY UPDATE
            is_active = VALUES(is_active),
            pause_threshold = VALUES(pause_threshold),
            resume_threshold = VALUES(resume_threshold),
            updated_at = NOW()
    """), {
        "tenant_id": tenant_id,
        "shop_id": shop_id,
        "is_active": 1 if req.is_active else 0,
        "pause_threshold": req.pause_threshold,
        "resume_threshold": req.resume_threshold,
    })
    db.commit()
    logger.info(
        f"shop_id={shop_id} 更新库存联动规则 "
        f"active={req.is_active} "
        f"pause={req.pause_threshold} resume={req.resume_threshold}"
    )
    return success(msg="规则已更新")


# ==================== 库存列表 ====================

@router.get("/stocks/{shop_id}")
def get_shop_stocks(
    shop_id: int,
    status: str = Query(None, description="状态筛选: normal/alert/paused"),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """获取店铺SKU库存列表"""
    params = {"shop_id": shop_id}
    where = "WHERE s.shop_id = :shop_id"
    if status in ("normal", "alert", "paused"):
        where += " AND s.status = :status"
        params["status"] = status

    rows = db.execute(text(f"""
        SELECT
            s.id, s.platform_sku_id, s.sku_name,
            s.campaign_id, s.quantity, s.status,
            s.paused_at, s.paused_bid, s.last_synced_at,
            c.name AS campaign_name,
            COALESCE(r.pause_threshold, 10) AS pause_threshold,
            COALESCE(r.resume_threshold, 20) AS resume_threshold
        FROM inventory_platform_stocks s
        JOIN ad_campaigns c ON c.id = s.campaign_id
        LEFT JOIN inventory_linkage_rules r ON r.shop_id = s.shop_id
        {where}
        ORDER BY
            FIELD(s.status, 'paused', 'alert', 'normal'),
            s.quantity ASC
    """), params).fetchall()

    items = [{
        "id": r.id,
        "platform_sku_id": r.platform_sku_id,
        "sku_name": r.sku_name,
        "campaign_id": r.campaign_id,
        "campaign_name": r.campaign_name,
        "quantity": r.quantity,
        "status": r.status,
        "paused_at": r.paused_at.isoformat() if r.paused_at else None,
        "paused_bid": float(r.paused_bid) if r.paused_bid is not None else None,
        "last_synced_at": r.last_synced_at.isoformat() if r.last_synced_at else None,
        "pause_threshold": r.pause_threshold,
        "resume_threshold": r.resume_threshold,
    } for r in rows]

    return success(items)


# ==================== 手动触发检查 ====================

@router.post("/linkage-check/{shop_id}")
async def manual_linkage_check(
    shop_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """手动触发库存联动检查

    流程：
    1. 从Ozon同步平台仓库存
    2. 执行联动检查（按阈值判断pause/resume/alert）
    """
    from app.models.shop import Shop
    from app.services.inventory.linkage_engine import run_linkage_check
    from app.services.inventory.stock_syncer import sync_ozon_platform_stocks

    shop = db.query(Shop).filter(Shop.id == shop_id).first()
    if not shop:
        return error(30001, "店铺不存在")

    try:
        synced = 0
        if shop.platform == "ozon":
            synced = await sync_ozon_platform_stocks(db, shop)

        result = await run_linkage_check(db, shop_id)

        return success({
            "synced_skus": synced,
            "linkage": result,
        }, msg="检查完成")
    except Exception as e:
        logger.error(f"手动库存联动检查失败 shop_id={shop_id}: {e}")
        return error(50001, f"检查失败: {e}")
