"""AI智能调价引擎

核心职责：
1. 读取品类配置 + 当日广告数据 + Ozon实时出价
2. 构建Prompt调用DeepSeek分析
3. 安全护栏校验
4. 写入ai_pricing_suggestions表
"""

import json
import asyncio
from datetime import datetime, date, timedelta
from typing import Optional, List

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.ai_pricing import AiPricingConfig, AiPricingSuggestion
from app.models.ad import AdCampaign, AdStat
from app.models.shop import Shop
from app.services.ai.deepseek import DeepSeekClient
from app.services.platform.ozon import OzonClient
from app.utils.logger import setup_logger

logger = setup_logger("ai.pricing_engine")
settings = get_settings()

# 莫斯科时区偏移 UTC+3
MOSCOW_UTC_OFFSET = 3

# Ozon Performance API 出价单位：纳卢布（1卢布 = 1,000,000纳卢布）
OZON_BID_UNIT = 1_000_000


def _get_moscow_hour() -> int:
    """获取当前莫斯科时间的小时"""
    from app.services.ai.time_strategy import get_current_moscow_hour
    return get_current_moscow_hour()


def _build_time_slot_rules(strategy) -> str:
    """根据时段策略生成Prompt中的出价规则文本"""
    if strategy.bid_adjust_direction == "up":
        return f"""【时段出价规则——高峰期加价】
- 当前是流量高峰期，核心目标是抢曝光抢订单
- ROAS高于（目标ROAS × {strategy.target_roas_multiplier}）的商品，主动加价{strategy.bid_adjust_min_pct}%-{strategy.bid_adjust_max_pct}%
- 即使ROAS略低于目标，只要高于最低ROAS，也可维持或小幅加价
- 预算充足时优先保证曝光，不要因为轻微ROAS问题降价
- 加价幅度：流量好的商品加{strategy.bid_adjust_max_pct}%，一般商品加{strategy.bid_adjust_min_pct}%"""
    elif strategy.bid_adjust_direction == "down":
        return f"""【时段出价规则——低谷期降价】
- 当前是深夜低谷期，核心目标是节省预算留给高峰期
- 所有商品统一降价{strategy.bid_adjust_min_pct}%-{strategy.bid_adjust_max_pct}%（相对于正常出价）
- 只有ROAS极高（>目标ROAS×2）且订单持续的商品可以少降一点
- 降价后如果ROAS仍低于（目标ROAS×{strategy.target_roas_multiplier}），建议暂停该商品广告
- 这个时段宁可少曝光，不要浪费预算"""
    else:
        return f"""【时段出价规则——平稳期优化】
- 当前是平稳过渡期，以ROI最优为核心目标
- ROAS低于目标的商品适度降价，ROAS高的商品维持或小幅加价
- 调整幅度保持温和，不超过{strategy.bid_adjust_max_pct}%
- 重点关注预算消耗节奏，避免高峰期前预算耗尽"""


def _build_ozon_client(shop: Shop) -> OzonClient:
    """从shop构建OzonClient"""
    return OzonClient(
        shop_id=shop.id,
        api_key=shop.api_key,
        client_id=shop.client_id,
        perf_client_id=getattr(shop, 'perf_client_id', None) or '',
        perf_client_secret=getattr(shop, 'perf_client_secret', None) or '',
    )


# ==================== Prompt模板 ====================

PRICING_SYSTEM_PROMPT = "你是俄罗斯电商Ozon平台的广告出价优化专家。请基于完整的历史数据和实时数据给出精准的调价建议。"


# ==================== 历史数据查询 ====================

