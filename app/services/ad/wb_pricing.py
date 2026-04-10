"""WB平台AI调价建议服务

WB广告特点：活动级别出价（整个活动共用一个CPM）
API限制：无法自动修改出价，只能生成建议+推送企微通知
用户点WB后台直链手动改价。
"""

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.models.ad import AdCampaign, AdStat
from app.models.ai_pricing import AiPricingConfig, AiPricingSuggestion
from app.models.shop import Shop
from app.services.ai.config_resolver import get_effective_config
from app.services.ai.pricing_engine import (
    get_campaign_history_stats, get_bid_history, get_shop_benchmark,
    _call_deepseek, _parse_ai_response, validate_suggestion,
    _build_time_slot_rules,
)
from app.services.ai.time_strategy import get_current_moscow_strategy
from app.services.notification.service import send_wechat_work_bot
from app.utils.logger import setup_logger

logger = setup_logger("ad.wb_pricing")

# WB广告后台直链模板
WB_CAMPAIGN_URL = "https://cmp.wildberries.ru/campaigns/list/active/edit/{campaign_id}"

# WB系统提示词
WB_SYSTEM_PROMPT = "你是俄罗斯Wildberries电商平台广告出价优化专家。WB广告是活动级别CPM出价。请基于数据给出精准的调价建议。"


