"""广告路由"""

from datetime import date, timedelta
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
import io

from app.dependencies import get_db, get_current_user, get_tenant_id
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
    get_ad_stats, get_ad_summary,
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
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """获取自动化规则列表"""
    result = list_automation_rules(db, tenant_id, rule_type=rule_type, enabled=enabled)
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


@router.post("/rules/execute")
def rules_execute(
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """手动执行所有启用的自动化规则"""
    result = execute_automation_rules(db, tenant_id)
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