def get_campaign_history_stats(db: Session, campaign_ids: List[int]) -> dict:
    """动态窗口采集活动历史数据（7-21天）

    数据充足用21天，一般用14天，不足用7天。
    自动排除大促异常数据。
    """
    twenty_one_ago = date.today() - timedelta(days=21)

    try:
        stats = db.query(AdStat).filter(
            AdStat.campaign_id.in_(campaign_ids),
            AdStat.stat_date >= twenty_one_ago,
            AdStat.stat_date < date.today(),
        ).all()

        if not stats:
            return {
                "is_new_campaign": True, "data_days": 0, "window_desc": "无数据",
                "avg_roas": 0, "avg_daily_spend": 0, "roas_trend": [],
                "total_orders": 0, "best_roas": 0, "worst_roas": 0,
                "has_promo_data": False, "promo_avg_roas": None,
                "note": "新活动，暂无历史数据，使用店铺基准",
            }

        # 按天汇总，区分正常/大促
        daily_normal = {}
        daily_promo = {}
        for s in stats:
            d = str(s.stat_date)
            is_promo = _is_promo_date(s.stat_date)
            target = daily_promo if is_promo else daily_normal
            if d not in target:
                target[d] = {"spend": 0, "revenue": 0, "clicks": 0, "orders": 0}
            target[d]["spend"] += float(s.spend)
            target[d]["revenue"] += float(s.revenue)
            target[d]["clicks"] += int(s.clicks)
            target[d]["orders"] += int(s.orders)

        data_days = len(daily_normal)
        is_new = data_days < 7

        if data_days == 0:
            return {
                "is_new_campaign": True, "data_days": 0, "window_desc": "无常规数据",
                "avg_roas": 0, "avg_daily_spend": 0, "roas_trend": [],
                "total_orders": 0, "best_roas": 0, "worst_roas": 0,
                "has_promo_data": len(daily_promo) > 0, "promo_avg_roas": None,
                "note": "新活动",
            }

        # 动态窗口
        sorted_days = sorted(daily_normal.keys())
        if data_days >= 14:
            use_days = sorted_days[-21:]
            window_desc = "近21天"
        elif data_days >= 7:
            use_days = sorted_days[-14:]
            window_desc = "近14天"
        else:
            use_days = sorted_days
            window_desc = f"近{data_days}天（数据有限）"

        roas_list = []
        total_spend = 0
        total_orders = 0
        for d in use_days:
            v = daily_normal[d]
            roas_list.append(round(v["revenue"] / v["spend"], 2) if v["spend"] > 0 else 0)
            total_spend += v["spend"]
            total_orders += v["orders"]

        # 大促数据
        promo_roas = None
        if daily_promo:
            promo_spends = [v["spend"] for v in daily_promo.values()]
            promo_revs = [v["revenue"] for v in daily_promo.values()]
            ts, tr = sum(promo_spends), sum(promo_revs)
            promo_roas = round(tr / ts, 2) if ts > 0 else None

        n = len(use_days)
        return {
            "is_new_campaign": is_new,
            "data_days": data_days,
            "window_desc": window_desc,
            "avg_roas": round(sum(roas_list) / n, 2) if n > 0 else 0,
            "avg_daily_spend": round(total_spend / n, 2) if n > 0 else 0,
            "roas_trend": roas_list[-7:],
            "total_orders": total_orders,
            "best_roas": round(max(roas_list), 2) if roas_list else 0,
            "worst_roas": round(min(roas_list), 2) if roas_list else 0,
            "has_promo_data": len(daily_promo) > 0,
            "promo_avg_roas": promo_roas,
        }
    except Exception as e:
        logger.error(f"查询历史数据失败: {e}")
        return {"is_new_campaign": True, "data_days": 0, "roas_trend": [], "avg_roas": 0}


# 大促日期列表（排除异常数据）
_PROMO_RANGES = [("03-06", "03-10"), ("12-28", "12-31"), ("01-01", "01-05")]

def _is_promo_date(d) -> bool:
    """判断是否为大促日期"""
    md = d.strftime("%m-%d") if hasattr(d, 'strftime') else str(d)[5:10]
    for start, end in _PROMO_RANGES:
        if start <= md <= end:
            return True
    return False