async def run_wb_ai_analysis(
    db: Session,
    tenant_id: int,
    shop_id: int,
    time_strategy=None,
    moscow_hour: int = None,
) -> dict:
    """WB店铺AI调价分析主函数

    返回活动级别的调价建议列表。
    """
    if time_strategy is None:
        moscow_hour, time_strategy = get_current_moscow_strategy()

    shop = db.query(Shop).filter(
        Shop.id == shop_id,
        Shop.tenant_id == tenant_id,
    ).first()
    if not shop:
        return {"code": 40004, "msg": "店铺不存在"}

    # 1. 获取该店铺所有active的WB广告活动
    campaigns = db.query(AdCampaign).filter(
        AdCampaign.shop_id == shop_id,
        AdCampaign.tenant_id == tenant_id,
        AdCampaign.platform == "wb",
        AdCampaign.status == "active",
    ).all()

    if not campaigns:
        logger.info(f"shop_id={shop_id} 无活跃WB广告活动")
        return {"code": 0, "data": {"analyzed_count": 0, "suggestion_count": 0, "suggestions": []}}

    logger.info(f"WB分析开始: shop_id={shop_id} shop={shop.name} 活动{len(campaigns)}个 时段={time_strategy.name}")

    # 2. 收集三层数据
    campaign_ids = [c.id for c in campaigns]
    history_stats = get_campaign_history_stats(db, campaign_ids)
    shop_benchmark = get_shop_benchmark(db, tenant_id, shop_id)
    bid_history = get_bid_history(db, campaign_ids)

    # 3. 获取今日数据
    today_stats = _get_wb_today_stats(db, tenant_id, campaigns)

    # 4. 获取配置模板（用第一个活动的模板）
    config = get_effective_config(db, tenant_id, campaigns[0])

    # 5. 构建活动明细
    campaign_lines = []
    for c in campaigns:
        stat = today_stats.get(c.id, {})
        spend = stat.get("spend", 0)
        revenue = stat.get("revenue", 0)
        orders = stat.get("orders", 0)
        roas = round(revenue / spend, 2) if spend > 0 else 0
        current_bid = float(c.daily_budget) if c.daily_budget else 0
        campaign_lines.append(
            f"{c.platform_campaign_id} | {c.name[:30]} | {int(current_bid)} | "
            f"{stat.get('clicks', 0)} | {orders} | {spend:.0f} | {revenue:.0f} | {roas}"
        )

    if not campaign_lines:
        return {"code": 0, "data": {"analyzed_count": 0, "suggestion_count": 0, "suggestions": []}}

    campaigns_data = "\n".join(campaign_lines)

    # 6. 构建Prompt
    roas_trend = history_stats.get("roas_trend", [])
    roas_trend_text = " → ".join(map(str, roas_trend)) if roas_trend else "暂无数据"

    total_spend = sum(s.get("spend", 0) for s in today_stats.values())
    total_revenue = sum(s.get("revenue", 0) for s in today_stats.values())
    total_orders = sum(s.get("orders", 0) for s in today_stats.values())
    daily_budget = float(config["daily_budget_limit"])
    budget_pct = round(total_spend / daily_budget * 100, 1) if daily_budget > 0 else 0
    overall_roas = round(total_revenue / total_spend, 2) if total_spend > 0 else 0

    prompt = f"""请基于以下数据，对每个WB广告活动给出CPM出价建议。
WB是活动级别出价，每个活动共用一个CPM值。

【策略模板】
模板：{config['template_name']}（{config['template_type']}）
目标ROAS：{config['target_roas']} | 最低ROAS：{config['min_roas']}
毛利率：{config['gross_margin'] * 100:.0f}% | 最高出价：{config['max_bid']}卢布
单次最大调幅：{config['max_adjust_pct']}%

【今日实时数据】
总花费：{total_spend:.0f}卢布 / 预算：{daily_budget:.0f}卢布（已消耗{budget_pct:.1f}%）
今日ROAS：{overall_roas} | 今日订单：{total_orders}单

【历史数据（{history_stats.get('window_desc', 'N/A')}）】
历史均值ROAS：{history_stats.get('avg_roas', 'N/A')}
ROAS走势：{roas_trend_text}
最高ROAS：{history_stats.get('best_roas', 'N/A')} | 最低ROAS：{history_stats.get('worst_roas', 'N/A')}

【店铺基准】
店铺今日均值ROAS：{shop_benchmark.get('shop_avg_roas_today', 'N/A')}
店铺7天均值ROAS：{shop_benchmark.get('shop_avg_roas_7d', 'N/A')}

【时段策略】
时段：{time_strategy.name}（莫斯科{moscow_hour}点）
调价方向：{time_strategy.bid_adjust_direction}
建议调幅：{time_strategy.bid_adjust_min_pct}%~{time_strategy.bid_adjust_max_pct}%

{_build_time_slot_rules(time_strategy)}

【各活动明细】
{campaigns_data}
（活动ID | 活动名 | 当前CPM | 今日点击 | 今日订单 | 今日花费 | 今日收入 | 今日ROAS）

【决策规则】
1. ROAS持续低于最低ROAS → 降价，decision_basis="history_weighted"
2. ROAS高于目标且预算充足 → 加价抢量，decision_basis="history_weighted"
3. 今日ROAS低但历史均值正常 → 维持不动，不输出
4. 预算消耗>85%且<20:00 → 降价保预算，decision_basis="budget_control"
5. 新活动数据不足 → 参考店铺基准，调幅≤10%，decision_basis="shop_benchmark"

【约束】
最低出价：3卢布 | 最高出价：{config['max_bid']}卢布 | 单次调幅≤{config['max_adjust_pct']}% | 出价取整数

【输出纯JSON】
""" + """{
  "summary": "分析总结",
  "suggestions": [
    {
      "campaign_id": "活动platform_campaign_id",
      "campaign_name": "活动名",
      "current_cpm": 当前出价,
      "suggested_cpm": 建议出价整数,
      "adjust_pct": 调整幅度,
      "reason": "建议理由",
      "current_roas": 当前ROAS,
      "expected_roas": 预期ROAS,
      "decision_basis": "history_weighted|shop_benchmark|budget_control|today_only"
    }
  ]
}
无需调整的活动不要出现在suggestions里。"""

    # 7. 调用DeepSeek
    ai_result = await _call_deepseek(prompt)
    if not ai_result:
        return {"code": 0, "data": {"analyzed_count": len(campaigns), "suggestion_count": 0, "suggestions": []}}

    summary = ai_result.get("summary", "WB分析完成")
    raw_suggestions = ai_result.get("suggestions", [])

    if not raw_suggestions:
        logger.info(f"shop_id={shop_id} WB DeepSeek未返回建议")
        return {"code": 0, "data": {"analyzed_count": len(campaigns), "suggestion_count": 0, "suggestions": [], "summary": summary}}

    # 8. 安全护栏 + 写入数据库
    # 将旧的pending WB建议标记expired
    db.query(AiPricingSuggestion).filter(
        AiPricingSuggestion.tenant_id == tenant_id,
        AiPricingSuggestion.shop_id == shop_id,
        AiPricingSuggestion.status == "pending",
    ).join(AdCampaign, AiPricingSuggestion.campaign_id == AdCampaign.id).filter(
        AdCampaign.platform == "wb",
    ).update({"status": "expired"}, synchronize_session="fetch")
    db.flush()

    saved = []
    for raw in raw_suggestions:
        raw_campaign_id = str(raw.get("campaign_id", ""))
        # 匹配活动
        matched = None
        for c in campaigns:
            if c.platform_campaign_id == raw_campaign_id:
                matched = c
                break
        if not matched:
            logger.warning(f"WB DeepSeek返回的campaign_id={raw_campaign_id}未找到，跳过")
            continue

        current_bid = float(matched.daily_budget) if matched.daily_budget else float(raw.get("current_cpm", 0))
        raw_suggested = float(raw.get("suggested_cpm", current_bid))

        # 护栏校验
        safe_bid = validate_suggestion(raw_suggested, current_bid, config, time_strategy)

        if safe_bid == int(current_bid):
            continue

        actual_pct = round((safe_bid - current_bid) / current_bid * 100, 2) if current_bid > 0 else 0
        wb_url = WB_CAMPAIGN_URL.format(campaign_id=matched.platform_campaign_id)

        suggestion = AiPricingSuggestion(
            tenant_id=tenant_id,
            shop_id=shop_id,
            campaign_id=matched.id,
            product_id=matched.platform_campaign_id,
            product_name=matched.name,
            current_bid=current_bid,
            suggested_bid=safe_bid,
            adjust_pct=actual_pct,
            reason=str(raw.get("reason", ""))[:500],
            current_roas=raw.get("current_roas"),
            expected_roas=raw.get("expected_roas"),
            current_spend=total_spend,
            daily_budget=daily_budget,
            ai_model="deepseek",
            status="pending",
            auto_executed=0,
            expires_at=datetime.now() + timedelta(hours=2),
            decision_basis=raw.get("decision_basis", "today_only"),
            history_avg_roas=history_stats.get("avg_roas", 0),
            data_days=history_stats.get("data_days", 0),
            time_slot=time_strategy.name,
            moscow_hour=moscow_hour,
            template_name=config.get("template_name", ""),
            data_source=raw.get("decision_basis", "today_only"),
            campaign_data_days=history_stats.get("data_days", 0),
            is_new_campaign=1 if history_stats.get("is_new_campaign") else 0,
            shop_avg_roas=shop_benchmark.get("shop_avg_roas_7d", 0),
        )
        db.add(suggestion)
        db.flush()

        saved.append({
            "id": suggestion.id,
            "campaign_id": matched.id,
            "campaign_name": matched.name,
            "platform_campaign_id": matched.platform_campaign_id,
            "current_bid": current_bid,
            "suggested_bid": safe_bid,
            "adjust_pct": actual_pct,
            "reason": raw.get("reason", ""),
            "current_roas": raw.get("current_roas"),
            "expected_roas": raw.get("expected_roas"),
            "decision_basis": raw.get("decision_basis", "today_only"),
            "wb_backend_url": wb_url,
            "data_days": history_stats.get("data_days", 0),
            "template_name": config.get("template_name", ""),
        })

    db.commit()

    logger.info(f"WB调价分析完成 shop_id={shop_id}: 分析{len(campaigns)}个活动, 生成{len(saved)}条建议")

    # 9. 推送企业微信
    if saved:
        try:
            msg = _format_wb_notification(saved, shop.name, summary)
            await send_wechat_work_bot(msg, msg_type="markdown")
        except Exception as e:
            logger.warning(f"WB企业微信通知发送失败: {e}")

    return {
        "code": 0,
        "data": {
            "analyzed_count": len(campaigns),
            "suggestion_count": len(saved),
            "suggestions": saved,
            "summary": summary,
        }
    }


