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


class ExcludeKeywordRequest(BaseModel):
    shop_id: int
    campaign_id: int
    nm_id: int
    keyword: str


@router.get("/keyword-campaigns")
def keyword_campaigns(
    shop_id: int = Query(...),
    keyword: str = Query(...),
    date_from: str = Query(None),
    date_to: str = Query(None),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """查看关键词关联了哪些活动和商品

    返回按活动分组的数据：活动名+商品列表+该活动下这个词的曝光/点击/花费
    """
    from app.models.ad import AdCampaign
    from app.models.keyword_stat import KeywordDailyStat
    from sqlalchemy import text

    date_from, date_to = _default_dates(date_from, date_to)

    sql = text("""
        SELECT kds.campaign_id, kds.platform_campaign_id, kds.sku,
               SUM(kds.impressions) imp, SUM(kds.clicks) clk, SUM(kds.spend) sp,
               ROUND(SUM(kds.clicks)/NULLIF(SUM(kds.impressions),0)*100, 2) ctr
        FROM keyword_daily_stats kds
        WHERE kds.tenant_id = :tid AND kds.shop_id = :sid
          AND kds.keyword = :kw AND kds.stat_date BETWEEN :df AND :dt
        GROUP BY kds.campaign_id, kds.platform_campaign_id, kds.sku
        ORDER BY sp DESC
    """)
    rows = db.execute(sql, {"tid": tenant_id, "sid": shop_id,
                            "kw": keyword, "df": date_from, "dt": date_to}).fetchall()

    # 按活动分组
    camp_map = {}
    for r in rows:
        cid = r.campaign_id
        if cid not in camp_map:
            camp = db.query(AdCampaign).filter(AdCampaign.id == cid).first()
            camp_map[cid] = {
                "campaign_id": cid,
                "platform_campaign_id": r.platform_campaign_id,
                "campaign_name": camp.name if camp else f"活动#{cid}",
                "platform": camp.platform if camp else "wb",
                "impressions": 0, "clicks": 0, "spend": 0,
                "skus": [],
                "products": [],  # 活动下的商品列表（用于选择屏蔽哪个商品）
            }
        entry = camp_map[cid]
        entry["impressions"] += int(r.imp or 0)
        entry["clicks"] += int(r.clk or 0)
        entry["spend"] += float(r.sp or 0)
        if r.sku:
            entry["skus"].append({
                "sku": r.sku,
                "impressions": int(r.imp or 0),
                "clicks": int(r.clk or 0),
                "spend": float(r.sp or 0),
                "ctr": float(r.ctr or 0),
            })

    # 为每个活动查关联商品（WB 屏蔽需要 nm_id，从 campaign_products 拿）
    from app.models.shop import Shop
    for cid, entry in camp_map.items():
        camp = db.query(AdCampaign).filter(AdCampaign.id == cid).first()
        if not camp:
            continue
        shop = db.query(Shop).filter(Shop.id == camp.shop_id).first()
        if not shop:
            continue
        try:
            if camp.platform == "wb":
                from app.services.platform.wb import WBClient
                import asyncio
                async def _get_products_and_excluded(kw_text):
                    client = WBClient(shop_id=shop.id, api_key=shop.api_key)
                    try:
                        prods = await client.fetch_campaign_products(camp.platform_campaign_id)
                        nm_ids = [int(p.get("sku", 0)) for p in prods if p.get("sku")]
                        excluded = await client.fetch_excluded_keywords(
                            camp.platform_campaign_id, nm_ids,
                        ) if nm_ids else {}
                        result = []
                        for p in prods:
                            nm = int(p.get("sku", 0))
                            if not nm:
                                continue
                            ex_words = excluded.get(nm, [])
                            is_exc = kw_text.lower().strip() in [w.lower().strip() for w in ex_words]
                            result.append({
                                "nm_id": nm,
                                "name": p.get("subject_name", ""),
                                "is_excluded": is_exc,
                            })
                        # 未屏蔽排前面
                        result.sort(key=lambda x: (x["is_excluded"], x["nm_id"]))
                        return result
                    finally:
                        await client.close()
                loop = asyncio.new_event_loop()
                try:
                    entry["products"] = loop.run_until_complete(
                        _get_products_and_excluded(keyword)
                    )
                finally:
                    loop.close()
        except Exception as e:
            logger.warning(f"查活动 {cid} 商品失败: {e}")

    return success({
        "keyword": keyword,
        "campaigns": list(camp_map.values()),
    })


@router.post("/exclude-keyword")
async def exclude_keyword(
    req: ExcludeKeywordRequest,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """屏蔽关键词（WB: 追加到 normquery/set-minus 列表）

    注意：WB set-minus 是覆盖模式，所以要先 get 已有列表再追加。
    """
    from app.models.ad import AdCampaign
    from app.models.shop import Shop

    camp = db.query(AdCampaign).filter(
        AdCampaign.id == req.campaign_id, AdCampaign.tenant_id == tenant_id,
    ).first()
    if not camp:
        return error(50001, "活动不存在")

    shop = db.query(Shop).filter(Shop.id == req.shop_id).first()
    if not shop:
        return error(30001, "店铺不存在")

    if camp.platform == "wb":
        from app.services.platform.wb import WBClient
        client = WBClient(shop_id=shop.id, api_key=shop.api_key)
        try:
            # 先拉已有屏蔽词列表
            existing = await client.fetch_excluded_keywords(
                camp.platform_campaign_id, [req.nm_id],
            )
            current_words = existing.get(req.nm_id, [])
            # 追加新词（去重）
            new_word = req.keyword.strip().lower()
            if new_word in [w.lower() for w in current_words]:
                return success({"msg": "该关键词已在屏蔽列表中", "already_excluded": True})
            updated_words = current_words + [req.keyword.strip()]
            result = await client.set_excluded_keywords(
                camp.platform_campaign_id, req.nm_id, updated_words,
            )
            if result.get("ok"):
                return success({
                    "msg": f"已屏蔽「{req.keyword}」",
                    "excluded_count": len(updated_words),
                })
            return error(92011, result.get("error", "屏蔽失败"))
        finally:
            await client.close()
    else:
        return error(10002, f"{camp.platform} 平台暂不支持关键词屏蔽")


def _default_dates(date_from, date_to):
    from datetime import date as d, timedelta
    if not date_to:
        date_to = (d.today() - timedelta(days=1)).isoformat()
    if not date_from:
        date_from = (d.fromisoformat(date_to) - timedelta(days=6)).isoformat()
    return date_from, date_to


@router.post("/translate-keywords")
async def translate_keywords(
    req: TranslateKeywordsRequest,
    tenant_id: int = Depends(get_tenant_id),
):
    """批量翻译俄文关键词为中文（Kimi AI，带内存缓存）"""
    from app.services.keyword_stats.translator import translate_keywords_cached
    result = await translate_keywords_cached(req.keywords)
    return success(result)
