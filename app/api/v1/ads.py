"""广告路由"""

from datetime import date, datetime, timedelta, timezone
from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.orm import Session
import io

from pydantic import BaseModel, Field
from app.dependencies import get_db, get_current_user, get_tenant_id, get_owned_shop
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
from app.config import get_settings

settings = get_settings()
router = APIRouter()


# ==================== WB summary 缓存（避免 fullstats v3 限流） ====================

_SUMMARY_CACHE_TTL = 300  # 5 分钟

def _summary_cache_key(advert_id, df: str, dt: str) -> str:
    return f"wb:camp_summary:{advert_id}:{df}:{dt}"

def _get_cached_summary(advert_id, df: str, dt: str):
    """Redis 不可用 / miss 时返回 None，调用方降级回拉 WB"""
    try:
        import redis as redis_lib
        import json
        r = redis_lib.Redis.from_url(settings.REDIS_URL, decode_responses=True)
        raw = r.get(_summary_cache_key(advert_id, df, dt))
        return json.loads(raw) if raw else None
    except Exception:
        return None

def _set_cached_summary(advert_id, df: str, dt: str, summary):
    try:
        import redis as redis_lib
        import json
        r = redis_lib.Redis.from_url(settings.REDIS_URL, decode_responses=True)
        r.setex(_summary_cache_key(advert_id, df, dt), _SUMMARY_CACHE_TTL,
                json.dumps(summary, ensure_ascii=False, default=str))
    except Exception:
        pass


# ==================== WB excluded-keywords 缓存 ====================
# WB get-minus 接口典型 19-23 秒，是 /campaign-keywords 主要瓶颈。
# 屏蔽词列表只在 exclude_keywords / 自动屏蔽 task 跑后才变 → 写后失效模型。

_EXCL_CACHE_TTL = 300  # 5 分钟

def _excl_cache_key(advert_id, nm_id) -> str:
    return f"wb:excl:{advert_id}:{nm_id}"

def _get_cached_excluded(advert_id, nm_id):
    try:
        import redis as redis_lib
        import json
        r = redis_lib.Redis.from_url(settings.REDIS_URL, decode_responses=True)
        raw = r.get(_excl_cache_key(advert_id, nm_id))
        return json.loads(raw) if raw else None
    except Exception:
        return None

def _set_cached_excluded(advert_id, nm_id, words: list):
    try:
        import redis as redis_lib
        import json
        r = redis_lib.Redis.from_url(settings.REDIS_URL, decode_responses=True)
        r.setex(_excl_cache_key(advert_id, nm_id), _EXCL_CACHE_TTL,
                json.dumps(words, ensure_ascii=False))
    except Exception:
        pass

def _invalidate_excluded(advert_id, nm_id):
    """写后失效：exclude_keywords / 自动屏蔽成功后调用"""
    try:
        import redis as redis_lib
        r = redis_lib.Redis.from_url(settings.REDIS_URL, decode_responses=True)
        r.delete(_excl_cache_key(advert_id, nm_id))
    except Exception:
        pass


# ==================== 今日实时汇总缓存 ====================
# 当日数据用户期望"实时"但 WB fullstats 限流 + 几小时延迟，缓存 5 分钟避反复打。
# 用户点"刷新"按钮可绕过缓存（直接清 key）。

_TODAY_CACHE_TTL = 300  # 5 分钟

def _today_cache_key(scope: str, scope_id) -> str:
    return f"wb:today_summary:{scope}:{scope_id}"

def _get_cached_today(scope: str, scope_id):
    try:
        import redis as redis_lib
        import json
        r = redis_lib.Redis.from_url(settings.REDIS_URL, decode_responses=True)
        raw = r.get(_today_cache_key(scope, scope_id))
        return json.loads(raw) if raw else None
    except Exception:
        return None

def _set_cached_today(scope: str, scope_id, data: dict):
    try:
        import redis as redis_lib
        import json
        r = redis_lib.Redis.from_url(settings.REDIS_URL, decode_responses=True)
        r.setex(_today_cache_key(scope, scope_id), _TODAY_CACHE_TTL,
                json.dumps(data, ensure_ascii=False, default=str))
    except Exception:
        pass

