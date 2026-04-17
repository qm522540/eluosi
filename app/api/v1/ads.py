"""广告路由"""

from datetime import date, datetime, timedelta, timezone
from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
import io

from pydantic import BaseModel, Field
from app.dependencies import get_db, get_current_user, get_tenant_id
from app.utils.logger import setup_logger

logger = setup_logger("api.ads")
from app.schemas.ad import (
    AdCampaignCreate, AdCampaignUpdate,
    AdGroupCreate, AdGroupUpdate,
    AdKeywordCreate, AdKeywordUpdate, AdKeywordBatchCreate,
    BidOptimizeRequest, AlertConfigUpdate,
    AutoRuleCreate, AutoRuleUpdate,
)
from app.services.ad.service import (
    list_campaigns, get_campaign, create_campaign, update_campaign, delete_campaign,
    list_ad_groups, create_ad_group, update_ad_group, delete_ad_group,
    list_keywords, create_keyword, batch_create_keywords, update_keyword, delete_keyword,
    get_ad_stats, get_ad_summary, get_shop_summary,
    optimize_bids, apply_bid_suggestions,
    export_stats_csv,
    get_roi_alerts,
    get_alert_config, update_alert_config,
    get_platform_comparison, get_campaign_ranking, get_product_roi,
    list_automation_rules, create_automation_rule, update_automation_rule,
    delete_automation_rule, execute_automation_rules,
    get_budget_overview, get_budget_suggestions,
)
from app.utils.response import success, error

router = APIRouter()


# ==================== 广告活动 ====================

