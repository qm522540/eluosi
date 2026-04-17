"""关键词统计路由"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_tenant_id
from app.services.keyword_stats.service import (
    summary, sku_detail, trend, negative_suggestions, sync_status,
)
from app.utils.response import success, error

router = APIRouter()


@router.get("/summary")
def keyword_summary(
    shop_id: int = Query(...),
    date_from: str = Query(None),
    date_to: str = Query(None),
    campaign_id: int = Query(None),
    keyword: str = Query(None),
    sort_by: str = Query("spend"),
    sort_order: str = Query("desc"),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """关键词汇总列表（主表格）"""
    result = summary(db, tenant_id, shop_id, date_from, date_to,
                     campaign_id, keyword, sort_by, sort_order, page, size)
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"])


@router.get("/sku-detail")
def keyword_sku_detail(
    shop_id: int = Query(...),
    keyword: str = Query(...),
    date_from: str = Query(None),
    date_to: str = Query(None),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """关键词 SKU 明细（Ozon 展开用）"""
    result = sku_detail(db, tenant_id, shop_id, keyword, date_from, date_to)
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"])


@router.get("/trend")
def keyword_trend(
    shop_id: int = Query(...),
    date_from: str = Query(None),
    date_to: str = Query(None),
    top: int = Query(10, ge=1, le=20),
    metric: str = Query("impressions"),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """趋势数据（折线图）"""
    result = trend(db, tenant_id, shop_id, date_from, date_to, top, metric)
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"])


@router.post("/backfill")
def keyword_backfill(
    shop_id: int = Query(...),
    days: int = Query(90, ge=1, le=90),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """手动回填历史关键词数据"""
    from app.tasks.keyword_stats_task import backfill_keyword_stats
    from app.models.shop import Shop
    shop = db.query(Shop).filter(Shop.id == shop_id, Shop.tenant_id == tenant_id).first()
    if not shop:
        return error(30001, "店铺不存在")
    task = backfill_keyword_stats.delay(shop_id, tenant_id, days)
    chunks = math.ceil(days / 7) if shop.platform == "wb" else 1
    return success({
        "task_id": task.id,
        "msg": f"回填任务已提交，{shop.platform.upper()} 需约 {chunks} 次请求，预计 {chunks * 10}-{chunks * 20} 秒",
    })


@router.get("/negative-suggestions")
def keyword_negative_suggestions(
    shop_id: int = Query(...),
    date_from: str = Query(None),
    date_to: str = Query(None),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """否定关键词建议"""
    result = negative_suggestions(db, tenant_id, shop_id, date_from, date_to)
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"])


@router.get("/sync-status")
def keyword_sync_status(
    shop_id: int = Query(...),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """数据同步状态"""
    result = sync_status(db, tenant_id, shop_id)
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"])


import math
from pydantic import BaseModel, Field
from typing import List


class TranslateKeywordsRequest(BaseModel):
    keywords: List[str] = Field(..., min_length=1, max_length=100)


@router.post("/translate-keywords")
async def translate_keywords(
    req: TranslateKeywordsRequest,
    tenant_id: int = Depends(get_tenant_id),
):
    """批量翻译俄文关键词为中文（Kimi AI，带内存缓存）"""
    from app.services.keyword_stats.translator import translate_keywords_cached
    result = await translate_keywords_cached(req.keywords)
    return success(result)