def get_bid_history(db: Session, campaign_ids: List[int]) -> dict:
    """从ad_bid_logs表查询历史调价记录"""
    from app.models.ad import AdBidLog

    thirty_days_ago = datetime.now() - timedelta(days=30)

    try:
        logs = db.query(AdBidLog).filter(
            AdBidLog.campaign_id.in_(campaign_ids),
            AdBidLog.created_at >= thirty_days_ago,
        ).order_by(AdBidLog.created_at.desc()).limit(20).all()

        if not logs:
            return {
                "recent_bids": [], "avg_bid_30d": 0,
                "bid_change_count": 0, "last_adjust_time": None,
                "last_adjust_direction": "none",
            }

        all_bids = [float(l.new_bid) for l in logs]
        last = logs[0]
        direction = "up" if float(last.new_bid) > float(last.old_bid) else (
            "down" if float(last.new_bid) < float(last.old_bid) else "none"
        )

        return {
            "recent_bids": [round(b) for b in all_bids[:5]],
            "avg_bid_30d": round(sum(all_bids) / len(all_bids), 2),
            "bid_change_count": len(logs),
            "last_adjust_time": last.created_at.strftime("%Y-%m-%d %H:%M"),
            "last_adjust_direction": direction,
        }
    except Exception as e:
        logger.error(f"查询出价历史失败: {e}")
        return {"recent_bids": [], "avg_bid_30d": 0, "bid_change_count": 0}


def get_shop_benchmark(db: Session, tenant_id: int, shop_id: int) -> dict:
    """查询店铺整体ROAS基准（今日+7天）"""
    today_date = date.today()
    seven_days_ago = today_date - timedelta(days=7)

    try:
        # 今日数据
        today_stats = db.query(AdStat).filter(
            AdStat.tenant_id == tenant_id,
            AdStat.stat_date == today_date,
        ).join(AdCampaign, AdStat.campaign_id == AdCampaign.id).filter(
            AdCampaign.shop_id == shop_id,
        ).all()

        today_spend = sum(float(s.spend) for s in today_stats)
        today_revenue = sum(float(s.revenue) for s in today_stats)
        campaign_roas = {}
        for s in today_stats:
            cid = s.campaign_id
            if cid not in campaign_roas:
                campaign_roas[cid] = {"spend": 0, "revenue": 0}
            campaign_roas[cid]["spend"] += float(s.spend)
            campaign_roas[cid]["revenue"] += float(s.revenue)

        active_count = len([c for c in campaign_roas.values() if c["spend"] > 0])
        roas_values = [c["revenue"] / c["spend"] for c in campaign_roas.values() if c["spend"] > 0]

        # 7天数据
        week_stats = db.query(AdStat).filter(
            AdStat.tenant_id == tenant_id,
            AdStat.stat_date >= seven_days_ago,
            AdStat.stat_date <= today_date,
        ).join(AdCampaign, AdStat.campaign_id == AdCampaign.id).filter(
            AdCampaign.shop_id == shop_id,
        ).all()

        week_spend = sum(float(s.spend) for s in week_stats)
        week_revenue = sum(float(s.revenue) for s in week_stats)

        return {
            "shop_avg_roas_today": round(today_revenue / today_spend, 2) if today_spend > 0 else 0,
            "shop_avg_roas_7d": round(week_revenue / week_spend, 2) if week_spend > 0 else 0,
            "top_performer_roas": round(max(roas_values), 2) if roas_values else 0,
            "active_campaigns": active_count,
        }
    except Exception as e:
        logger.error(f"查询店铺基准失败 shop_id={shop_id}: {e}")
        return {"shop_avg_roas_today": 0, "shop_avg_roas_7d": 0, "top_performer_roas": 0, "active_campaigns": 0}


# ==================== 安全护栏 ====================

