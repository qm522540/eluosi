"""AI智能调价业务逻辑层

核心职责：
1. approve_suggestion — 确认执行建议（调Ozon API + 写日志 + 通知）
2. run_ai_analysis — 触发完整AI分析流程（调引擎 + 自动/手动模式处理）
"""

import asyncio
from datetime import datetime
from typing import Optional, List

from sqlalchemy.orm import Session

from app.models.ai_pricing import AiPricingConfig, AiPricingSuggestion
from app.models.ad import AdCampaign, AdBidLog
from app.models.shop import Shop
from app.services.ai.pricing_engine import (
    run_pricing_analysis, _build_ozon_client, _suggestion_to_dict,
)
from app.services.notification.service import send_wechat_work_bot
from app.utils.logger import setup_logger

logger = setup_logger("ad.ai_pricing")


# ==================== 执行建议 ====================

async def approve_suggestion(db: Session, tenant_id: int, suggestion_id: int) -> dict:
    """确认执行一条AI调价建议

    流程：
    1. 检查建议状态（必须pending且未过期）
    2. 调Ozon Performance API修改出价
    3. 更新suggestion状态为executed
    4. 写AdBidLog日志
    5. 发企业微信通知
    """
    suggestion = db.query(AiPricingSuggestion).filter(
        AiPricingSuggestion.id == suggestion_id,
        AiPricingSuggestion.tenant_id == tenant_id,
    ).first()
    if not suggestion:
        return {"code": 40004, "msg": "建议记录不存在"}

    if suggestion.status != "pending":
        return {"code": 40001, "msg": f"当前状态为{suggestion.status}，仅pending可执行"}

    # 检查过期
    if suggestion.expires_at and suggestion.expires_at < datetime.now():
        suggestion.status = "expired"
        db.commit()
        return {"code": 40001, "msg": "建议已过期（2小时有效期）"}

    # 获取店铺信息
    shop = db.query(Shop).filter(Shop.id == suggestion.shop_id).first()
    if not shop:
        return {"code": 40004, "msg": "店铺不存在"}

    # 获取活动信息
    campaign = db.query(AdCampaign).filter(AdCampaign.id == suggestion.campaign_id).first()
    if not campaign:
        return {"code": 40004, "msg": "广告活动不存在"}

    # 调Ozon API修改出价
    api_result = await _execute_bid_change(shop, campaign, suggestion)

    if not api_result["ok"]:
        logger.error(f"出价修改API失败: suggestion_id={suggestion_id}, error={api_result['error']}")
        return {"code": 50001, "msg": f"Ozon API调用失败: {api_result['error']}"}

    # 更新建议状态
    suggestion.status = "executed"
    suggestion.executed_at = datetime.now()

    # 写AdBidLog日志
    bid_log = AdBidLog(
        tenant_id=tenant_id,
        campaign_id=campaign.id,
        platform="ozon",
        campaign_name=campaign.name,
        old_bid=float(suggestion.current_bid),
        new_bid=float(suggestion.suggested_bid),
        change_pct=float(suggestion.adjust_pct),
        reason=f"AI调价: {suggestion.reason[:200] if suggestion.reason else ''}",
        rule_name="ai_pricing",
    )
    db.add(bid_log)
    db.commit()
    db.refresh(suggestion)

    logger.info(
        f"建议已执行: id={suggestion_id} "
        f"sku={suggestion.product_id} "
        f"{suggestion.current_bid}→{suggestion.suggested_bid}卢布"
    )

    # 异步发企业微信通知（不阻塞主流程）
    try:
        msg = (
            f"**AI调价已执行** | {shop.name}\n"
            f"商品: {suggestion.product_name}\n"
            f"出价: {int(suggestion.current_bid)}→{int(suggestion.suggested_bid)}卢布 "
            f"({float(suggestion.adjust_pct):+.1f}%)\n"
            f"原因: {suggestion.reason[:100] if suggestion.reason else ''}"
        )
        await send_wechat_work_bot(msg, msg_type="markdown")
    except Exception as e:
        logger.warning(f"企业微信通知发送失败（不影响主流程）: {e}")

    return {
        "code": 0,
        "data": {
            "id": suggestion.id,
            "status": suggestion.status,
            "executed_at": suggestion.executed_at.isoformat(),
            "product_id": suggestion.product_id,
            "old_bid": float(suggestion.current_bid),
            "new_bid": float(suggestion.suggested_bid),
        }
    }


async def _execute_bid_change(shop: Shop, campaign: AdCampaign, suggestion: AiPricingSuggestion) -> dict:
    """调用Ozon Performance API修改出价"""
    ozon_client = _build_ozon_client(shop)
    try:
        result = await ozon_client.update_campaign_bid(
            campaign_id=campaign.platform_campaign_id,
            sku=suggestion.product_id,
            new_bid=str(int(suggestion.suggested_bid)),
        )
        return result
    except Exception as e:
        logger.error(f"Ozon出价API异常: {e}")
        return {"ok": False, "error": str(e)}


