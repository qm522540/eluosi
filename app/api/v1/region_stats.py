"""地区销售统计路由"""
import math
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.dependencies import get_db, get_tenant_id
from app.services.region_stats.service import ranking, trend, sync_status
from app.utils.response import success, error

router = APIRouter()


@router.get("/ranking")
def region_ranking(
    shop_id: int = Query(...),
    date_from: str = Query(None),
    date_to: str = Query(None),
    sort_by: str = Query("revenue"),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    r = ranking(db, tenant_id, shop_id, date_from, date_to, sort_by, limit)
    if r["code"] != 0:
        return error(r["code"], r["msg"])
    return success(r["data"])


@router.get("/trend")
def region_trend(
    shop_id: int = Query(...),
    date_from: str = Query(None),
    date_to: str = Query(None),
    top: int = Query(5, ge=1, le=20),
    metric: str = Query("orders"),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    r = trend(db, tenant_id, shop_id, date_from, date_to, top, metric)
    if r["code"] != 0:
        return error(r["code"], r["msg"])
    return success(r["data"])


@router.post("/backfill")
def region_backfill(
    shop_id: int = Query(...),
    days: int = Query(90, ge=1, le=90),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    from app.tasks.region_stats_task import backfill_region_stats
    from app.models.shop import Shop
    shop = db.query(Shop).filter(Shop.id == shop_id, Shop.tenant_id == tenant_id).first()
    if not shop:
        return error(30001, "店铺不存在")
    task = backfill_region_stats.delay(shop_id, tenant_id, days)
    chunks = math.ceil(days / 31) if shop.platform == "wb" else 1
    return success({
        "task_id": task.id,
        "msg": f"地区数据回填已提交，{shop.platform.upper()} 需约 {chunks} 次请求",
    })


@router.get("/sync-status")
def region_sync_status(
    shop_id: int = Query(...),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    r = sync_status(db, tenant_id, shop_id)
    if r["code"] != 0:
        return error(r["code"], r["msg"])
    return success(r["data"])