def validate_suggestion(suggested_bid: float, current_bid: float, config, time_strategy=None) -> int:
    """安全护栏校验，返回校验后的整数出价。config可以是dict或ORM对象。"""
    _get = lambda k: float(config[k]) if isinstance(config, dict) else float(getattr(config, k))
    min_bid = _get("min_bid")
    max_bid = _get("max_bid")
    max_adjust_pct = _get("max_adjust_pct")
    # 时段策略有独立的单次最大调幅限制，取两者较小值
    if time_strategy and hasattr(time_strategy, 'max_single_change_pct'):
        max_adjust_pct = min(max_adjust_pct, time_strategy.max_single_change_pct)

    # 1. 最低出价检查
    suggested_bid = max(suggested_bid, min_bid)
    # 2. 最高出价检查
    suggested_bid = min(suggested_bid, max_bid)
    # 3. 单次调幅检查
    max_change = current_bid * max_adjust_pct / 100
    suggested_bid = max(current_bid - max_change,
                        min(current_bid + max_change, suggested_bid))
    # 4. 取整（Ozon要求整数卢布）
    suggested_bid = round(suggested_bid)
    # 5. 再次确保不低于最低出价
    suggested_bid = max(suggested_bid, int(min_bid))

    return suggested_bid


# ==================== 核心引擎 ====================