def _invalidate_today(scope: str, scope_id):
    try:
        import redis as redis_lib
        r = redis_lib.Redis.from_url(settings.REDIS_URL, decode_responses=True)
        r.delete(_today_cache_key(scope, scope_id))
    except Exception:
        pass


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

    # WB 数据有 ~1 天延迟，今天那格通常是空的；用 [today-7, today-1] 拿满 7 天数据。
    # WB 限制：from 和 to 跨度最多 7 天（差值 ≤ 6 天），否则 400
    span = min(days, 7) - 1
    date_to = _date.today() - _td(days=1)
    date_from = date_to - _td(days=span)

    from app.services.platform.wb import WBClient
    client = WBClient(shop_id=shop.id, api_key=shop.api_key)
    try:
        # 并行拉关键词统计 + 活动汇总 + 屏蔽词
        df = date_from.strftime("%Y-%m-%d")
        dt = date_to.strftime("%Y-%m-%d")
        import asyncio as _aio

        # 活动 summary 是活动级总数据，所有 SKU 共享。每个 SKU 展开都重拉
        # 触发 WB fullstats v3 的 3-5 req/min 限流 → 429。Redis 缓存 5 分钟，
        # 同活动多 SKU 展开走缓存。
        summary = _get_cached_summary(camp.platform_campaign_id, df, dt)
        if summary is None:
            kw_task = client.fetch_campaign_keywords(
                advert_id=camp.platform_campaign_id, date_from=df, date_to=dt)
            summary_task = client.fetch_campaign_summary(
                advert_id=camp.platform_campaign_id, date_from=df, date_to=dt)
            keywords, summary = await _aio.gather(kw_task, summary_task)
            _set_cached_summary(camp.platform_campaign_id, df, dt, summary)
        else:
            keywords = await client.fetch_campaign_keywords(
                advert_id=camp.platform_campaign_id, date_from=df, date_to=dt)

        # 有 nm_id 时拉屏蔽词（先查缓存，WB get-minus 慢 19-23s）
        excluded_map = {}
        if nm_id:
            cached = _get_cached_excluded(camp.platform_campaign_id, nm_id)
            if cached is not None:
                excluded_map = {int(nm_id): cached}
            else:
                excluded_map = await client.fetch_excluded_keywords(
                    advert_id=camp.platform_campaign_id, nm_ids=[nm_id])
                _set_cached_excluded(
                    camp.platform_campaign_id, nm_id,
                    excluded_map.get(int(nm_id), []),
                )
    finally:
        await client.close()

    # 屏蔽词集合（用于交叉标注）
    excluded_set = set()
    excluded_list = []
    if nm_id and excluded_map:
        excluded_list = excluded_map.get(int(nm_id), [])
        excluded_set = {w.lower().strip() for w in excluded_list}

    # 智能屏蔽白名单：(tenant, shop, campaign, nm_id, keyword) 五元组
    protected_set = set()
    if nm_id:
        from app.models.ad import AdKeywordProtected
        protected_rows = db.query(AdKeywordProtected.keyword).filter(
            AdKeywordProtected.tenant_id == tenant_id,
            AdKeywordProtected.shop_id == shop.id,
            AdKeywordProtected.campaign_id == campaign_id,
            AdKeywordProtected.nm_id == int(nm_id),
        ).all()
        protected_set = {r.keyword.lower().strip() for r in protected_rows}

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

        # 交叉标注：该关键词是否已被屏蔽 / 是否在智能屏蔽白名单
        kw_text = (kw.get("keyword") or "").lower().strip()
        kw["is_excluded"] = kw_text in excluded_set if excluded_set else False
        kw["is_protected"] = kw_text in protected_set if protected_set else False

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

    # 先剔除白名单的词（即使前端没过滤，后端兜底）
    from app.models.ad import AdKeywordProtected
    protected_rows = db.query(AdKeywordProtected.keyword).filter(
        AdKeywordProtected.tenant_id == tenant_id,
        AdKeywordProtected.shop_id == shop.id,
        AdKeywordProtected.campaign_id == campaign_id,
        AdKeywordProtected.nm_id == int(req.nm_id),
    ).all()
    protected_lower = {r.keyword.lower().strip() for r in protected_rows}
    requested = [w.strip() for w in req.keywords if w.strip()]
    skipped_protected = [w for w in requested if w.lower() in protected_lower]
    after_white = [w for w in requested if w.lower() not in protected_lower]
    # 后端兜底：剔除含空格短语（WB API 不接受），归入 dropped_invalid
    skipped_phrase = [w for w in after_white if ' ' in w]
    effective = [w for w in after_white if ' ' not in w]

    if not effective:
        return success({
            "campaign_id": campaign_id,
            "nm_id": req.nm_id,
            "added": [],
            "total_excluded": 0,
            "skipped_protected": skipped_protected,
            "dropped_invalid": skipped_phrase,
            "msg": "传入关键词全部为白名单或含空格短语，未屏蔽任何词",
        })

    from app.services.platform.wb import WBClient
    client = WBClient(shop_id=shop.id, api_key=shop.api_key)
    try:
        # 1. 先拉现有屏蔽词
        existing_map = await client.fetch_excluded_keywords(
            advert_id=camp.platform_campaign_id, nm_ids=[req.nm_id])
        existing = set(existing_map.get(int(req.nm_id), []))

        # 2. 合并新词（已剔除白名单）
        new_words = set(effective)
        merged = list(existing | new_words)

        # 3. 全量写入 WB（body 字段名是 norm_queries —— wb.py 客户端已对齐）
        # set_excluded_keywords 内部会自动剔除 WB 拒绝的无效词重试，
        # 返回 dropped_invalid: [...] —— 这些词不会被写入屏蔽列表也不写日志
        result = await client.set_excluded_keywords(
            advert_id=camp.platform_campaign_id,
            nm_id=int(req.nm_id),
            words=merged,
        )
        if not result.get("ok"):
            return error(92011, result.get("error", "WB 屏蔽接口调用失败"))

        # 写后失效：屏蔽词列表已变化，下次 /campaign-keywords 必须重新拉 WB
        _invalidate_excluded(camp.platform_campaign_id, int(req.nm_id))

        dropped_invalid = (result.get("dropped_invalid") or []) + skipped_phrase
        dropped_lower = {w.lower().strip() for w in dropped_invalid}
        # 真实新加入屏蔽的词 = 用户传入 - 白名单 - 短语 - WB 拒绝
        added_effective = [w for w in new_words if w.lower().strip() not in dropped_lower]

        logger.info(
            f"WB 屏蔽关键词成功 advert={camp.platform_campaign_id} "
            f"nm={req.nm_id}: 实际新增{len(added_effective)}个 / 总计{len(merged) - len(dropped_invalid)}个 / "
            f"白名单跳过{len(skipped_protected)}个 / WB拒绝{len(dropped_invalid)}个"
        )

        # 写自动屏蔽日志（source='manual'），仅对真实写入的词
        if added_effective:
            from app.models.ad import AdAutoExcludeLog
            import uuid as _uuid
            from datetime import date as _date, timedelta as _td
            run_id = _uuid.uuid4().hex[:16]
            since = (_date.today() - _td(days=6)).isoformat()
            for w in added_effective:
                avg_daily = db.execute(text("""
                    SELECT AVG(spend) FROM keyword_daily_stats
                    WHERE tenant_id=:tid AND shop_id=:sid AND campaign_id=:cid
                      AND keyword=:kw AND stat_date >= :since
                """), {
                    "tid": tenant_id, "sid": shop.id, "cid": campaign_id,
                    "kw": w, "since": since,
                }).scalar() or 0
                db.add(AdAutoExcludeLog(
                    tenant_id=tenant_id, shop_id=shop.id,
                    campaign_id=campaign_id, nm_id=int(req.nm_id),
                    keyword=w, run_id=run_id,
                    saved_per_day=float(avg_daily),
                    reason="用户手动一键屏蔽",
                    source="manual",
                ))
            db.commit()
    finally:
        await client.close()

    return success({
        "campaign_id": campaign_id,
        "nm_id": req.nm_id,
        "added": added_effective,
        "total_excluded": len(merged) - len(dropped_invalid),
        "skipped_protected": skipped_protected,
        "dropped_invalid": dropped_invalid,
    })


