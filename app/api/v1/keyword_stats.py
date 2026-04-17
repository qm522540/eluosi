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
async def keyword_campaigns(
    shop_id: int = Query(...),
    keyword: str = Query(...),
    date_from: str = Query(None),
    date_to: str = Query(None),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """查看关键词关联了哪些活动和商品"""
    from app.models.ad import AdCampaign, AdStat
    from app.models.shop import Shop
    from sqlalchemy import text, func as sqlfunc

    date_from, date_to = _default_dates(date_from, date_to)
    params = {"tid": tenant_id, "sid": shop_id, "kw": keyword, "df": date_from, "dt": date_to}

    # 按活动汇总关键词统计
    rows = db.execute(text("""
        SELECT campaign_id, platform_campaign_id,
               SUM(impressions) imp, SUM(clicks) clk, SUM(spend) sp,
               MIN(stat_date) first_seen
        FROM keyword_daily_stats
        WHERE tenant_id=:tid AND shop_id=:sid AND keyword=:kw AND stat_date BETWEEN :df AND :dt
        GROUP BY campaign_id, platform_campaign_id ORDER BY sp DESC
    """), params).fetchall()

    campaigns = []
    shop = db.query(Shop).filter(Shop.id == shop_id).first()

    for r in rows:
        camp = db.query(AdCampaign).filter(AdCampaign.id == r.campaign_id).first()
        entry = {
            "campaign_id": r.campaign_id,
            "platform_campaign_id": r.platform_campaign_id,
            "campaign_name": camp.name if camp else f"活动#{r.campaign_id}",
            "platform": camp.platform if camp else "wb",
            "status": camp.status if camp else "unknown",
            "impressions": int(r.imp or 0),
            "clicks": int(r.clk or 0),
            "spend": float(r.sp or 0),
            "keyword_first_seen": r.first_seen.isoformat() if r.first_seen else None,
            "products": [],
        }

        # WB: 查活动商品 + 屏蔽状态 + 每个商品的广告统计
        if camp and camp.platform == "wb" and shop:
            try:
                from app.services.platform.wb import WBClient
                client = WBClient(shop_id=shop.id, api_key=shop.api_key)
                try:
                    prods = await client.fetch_campaign_products(camp.platform_campaign_id)
                    nm_ids = [int(p.get("sku", 0)) for p in prods if p.get("sku")]
                    # 批量查屏蔽状态
                    excluded = await client.fetch_excluded_keywords(
                        camp.platform_campaign_id, nm_ids,
                    ) if nm_ids else {}
                finally:
                    await client.close()

                # 批量查每个 nm_id 的广告统计（整体，非关键词级）
                nm_stats = {}
                if nm_ids:
                    for sr in db.query(
                        AdStat.ad_group_id,
                        sqlfunc.sum(AdStat.impressions).label("imp"),
                        sqlfunc.sum(AdStat.clicks).label("clk"),
                        sqlfunc.sum(AdStat.spend).label("sp"),
                    ).filter(
                        AdStat.campaign_id == camp.id,
                        AdStat.ad_group_id.in_(nm_ids),
                    ).group_by(AdStat.ad_group_id).all():
                        nm_stats[sr.ad_group_id] = {
                            "impressions": int(sr.imp or 0),
                            "clicks": int(sr.clk or 0),
                            "spend": float(sr.sp or 0),
                        }

                # 批量查 nm_id → SKU(卖家编码) + 中文名
                from app.models.product import PlatformListing, Product
                nm_product_info = {}
                if nm_ids:
                    listing_rows = db.query(
                        PlatformListing.platform_product_id,
                        PlatformListing.product_id,
                    ).filter(
                        PlatformListing.shop_id == shop.id,
                        PlatformListing.platform == "wb",
                        PlatformListing.platform_product_id.in_([str(n) for n in nm_ids]),
                    ).all()
                    pid_map = {r.platform_product_id: r.product_id for r in listing_rows}
                    if pid_map:
                        prod_rows = db.query(
                            Product.id, Product.sku, Product.name_zh,
                        ).filter(Product.id.in_(list(pid_map.values()))).all()
                        prod_info = {r.id: {"sku": r.sku, "name_zh": r.name_zh} for r in prod_rows}
                        for pp_id, prod_id in pid_map.items():
                            info = prod_info.get(prod_id, {})
                            nm_product_info[int(pp_id)] = info

                products = []
                kw_lower = keyword.lower().strip()
                for p in prods:
                    nm = int(p.get("sku", 0))
                    if not nm:
                        continue
                    ex_words = excluded.get(nm, [])
                    is_exc = kw_lower in [w.lower().strip() for w in ex_words]
                    pinfo = nm_product_info.get(nm, {})
                    products.append({
                        "nm_id": nm,
                        "name": p.get("subject_name", ""),
                        "sku": pinfo.get("sku", ""),
                        "name_zh": pinfo.get("name_zh", ""),
                        "is_excluded": is_exc,
                    })
                products.sort(key=lambda x: (x["is_excluded"], x["nm_id"]))
                entry["products"] = products
            except Exception as e:
                logger.warning(f"查活动 {camp.id} 商品失败: {e}")

        campaigns.append(entry)

    return success({"keyword": keyword, "campaigns": campaigns})


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