async def run_pricing_analysis(
    db: Session,
    tenant_id: int,
    shop: Shop,
    campaign_ids: Optional[List[int]] = None,
    time_strategy=None,
    moscow_hour: int = None,
) -> dict:
    """对一个店铺执行AI调价分析

    Returns:
        {
            "analyzed_count": int,
            "suggestion_count": int,
            "suggestions": [dict],
            "summary": str,
        }
    """
    # 1. 获取活跃广告活动（配置在后面按活动解析）
    from app.services.ai.config_resolver import get_effective_config

    # 2. 获取活跃广告活动
    campaign_query = db.query(AdCampaign).filter(
        AdCampaign.tenant_id == tenant_id,
        AdCampaign.shop_id == shop.id,
        AdCampaign.status == "active",
        AdCampaign.platform == "ozon",
    )
    if campaign_ids:
        campaign_query = campaign_query.filter(AdCampaign.id.in_(campaign_ids))
    campaigns = campaign_query.all()

    if not campaigns:
        logger.info(f"shop_id={shop.id} 无活跃Ozon广告活动")
        return {"analyzed_count": 0, "suggestion_count": 0, "suggestions": [], "summary": "无活跃广告活动"}

    # 2.5 解析配置（用第一个活动的模板，后续可按活动差异化）
    config = get_effective_config(db, tenant_id, campaigns[0])

    # 3. 获取今日统计数据
    today = date.today()
    stats_map = _get_today_stats(db, tenant_id, campaigns, today)

    # 4. 获取Ozon实时出价
    ozon_client = _build_ozon_client(shop)
    products_bids = {}
    for campaign in campaigns:
        try:
            products = await ozon_client.fetch_campaign_products(campaign.platform_campaign_id)
            for p in products:
                sku = str(p.get("sku", ""))
                if sku:
                    raw_bid = float(p.get("bid", 0))
                    bid_rub = raw_bid / OZON_BID_UNIT  # 纳卢布→卢布
                    products_bids[f"{campaign.id}_{sku}"] = {
                        "sku": sku,
                        "bid": bid_rub,
                        "bid_raw": raw_bid,  # 保留原始值供回写
                        "name": p.get("title", "") or p.get("name", "") or sku,
                        "campaign_id": campaign.id,
                        "platform_campaign_id": campaign.platform_campaign_id,
                    }
        except Exception as e:
            logger.error(f"获取活动 {campaign.platform_campaign_id} 商品出价失败: {e}")

    if not products_bids:
        logger.warning(f"shop_id={shop.id} 未获取到商品出价数据")
        return {"analyzed_count": len(campaigns), "suggestion_count": 0, "suggestions": [], "summary": "未获取到商品出价"}

    # 4.5 商品图片（Ozon Seller API当前不可用，暂置空，恢复后补充）
    image_map = {}

    # 5. 收集历史数据（顺序查询，Session非线程安全不可并发）
    campaign_ids_list = [c.id for c in campaigns]

    try:
        history_stats = get_campaign_history_stats(db, campaign_ids_list)
    except Exception as e:
        logger.warning(f"历史数据查询失败: {e}")
        history_stats = {"avg_roas": 0, "data_days": 0, "roas_trend": []}

    try:
        bid_history = get_bid_history(db, campaign_ids_list)
    except Exception as e:
        logger.warning(f"出价历史查询失败: {e}")
        bid_history = {"recent_bids": [], "avg_bid_30d": 0, "bid_change_count": 0}

    try:
        shop_benchmark = get_shop_benchmark(db, tenant_id, shop.id)
    except Exception as e:
        logger.warning(f"店铺基准查询失败: {e}")
        shop_benchmark = {"shop_avg_roas_today": 0, "shop_avg_roas_7d": 0}

    logger.info(
        f"AI调价数据收集完成 shop_id={shop.id}: "
        f"历史{history_stats.get('data_days', 0)}天数据 "
        f"7天均值ROAS={history_stats.get('avg_roas', 0)} "
        f"调价记录{bid_history.get('bid_change_count', 0)}条"
    )

    # 6. 构建Prompt数据
    total_spend = sum(s.get("spend", 0) for s in stats_map.values())
    total_revenue = sum(s.get("revenue", 0) for s in stats_map.values())
    total_orders = sum(s.get("orders", 0) for s in stats_map.values())
    daily_budget = float(config["daily_budget_limit"])
    budget_pct = round(total_spend / daily_budget * 100, 1) if daily_budget > 0 else 0
    overall_roas = round(total_revenue / total_spend, 2) if total_spend > 0 else 0
    if moscow_hour is None:
        moscow_hour = _get_moscow_hour()

    # 获取时段策略（如果没传入）
    if time_strategy is None:
        from app.services.ai.time_strategy import get_strategy_for_hour
        time_strategy = get_strategy_for_hour(moscow_hour)

    # 构建商品明细表
    products_lines = []
    for key, pb in products_bids.items():
        campaign_id = pb["campaign_id"]
        stat = stats_map.get(campaign_id, {})
        clicks = stat.get("clicks", 0)
        orders = stat.get("orders", 0)
        spend = stat.get("spend", 0)
        revenue = stat.get("revenue", 0)
        prod_roas = round(revenue / spend, 2) if spend > 0 else 0
        products_lines.append(
            f"{pb['sku']} | {pb['name'][:30]} | {int(pb['bid'])} | {clicks} | {orders} | {spend:.0f} | {revenue:.0f} | {prod_roas}"
        )

    if not products_lines:
        return {"analyzed_count": len(campaigns), "suggestion_count": 0, "suggestions": [], "summary": "无商品数据"}

    products_data = "\n".join(products_lines)

    # 冷启动/大促提示
    cold_start_note = ""
    if history_stats.get("is_new_campaign"):
        cold_start_note = f"""
!! 新活动冷启动提示：该活动历史数据不足7天（当前{history_stats.get('data_days', 0)}天），
请以店铺整体基准为主要参考，调价幅度控制在10%以内，标注 decision_basis = "shop_benchmark"
"""
    promo_note = ""
    if history_stats.get("has_promo_data"):
        promo_note = f"注意：历史数据中包含大促期间数据（已排除在均值计算外），大促ROAS={history_stats.get('promo_avg_roas', 'N/A')}"

    budget_note = "不设预算上限（激进冲量模板）" if config.get("no_budget_limit") else f"日预算上限：{daily_budget:.0f}卢布"

    # ROAS趋势文本
    roas_trend = history_stats.get("roas_trend", [])
    roas_trend_text = " → ".join(map(str, roas_trend)) if roas_trend else "暂无数据"
    recent_bids = bid_history.get("recent_bids", [])
    recent_bids_text = " → ".join(map(str, recent_bids)) if recent_bids else "暂无记录"

    prompt = f"""请基于以下三层数据，对每个商品给出调价建议。
{cold_start_note}{promo_note}

【当前策略模板】
模板名称：{config['template_name']}（{config['template_type']}）
模板说明：{config.get('description', '')}
目标ROAS：{config['target_roas']}
最低ROAS：{config['min_roas']}（低于此值必须降价或暂停）
毛利率：{config['gross_margin'] * 100:.0f}%
{budget_note}
最高出价：{config['max_bid']}卢布
单次最大调幅：{config['max_adjust_pct']}%

【第一层：活动历史数据（权重60%）】
数据窗口：{history_stats.get('window_desc', 'N/A')}
历史平均ROAS：{history_stats.get('avg_roas', 'N/A')}
ROAS走势（近7天）：{roas_trend_text}
历史最高ROAS：{history_stats.get('best_roas', 'N/A')}
历史最低ROAS：{history_stats.get('worst_roas', 'N/A')}
日均花费：{history_stats.get('avg_daily_spend', 'N/A')}卢布
历史总订单：{history_stats.get('total_orders', 0)}单
有效数据天数：{history_stats.get('data_days', 0)}天

【第二层：店铺整体基准（权重30%）】
店铺今日平均ROAS：{shop_benchmark.get('shop_avg_roas_today', 'N/A')}
店铺7天平均ROAS：{shop_benchmark.get('shop_avg_roas_7d', 'N/A')}
今日最佳商品ROAS：{shop_benchmark.get('top_performer_roas', 'N/A')}
今日活跃广告数：{shop_benchmark.get('active_campaigns', 0)}个

【今日实时数据】
总花费：{total_spend:.0f}卢布 / 预算：{daily_budget:.0f}卢布（已消耗{budget_pct:.1f}%）
今日ROAS：{overall_roas}
今日订单：{total_orders}单
当前莫斯科时间：{moscow_hour}点

【时段策略】
时段：{time_strategy.name}（{time_strategy.bid_adjust_direction}）
建议调幅：{time_strategy.bid_adjust_min_pct}%~{time_strategy.bid_adjust_max_pct}%

{_build_time_slot_rules(time_strategy)}

【历史出价记录】
近期出价：{recent_bids_text}卢布 | 30天均值：{bid_history.get('avg_bid_30d', 'N/A')}卢布
最近调价方向：{bid_history.get('last_adjust_direction', 'none')} | 调价{bid_history.get('bid_change_count', 0)}次

【各商品明细】
{products_data}
（商品ID | 商品名 | 当前出价 | 今日点击 | 今日订单 | 今日花费 | 今日收入 | 今日ROAS）

【三层数据决策规则】
1. 活动历史ROAS > 目标×0.9，今日偏低 → 短期波动，维持或小幅调整，decision_basis="history_weighted"
2. 活动历史ROAS低，今日也低 → 持续低效，降价，decision_basis="history_weighted"
3. 活动历史差，但店铺整体今日也差 → 市场问题，不过度调，decision_basis="shop_benchmark"
4. 新活动数据不足 → 以店铺均值参考，调幅≤10%，decision_basis="shop_benchmark"
5. 预算消耗>85%且<20:00 → 全线降价保预算，decision_basis="budget_control"
6. 近期刚降过价 → 谨慎再次降价

【约束】
最低出价：3卢布 | 最高出价：{config['max_bid']}卢布 | 单次调幅：≤{time_strategy.max_single_change_pct}% | 出价取整数

【输出：纯JSON】
""" + """{
  "summary": "分析总结（说明判断依据和数据来源）",
  "data_quality": "good|limited|poor",
  "suggestions": [
    {
      "product_id": "商品ID",
      "product_name": "商品名",
      "current_bid": 45,
      "suggested_bid": 38,
      "adjust_pct": -15.6,
      "reason": "调价理由（说明参考了哪层数据）",
      "current_roas": 1.2,
      "expected_roas": 1.8,
      "decision_basis": "history_weighted|shop_benchmark|budget_control|today_only"
    }
  ]
}
ROAS正常无需调整的商品不要出现在suggestions里。"""

    # 6. 调用DeepSeek
    ai_result = await _call_deepseek(prompt)
    if not ai_result:
        return {"analyzed_count": len(campaigns), "suggestion_count": 0, "suggestions": [], "summary": "AI分析失败"}

    summary = ai_result.get("summary", "AI分析完成")
    raw_suggestions = ai_result.get("suggestions", [])

    if not raw_suggestions:
        logger.info(f"shop_id={shop.id} DeepSeek未返回调价建议（所有商品正常）")
        return {"analyzed_count": len(campaigns), "suggestion_count": 0, "suggestions": [], "summary": summary}

    # 7. 将该店铺已有的pending建议标记为expired（防止重复）
    db.query(AiPricingSuggestion).filter(
        AiPricingSuggestion.tenant_id == tenant_id,
        AiPricingSuggestion.shop_id == shop.id,
        AiPricingSuggestion.status == "pending",
    ).update({"status": "expired"})
    db.flush()

    # 8. 安全护栏校验 + 写入数据库
    saved = []
    for raw in raw_suggestions:
        product_id = str(raw.get("product_id", ""))
        # 查找对应的出价信息
        matched_pb = None
        for key, pb in products_bids.items():
            if pb["sku"] == product_id:
                matched_pb = pb
                break
        if not matched_pb:
            logger.warning(f"DeepSeek返回的product_id={product_id}未在出价数据中找到，跳过")
            continue

        current_bid = matched_pb["bid"]
        raw_suggested = float(raw.get("suggested_bid", current_bid))

        # 护栏校验
        safe_bid = validate_suggestion(raw_suggested, current_bid, config, time_strategy)

        # 跳过无变化的建议
        if safe_bid == int(current_bid):
            continue

        actual_adjust_pct = round((safe_bid - current_bid) / current_bid * 100, 2) if current_bid > 0 else 0

        suggestion = AiPricingSuggestion(
            tenant_id=tenant_id,
            shop_id=shop.id,
            campaign_id=matched_pb["campaign_id"],
            product_id=product_id,
            product_name=raw.get("product_name", matched_pb["name"])[:200],
            image_url=image_map.get(product_id, None),
            current_bid=current_bid,
            suggested_bid=safe_bid,
            adjust_pct=actual_adjust_pct,
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
            time_slot=time_strategy.name if time_strategy else None,
            moscow_hour=moscow_hour,
            template_name=config.get("template_name", ""),
            data_source=raw.get("decision_basis", "today_only"),
            campaign_data_days=history_stats.get("data_days", 0),
            is_new_campaign=1 if history_stats.get("is_new_campaign") else 0,
            shop_avg_roas=shop_benchmark.get("shop_avg_roas_7d", 0),
        )
        db.add(suggestion)
        db.flush()
        saved.append(_suggestion_to_dict(suggestion))

    db.commit()

    logger.info(f"shop_id={shop.id} AI分析完成: 分析{len(campaigns)}个活动, 生成{len(saved)}条建议")
    return {
        "analyzed_count": len(campaigns),
        "suggestion_count": len(saved),
        "suggestions": saved,
        "summary": summary,
    }