# ==================== 关键词智能屏蔽白名单（A 粒度） ====================

class KeywordProtectedRequest(BaseModel):
    nm_id: int = Field(..., description="WB 商品 nm_id")
    keyword: str = Field(..., min_length=1, max_length=500)


@router.post("/campaign-keywords/{campaign_id}/protected")
def add_protected_keyword(
    campaign_id: int,
    req: KeywordProtectedRequest,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """加入智能屏蔽白名单（幂等：已存在不报错）"""
    from app.models.ad import AdCampaign, AdKeywordProtected
    camp = db.query(AdCampaign).filter(
        AdCampaign.id == campaign_id, AdCampaign.tenant_id == tenant_id,
    ).first()
    if not camp:
        return error(50001, "广告活动不存在")

    kw = req.keyword.strip()
    existing = db.query(AdKeywordProtected).filter(
        AdKeywordProtected.tenant_id == tenant_id,
        AdKeywordProtected.shop_id == camp.shop_id,
        AdKeywordProtected.campaign_id == campaign_id,
        AdKeywordProtected.nm_id == req.nm_id,
        AdKeywordProtected.keyword == kw,
    ).first()
    if existing:
        return success({"id": existing.id, "msg": "已在白名单"})

    row = AdKeywordProtected(
        tenant_id=tenant_id, shop_id=camp.shop_id,
        campaign_id=campaign_id, nm_id=req.nm_id, keyword=kw,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return success({"id": row.id, "msg": "已加入白名单"})


@router.delete("/campaign-keywords/{campaign_id}/protected")
def remove_protected_keyword(
    campaign_id: int,
    req: KeywordProtectedRequest,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """从白名单移除（幂等：不存在也返回 success）"""
    from app.models.ad import AdCampaign, AdKeywordProtected
    camp = db.query(AdCampaign).filter(
        AdCampaign.id == campaign_id, AdCampaign.tenant_id == tenant_id,
    ).first()
    if not camp:
        return error(50001, "广告活动不存在")

    deleted = db.query(AdKeywordProtected).filter(
        AdKeywordProtected.tenant_id == tenant_id,
        AdKeywordProtected.shop_id == camp.shop_id,
        AdKeywordProtected.campaign_id == campaign_id,
        AdKeywordProtected.nm_id == req.nm_id,
        AdKeywordProtected.keyword == req.keyword.strip(),
    ).delete()
    db.commit()
    return success({"deleted": deleted})


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


# ==================== Ozon SKU × 搜索词数据 ====================

@router.get("/ozon-sku-queries")
def ozon_sku_queries(
    sku: str = Query(...),
    days: int = Query(7, ge=1, le=90),
    db: Session = Depends(get_db),
    shop=Depends(get_owned_shop),
):
    """拉某 Ozon SKU 近 N 天的搜索词维度数据

    数据源：product_search_queries（platform='ozon'），与老张的搜索词洞察共用表。
    本地表由 Celery 每日同步（莫斯科 05:30），主动触发用 /sync。
    """
    from datetime import datetime as _dt, timedelta as _td

    if shop.platform != "ozon":
        return error(30001, "店铺非 Ozon")

    cutoff = (_dt.now(timezone.utc).date() - _td(days=days)).isoformat()
    rows = db.execute(text("""
        SELECT query_text AS query, impressions, clicks, add_to_cart, orders, revenue,
               frequency, view_conversion, stat_date, extra
        FROM product_search_queries
        WHERE tenant_id=:tid AND shop_id=:sid AND platform='ozon'
              AND platform_sku_id=:sku AND stat_date >= :cutoff
        ORDER BY stat_date DESC, revenue DESC, orders DESC, clicks DESC
    """), {"tid": shop.tenant_id, "sid": shop.id, "sku": sku, "cutoff": cutoff}).fetchall()

    # 取最新日期那批数据（API 返回的是区间总和，每天拉一次会有多份"区间快照"）
    if rows:
        latest_date = rows[0].stat_date
        rows = [r for r in rows if r.stat_date == latest_date]

    items = []
    for r in rows:
        imp = int(r.impressions or 0)
        clk = int(r.clicks or 0)
        atc = int(r.add_to_cart or 0)
        ords = int(r.orders or 0)
        rev = float(r.revenue or 0)
        items.append({
            "query": r.query,
            "impressions": imp,
            "clicks": clk,
            "ctr": round(clk / imp * 100, 2) if imp > 0 else 0,
            "add_to_cart": atc,
            "atc_rate": round(atc / clk * 100, 2) if clk > 0 else 0,
            "orders": ords,
            "cvr": round(ords / clk * 100, 2) if clk > 0 else 0,
            "revenue": rev,
            "aov": round(rev / ords, 2) if ords > 0 else 0,
            "frequency": int(r.frequency or 0),
            "view_conversion": float(r.view_conversion or 0),
        })

    # 从 extra JSON 取 date_from/date_to（task 写入时存的）
    date_from_iso = date_to_iso = None
    if rows and rows[0].extra:
        import json
        try:
            blob = rows[0].extra if isinstance(rows[0].extra, dict) else json.loads(rows[0].extra)
            date_from_iso = blob.get("date_from")
            date_to_iso = blob.get("date_to")
        except Exception:
            pass

    total_clicks = sum(i["clicks"] for i in items)
    total_orders = sum(i["orders"] for i in items)
    total_revenue = sum(i["revenue"] for i in items)
    return success({
        "shop_id": shop.id, "sku": sku, "days": days,
        "stat_date": rows[0].stat_date.isoformat() if rows else None,
        "date_from": date_from_iso,
        "date_to": date_to_iso,
        "total_queries": len(items),
        "total_clicks": total_clicks,
        "total_orders": total_orders,
        "total_revenue": round(total_revenue, 2),
        "items": items,
    })


@router.post("/ozon-sku-queries/sync")
def ozon_sku_queries_sync(
    days: int = Query(7, ge=1, le=30),
    shop=Depends(get_owned_shop),
):
    """主动触发 Ozon SKU × 搜索词数据同步（"立即同步"按钮）

    异步触发 Celery 任务，前端轮询 /ozon-sku-queries 看是否有新数据。
    """
    if shop.platform != "ozon":
        return error(30001, "店铺非 Ozon")

    from app.tasks.ozon_product_queries_task import sync_ozon_product_queries_for_shop
    task = sync_ozon_product_queries_for_shop.delay(shop.id, shop.tenant_id, days)
    return success({
        "task_id": task.id,
        "msg": f"同步任务已提交，预计 1-3 分钟（取决于商品数量）",
    })


# ==================== 活动汇总指标（基本信息页用）====================

@router.get("/campaign-summary/{campaign_id}")
async def campaign_summary(
    campaign_id: int,
    days: int = Query(7, ge=1, le=30),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """活动汇总指标：曝光/点击/订单/加购/CTR/CPC/ROAS（fullstats v3）"""
    from app.models.ad import AdCampaign
    from app.models.shop import Shop
    from datetime import date as _date, timedelta as _td

    camp = db.query(AdCampaign).filter(
        AdCampaign.id == campaign_id, AdCampaign.tenant_id == tenant_id,
    ).first()
    if not camp:
        return error(50001, "广告活动不存在")
    if camp.platform != "wb":
        return success({"days": days, "available": False, "msg": "暂仅支持 WB"})

    shop = db.query(Shop).filter(Shop.id == camp.shop_id).first()
    if not shop:
        return error(30001, "店铺不存在")

    today = _date.today()
    date_to = today.strftime("%Y-%m-%d")
    date_from = (today - _td(days=days - 1)).strftime("%Y-%m-%d")

    from app.services.platform.wb import WBClient
    client = WBClient(shop_id=shop.id, api_key=shop.api_key)
    try:
        s = await client.fetch_campaign_summary(
            advert_id=camp.platform_campaign_id,
            date_from=date_from, date_to=date_to,
        )
    finally:
        await client.close()

    spend = float(s.get("sum") or 0)
    revenue = float(s.get("sum_price") or 0)
    clicks = int(s.get("clicks") or 0)
    views = int(s.get("views") or 0)
    return success({
        "days": days,
        "date_from": date_from, "date_to": date_to,
        "available": True,
        "views": views,
        "clicks": clicks,
        "ctr": round(clicks / views * 100, 2) if views > 0 else 0,
        "cpc": round(spend / clicks, 2) if clicks > 0 else 0,
        "orders": int(s.get("orders") or 0),
        "atbs": int(s.get("atbs") or 0),
        "cr": round(int(s.get("orders") or 0) / clicks * 100, 2) if clicks > 0 else 0,
        "spend": round(spend, 2),
        "revenue": round(revenue, 2),
        "roas": round(revenue / spend, 2) if spend > 0 else 0,
    })


# ==================== 活动级自动屏蔽托管 ====================

class AutoExcludeToggleRequest(BaseModel):
    enabled: bool


@router.get("/campaign-auto-exclude/{campaign_id}")
def get_auto_exclude_config(
    campaign_id: int,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """活动级自动屏蔽配置 + 累计成果（顶部卡片用）"""
    from app.models.ad import AdCampaign, AdCampaignAutoExclude, AdAutoExcludeLog
    from sqlalchemy import func as sqlfunc

    camp = db.query(AdCampaign).filter(
        AdCampaign.id == campaign_id, AdCampaign.tenant_id == tenant_id,
    ).first()
    if not camp:
        return error(50001, "广告活动不存在")

    cfg = db.query(AdCampaignAutoExclude).filter(
        AdCampaignAutoExclude.tenant_id == tenant_id,
        AdCampaignAutoExclude.campaign_id == campaign_id,
    ).first()

    # 累计：本月已屏蔽词数 + 累计估算节省（按 source 分组）
    from datetime import date as _date
    month_start = _date.today().replace(day=1).isoformat()
    rows = db.execute(text("""
        SELECT source, COUNT(*) cnt, COALESCE(SUM(saved_per_day), 0) saved_per_day
        FROM ad_auto_exclude_log
        WHERE tenant_id=:tid AND campaign_id=:cid AND excluded_at >= :ms
        GROUP BY source
    """), {"tid": tenant_id, "cid": campaign_id, "ms": month_start}).fetchall()
    by_source = {r.source: {"cnt": int(r.cnt), "saved": float(r.saved_per_day)} for r in rows}
    auto_d = by_source.get("auto", {"cnt": 0, "saved": 0})
    manual_d = by_source.get("manual", {"cnt": 0, "saved": 0})
    total_cnt = auto_d["cnt"] + manual_d["cnt"]
    total_saved = auto_d["saved"] + manual_d["saved"]

    return success({
        "campaign_id": campaign_id,
        "enabled": bool(cfg.enabled) if cfg else False,
        "last_run_at": cfg.last_run_at.isoformat() if cfg and cfg.last_run_at else None,
        "last_run_excluded": cfg.last_run_excluded if cfg else 0,
        "last_run_saved_monthly": float(cfg.last_run_saved) if cfg else 0,
        "month_excluded_total": total_cnt,
        "month_saved_estimated": round(total_saved * 30, 2),
        "month_excluded_auto": auto_d["cnt"],
        "month_excluded_manual": manual_d["cnt"],
        "month_saved_auto": round(auto_d["saved"] * 30, 2),
        "month_saved_manual": round(manual_d["saved"] * 30, 2),
    })


@router.put("/campaign-auto-exclude/{campaign_id}")
def toggle_auto_exclude(
    campaign_id: int,
    req: AutoExcludeToggleRequest,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """切换活动级自动屏蔽开关（首次开启会自动创建配置行）"""
    from app.models.ad import AdCampaign, AdCampaignAutoExclude
    camp = db.query(AdCampaign).filter(
        AdCampaign.id == campaign_id, AdCampaign.tenant_id == tenant_id,
    ).first()
    if not camp:
        return error(50001, "广告活动不存在")
    if camp.platform != "wb":
        return error(10002, "自动屏蔽当前仅支持 WB")

    cfg = db.query(AdCampaignAutoExclude).filter(
        AdCampaignAutoExclude.tenant_id == tenant_id,
        AdCampaignAutoExclude.campaign_id == campaign_id,
    ).first()
    if not cfg:
        cfg = AdCampaignAutoExclude(
            tenant_id=tenant_id, shop_id=camp.shop_id,
            campaign_id=campaign_id, enabled=1 if req.enabled else 0,
        )
        db.add(cfg)
    else:
        cfg.enabled = 1 if req.enabled else 0
    db.commit()
    return success({"enabled": bool(cfg.enabled)})


@router.post("/campaign-auto-exclude/{campaign_id}/run")
def run_auto_exclude_now(
    campaign_id: int,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """立即触发一次自动屏蔽（同步等待结果，方便前端 toast 展示）"""
    from app.models.ad import AdCampaign, AdCampaignAutoExclude
    camp = db.query(AdCampaign).filter(
        AdCampaign.id == campaign_id, AdCampaign.tenant_id == tenant_id,
    ).first()
    if not camp:
        return error(50001, "广告活动不存在")
    if camp.platform != "wb":
        return error(10002, "自动屏蔽当前仅支持 WB")

    # 没开关也允许手动跑一次（先建配置 enabled=0 不影响定时任务）
    cfg = db.query(AdCampaignAutoExclude).filter(
        AdCampaignAutoExclude.tenant_id == tenant_id,
        AdCampaignAutoExclude.campaign_id == campaign_id,
    ).first()
    if not cfg:
        cfg = AdCampaignAutoExclude(
            tenant_id=tenant_id, shop_id=camp.shop_id,
            campaign_id=campaign_id, enabled=0,
        )
        db.add(cfg)
        db.commit()

    from app.tasks.ad_auto_exclude_task import auto_exclude_for_campaign
    # 同步执行（task 内部自管 db session），方便前端立刻拿到结果
    result = auto_exclude_for_campaign.apply(
        args=[campaign_id, tenant_id]
    ).get(disable_sync_subtasks=False)
    if result.get("error"):
        return error(92011, result["error"])
    return success(result)


@router.get("/campaign-auto-exclude/{campaign_id}/logs")
def list_auto_exclude_logs(
    campaign_id: int,
    days: int = Query(30, ge=1, le=180),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """活动自动屏蔽日志（详情 Drawer 用）"""
    from app.models.ad import AdCampaign
    camp = db.query(AdCampaign).filter(
        AdCampaign.id == campaign_id, AdCampaign.tenant_id == tenant_id,
    ).first()
    if not camp:
        return error(50001, "广告活动不存在")

    from datetime import date as _date, timedelta as _td
    since = (_date.today() - _td(days=days)).isoformat()
    rows = db.execute(text("""
        SELECT keyword, nm_id, excluded_at, saved_per_day, reason
        FROM ad_auto_exclude_log
        WHERE tenant_id=:tid AND campaign_id=:cid AND excluded_at >= :since
        ORDER BY excluded_at DESC
        LIMIT 500
    """), {"tid": tenant_id, "cid": campaign_id, "since": since}).fetchall()
    return success({
        "items": [{
            "keyword": r.keyword, "nm_id": int(r.nm_id),
            "excluded_at": r.excluded_at.isoformat(),
            "saved_per_day": float(r.saved_per_day),
            "saved_per_month": round(float(r.saved_per_day) * 30, 2),
            "reason": r.reason,
        } for r in rows],
        "total": len(rows),
    })


@router.get("/auto-exclude/summary")
def auto_exclude_summary(
    days: int = Query(30, ge=1, le=180),
    db: Session = Depends(get_db),
    shop=Depends(get_owned_shop),
):
    """店铺级自动屏蔽成果汇总（关键词统计页顶部条用）

    规则 4：手动触发型聚合接口必须按 shop_id 过滤；用户先选店铺再操作。
    """
    since = (datetime.now(timezone.utc).date() - timedelta(days=days)).isoformat()

    # 按 source 分组的总和（限定本店）
    src_rows = db.execute(text("""
        SELECT source, COUNT(*) cnt, COALESCE(SUM(saved_per_day), 0) saved_per_day
        FROM ad_auto_exclude_log
        WHERE tenant_id=:tid AND shop_id=:sid AND excluded_at >= :since
        GROUP BY source
    """), {"tid": shop.tenant_id, "sid": shop.id, "since": since}).fetchall()
    by_source = {r.source: {"cnt": int(r.cnt), "saved": float(r.saved_per_day)} for r in src_rows}
    auto_d = by_source.get("auto", {"cnt": 0, "saved": 0})
    manual_d = by_source.get("manual", {"cnt": 0, "saved": 0})
    total_cnt = auto_d["cnt"] + manual_d["cnt"]
    total_saved = auto_d["saved"] + manual_d["saved"]

    # 按活动展开（JOIN 加 c.tenant_id 兜底，防跨租户 campaign_id 碰撞）
    by_camp = db.execute(text("""
        SELECT l.campaign_id, c.name campaign_name,
               COUNT(*) excluded_cnt, COALESCE(SUM(l.saved_per_day), 0) saved_per_day
        FROM ad_auto_exclude_log l
        JOIN ad_campaigns c ON c.id = l.campaign_id AND c.tenant_id = l.tenant_id
        WHERE l.tenant_id=:tid AND l.shop_id=:sid AND l.excluded_at >= :since
        GROUP BY l.campaign_id, c.name
        ORDER BY saved_per_day DESC
    """), {"tid": shop.tenant_id, "sid": shop.id, "since": since}).fetchall()

    return success({
        "days": days,
        "total_excluded": total_cnt,
        "total_saved_estimated": round(total_saved * 30, 2),
        "auto_excluded": auto_d["cnt"],
        "auto_saved_estimated": round(auto_d["saved"] * 30, 2),
        "manual_excluded": manual_d["cnt"],
        "manual_saved_estimated": round(manual_d["saved"] * 30, 2),
        "by_campaign": [{
            "campaign_id": int(r.campaign_id),
            "campaign_name": r.campaign_name,
            "excluded_count": int(r.excluded_cnt),
            "saved_estimated": round(float(r.saved_per_day) * 30, 2),
        } for r in by_camp],
    })


# ==================== 当日实时汇总 ====================

@router.get("/today-summary/campaign/{campaign_id}")
async def today_summary_campaign(
    campaign_id: int,
    refresh: bool = Query(False, description="true 跳过缓存直接拉平台"),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """活动级当日实时汇总：今日花费 / 订单 / 曝光 / 点击 / CTR / ROAS + 预算余额

    用于商品出价 Tab 顶部条。WB 数据有几小时延迟（早上常空，下午陆续就位）。
    Redis 缓存 5 分钟避反复打 fullstats（限流 3-5 req/min）。
    """
    from app.models.ad import AdCampaign
    from app.models.shop import Shop
    from datetime import date as _date

    camp = db.query(AdCampaign).filter(
        AdCampaign.id == campaign_id, AdCampaign.tenant_id == tenant_id,
    ).first()
    if not camp:
        return error(50001, "广告活动不存在")
    shop = db.query(Shop).filter(Shop.id == camp.shop_id).first()
    if not shop:
        return error(30001, "店铺不存在")

    # 缓存命中
    if not refresh:
        cached = _get_cached_today("camp", campaign_id)
        if cached is not None:
            cached["from_cache"] = True
            return success(cached)

    today_iso = _date.today().isoformat()

    if camp.platform != "wb":
        # Ozon / Yandex 后续接入；先返个空结构让前端渲染
        result = {
            "today_date": today_iso, "platform": camp.platform,
            "spend": 0, "orders": 0, "views": 0, "clicks": 0,
            "atbs": 0, "revenue": 0, "ctr": 0, "cpc": 0, "cr": 0, "roas": 0,
            "budget_remaining": None,
            "msg": "Ozon / Yandex 当日汇总后续接入",
        }
        _set_cached_today("camp", campaign_id, result)
        result["from_cache"] = False
        return success(result)

    from app.services.platform.wb import WBClient
    import asyncio as _aio
    client = WBClient(shop_id=shop.id, api_key=shop.api_key)
    try:
        # 并行：今日 fullstats + 当前预算余额
        async def _fetch_budget():
            try:
                r = await client._request(
                    "GET", "https://advert-api.wildberries.ru/adv/v1/budget",
                    params={"id": int(camp.platform_campaign_id)},
                )
                return r.get("total") if isinstance(r, dict) else None
            except Exception:
                return None

        summary, budget_remaining = await _aio.gather(
            client.fetch_campaign_summary(
                advert_id=camp.platform_campaign_id,
                date_from=today_iso, date_to=today_iso),
            _fetch_budget(),
        )
    finally:
        await client.close()

    spend = float(summary.get("sum") or 0)
    revenue = float(summary.get("sum_price") or 0)
    result = {
        "today_date": today_iso,
        "platform": "wb",
        "spend": round(spend, 2),
        "orders": int(summary.get("orders") or 0),
        "atbs": int(summary.get("atbs") or 0),
        "views": int(summary.get("views") or 0),
        "clicks": int(summary.get("clicks") or 0),
        "ctr": float(summary.get("ctr") or 0),
        "cpc": float(summary.get("cpc") or 0),
        "cr": float(summary.get("cr") or 0),
        "revenue": round(revenue, 2),
        "roas": round(revenue / spend, 2) if spend > 0 else 0,
        "budget_remaining": budget_remaining,
        "from_cache": False,
    }
    _set_cached_today("camp", campaign_id, result)
    return success(result)


@router.get("/today-summary/shop/{shop_id}")
async def today_summary_shop(
    refresh: bool = Query(False),
    db: Session = Depends(get_db),
    shop=Depends(get_owned_shop),
):
    """店铺级当日实时汇总：聚合所有 active WB 活动

    用于关键词统计页顶部条。WB 限速，并发拉所有活动 fullstats 后聚合。
    """
    from app.models.ad import AdCampaign
    from datetime import date as _date
    import asyncio as _aio

    if not refresh:
        cached = _get_cached_today("shop", shop.id)
        if cached is not None:
            cached["from_cache"] = True
            return success(cached)

    today_iso = _date.today().isoformat()
    if shop.platform != "wb":
        result = {
            "today_date": today_iso, "platform": shop.platform,
            "spend": 0, "orders": 0, "views": 0, "clicks": 0,
            "atbs": 0, "revenue": 0, "ctr": 0, "roas": 0,
            "campaign_count": 0, "active_campaign_count": 0,
            "msg": "Ozon / Yandex 当日汇总后续接入",
        }
        _set_cached_today("shop", shop.id, result)
        result["from_cache"] = False
        return success(result)

    # 拉店铺下 active WB 活动
    camps = db.query(AdCampaign).filter(
        AdCampaign.shop_id == shop.id, AdCampaign.tenant_id == shop.tenant_id,
        AdCampaign.platform == "wb", AdCampaign.status == "active",
    ).all()
    if not camps:
        result = {
            "today_date": today_iso, "platform": "wb",
            "spend": 0, "orders": 0, "views": 0, "clicks": 0,
            "atbs": 0, "revenue": 0, "ctr": 0, "roas": 0,
            "campaign_count": 0, "active_campaign_count": 0,
        }
        _set_cached_today("shop", shop.id, result)
        result["from_cache"] = False
        return success(result)

    from app.services.platform.wb import WBClient
    client = WBClient(shop_id=shop.id, api_key=shop.api_key)
    try:
        # WB fullstats v3 单次请求 ids 参数支持多 advert_id 逗号分隔，但限制不明；
        # 保险起见小批 5 个并发，避免触发 429
        async def _fetch_one(camp):
            return await client.fetch_campaign_summary(
                advert_id=camp.platform_campaign_id,
                date_from=today_iso, date_to=today_iso,
            )
        results = []
        BATCH = 5
        for i in range(0, len(camps), BATCH):
            batch = camps[i:i + BATCH]
            results.extend(await _aio.gather(*[_fetch_one(c) for c in batch]))
    finally:
        await client.close()

    spend = sum(float(r.get("sum") or 0) for r in results)
    revenue = sum(float(r.get("sum_price") or 0) for r in results)
    views = sum(int(r.get("views") or 0) for r in results)
    clicks = sum(int(r.get("clicks") or 0) for r in results)
    orders = sum(int(r.get("orders") or 0) for r in results)
    atbs = sum(int(r.get("atbs") or 0) for r in results)

    result = {
        "today_date": today_iso, "platform": "wb",
        "spend": round(spend, 2),
        "revenue": round(revenue, 2),
        "views": views, "clicks": clicks,
        "orders": orders, "atbs": atbs,
        "ctr": round(clicks / views * 100, 2) if views > 0 else 0,
        "roas": round(revenue / spend, 2) if spend > 0 else 0,
        "campaign_count": len(camps),
        "active_campaign_count": len(camps),
        "from_cache": False,
    }
    _set_cached_today("shop", shop.id, result)
    return success(result)
