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
    return (datetime.utcnow().hour + MOSCOW_UTC_OFFSET) % 24


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

PRICING_SYSTEM_PROMPT = "你是俄罗斯电商Ozon平台的广告出价优化专家。请基于数据给出精准的调价建议。"

PRICING_USER_PROMPT = """请基于以下数据，对每个商品给出调价建议。

【店铺配置】
品类：{category_name}
目标ROAS：{target_roas}
最低可接受ROAS：{min_roas}
毛利率：{gross_margin}
日预算：{daily_budget_limit}卢布
当前莫斯科时间：{moscow_hour}点

【今日广告数据】
总花费：{total_spend}卢布 / 日预算：{daily_budget}卢布（已用{budget_pct}%）
整体ROAS：{overall_roas}

【各商品明细】
{products_data}
（格式：商品ID | 商品名 | 当前出价 | 今日点击 | 今日订单 | 今日花费 | 今日收入 | ROAS）

【调价规则约束】
- 最低出价：3卢布（Ozon平台限制）
- 最高出价：{max_bid}卢布
- 单次最大调幅：{max_adjust_pct}%
- 出价必须取整数（卢布）

【输出格式】
必须输出纯JSON，格式如下：
{{
  "summary": "本次分析总结（一句话）",
  "suggestions": [
    {{
      "product_id": "商品ID",
      "product_name": "商品名",
      "current_bid": 45,
      "suggested_bid": 38,
      "adjust_pct": -15.6,
      "reason": "当前ROAS 1.2低于目标2.5，且日预算已消耗78%，建议降价减少无效消耗",
      "current_roas": 1.2,
      "expected_roas": 1.8
    }}
  ]
}}

注意：如果某商品数据正常无需调整，不要包含在suggestions里。"""


# ==================== 安全护栏 ====================

def validate_suggestion(suggested_bid: float, current_bid: float, config: AiPricingConfig) -> int:
    """安全护栏校验，返回校验后的整数出价"""
    min_bid = float(config.min_bid)
    max_bid = float(config.max_bid)
    max_adjust_pct = float(config.max_adjust_pct)

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
    category_name: Optional[str] = None,
    campaign_ids: Optional[List[int]] = None,
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
    # 1. 获取品类配置
    config_query = db.query(AiPricingConfig).filter(
        AiPricingConfig.tenant_id == tenant_id,
        AiPricingConfig.shop_id == shop.id,
        AiPricingConfig.is_active == 1,
    )
    if category_name:
        config_query = config_query.filter(AiPricingConfig.category_name == category_name)
    configs = config_query.all()

    if not configs:
        logger.info(f"shop_id={shop.id} 无有效配置，使用默认配置")
        configs = [_default_config(tenant_id, shop.id)]
    config = configs[0]

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

    # 5. 构建Prompt数据
    total_spend = sum(s.get("spend", 0) for s in stats_map.values())
    total_revenue = sum(s.get("revenue", 0) for s in stats_map.values())
    daily_budget = float(config.daily_budget_limit)
    budget_pct = round(total_spend / daily_budget * 100, 1) if daily_budget > 0 else 0
    overall_roas = round(total_revenue / total_spend, 2) if total_spend > 0 else 0

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

    prompt = PRICING_USER_PROMPT.format(
        category_name=config.category_name,
        target_roas=float(config.target_roas),
        min_roas=float(config.min_roas),
        gross_margin=float(config.gross_margin),
        daily_budget_limit=daily_budget,
        moscow_hour=_get_moscow_hour(),
        total_spend=f"{total_spend:.0f}",
        daily_budget=f"{daily_budget:.0f}",
        budget_pct=budget_pct,
        overall_roas=overall_roas,
        products_data=products_data,
        max_bid=float(config.max_bid),
        max_adjust_pct=float(config.max_adjust_pct),
    )

    # 6. 调用DeepSeek
    ai_result = await _call_deepseek(prompt)
    if not ai_result:
        return {"analyzed_count": len(campaigns), "suggestion_count": 0, "suggestions": [], "summary": "AI分析失败"}

    summary = ai_result.get("summary", "AI分析完成")
    raw_suggestions = ai_result.get("suggestions", [])

    if not raw_suggestions:
        logger.info(f"shop_id={shop.id} DeepSeek未返回调价建议（所有商品正常）")
        return {"analyzed_count": len(campaigns), "suggestion_count": 0, "suggestions": [], "summary": summary}

    # 7. 安全护栏校验 + 写入数据库
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
        safe_bid = validate_suggestion(raw_suggested, current_bid, config)

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


def _default_config(tenant_id: int, shop_id: int) -> AiPricingConfig:
    """返回默认配置对象（不持久化）"""
    config = AiPricingConfig()
    config.tenant_id = tenant_id
    config.shop_id = shop_id
    config.category_name = "通用默认"
    config.target_roas = 2.00
    config.min_roas = 1.20
    config.gross_margin = 0.45
    config.daily_budget_limit = 1500.00
    config.max_bid = 180.00
    config.min_bid = 3.00
    config.max_adjust_pct = 30.00
    config.auto_execute = 0
    config.is_active = 1
    return config


def _suggestion_to_dict(s: AiPricingSuggestion) -> dict:
    return {
        "id": s.id,
        "campaign_id": s.campaign_id,
        "product_id": s.product_id,
        "product_name": s.product_name,
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
    }