# ==================== DeepSeek调用 ====================

async def _call_deepseek(prompt: str) -> Optional[dict]:
    """调用DeepSeek API并解析JSON响应"""
    if not settings.DEEPSEEK_API_KEY:
        logger.error("DEEPSEEK_API_KEY未配置")
        return None

    client = DeepSeekClient(
        api_key=settings.DEEPSEEK_API_KEY,
        base_url=settings.DEEPSEEK_BASE_URL or "https://api.deepseek.com",
    )

    try:
        result = await client.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=4000,
            system_prompt=PRICING_SYSTEM_PROMPT,
        )
        content = result.get("content", "")
        logger.info(f"DeepSeek响应: tokens={result.get('total_tokens', 0)}, duration={result.get('duration_ms', 0)}ms")

        # 容错解析JSON
        return _parse_ai_response(content)

    except Exception as e:
        logger.error(f"DeepSeek调用失败: {e}")
        return None


def _parse_ai_response(content: str) -> Optional[dict]:
    """容错解析DeepSeek返回的JSON

    DeepSeek可能返回:
    1. 纯JSON
    2. ```json ... ```
    3. 带前后文字的JSON
    """
    if not content:
        return None

    # 尝试直接解析
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    # 尝试提取```json```代码块
    if "```json" in content:
        try:
            start = content.index("```json") + 7
            end = content.index("```", start)
            return json.loads(content[start:end].strip())
        except (ValueError, json.JSONDecodeError):
            pass

    # 尝试提取第一个{ }
    try:
        start = content.index("{")
        end = content.rindex("}") + 1
        return json.loads(content[start:end])
    except (ValueError, json.JSONDecodeError):
        pass

    logger.error(f"无法解析DeepSeek响应为JSON: {content[:200]}")
    return None