# ==================== 批量执行 ====================

async def batch_approve_suggestions(db: Session, tenant_id: int, suggestion_ids: List[int]) -> dict:
    """批量执行多条建议"""
    results = []
    success_count = 0
    fail_count = 0

    for sid in suggestion_ids:
        result = await approve_suggestion(db, tenant_id, sid)
        results.append({"suggestion_id": sid, **result})
        if result.get("code") == 0:
            success_count += 1
        else:
            fail_count += 1

    return {
        "code": 0,
        "data": {
            "total": len(suggestion_ids),
            "success": success_count,
            "failed": fail_count,
            "details": results,
        }
    }


# ==================== 触发AI分析 ====================

async def run_ai_analysis(
    db: Session,
    tenant_id: int,
    shop_id: int,
    category_name: Optional[str] = None,
    campaign_ids: Optional[List[int]] = None,
) -> dict:
    """触发一次完整的AI调价分析

    流程：
    1. 调pricing_engine生成建议
    2. auto_execute=True → 自动approve所有建议
    3. auto_execute=False → 发企业微信推送待确认通知
    """
    shop = db.query(Shop).filter(
        Shop.id == shop_id,
        Shop.tenant_id == tenant_id,
    ).first()
    if not shop:
        return {"code": 40004, "msg": "店铺不存在"}

    # 调引擎生成建议
    logger.info(f"开始AI分析: shop_id={shop_id}, shop_name={shop.name}")
    analysis_result = await run_pricing_analysis(
        db, tenant_id, shop,
        category_name=category_name,
        campaign_ids=campaign_ids,
    )

    suggestion_count = analysis_result.get("suggestion_count", 0)
    suggestions = analysis_result.get("suggestions", [])
    summary = analysis_result.get("summary", "")

    if suggestion_count == 0:
        logger.info(f"shop_id={shop_id} AI分析完成，无需调价")
        return {"code": 0, "data": analysis_result}

    # 检查是否自动执行
    config = db.query(AiPricingConfig).filter(
        AiPricingConfig.tenant_id == tenant_id,
        AiPricingConfig.shop_id == shop_id,
        AiPricingConfig.is_active == 1,
    )
    if category_name:
        config = config.filter(AiPricingConfig.category_name == category_name)
    config = config.first()

    auto_execute = config and bool(config.auto_execute)

    if auto_execute:
        # 自动模式：逐条执行
        logger.info(f"shop_id={shop_id} 自动执行模式，执行{suggestion_count}条建议")
        executed = 0
        for s in suggestions:
            result = await approve_suggestion(db, tenant_id, s["id"])
            if result.get("code") == 0:
                executed += 1
                # 更新auto_executed标记
                sugg = db.query(AiPricingSuggestion).filter(AiPricingSuggestion.id == s["id"]).first()
                if sugg:
                    sugg.auto_executed = 1
                    db.commit()

        analysis_result["auto_executed_count"] = executed

        # 发通知：自动执行完成
        try:
            msg = (
                f"**AI自动调价完成** | {shop.name}\n"
                f"分析{analysis_result['analyzed_count']}个活动，"
                f"自动执行{executed}/{suggestion_count}条建议\n"
                f"{summary}"
            )
            await send_wechat_work_bot(msg, msg_type="markdown")
        except Exception as e:
            logger.warning(f"企业微信通知发送失败: {e}")

    else:
        # 手动模式：发通知提醒确认
        logger.info(f"shop_id={shop_id} 手动确认模式，推送{suggestion_count}条待确认建议")
        try:
            msg = _format_suggestion_message(suggestions, shop.name, summary)
            await send_wechat_work_bot(msg, msg_type="markdown")
        except Exception as e:
            logger.warning(f"企业微信通知发送失败: {e}")

    return {"code": 0, "data": analysis_result}


# ==================== 消息格式化 ====================

def _format_suggestion_message(suggestions: list, shop_name: str, summary: str) -> str:
    """格式化企业微信建议通知"""
    lines = [
        f"**AI调价建议** | {shop_name}",
        f"{datetime.now().strftime('%m-%d %H:%M')}",
        f"{summary}",
        "---"
    ]
    for s in suggestions[:5]:
        arrow = "↓" if s['adjust_pct'] < 0 else "↑"
        lines.append(
            f"{arrow} {s['product_name'][:15]}: "
            f"{int(s['current_bid'])}→{int(s['suggested_bid'])}卢布 "
            f"({s['adjust_pct']:+.1f}%)"
        )
    if len(suggestions) > 5:
        lines.append(f"... 共{len(suggestions)}条建议")
    lines.append("---")
    lines.append("请登录系统确认执行，或开启自动模式")
    return "\n".join(lines)