@router.get("/campaigns")
def campaign_list(
    shop_id: int = Query(None, description="店铺ID筛选"),
    platform: str = Query(None, description="平台筛选: wb/ozon/yandex"),
    status: str = Query(None, description="状态筛选: active/paused/archived"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """获取广告活动列表"""
    result = list_campaigns(db, tenant_id, shop_id=shop_id, platform=platform,
                            status=status, page=page, page_size=page_size)
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"])


@router.get("/campaigns/{campaign_id}")
def campaign_detail(
    campaign_id: int,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """获取广告活动详情（含广告组）"""
    result = get_campaign(db, campaign_id, tenant_id)
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"])


@router.post("/campaigns")
def campaign_create(
    req: AdCampaignCreate,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """创建广告活动"""
    result = create_campaign(db, tenant_id, req.model_dump())
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"], msg="广告活动创建成功")


@router.put("/campaigns/{campaign_id}")
def campaign_update(
    campaign_id: int,
    req: AdCampaignUpdate,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """更新广告活动（调整预算/状态）"""
    result = update_campaign(db, campaign_id, tenant_id, req.model_dump(exclude_none=True))
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"], msg="广告活动更新成功")


@router.delete("/campaigns/{campaign_id}")
def campaign_delete(
    campaign_id: int,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """删除广告活动（含关联广告组/关键词/统计）"""
    result = delete_campaign(db, campaign_id, tenant_id)
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(msg="广告活动已删除")


# ==================== 广告组 ====================

@router.get("/groups")
def ad_group_list(
    campaign_id: int = Query(..., description="广告活动ID"),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """获取广告组列表"""
    result = list_ad_groups(db, tenant_id, campaign_id)
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"])


@router.post("/groups")
def ad_group_create(
    req: AdGroupCreate,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """创建广告组"""
    result = create_ad_group(db, tenant_id, req.model_dump())
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"], msg="广告组创建成功")


@router.put("/groups/{group_id}")
def ad_group_update(
    group_id: int,
    req: AdGroupUpdate,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """更新广告组"""
    result = update_ad_group(db, group_id, tenant_id, req.model_dump(exclude_none=True))
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"], msg="广告组更新成功")


@router.delete("/groups/{group_id}")
def ad_group_delete(
    group_id: int,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """删除广告组（含关联关键词）"""
    result = delete_ad_group(db, group_id, tenant_id)
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(msg="广告组已删除")


# ==================== 关键词 ====================

@router.get("/keywords")
def keyword_list(
    ad_group_id: int = Query(..., description="广告组ID"),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """获取关键词列表"""
    result = list_keywords(db, tenant_id, ad_group_id)
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"])


@router.post("/keywords")
def keyword_create(
    req: AdKeywordCreate,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """创建关键词"""
    result = create_keyword(db, tenant_id, req.model_dump())
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"], msg="关键词创建成功")


@router.post("/keywords/batch")
def keyword_batch_create(
    req: AdKeywordBatchCreate,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """批量创建关键词"""
    result = batch_create_keywords(db, tenant_id, req.model_dump())
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"], msg=f"成功创建{len(result['data'])}个关键词")


@router.put("/keywords/{keyword_id}")
def keyword_update(
    keyword_id: int,
    req: AdKeywordUpdate,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """更新关键词"""
    result = update_keyword(db, keyword_id, tenant_id, req.model_dump(exclude_none=True))
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"], msg="关键词更新成功")


@router.delete("/keywords/{keyword_id}")
def keyword_delete(
    keyword_id: int,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """删除关键词"""
    result = delete_keyword(db, keyword_id, tenant_id)
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(msg="关键词已删除")


# ==================== 统计 ====================

@router.get("/stats")
def ad_stats(
    start_date: date = Query(..., description="开始日期"),
    end_date: date = Query(..., description="结束日期"),
    shop_id: int = Query(None, description="店铺ID"),
    campaign_id: int = Query(None, description="广告活动ID"),
    platform: str = Query(None, description="平台筛选"),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """查询广告统计数据（按天+平台汇总）"""
    result = get_ad_stats(db, tenant_id, start_date, end_date,
                          shop_id=shop_id, campaign_id=campaign_id, platform=platform)
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"])


@router.get("/summary")
def ad_summary(
    start_date: date = Query(None, description="开始日期(默认今天)"),
    end_date: date = Query(None, description="结束日期(默认今天)"),
    shop_id: int = Query(None, description="店铺ID"),
    platform: str = Query(None, description="平台筛选"),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """获取广告汇总数据（Dashboard用）"""
    today = date.today()
    if not start_date:
        start_date = today
    if not end_date:
        end_date = today
    result = get_ad_summary(db, tenant_id, start_date, end_date,
                            shop_id=shop_id, platform=platform)
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"])


@router.get("/shop-summary/{shop_id}")
def shop_summary(
    shop_id: int,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """店铺今日/昨日/7天汇总（概览卡片用）"""
    result = get_shop_summary(db, tenant_id, shop_id)
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"])


# ==================== 出价优化 ====================

@router.post("/optimize")
def bid_optimize(
    req: BidOptimizeRequest,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """获取出价优化建议"""
    result = optimize_bids(db, tenant_id, req.model_dump())
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"])


@router.post("/optimize/apply")
def bid_apply(
    suggestions: list,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """应用出价优化建议"""
    result = apply_bid_suggestions(db, tenant_id, suggestions)
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"], msg="出价已更新")


# ==================== 数据导出 ====================

@router.get("/export")
def stats_export(
    start_date: date = Query(..., description="开始日期"),
    end_date: date = Query(..., description="结束日期"),
    shop_id: int = Query(None),
    platform: str = Query(None),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """导出广告统计数据为CSV"""
    csv_content = export_stats_csv(db, tenant_id, start_date, end_date,
                                   shop_id=shop_id, platform=platform)
    if not csv_content:
        return error(50002, "导出数据为空")

    # 添加 BOM 以支持 Excel 打开中文
    bom = '\ufeff'
    output = io.BytesIO((bom + csv_content).encode('utf-8'))

    filename = f"ad_stats_{start_date}_{end_date}.csv"
    return StreamingResponse(
        output,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ==================== ROI告警 ====================

@router.get("/alerts")
def alert_list(
    is_read: int = Query(None, description="已读状态: 0=未读, 1=已读"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """获取ROI告警通知列表"""
    result = get_roi_alerts(db, tenant_id, is_read=is_read, page=page, page_size=page_size)
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"])


# ==================== 告警阈值配置 ====================

@router.get("/alert-config")
def get_config(
    tenant_id: int = Depends(get_tenant_id),
):
    """获取告警阈值配置"""
    result = get_alert_config(tenant_id)
    return success(result["data"])


@router.put("/alert-config")
def update_config(
    req: AlertConfigUpdate,
    tenant_id: int = Depends(get_tenant_id),
):
    """更新告警阈值配置"""
    result = update_alert_config(tenant_id, req.model_dump(exclude_none=True))
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"], msg="告警配置已更新")


# ==================== 数据分析 ====================

@router.get("/analysis/platform-comparison")
def platform_comparison(
    start_date: date = Query(..., description="开始日期"),
    end_date: date = Query(..., description="结束日期"),
    shop_id: int = Query(None),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """多平台对比分析"""
    result = get_platform_comparison(db, tenant_id, start_date, end_date, shop_id=shop_id)
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"])


@router.get("/analysis/campaign-ranking")
def campaign_ranking(
    start_date: date = Query(..., description="开始日期"),
    end_date: date = Query(..., description="结束日期"),
    sort_by: str = Query("spend", description="排序字段: spend/revenue/clicks/orders"),
    limit: int = Query(10, ge=1, le=50),
    shop_id: int = Query(None),
    platform: str = Query(None),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """广告活动TOP排名"""
    result = get_campaign_ranking(db, tenant_id, start_date, end_date,
                                  sort_by=sort_by, limit=limit,
                                  shop_id=shop_id, platform=platform)
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"])


@router.get("/analysis/product-roi")
def product_roi(
    start_date: date = Query(..., description="开始日期"),
    end_date: date = Query(..., description="结束日期"),
    shop_id: int = Query(None),
    platform: str = Query(None),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """商品级ROI分析"""
    result = get_product_roi(db, tenant_id, start_date, end_date,
                             shop_id=shop_id, platform=platform)
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"])


# ==================== 自动化规则 ====================

@router.get("/rules")
def rule_list(
    rule_type: str = Query(None, description="规则类型"),
    enabled: int = Query(None, description="启用状态: 0/1"),
    shop_id: int = Query(None, description="店铺ID筛选"),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """获取自动化规则列表"""
    result = list_automation_rules(db, tenant_id, rule_type=rule_type, enabled=enabled, shop_id=shop_id)
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"])


@router.post("/rules")
def rule_create(
    req: AutoRuleCreate,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """创建自动化规则"""
    result = create_automation_rule(db, tenant_id, req.model_dump())
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"], msg="自动化规则创建成功")


@router.put("/rules/{rule_id}")
def rule_update(
    rule_id: int,
    req: AutoRuleUpdate,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """更新自动化规则"""
    result = update_automation_rule(db, rule_id, tenant_id, req.model_dump(exclude_none=True))
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"], msg="自动化规则更新成功")


@router.delete("/rules/{rule_id}")
def rule_delete(
    rule_id: int,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """删除自动化规则"""
    result = delete_automation_rule(db, rule_id, tenant_id)
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(msg="自动化规则已删除")


@router.post("/rules/{rule_id}/restore-bids")
async def rule_restore_bids(
    rule_id: int,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """恢复分时调价规则的原始出价"""
    from app.services.ad.service import restore_auto_bid
    result = await restore_auto_bid(db, rule_id, tenant_id)
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"], msg="出价已恢复")


@router.post("/rules/execute")
async def rules_execute(
    shop_id: int = Query(None, description="店铺ID，传入时只执行该店铺的规则"),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """手动执行启用的自动化规则

    - 传 shop_id 时：只执行该店铺下启用的规则
    - 不传时：执行整个租户下所有启用规则（保留给定时任务用）
    """
    result = await execute_automation_rules(db, tenant_id, shop_id=shop_id)
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"], msg="规则执行完成")


# ==================== 预算管理 ====================

@router.get("/budget/overview")
def budget_overview(
    shop_id: int = Query(None),
    platform: str = Query(None),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """预算消耗概览"""
    result = get_budget_overview(db, tenant_id, shop_id=shop_id, platform=platform)
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"])


def _enrich_products_with_listing_id(
    db, tenant_id: int, shop_id: int, platform: str, products: list
) -> list:
    """为 campaign-products 返回的每条商品挂上 listing_id，
    前端可直接用 listing_id 定位广告组和关键词，无需额外拉 listings 列表。

    - WB: 返回的 sku 是 nm_id，直接匹配 platform_listings.platform_product_id
    - Ozon: 返回的 sku 是 Ozon 的 sku_id（和商家 product_id 不同），
            当前 platform_listings 没有 platform_sku_id 字段，匹配不上，
            返回 listing_id=None（待后续加字段回填）
    """
    from app.models.product import PlatformListing, Product
    if not products:
        return products
    skus = list({str(p.get("sku") or "") for p in products if p.get("sku")})
    if not skus:
        for p in products:
            p["listing_id"] = None
            p["product_code"] = None
        return products
    # 统一按 platform_sku_id 反查 + JOIN products 拿商家编码 (products.sku)
    rows = db.query(
        PlatformListing.id.label("listing_id"),
        PlatformListing.platform_sku_id,
        Product.sku.label("product_code"),
    ).outerjoin(
        Product, Product.id == PlatformListing.product_id
    ).filter(
        PlatformListing.tenant_id == tenant_id,
        PlatformListing.shop_id == shop_id,
        PlatformListing.platform == platform,
        PlatformListing.platform_sku_id.in_(skus),
        PlatformListing.status != "deleted",
    ).all()
    info_map = {
        str(r.platform_sku_id): {"listing_id": r.listing_id, "product_code": r.product_code}
        for r in rows
    }
    for p in products:
        info = info_map.get(str(p.get("sku") or ""), {})
        p["listing_id"] = info.get("listing_id")
        p["product_code"] = info.get("product_code")
    return products


@router.get("/campaign-products/{campaign_id}")
async def campaign_products(
    campaign_id: int,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """获取广告活动关联的商品列表及出价（Ozon / WB）

    每条 product 额外带 listing_id 字段，前端可直接 join
    广告组/关键词，不需要再拉整店 listings 列表。
    """
    from app.models.ad import AdCampaign
    from app.models.shop import Shop

    camp = db.query(AdCampaign).filter(
        AdCampaign.id == campaign_id, AdCampaign.tenant_id == tenant_id
    ).first()
    if not camp:
        return error(50001, "广告活动不存在")

    shop = db.query(Shop).filter(Shop.id == camp.shop_id).first()
    if not shop:
        return error(30001, "店铺不存在")

    if camp.platform == "ozon":
        from app.services.platform.ozon import OzonClient
        client = OzonClient(
            shop_id=shop.id, api_key=shop.api_key, client_id=shop.client_id,
            perf_client_id=shop.perf_client_id or '',
            perf_client_secret=shop.perf_client_secret or '',
        )
        try:
            products = await client.fetch_campaign_products(camp.platform_campaign_id)
            products = _enrich_products_with_listing_id(
                db, tenant_id, shop.id, "ozon", products
            )
            return success(products)
        finally:
            await client.close()
    elif camp.platform == "wb":
        from app.services.platform.wb import WBClient
        client = WBClient(shop_id=shop.id, api_key=shop.api_key)
        try:
            products = await client.fetch_campaign_products(camp.platform_campaign_id)
            products = _enrich_products_with_listing_id(
                db, tenant_id, shop.id, "wb", products
            )
            return success(products)
        finally:
            await client.close()
    else:
        return success([])


@router.get("/campaign-keywords/{campaign_id}")
async def campaign_keywords(
    campaign_id: int,
    days: int = Query(7, ge=1, le=30),
    nm_id: int = Query(None),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """获取广告活动的关键词统计 + 屏蔽词列表

    返回最近 N 天（默认7天）该活动触发的搜索词聚合统计。
    传 nm_id 时同时返回该 SKU 的屏蔽关键词列表（WB auction/unified 支持）。
    """
    from app.models.ad import AdCampaign
    from app.models.shop import Shop
    from datetime import date as _date, timedelta as _td

    camp = db.query(AdCampaign).filter(
        AdCampaign.id == campaign_id, AdCampaign.tenant_id == tenant_id
    ).first()
    if not camp:
        return error(50001, "广告活动不存在")

    shop = db.query(Shop).filter(Shop.id == camp.shop_id).first()
    if not shop:
        return error(30001, "店铺不存在")

    if camp.platform != "wb":
        # Ozon 关键词走不同的 API（未来实现），当前返回空
        return success({"campaign_id": campaign_id, "keywords": [],
                        "msg": "当前仅支持 WB 平台的关键词统计"})

    date_to = _date.today()
    # WB 限制：from 和 to 跨度最多 7 天（差值 ≤ 6 天），否则 400
    date_from = date_to - _td(days=min(days, 7) - 1)

    from app.services.platform.wb import WBClient
    client = WBClient(shop_id=shop.id, api_key=shop.api_key)
    try:
        # 并行拉关键词统计 + 活动汇总 + 屏蔽词
        df = date_from.strftime("%Y-%m-%d")
        dt = date_to.strftime("%Y-%m-%d")
        import asyncio as _aio
        kw_task = client.fetch_campaign_keywords(
            advert_id=camp.platform_campaign_id, date_from=df, date_to=dt)
        summary_task = client.fetch_campaign_summary(
            advert_id=camp.platform_campaign_id, date_from=df, date_to=dt)
        keywords, summary = await _aio.gather(kw_task, summary_task)

        # 有 nm_id 时拉屏蔽词
        excluded_map = {}
        if nm_id:
            excluded_map = await client.fetch_excluded_keywords(
                advert_id=camp.platform_campaign_id, nm_ids=[nm_id])
    finally:
        await client.close()

    # 屏蔽词集合（用于交叉标注）
    excluded_set = set()
    excluded_list = []
    if nm_id and excluded_map:
        excluded_list = excluded_map.get(int(nm_id), [])
        excluded_set = {w.lower().strip() for w in excluded_list}

    # 关键词级订单归因估算：按点击占比分摊活动总订单/营收
    total_clicks = summary.get("clicks", 0)
    total_orders = summary.get("orders", 0)
    total_revenue = summary.get("sum_price", 0)
    total_atbs = summary.get("atbs", 0)

    for kw in keywords:
        kw_clicks = kw.get("clicks", 0)
        if total_clicks > 0 and kw_clicks > 0:
            ratio = kw_clicks / total_clicks
            kw["est_orders"] = round(total_orders * ratio, 1)
            kw["est_revenue"] = round(total_revenue * ratio, 2)
            kw["est_atbs"] = round(total_atbs * ratio, 1)
            kw_sum = kw.get("sum", 0)
            kw["est_roas"] = (
                round(kw["est_revenue"] / kw_sum, 2) if kw_sum > 0 else 0
            )
        else:
            kw["est_orders"] = 0
            kw["est_revenue"] = 0
            kw["est_atbs"] = 0
            kw["est_roas"] = 0

        # 交叉标注：该关键词是否已被屏蔽
        kw_text = (kw.get("keyword") or "").lower().strip()
        kw["is_excluded"] = kw_text in excluded_set if excluded_set else False

    return success({
        "campaign_id": campaign_id,
        "date_from": str(date_from),
        "date_to": str(date_to),
        "days": days,
        "total": len(keywords),
        "summary": summary,
        "keywords": keywords,
        "excluded_keywords": excluded_list,
        "excluded_count": len(excluded_list),
    })


class ExcludeKeywordsRequest(BaseModel):
    nm_id: int = Field(..., description="WB 商品 nm_id")
    keywords: list = Field(..., description="要屏蔽的关键词列表")


@router.post("/campaign-keywords/{campaign_id}/exclude")
async def exclude_keywords(
    campaign_id: int,
    req: ExcludeKeywordsRequest,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """屏蔽关键词：把指定词加入 WB 活动的 minus-phrases

    WB API: POST /adv/v0/normquery/set-minus
    注意：set-minus 是全量覆盖（不是追加），所以需要先 get 现有列表再合并。
    """
    from app.models.ad import AdCampaign
    from app.models.shop import Shop

    camp = db.query(AdCampaign).filter(
        AdCampaign.id == campaign_id, AdCampaign.tenant_id == tenant_id
    ).first()
    if not camp:
        return error(50001, "广告活动不存在")
    if camp.platform != "wb":
        return error(10002, "仅支持 WB 平台")

    shop = db.query(Shop).filter(Shop.id == camp.shop_id).first()
    if not shop:
        return error(30001, "店铺不存在")

    from app.services.platform.wb import WBClient
    client = WBClient(shop_id=shop.id, api_key=shop.api_key)
    try:
        # 1. 先拉现有屏蔽词
        existing_map = await client.fetch_excluded_keywords(
            advert_id=camp.platform_campaign_id, nm_ids=[req.nm_id])
        existing = set(existing_map.get(int(req.nm_id), []))

        # 2. 合并新词
        new_words = set(w.strip() for w in req.keywords if w.strip())
        merged = list(existing | new_words)

        # 3. 全量写入 WB
        url = f"https://advert-api.wildberries.ru/adv/v0/normquery/set-minus"
        resp = await client._request("POST", url, json={
            "advert_id": int(camp.platform_campaign_id),
            "nm_id": int(req.nm_id),
            "norm_queries": merged,
        })

        logger.info(
            f"WB 屏蔽关键词成功 advert={camp.platform_campaign_id} "
            f"nm={req.nm_id}: 新增{len(new_words)}个 总计{len(merged)}个"
        )
    finally:
        await client.close()

    return success({
        "campaign_id": campaign_id,
        "nm_id": req.nm_id,
        "added": list(new_words),
        "total_excluded": len(merged),
    })


class BidUpdateRequest(BaseModel):
    sku: str = Field(..., description="商品SKU")
    bid: str = Field(..., description="新出价")


@router.post("/campaign-products/{campaign_id}/update-bid")
async def update_campaign_bid(
    campaign_id: int,
    req: BidUpdateRequest,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """修改广告活动中商品的出价"""
    from app.models.ad import AdCampaign
    from app.models.shop import Shop

    camp = db.query(AdCampaign).filter(
        AdCampaign.id == campaign_id, AdCampaign.tenant_id == tenant_id
    ).first()
    if not camp:
        return error(50001, "广告活动不存在")

    shop = db.query(Shop).filter(Shop.id == camp.shop_id).first()
    if not shop:
        return error(30001, "店铺不存在")

    sku = req.sku
    new_bid = req.bid

    if camp.platform == "ozon":
        from app.services.platform.ozon import OzonClient
        client = OzonClient(
            shop_id=shop.id, api_key=shop.api_key, client_id=shop.client_id,
            perf_client_id=shop.perf_client_id or '',
            perf_client_secret=shop.perf_client_secret or '',
        )
        try:
            api_result = await client.update_campaign_bid(camp.platform_campaign_id, str(sku), str(new_bid))
            if api_result["ok"]:
                return success(msg="出价修改成功")
            return error(50003, f"出价修改失败: {api_result.get('error', '未知错误')}")
        finally:
            await client.close()
    elif camp.platform == "wb":
        # WB：bid 字段约定传卢布（float 字符串），内部转戈比，同时改 search+recommendations
        try:
            bid_rub = float(new_bid)
        except (ValueError, TypeError):
            return error(10003, "WB 出价必须是有效数字（卢布）")
        from app.services.platform.wb import WBClient
        client = WBClient(shop_id=shop.id, api_key=shop.api_key)
        try:
            api_result = await client.update_campaign_cpm(
                advert_id=camp.platform_campaign_id,
                nm_id=int(sku),
                cpm_rub=bid_rub,
            )
            if api_result["ok"]:
                updated = api_result.get("updated") or []
                skipped = api_result.get("skipped") or []
                msg = f"出价修改成功（已更新 {', '.join(updated)}）"
                if skipped:
                    msg += f"；{', '.join(skipped)} 广告位未启用已跳过"
                return success({"updated": updated, "skipped": skipped}, msg=msg)
            return error(50003, f"出价修改失败: {api_result.get('error', '未知错误')}")
        finally:
            await client.close()
    else:
        return error(10002, "该平台暂不支持出价修改")


@router.get("/campaign-budget/{campaign_id}")
async def campaign_budget(
    campaign_id: int,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """获取广告活动预算余额（实时从平台API获取）"""
    from app.models.ad import AdCampaign
    from app.models.shop import Shop

    camp = db.query(AdCampaign).filter(
        AdCampaign.id == campaign_id, AdCampaign.tenant_id == tenant_id
    ).first()
    if not camp:
        return error(50001, "广告活动不存在")

    shop = db.query(Shop).filter(Shop.id == camp.shop_id).first()
    if not shop:
        return error(30001, "店铺不存在")

    if camp.platform == "wb":
        from app.services.platform.wb import WBClient
        client = WBClient(shop_id=shop.id, api_key=shop.api_key)
        try:
            budget_data = await client._request(
                "GET", "https://advert-api.wildberries.ru/adv/v1/budget",
                params={"id": int(camp.platform_campaign_id)}
            )
            return success(budget_data)
        except Exception as e:
            return error(50002, f"获取预算失败: {str(e)}")
        finally:
            await client.close()
    elif camp.platform == "ozon":
        # Ozon 预算在活动信息中已包含
        return success({
            "total": float(camp.daily_budget) if camp.daily_budget is not None else 0,
            "currency": "RUB",
        })
    else:
        return success({"total": 0, "currency": "RUB"})


@router.get("/bid-logs")
def bid_log_list(
    campaign_id: int = Query(None, description="活动ID筛选"),
    rule_id: int = Query(None, description="规则ID筛选"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """获取出价调整日志"""
    from app.models.ad import AdBidLog
    query = db.query(AdBidLog).filter(AdBidLog.tenant_id == tenant_id)
    if campaign_id:
        query = query.filter(AdBidLog.campaign_id == campaign_id)
    if rule_id:
        query = query.filter(AdBidLog.rule_id == rule_id)
    total = query.count()
    items = query.order_by(AdBidLog.created_at.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()
    return success({
        "items": [{
            "id": log.id,
            "campaign_id": log.campaign_id,
            "campaign_name": log.campaign_name,
            "platform": log.platform,
            "group_name": log.group_name,
            "old_bid": float(log.old_bid),
            "new_bid": float(log.new_bid),
            "change_pct": float(log.change_pct),
            "reason": log.reason,
            "rule_name": log.rule_name,
            "created_at": log.created_at.isoformat() if log.created_at else None,
        } for log in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    })


@router.get("/budget/suggestions")
def budget_suggestions(
    shop_id: int = Query(None),
    platform: str = Query(None),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """预算分配优化建议"""
    result = get_budget_suggestions(db, tenant_id, shop_id=shop_id, platform=platform)
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"])


# ==================== 手动同步 ====================


def _map_ozon_status(ozon_state: str) -> str:
    """
    Ozon活动状态映射
    先打日志确认真实的state值，再完善映射
    """
    mapping = {
        # 常见状态，根据实际返回值补充
        "CAMPAIGN_STATE_RUNNING":   "active",
        "CAMPAIGN_STATE_STOPPED":   "paused",
        "CAMPAIGN_STATE_ARCHIVED":  "archived",
        "CAMPAIGN_STATE_INACTIVE":  "paused",
        "CAMPAIGN_STATE_MODERATION": "paused",
        "CAMPAIGN_STATE_REJECTED":  "paused",
        "CAMPAIGN_STATE_PLANNED":   "draft",
        "CAMPAIGN_STATE_FINISHED":  "archived",
        # 简短格式（部分API版本）
        "RUNNING":   "active",
        "STOPPED":   "paused",
        "ARCHIVED":  "archived",
        "INACTIVE":  "paused",
    }
    result = mapping.get(ozon_state, "paused")
    if ozon_state not in mapping:
        logger.warning(
            f"未知的Ozon活动状态: {ozon_state}，默认映射为paused"
        )
    return result


async def _sync_ozon_campaigns(db, shop) -> tuple:
    """同步Ozon活动列表和状态（精简版：不拉统计/出价）"""
    from app.services.platform.ozon import OzonClient
    from sqlalchemy import text

    client = OzonClient(
        shop_id=shop.id, api_key=shop.api_key, client_id=shop.client_id,
        perf_client_id=getattr(shop, 'perf_client_id', None) or '',
        perf_client_secret=getattr(shop, 'perf_client_secret', None) or '',
    )

    try:
        campaigns_from_api = await client.fetch_ad_campaigns()
    finally:
        await client.close()

    if not campaigns_from_api:
        logger.warning(f"shop_id={shop.id} Ozon返回空活动列表")
        return [], 0

    updated = 0

    for c in campaigns_from_api:
        platform_id = c.get("platform_campaign_id", "")
        if not platform_id:
            continue

        # 跳过Ozon系统级SEARCH_PROMO活动（平台自动创建的"搜索中推广-所有商品"）
        # 这类活动无法手动创建或删除，业务上不需要同步到本地
        if c.get("ad_type") == "search":
            logger.info(
                f"跳过Ozon系统搜索推广活动 {c.get('name')} "
                f"platform_id={platform_id}"
            )
            continue

        # fetch_ad_campaigns已经通过_parse_campaign做了状态映射
        # 但这里我们用原始state再映射一次以打印日志
        # _parse_campaign返回的data里status已经是映射后的值
        mapped_status = c.get("status", "paused")

        logger.info(
            f"活动 {c.get('name')} "
            f"platform_id={platform_id} "
            f"→ 本地状态={mapped_status}"
        )

        result = db.execute(text("""
            INSERT INTO ad_campaigns (
                shop_id, tenant_id, platform,
                platform_campaign_id,
                name, ad_type, payment_type, status,
                daily_budget, created_at
            ) VALUES (
                :shop_id, :tenant_id, 'ozon',
                :platform_id,
                :name, :ad_type, :payment_type, :status,
                :budget, NOW()
            )
            ON DUPLICATE KEY UPDATE
                name          = VALUES(name),
                payment_type  = VALUES(payment_type),
                status        = VALUES(status),
                daily_budget  = VALUES(daily_budget),
                updated_at    = NOW()
        """), {
            "shop_id": shop.id,
            "tenant_id": shop.tenant_id,
            "platform_id": platform_id,
            "name": c.get("name", ""),
            "ad_type": c.get("ad_type", "search"),
            "payment_type": c.get("payment_type", "cpc"),
            "status": mapped_status,
            "budget": min(float(c.get("daily_budget") or 0), 99999999.99),
        })

        if result.rowcount > 0:
            updated += 1

    db.commit()

    # 返回本地campaign对象列表（供后续步骤使用）
    from app.models.ad import AdCampaign
    campaigns = db.query(AdCampaign).filter(
        AdCampaign.shop_id == shop.id,
        AdCampaign.platform == "ozon",
    ).all()

    logger.info(
        f"shop_id={shop.id} Ozon活动同步完成 "
        f"共{len(campaigns_from_api)}个活动 "
        f"更新{updated}条"
    )

    return campaigns, updated


async def _sync_wb_campaigns(db, shop) -> tuple:
    """同步WB活动列表和状态（精简版：不拉统计/出价）"""
    from app.services.platform.wb import WBClient
    from sqlalchemy import text

    client = WBClient(shop_id=shop.id, api_key=shop.api_key)

    try:
        campaigns_from_api = await client.fetch_ad_campaigns()
    finally:
        await client.close()

    if not campaigns_from_api:
        logger.warning(f"shop_id={shop.id} WB返回空活动列表")
        return [], 0

    updated = 0

    for c in campaigns_from_api:
        platform_id = c.get("platform_campaign_id", "")
        if not platform_id:
            continue

        mapped_status = c.get("status", "paused")

        logger.info(
            f"WB活动 {c.get('name')} "
            f"platform_id={platform_id} "
            f"→ 本地状态={mapped_status}"
        )

        result = db.execute(text("""
            INSERT INTO ad_campaigns (
                shop_id, tenant_id, platform,
                platform_campaign_id,
                name, ad_type, payment_type, status,
                daily_budget, created_at
            ) VALUES (
                :shop_id, :tenant_id, 'wb',
                :platform_id,
                :name, :ad_type, :payment_type, :status,
                :budget, NOW()
            )
            ON DUPLICATE KEY UPDATE
                name          = IF(VALUES(name) != '', VALUES(name), name),
                payment_type  = VALUES(payment_type),
                status        = VALUES(status),
                daily_budget  = VALUES(daily_budget),
                updated_at    = NOW()
        """), {
            "shop_id": shop.id,
            "tenant_id": shop.tenant_id,
            "platform_id": platform_id,
            "name": c.get("name", ""),
            "ad_type": c.get("ad_type", "search"),
            "payment_type": c.get("payment_type", "cpm"),
            "status": mapped_status,
            "budget": min(float(c.get("daily_budget") or 0), 99999999.99),
        })

        if result.rowcount > 0:
            updated += 1

    db.commit()

    from app.models.ad import AdCampaign
    campaigns = db.query(AdCampaign).filter(
        AdCampaign.shop_id == shop.id,
        AdCampaign.platform == "wb",
    ).all()

    logger.info(
        f"shop_id={shop.id} WB活动同步完成 "
        f"共{len(campaigns_from_api)}个活动 "
        f"更新{updated}条"
    )

    return campaigns, updated


@router.post("/sync/{shop_id}")
async def manual_sync_shop(
    shop_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """手动同步店铺广告活动列表和状态（不含统计数据）"""
    from app.models.shop import Shop
    from sqlalchemy import text

    shop = db.query(Shop).filter(Shop.id == shop_id).first()
    if not shop:
        raise HTTPException(status_code=404, detail="店铺不存在")

    try:
        if shop.platform == "ozon":
            _, updated = await _sync_ozon_campaigns(db, shop)
        elif shop.platform == "wb":
            _, updated = await _sync_wb_campaigns(db, shop)
        else:
            updated = 0

        # 更新同步时间（用 Python tz-aware UTC，不依赖 MySQL NOW() 的服务器时区）
        now_utc = datetime.now(timezone.utc)
        db.execute(text("""
            INSERT INTO shop_data_init_status
                (shop_id, tenant_id, last_sync_at)
            VALUES (:shop_id, :tenant_id, :now_utc)
            ON DUPLICATE KEY UPDATE
                last_sync_at = :now_utc
        """), {
            "shop_id": shop_id,
            "tenant_id": shop.tenant_id,
            "now_utc": now_utc,
        })
        db.commit()

        return {
            "code": 0,
            "data": {"updated_campaigns": updated},
        }

    except Exception as e:
        logger.error(f"同步失败 shop_id={shop_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