# ==================== 辅助函数 ====================

def _get_today_stats(db: Session, tenant_id: int, campaigns: list, today: date) -> dict:
    """获取今日各活动的统计数据，返回 {campaign_id: {spend, revenue, clicks, orders}}"""
    campaign_ids = [c.id for c in campaigns]
    stats = db.query(AdStat).filter(
        AdStat.tenant_id == tenant_id,
        AdStat.campaign_id.in_(campaign_ids),
        AdStat.stat_date == today,
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


# _default_config已移至config_resolver.py


def _suggestion_to_dict(s: AiPricingSuggestion) -> dict:
    return {
        "id": s.id,
        "campaign_id": s.campaign_id,
        "product_id": s.product_id,
        "product_name": s.product_name,
        "image_url": s.image_url,
        "current_bid": float(s.current_bid),
        "suggested_bid": float(s.suggested_bid),
        "adjust_pct": float(s.adjust_pct),
        "reason": s.reason,
        "current_roas": float(s.current_roas) if s.current_roas else None,
        "expected_roas": float(s.expected_roas) if s.expected_roas else None,
        "current_spend": float(s.current_spend) if s.current_spend else None,
        "daily_budget": float(s.daily_budget) if s.daily_budget else None,
        "ai_model": s.ai_model,
        "status": s.status,
        "auto_executed": bool(s.auto_executed),
        "executed_at": s.executed_at.isoformat() if s.executed_at else None,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "expires_at": s.expires_at.isoformat() if s.expires_at else None,
        "decision_basis": getattr(s, "decision_basis", "today_only"),
        "history_avg_roas": float(s.history_avg_roas) if getattr(s, "history_avg_roas", None) else None,
        "data_days": getattr(s, "data_days", 0),
        "time_slot": getattr(s, "time_slot", None),
        "moscow_hour": getattr(s, "moscow_hour", None),
        "template_name": getattr(s, "template_name", None),
        "data_source": getattr(s, "data_source", "today_only"),
        "campaign_data_days": getattr(s, "campaign_data_days", 0),
        "is_new_campaign": bool(getattr(s, "is_new_campaign", 0)),
        "shop_avg_roas": float(s.shop_avg_roas) if getattr(s, "shop_avg_roas", None) else None,
    }