# ==================== 辅助函数 ====================

def _get_wb_today_stats(db: Session, tenant_id: int, campaigns: list) -> dict:
    """获取WB各活动今日统计"""
    from datetime import date
    campaign_ids = [c.id for c in campaigns]
    stats = db.query(AdStat).filter(
        AdStat.tenant_id == tenant_id,
        AdStat.campaign_id.in_(campaign_ids),
        AdStat.stat_date == date.today(),
    ).all()

    result = {}
    for s in stats:
        cid = s.campaign_id
        if cid not in result:
            result[cid] = {"spend": 0, "revenue": 0, "clicks": 0, "orders": 0}
        result[cid]["spend"] += float(s.spend)
        result[cid]["revenue"] += float(s.revenue)
        result[cid]["clicks"] += int(s.clicks)
        result[cid]["orders"] += int(s.orders)
    return result


def _format_wb_notification(suggestions: list, shop_name: str, summary: str) -> str:
    """格式化WB企业微信通知"""
    lines = [
        f"**WB广告调价建议** | {shop_name}",
        f"{datetime.now().strftime('%m-%d %H:%M')}",
        f"{summary}",
        f"共{len(suggestions)}条建议需要手动执行",
        "---",
    ]
    for s in suggestions[:8]:
        arrow = "↑" if s["adjust_pct"] > 0 else "↓"
        lines.append(
            f"{arrow} **{s['campaign_name'][:18]}**\n"
            f"   {int(s['current_bid'])}→{int(s['suggested_bid'])}卢布 "
            f"({s['adjust_pct']:+.1f}%)\n"
            f"   [去WB后台改价]({s['wb_backend_url']})"
        )
    if len(suggestions) > 8:
        lines.append(f"... 还有{len(suggestions) - 8}条，请登录系统查看")
    lines.extend(["---", "WB平台需手动执行，点击链接直达对应活动"])
    return "\n".join(lines)
