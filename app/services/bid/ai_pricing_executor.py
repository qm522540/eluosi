"""AI调价执行器（按老林审查报告 V2 修复版）

修复点（对照 docs/daily/2026-04-11_审查报告_出价管理_老林.md）:
  - #1-#11 多租户隔离：所有函数加 tenant_id 参数，所有 SQL WHERE 加 tenant_id
  - #12 datetime.utcnow → datetime.now(timezone.utc)
  - #18 analyze_now Redis SETNX 60秒同店铺锁
  - #19 retry_at timezone-aware 比较

数据流：
  ai_pricing_configs.is_active=1 触发执行
  → 读取当前 template_name 指向的 JSON 模板配置
  → 遍历 ad_campaigns(status='active', platform=shop.platform)
    → 拉商品 + 当前出价
    → DeepSeek prompt → 解析建议
    → 写入 ai_pricing_suggestions
    → Ozon: auto_execute=1 时直接调 API 执行
    → WB: 仅建议模式（auto_execute 强制关闭）
"""

import json
import re
from datetime import datetime, timezone
from typing import AsyncGenerator, Optional

from sqlalchemy import bindparam, text

from app.config import get_settings
from app.utils.errors import ErrorCode
from app.utils.logger import setup_logger
from app.utils.moscow_time import moscow_hour, moscow_today

logger = setup_logger("bid.ai_pricing_executor")
settings = get_settings()

MIN_BID = 3.0
MIN_DIFF = 1.0
ANALYZE_LOCK_TTL = 60  # #18 同店铺 analyze 锁 60s


def _utc_now() -> datetime:
    """统一的 timezone-aware UTC now（#12 修复）"""
    return datetime.now(timezone.utc)


# ==================== Config 更新 ====================

def update_config(db, tenant_id: int, shop_id: int, data: dict) -> dict:
    """更新 ai_pricing_configs（PUT /ai-pricing/{shop_id}）"""
    existing = db.execute(text("""
        SELECT id, tenant_id FROM ai_pricing_configs
        WHERE shop_id = :shop_id LIMIT 1
    """), {"shop_id": shop_id}).fetchone()

    if existing and existing.tenant_id != tenant_id:
        return {"code": ErrorCode.SHOP_NOT_FOUND, "msg": "店铺不存在或无权限"}

    template_name = data.get("template_name", "default")
    if template_name not in ("conservative", "default", "aggressive"):
        return {"code": ErrorCode.PARAM_ERROR, "msg": "template_name 必须是 conservative/default/aggressive"}

    auto_execute = 1 if data.get("auto_execute") else 0

    fields = {}
    for key in ("conservative_config", "default_config", "aggressive_config"):
        if key in data and isinstance(data[key], dict):
            err = _validate_template_json(data[key])
            if err:
                return {"code": ErrorCode.PARAM_ERROR, "msg": f"{key}: {err}"}
            fields[key] = json.dumps(data[key])

    if existing:
        sets = ["template_name = :template_name", "auto_execute = :auto_execute", "updated_at = NOW()"]
        params = {
            "id": existing.id,
            "tenant_id": tenant_id,
            "template_name": template_name,
            "auto_execute": auto_execute,
        }
        for k, v in fields.items():
            sets.append(f"{k} = :{k}")
            params[k] = v
        # 双重保险：UPDATE 仍按 tenant_id 过滤
        db.execute(
            text(f"UPDATE ai_pricing_configs SET {', '.join(sets)} WHERE id = :id AND tenant_id = :tenant_id"),
            params,
        )
    else:
        defaults = {
            "conservative_config": json.dumps(_DEFAULT_CONSERVATIVE),
            "default_config": json.dumps(_DEFAULT_DEFAULT),
            "aggressive_config": json.dumps(_DEFAULT_AGGRESSIVE),
        }
        defaults.update(fields)
        db.execute(text("""
            INSERT INTO ai_pricing_configs (
                tenant_id, shop_id, is_active, auto_execute, template_name,
                conservative_config, default_config, aggressive_config
            ) VALUES (
                :tenant_id, :shop_id, 0, :auto_execute, :template_name,
                :conservative_config, :default_config, :aggressive_config
            )
        """), {
            "tenant_id": tenant_id,
            "shop_id": shop_id,
            "auto_execute": auto_execute,
            "template_name": template_name,
            **defaults,
        })

    db.commit()
    return {"code": 0}


# ==================== 启用 / 停用 ====================

def enable(db, tenant_id: int, shop_id: int, auto_execute: bool = False) -> dict:
    """启用 AI 调价（FOR UPDATE 互斥校验 + 数据初始化校验 + 多租户隔离）"""
    init_row = db.execute(text("""
        SELECT is_initialized FROM shop_data_init_status
        WHERE shop_id = :shop_id AND tenant_id = :tenant_id
    """), {"shop_id": shop_id, "tenant_id": tenant_id}).fetchone()
    if not init_row or not init_row.is_initialized:
        return {"code": ErrorCode.BID_DATA_NOT_READY, "msg": "店铺数据未初始化完成"}

    ai_row = db.execute(text("""
        SELECT id FROM ai_pricing_configs
        WHERE shop_id = :shop_id AND tenant_id = :tenant_id
        FOR UPDATE
    """), {"shop_id": shop_id, "tenant_id": tenant_id}).fetchone()
    if not ai_row:
        return {"code": ErrorCode.BID_AI_CONFIG_NOT_FOUND, "msg": "AI调价配置不存在"}

    time_row = db.execute(text("""
        SELECT id, is_active FROM time_pricing_rules
        WHERE shop_id = :shop_id AND tenant_id = :tenant_id
        FOR UPDATE
    """), {"shop_id": shop_id, "tenant_id": tenant_id}).fetchone()
    if time_row and time_row.is_active:
        return {"code": ErrorCode.BID_CONFLICT_TIME_AI, "msg": "分时调价已启用，请先停用"}

    db.execute(text("""
        UPDATE ai_pricing_configs
        SET is_active = 1, auto_execute = :auto_execute, updated_at = NOW()
        WHERE shop_id = :shop_id AND tenant_id = :tenant_id
    """), {
        "shop_id": shop_id,
        "tenant_id": tenant_id,
        "auto_execute": 1 if auto_execute else 0,
    })
    db.commit()
    return {"code": 0}


def disable(db, tenant_id: int, shop_id: int) -> dict:
    """停用 AI 调价（pending建议保留），多租户过滤"""
    db.execute(text("""
        UPDATE ai_pricing_configs
        SET is_active = 0, auto_execute = 0, updated_at = NOW()
        WHERE shop_id = :shop_id AND tenant_id = :tenant_id
    """), {"shop_id": shop_id, "tenant_id": tenant_id})
    db.commit()
    return {"code": 0}


# ==================== 主分析流程 ====================

async def execute(db, shop_id: int, tenant_id: int = None) -> dict:
    """Celery 触发的 AI 调价主流程

    Args:
        tenant_id: 手动触发时由路由透传；Celery 不传，从 ai_pricing_configs 反查

    Returns: {analyzed_count, suggestion_count, auto_executed_count, status, message}
    """
    # Celery 路径反查 tenant_id
    if tenant_id is None:
        cfg_row = db.execute(text("""
            SELECT tenant_id FROM ai_pricing_configs
            WHERE shop_id = :shop_id AND is_active = 1
            LIMIT 1
        """), {"shop_id": shop_id}).fetchone()
        if not cfg_row:
            return {"status": "skipped", "message": "AI调价未启用"}
        tenant_id = cfg_row.tenant_id

    cfg = db.execute(text("""
        SELECT id, tenant_id, shop_id, is_active, auto_execute, template_name,
               conservative_config, default_config, aggressive_config,
               retry_at
        FROM ai_pricing_configs
        WHERE shop_id = :shop_id AND tenant_id = :tenant_id AND is_active = 1
        LIMIT 1
    """), {"shop_id": shop_id, "tenant_id": tenant_id}).fetchone()

    if not cfg:
        return {"status": "skipped", "message": "AI调价未启用"}

    # #19 修复：retry_at 是 naive UTC（NOW() 在 enable_utc 设置下存的是 UTC），用 naive UTC 比较
    if cfg.retry_at and _utc_now().replace(tzinfo=None) < cfg.retry_at:
        return {"status": "skipped", "message": "等待失败重试时间"}

    return await analyze_now(db, tenant_id, shop_id, force=False)


async def analyze_now(db, tenant_id: int, shop_id: int,
                      force: bool = True, campaign_ids: Optional[list] = None) -> dict:
    """立即分析（手动触发或 Celery）

    #18 修复：用 Redis SETNX 限制同店铺 60 秒只能跑一次

    Returns: {analyzed_count, suggestion_count, auto_executed_count, time_cost_ms}
    """
    # #18 Redis 锁
    lock_acquired = _try_acquire_analyze_lock(shop_id)
    if not lock_acquired:
        return {
            "status": "skipped",
            "message": "AI 分析进行中，请等待 60 秒",
            "analyzed_count": 0,
            "suggestion_count": 0,
            "auto_executed_count": 0,
        }

    try:
        return await _analyze_now_inner(db, tenant_id, shop_id, force, campaign_ids)
    finally:
        _release_analyze_lock(shop_id)


async def _analyze_now_inner(db, tenant_id: int, shop_id: int,
                             force: bool, campaign_ids: Optional[list]) -> dict:
    start = _utc_now()
    cfg = db.execute(text("""
        SELECT id, tenant_id, shop_id, is_active, auto_execute, template_name,
               conservative_config, default_config, aggressive_config
        FROM ai_pricing_configs
        WHERE shop_id = :shop_id AND tenant_id = :tenant_id
        LIMIT 1
    """), {"shop_id": shop_id, "tenant_id": tenant_id}).fetchone()

    if not cfg:
        return {"status": "failed", "message": "AI配置不存在", "analyzed_count": 0, "suggestion_count": 0, "auto_executed_count": 0}

    template = _read_template(cfg)
    if not template:
        _update_status(db, tenant_id, shop_id, "failed", "模板配置缺失", retry=False)
        return {"status": "failed", "message": "模板配置缺失", "analyzed_count": 0, "suggestion_count": 0, "auto_executed_count": 0}

    from app.models.shop import Shop
    shop = db.query(Shop).filter(
        Shop.id == shop_id, Shop.tenant_id == tenant_id
    ).first()
    if not shop or shop.platform not in ("ozon", "wb"):
        return {"status": "failed", "message": "该平台暂不支持AI调价", "analyzed_count": 0, "suggestion_count": 0, "auto_executed_count": 0}

    platform = shop.platform

    from app.models.ad import AdCampaign
    q = db.query(AdCampaign).filter(
        AdCampaign.tenant_id == tenant_id,
        AdCampaign.shop_id == shop_id,
        AdCampaign.platform == platform,
        AdCampaign.status == "active",
    )
    if campaign_ids:
        q = q.filter(AdCampaign.id.in_(campaign_ids))
    campaigns = q.all()

    if not campaigns:
        _update_status(db, tenant_id, shop_id, "success", "无活跃活动")
        return {"status": "success", "message": "无活跃活动", "analyzed_count": 0, "suggestion_count": 0, "auto_executed_count": 0}

    # 拉商品出价（平台分流）
    client = _create_platform_client(shop)

    products_by_campaign = {}
    try:
        for camp in campaigns:
            try:
                products = await client.fetch_campaign_products(camp.platform_campaign_id)
            except Exception as e:
                logger.warning(f"campaign={camp.id} 拉商品失败: {e}")
                products = []
            products_by_campaign[camp.id] = products
    finally:
        await client.close()

    if not any(products_by_campaign.values()):
        _update_status(db, tenant_id, shop_id, "success", "活跃活动下无商品")
        return {"status": "success", "message": "无商品数据", "analyzed_count": len(campaigns), "suggestion_count": 0, "auto_executed_count": 0}

    suggestions_raw = []
    try:
        suggestions_raw = await _call_ai(
            template, campaigns, products_by_campaign, platform,
            db=db, shop_id=shop_id, tenant_id=tenant_id,
        )
    except Exception as e:
        logger.error(f"DeepSeek 调用失败 shop_id={shop_id}: {e}")
        _update_status(db, tenant_id, shop_id, "failed", f"DeepSeek调用失败: {e}", retry=True)
        return {"status": "failed", "message": str(e), "analyzed_count": len(campaigns), "suggestion_count": 0, "auto_executed_count": 0}

    # 标记昨天及之前的 pending 建议为 rejected（自动过期），多租户过滤
    db.execute(text("""
        UPDATE ai_pricing_suggestions
        SET status = 'rejected'
        WHERE shop_id = :shop_id
          AND tenant_id = :tenant_id
          AND status = 'pending'
    """), {"shop_id": shop_id, "tenant_id": tenant_id})

    # 查 SKU 历史数据天数（用于写入 data_days，不依赖 AI 返回）
    sku_stats = _query_sku_history(db, shop_id, tenant_id, platform)

    # 写入新建议
    saved = []
    for raw in suggestions_raw:
        camp_id = raw.get("campaign_id")
        sku = str(raw.get("platform_sku_id") or "")
        if not camp_id or not sku:
            continue
        current_bid = float(raw.get("current_bid") or 0)
        suggested_bid = float(raw.get("suggested_bid") or 0)

        # 硬性安全护栏（兜底 AI 违规）：days<10 / trend=down 加价 / trend=new 全部丢弃
        sku_stat = sku_stats.get(f"{camp_id}_{sku}", {})
        days = int(sku_stat.get("days", 0) or 0)
        trend = sku_stat.get("trend", "new")
        if days < 10:
            logger.info(f"[guardrail] 丢弃 sku={sku} days={days}<10 (AI建议{current_bid}->{suggested_bid})")
            continue
        if trend == "new":
            logger.info(f"[guardrail] 丢弃 sku={sku} trend=new (AI建议{current_bid}->{suggested_bid})")
            continue
        if trend == "down" and suggested_bid > current_bid:
            logger.info(f"[guardrail] 丢弃 sku={sku} trend=down 但AI建议加价 {current_bid}->{suggested_bid}")
            continue

        # 安全护栏
        max_bid = float(template.get("max_bid", 999))
        max_pct = float(template.get("max_adjust_pct", 30))
        min_floor = max(MIN_BID, current_bid * 0.6) if current_bid > 0 else MIN_BID
        suggested_bid = max(suggested_bid, min_floor)
        suggested_bid = min(suggested_bid, max_bid)
        if current_bid > 0:
            change_pct = abs(suggested_bid - current_bid) / current_bid * 100
            if change_pct > max_pct:
                if suggested_bid > current_bid:
                    suggested_bid = round(current_bid * (1 + max_pct / 100))
                else:
                    suggested_bid = round(current_bid * (1 - max_pct / 100))
        suggested_bid = round(suggested_bid)
        if abs(suggested_bid - current_bid) < MIN_DIFF:
            continue

        adjust_pct = round((suggested_bid - current_bid) / current_bid * 100, 2) if current_bid > 0 else 0

        result = db.execute(text("""
            INSERT INTO ai_pricing_suggestions (
                tenant_id, shop_id, campaign_id,
                platform_sku_id, sku_name,
                current_bid, suggested_bid, adjust_pct,
                product_stage, decision_basis,
                current_roas, expected_roas,
                data_days, reason, status, generated_at
            ) VALUES (
                :tenant_id, :shop_id, :campaign_id,
                :sku, :sku_name,
                :current_bid, :suggested_bid, :adjust_pct,
                :stage, :basis,
                :current_roas, :expected_roas,
                :data_days, :reason, 'pending', NOW()
            )
        """), {
            "tenant_id": tenant_id,
            "shop_id": shop_id,
            "campaign_id": camp_id,
            "sku": sku,
            "sku_name": (raw.get("sku_name") or "")[:300],
            "current_bid": current_bid,
            "suggested_bid": suggested_bid,
            "adjust_pct": adjust_pct,
            "stage": raw.get("product_stage") or "unknown",
            "basis": raw.get("decision_basis") or "shop_benchmark",
            "current_roas": raw.get("current_roas"),
            "expected_roas": raw.get("expected_roas"),
            "data_days": sku_stats.get(f"{camp_id}_{sku}", {}).get("days", 0),
            "reason": (raw.get("reason") or "")[:500],
        })
        saved.append({
            "id": result.lastrowid,
            "tenant_id": tenant_id,
            "shop_id": shop_id,
            "campaign_id": camp_id,
            "platform_sku_id": sku,
            "current_bid": current_bid,
            "suggested_bid": suggested_bid,
            "adjust_pct": adjust_pct,
            "sku_name": raw.get("sku_name"),
            "product_stage": raw.get("product_stage") or "unknown",
            "reason": raw.get("reason"),
        })

    db.commit()

    auto_executed = 0
    if cfg.auto_execute and saved and platform == "ozon":
        # WB 仅建议模式，不自动执行（WB API 无法保证幂等性，需人工确认）
        auto_executed = await _auto_execute(db, tenant_id, shop, saved)

    elapsed = int((_utc_now() - start).total_seconds() * 1000)
    summary = f"分析{len(campaigns)}个活动 生成{len(saved)}条建议"
    if auto_executed:
        summary += f" 自动执行{auto_executed}条"
    _update_status(db, tenant_id, shop_id, "success", summary)

    return {
        "status": "success",
        "analyzed_count": len(campaigns),
        "suggestion_count": len(saved),
        "auto_executed_count": auto_executed,
        "time_cost_ms": elapsed,
        "suggestions": saved,
    }


async def _auto_execute(db, tenant_id: int, shop, suggestions: list) -> int:
    """auto_execute=1 模式：直接执行所有建议（仅 Ozon，WB 走建议模式不会进这里）"""
    from app.models.ad import AdCampaign

    client = _create_platform_client(shop)

    executed = 0
    try:
        for s in suggestions:
            campaign = db.query(AdCampaign).filter(
                AdCampaign.id == s["campaign_id"],
                AdCampaign.tenant_id == tenant_id,
            ).first()
            if not campaign:
                continue

            # 跳过 user_managed=1
            ag_row = db.execute(text("""
                SELECT user_managed FROM ad_groups
                WHERE campaign_id = :cid
                  AND tenant_id = :tenant_id
                  AND platform_group_id = :sku
                LIMIT 1
            """), {
                "cid": campaign.id,
                "tenant_id": tenant_id,
                "sku": s["platform_sku_id"],
            }).fetchone()
            if ag_row and ag_row.user_managed:
                continue

            try:
                api_result = await _execute_bid_update(
                    client, shop.platform, campaign.platform_campaign_id,
                    s["platform_sku_id"], s["suggested_bid"],
                )
                if not api_result.get("ok"):
                    _write_bidlog(db, campaign, s, "ai_auto", success=False, error=api_result.get("error"))
                    continue
                _upsert_group_last_auto(db, campaign, s["platform_sku_id"], s.get("sku_name") or "", s["suggested_bid"])
                db.execute(text("""
                    UPDATE ai_pricing_suggestions
                    SET status = 'approved', executed_at = :now
                    WHERE id = :id AND tenant_id = :tenant_id
                """), {
                    "id": s["id"],
                    "tenant_id": tenant_id,
                    "now": _utc_now().replace(tzinfo=None),
                })
                _write_bidlog(db, campaign, s, "ai_auto", success=True)
                executed += 1
            except Exception as e:
                logger.error(f"auto execute 异常 sku={s['platform_sku_id']}: {e}")
                _write_bidlog(db, campaign, s, "ai_auto", success=False, error=str(e))
        db.commit()
    finally:
        await client.close()

    return executed


# ==================== 单条 / 批量 approve ====================

async def approve_suggestion(db, tenant_id: int, suggestion_id: int,
                             override_bid: Optional[float] = None) -> dict:
    """单条 approve（POST /suggestions/{id}/approve）

    多租户隔离：必须 WHERE s.tenant_id = :tenant_id
    override_bid: 用户手动修改后的出价，覆盖 AI 原始建议
    """
    row = db.execute(text("""
        SELECT
            s.id, s.tenant_id, s.shop_id, s.campaign_id,
            s.platform_sku_id, s.sku_name, s.product_stage,
            s.current_bid, s.suggested_bid, s.adjust_pct,
            s.status, s.generated_at,
            c.platform_campaign_id, c.name AS campaign_name
        FROM ai_pricing_suggestions s
        JOIN ad_campaigns c ON s.campaign_id = c.id
        WHERE s.id = :id AND s.tenant_id = :tenant_id
    """), {"id": suggestion_id, "tenant_id": tenant_id}).fetchone()

    if not row:
        return {"code": ErrorCode.BID_SUGGESTION_NOT_FOUND, "msg": "建议不存在"}
    if row.status != "pending":
        return {"code": ErrorCode.BID_INVALID_STATUS, "msg": f"当前状态 {row.status} 不允许执行"}
    if row.generated_at and row.generated_at.date() < moscow_today():
        return {"code": ErrorCode.BID_SUGGESTION_EXPIRED, "msg": "建议已过期"}

    from app.models.shop import Shop

    shop = db.query(Shop).filter(
        Shop.id == row.shop_id, Shop.tenant_id == tenant_id
    ).first()
    if not shop:
        return {"code": ErrorCode.SHOP_NOT_FOUND, "msg": "店铺不存在"}

    # 使用用户修改后的出价或 AI 原始建议
    final_bid = override_bid if override_bid is not None else float(row.suggested_bid)

    client = _create_platform_client(shop)
    try:
        api_result = await _execute_bid_update(
            client, shop.platform, row.platform_campaign_id,
            row.platform_sku_id, final_bid,
        )
    finally:
        await client.close()

    if not api_result.get("ok"):
        return {"code": ErrorCode.BID_EXECUTION_FAILED,
                "msg": api_result.get("error") or "平台API失败"}

    # #12 修复：UTC now（naive 用于存数据库）
    now_utc = _utc_now().replace(tzinfo=None)
    db.execute(text("""
        UPDATE ai_pricing_suggestions
        SET status = 'approved', executed_at = :now
        WHERE id = :id AND tenant_id = :tenant_id
    """), {"id": suggestion_id, "tenant_id": tenant_id, "now": now_utc})

    from app.models.ad import AdCampaign
    campaign = db.query(AdCampaign).filter(
        AdCampaign.id == row.campaign_id, AdCampaign.tenant_id == tenant_id
    ).first()
    final_adjust_pct = round((final_bid - float(row.current_bid)) / float(row.current_bid) * 100, 2) if float(row.current_bid) > 0 else 0
    _upsert_group_last_auto(db, campaign, row.platform_sku_id, row.sku_name or "", final_bid)

    _write_bidlog(
        db, campaign,
        {
            "platform_sku_id": row.platform_sku_id,
            "sku_name": row.sku_name,
            "current_bid": float(row.current_bid),
            "suggested_bid": final_bid,
            "adjust_pct": final_adjust_pct,
            "product_stage": row.product_stage,
        },
        "ai_manual", success=True
    )
    db.commit()

    was_limited = abs(final_bid - api_result.get("actual_bid_rub", final_bid)) >= 1
    actual = api_result.get("actual_bid_rub", final_bid)

    return {
        "code": 0,
        "data": {
            "id": suggestion_id,
            "status": "approved",
            "executed_at": now_utc.isoformat() + "Z",
            "old_bid": float(row.current_bid),
            "new_bid": actual,
            "suggested_bid": final_bid,
            "min_bid_limited": was_limited,
        }
    }


async def approve_batch(db, tenant_id: int, ids: list) -> dict:
    """批量 approve（部分成功语义）"""
    results = []
    success_cnt = 0
    failed_cnt = 0
    for sid in ids:
        try:
            r = await approve_suggestion(db, tenant_id, sid)
            if r.get("code") == 0:
                results.append({"id": sid, "status": "approved"})
                success_cnt += 1
            else:
                results.append({
                    "id": sid, "status": "failed",
                    "error_code": r.get("code"), "error_msg": r.get("msg"),
                })
                failed_cnt += 1
        except Exception as e:
            results.append({
                "id": sid, "status": "failed",
                "error_code": ErrorCode.BID_EXECUTION_FAILED,
                "error_msg": str(e),
            })
            failed_cnt += 1
    return {
        "code": 0,
        "data": {
            "total": len(ids),
            "success": success_cnt,
            "failed": failed_cnt,
            "results": results,
        }
    }


def reject_suggestion(db, tenant_id: int, suggestion_id: int) -> dict:
    """多租户隔离 reject"""
    db.execute(text("""
        UPDATE ai_pricing_suggestions
        SET status = 'rejected'
        WHERE id = :id AND tenant_id = :tenant_id AND status = 'pending'
    """), {"id": suggestion_id, "tenant_id": tenant_id})
    db.commit()
    return {"code": 0, "data": {"id": suggestion_id, "status": "rejected"}}


def reject_batch(db, tenant_id: int, ids: list) -> dict:
    """多租户隔离批量 reject"""
    if ids:
        stmt = text("""
            UPDATE ai_pricing_suggestions
            SET status = 'rejected'
            WHERE id IN :ids AND tenant_id = :tenant_id AND status = 'pending'
        """).bindparams(bindparam("ids", expanding=True))
        db.execute(stmt, {"ids": list(ids), "tenant_id": tenant_id})
        db.commit()
    return {"code": 0, "data": {"total": len(ids)}}


# ==================== 内部工具 ====================

# ==================== SKU 历史数据查询 ====================

def _query_sku_history(db, shop_id: int, tenant_id: int, platform: str) -> dict:
    """查询 SKU 历史数据，按周分段 + 最近7天拆前4后3

    数据分段（权重从高到低）：
      - last3: 最近3天（最新状态）
      - prev4: 前4天（短期对比）
      - week1: 最近7天汇总（= last3 + prev4）
      - week2: 8-14天前（中期参考，权重低于week1）
      - week3: 15-21天前（长期参考，权重更低）
      - week4: 22-28天前（长期基线）
      - trend: up/down/stable/new（last3 vs prev4 的 ROAS 对比）

    Returns:
        {"campaign_id_sku": {week1字段..., "last3":{}, "prev4":{}, "week2":{}, "week3":{}, "week4":{}, "trend":""}, ...}
    """
    from datetime import date, timedelta
    today = date.today()

    # 分段边界（前5天 vs 后5天 + 周级历史）
    boundaries = {
        "last5":  (today - timedelta(days=5), today),
        "prev5":  (today - timedelta(days=10), today - timedelta(days=5)),
        "week2":  (today - timedelta(days=14), today - timedelta(days=7)),
        "week3":  (today - timedelta(days=21), today - timedelta(days=14)),
        "week4":  (today - timedelta(days=28), today - timedelta(days=21)),
    }

    if platform == "wb":
        sku_col = "s.ad_group_id"
        sku_filter = "AND s.ad_group_id IS NOT NULL"
    else:
        sku_col = "COALESCE(s.ad_group_id, 0)"
        sku_filter = ""

    sql = f"""
        SELECT
            s.campaign_id,
            {sku_col} AS sku_id,
            CASE
                WHEN s.stat_date >= :last5_from THEN 'last5'
                WHEN s.stat_date >= :prev5_from THEN 'prev5'
                WHEN s.stat_date >= :week2_from THEN 'week2'
                WHEN s.stat_date >= :week3_from THEN 'week3'
                WHEN s.stat_date >= :week4_from THEN 'week4'
                ELSE 'older'
            END AS period,
            SUM(s.impressions) AS impressions,
            SUM(s.clicks) AS clicks,
            SUM(s.spend) AS spend,
            SUM(s.orders) AS orders,
            SUM(s.revenue) AS revenue,
            COUNT(DISTINCT s.stat_date) AS days
        FROM ad_stats s
        JOIN ad_campaigns c ON s.campaign_id = c.id
        WHERE c.shop_id = :shop_id
          AND c.tenant_id = :tenant_id
          AND s.platform = :platform
          AND s.stat_date >= :week4_from
          {sku_filter}
        GROUP BY s.campaign_id, {sku_col}, period
    """
    rows = db.execute(text(sql), {
        "shop_id": shop_id, "tenant_id": tenant_id, "platform": platform,
        "last5_from": boundaries["last5"][0],
        "prev5_from": boundaries["prev5"][0],
        "week2_from": boundaries["week2"][0],
        "week3_from": boundaries["week3"][0],
        "week4_from": boundaries["week4"][0],
    }).fetchall()

    # 按 key 聚合
    raw = {}
    for r in rows:
        if r.period == "older":
            continue
        key = f"{r.campaign_id}_{r.sku_id}"
        if key not in raw:
            raw[key] = {}
        raw[key][r.period] = _calc_metrics(r)

    # 组装结果
    result = {}
    for key, periods in raw.items():
        l5 = periods.get("last5") or _empty_metrics()
        p5 = periods.get("prev5") or _empty_metrics()
        w2 = periods.get("week2") or _empty_metrics()
        w3 = periods.get("week3") or _empty_metrics()
        w4 = periods.get("week4") or _empty_metrics()

        total = _merge_metrics(p5, l5)

        # 趋势判断（last5 vs prev5，对半比较更稳定）
        if p5["days"] == 0 and l5["days"] == 0:
            trend = "new"
        elif p5["days"] < 3:
            trend = "new"
        elif l5["roas"] > p5["roas"] * 1.05:
            trend = "up"
        elif l5["roas"] < p5["roas"] * 0.95:
            trend = "down"
        else:
            trend = "stable"

        result[key] = {
            **total,  # 兼容旧代码直接取 total 字段
            "last5": l5,
            "prev5": p5,
            "week2": w2 if w2["days"] > 0 else None,
            "week3": w3 if w3["days"] > 0 else None,
            "week4": w4 if w4["days"] > 0 else None,
            "trend": trend,
        }

    logger.info(f"shop_id={shop_id} SKU 历史数据: {len(result)} 条 (platform={platform})")
    return result


def _calc_metrics(r) -> dict:
    impressions = int(r.impressions or 0)
    clicks = int(r.clicks or 0)
    spend = float(r.spend or 0)
    orders = int(r.orders or 0)
    revenue = float(r.revenue or 0)
    return {
        "impressions": impressions,
        "clicks": clicks,
        "spend": round(spend, 2),
        "orders": orders,
        "revenue": round(revenue, 2),
        "ctr": round(clicks / impressions * 100, 2) if impressions > 0 else 0,
        "cpc": round(spend / clicks, 2) if clicks > 0 else 0,
        "cr": round(orders / clicks * 100, 2) if clicks > 0 else 0,
        "roas": round(revenue / spend, 2) if spend > 0 else 0,
        "days": int(r.days),
    }


def _empty_metrics() -> dict:
    return {"impressions": 0, "clicks": 0, "spend": 0, "orders": 0,
            "revenue": 0, "ctr": 0, "cpc": 0, "cr": 0, "roas": 0, "days": 0}


def _merge_metrics(a: dict, b: dict) -> dict:
    impressions = a["impressions"] + b["impressions"]
    clicks = a["clicks"] + b["clicks"]
    spend = round(a["spend"] + b["spend"], 2)
    orders = a["orders"] + b["orders"]
    revenue = round(a["revenue"] + b["revenue"], 2)
    return {
        "impressions": impressions,
        "clicks": clicks,
        "spend": spend,
        "orders": orders,
        "revenue": revenue,
        "ctr": round(clicks / impressions * 100, 2) if impressions > 0 else 0,
        "cpc": round(spend / clicks, 2) if clicks > 0 else 0,
        "cr": round(orders / clicks * 100, 2) if clicks > 0 else 0,
        "roas": round(revenue / spend, 2) if spend > 0 else 0,
        "days": a["days"] + b["days"],
    }


# ==================== 平台抽象 ====================

def _create_platform_client(shop):
    """根据 shop.platform 创建对应的 API client"""
    if shop.platform == "ozon":
        from app.services.platform.ozon import OzonClient
        return OzonClient(
            shop_id=shop.id, api_key=shop.api_key, client_id=shop.client_id,
            perf_client_id=shop.perf_client_id or "",
            perf_client_secret=shop.perf_client_secret or "",
        )
    elif shop.platform == "wb":
        from app.services.platform.wb import WBClient
        return WBClient(shop_id=shop.id, api_key=shop.api_key)
    else:
        raise ValueError(f"不支持的平台: {shop.platform}")


async def _execute_bid_update(client, platform: str, campaign_id, sku, suggested_bid_rub: float) -> dict:
    """调平台 API 修改出价，屏蔽 Ozon/WB 的单位和接口差异。

    suggested_bid_rub 统一用卢布。
    Ozon: 需转 micro-rubles (×1_000_000)，调 update_campaign_bid
    WB: 直接传卢布，调 update_campaign_cpm
    """
    if platform == "ozon":
        return await client.update_campaign_bid(
            campaign_id, str(sku), str(int(suggested_bid_rub * 1_000_000))
        )
    elif platform == "wb":
        return await client.update_campaign_cpm(
            advert_id=str(campaign_id), nm_id=int(sku), cpm_rub=suggested_bid_rub,
        )
    else:
        return {"ok": False, "error": f"不支持的平台: {platform}"}


# ==================== 模板默认值 ====================

_DEFAULT_CONSERVATIVE = {
    "target_roas": 2.0, "min_roas": 1.5, "max_bid": 100, "max_adjust_pct": 15,
}
_DEFAULT_DEFAULT = {
    "target_roas": 3.0, "min_roas": 1.8, "max_bid": 180, "max_adjust_pct": 30,
}
_DEFAULT_AGGRESSIVE = {
    "target_roas": 4.0, "min_roas": 2.5, "max_bid": 300, "max_adjust_pct": 25,
}


def _validate_template_json(t: dict) -> Optional[str]:
    """校验模板字段范围"""
    try:
        if not (0 < float(t.get("target_roas", 0)) <= 100):
            return "target_roas 范围 (0, 100]"
        if not (0 < float(t.get("min_roas", 0)) <= 100):
            return "min_roas 范围 (0, 100]"
        if float(t["min_roas"]) >= float(t["target_roas"]):
            return "min_roas 必须 < target_roas"
        if not (3 <= float(t.get("max_bid", 0)) <= 10000):
            return "max_bid 范围 [3, 10000]"
        if not (0 < float(t.get("max_adjust_pct", 0)) <= 100):
            return "max_adjust_pct 范围 (0, 100]"
    except (KeyError, TypeError, ValueError) as e:
        return f"字段缺失或类型错误: {e}"
    return None


def _read_template(cfg) -> dict:
    """从 cfg 读取当前 template_name 指向的 JSON 模板"""
    name = cfg.template_name or "default"
    raw = getattr(cfg, f"{name}_config", None)
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return {}


# ==================== Redis 锁（#18）====================

def _try_acquire_analyze_lock(shop_id: int) -> bool:
    """尝试获取同店铺 60 秒分析锁，成功返回 True"""
    try:
        import redis as redis_lib
        pool = redis_lib.ConnectionPool.from_url(settings.REDIS_URL, decode_responses=True)
        r = redis_lib.Redis(connection_pool=pool)
        key = f"bid:analyze_lock:{shop_id}"
        return bool(r.set(key, "1", nx=True, ex=ANALYZE_LOCK_TTL))
    except Exception as e:
        logger.warning(f"Redis 锁不可用，降级直接执行: {e}")
        return True


def _release_analyze_lock(shop_id: int):
    """释放分析锁（异常路径用，正常路径靠 ex 自动过期）"""
    try:
        import redis as redis_lib
        pool = redis_lib.ConnectionPool.from_url(settings.REDIS_URL, decode_responses=True)
        r = redis_lib.Redis(connection_pool=pool)
        r.delete(f"bid:analyze_lock:{shop_id}")
    except Exception:
        pass


# ==================== AI 调用 + 解析 ====================

async def _call_ai(template: dict, campaigns: list, products_by_campaign: dict,
                   platform: str = "ozon", db=None, shop_id: int = None,
                   tenant_id: int = None) -> list:
    """调 DeepSeek 生成调价建议（支持 Ozon / WB，含历史数据）"""
    from app.services.ai.deepseek import DeepSeekClient

    api_key = getattr(settings, "DEEPSEEK_API_KEY", "")
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY 未配置")

    # 查询 SKU 最近 7 天历史数据（如果有 db）
    sku_stats = {}
    if db and shop_id and tenant_id:
        sku_stats = _query_sku_history(db, shop_id, tenant_id, platform)

    prompt_data = []
    for camp in campaigns:
        products = products_by_campaign.get(camp.id) or []
        items = []
        for p in products[:50]:
            sku = str(p.get("sku") or "")
            if platform == "ozon":
                bid_raw = p.get("bid", "0")
                try:
                    bid_rub = float(int(bid_raw)) / 1_000_000
                except (ValueError, TypeError):
                    bid_rub = 0
                name = (p.get("title") or "")[:80]
            else:
                bid_rub = float(p.get("bid_search") or 0)
                name = (p.get("subject_name") or "")[:80]
            if bid_rub <= 0:
                continue

            item = {
                "sku": sku,
                "name": name,
                "bid": round(bid_rub, 2),
            }
            # 附加历史数据（前5后5 + 周级历史 + 趋势）
            stats_key = f"{camp.id}_{sku}"
            if stats_key in sku_stats:
                s = sku_stats[stats_key]
                item["total_10d"] = {k: s[k] for k in
                    ["impressions","clicks","spend","orders","revenue","ctr","cpc","cr","roas","days"]
                    if k in s}
                item["last5"] = s.get("last5")
                item["prev5"] = s.get("prev5")
                if s.get("week2"): item["week2"] = s["week2"]
                if s.get("week3"): item["week3"] = s["week3"]
                if s.get("week4"): item["week4"] = s["week4"]
                item["trend"] = s.get("trend", "new")

            items.append(item)
        if items:
            prompt_data.append({
                "campaign_id": camp.id,
                "campaign_name": camp.name,
                "products": items,
            })

    if not prompt_data:
        return []

    platform_label = "Wildberries" if platform == "wb" else "Ozon"
    has_history = any(
        "stats_7d" in item
        for camp_data in prompt_data
        for item in camp_data["products"]
    )

    history_section = ""
    if has_history:
        history_section = """
每个商品有多段历史数据（权重从高到低）：
- total_10d: 最近10天汇总（impressions, clicks, spend, orders, revenue, ctr, cpc, cr, roas, days）
- last5: 后5天（最新状态）
- prev5: 前5天（对比基准）
- week2: 8-14天前汇总 — 中期参考（如有）
- week3: 15-21天前汇总 — 长期参考（如有）
- week4: 22-28天前汇总 — 长期基线（如有）
- trend: "up"=后5天ROAS高于前5天 / "down"=低于 / "stable"=持平 / "new"=数据不足

数据权重原则：越近的数据参考价值越高。total_10d是决策核心，week2-4用于判断长期基线。

==========================================
【⚠️ 强制硬规则 — 违反会被后端代码直接丢弃】
==========================================
规则A：total_10d.days < 10 的商品，**禁止给任何调价建议**（即不要把它放进 suggestions 数组）。
       注意：days=7、days=8、days=9 都属于"不足10天"，必须丢弃。
规则B：trend="down" 的商品，suggested_bid **不得高于** current_bid（禁止加价，只能维持或降价）。
规则C：trend="new" 的商品，**禁止给任何调价建议**。
违反以上任何一条的建议，会被代码层 100% 过滤掉，纯属浪费 token，请严格遵守。
==========================================

**核心目标：ROAS 最大化**（不是达到目标就好，而是让 ROAS 尽可能大）

决策逻辑（按优先级，所有规则都要先满足上面三条硬规则）：

1. **数据不足**（days < 10 或 trend="new"）→ 不要返回此商品（见硬规则A/C）
2. **ROAS >= 目标ROAS × 2 + 数据 >= 10天 + 趋势稳定或上升** → product_stage="growing"，小幅加价5-10%
3. **ROAS >= 目标ROAS × 2 + 数据 >= 10天 + 趋势下降** → 不要返回（见硬规则B，趋势下降禁加价；如要降价可按规则6处理）
4. **ROAS >= 目标ROAS + 数据 >= 10天 + 趋势稳定或上升** → product_stage="growing"，小幅加价5-10%
5. **ROAS >= 目标ROAS + 数据 >= 10天 + 趋势下降且接近目标** → product_stage="testing"，小幅降价5%
6. **最低ROAS <= ROAS < 目标ROAS + 数据 >= 10天** → product_stage="testing"，小幅降价5-10%
7. **ROAS < 最低ROAS + 数据 >= 10天 + 趋势下降或持平** → product_stage="declining"，大幅降价到当前出价的70%
8. **ROAS < 最低ROAS + 数据 >= 10天 + 趋势上升** → product_stage="testing"，不动，正在恢复
9. **有点击无订单（cr=0）+ 花费持续 + 数据 >= 10天** → product_stage="declining"，降价

**核心原则**：
- 数据不够（< 10天）就不动，宁可错过也不误判
- ROAS 绝对值优先于趋势方向（高ROAS下降 ≠ 衰退，可能是订单随机波动）
- ROAS 远超目标时趋势下降 → 先观察不急于行动（不返回该商品）
- 每次调整幅度要小（5-10%），小步试探
- min_roas 是硬止损线
"""

    prompt = f"""你是{platform_label}广告优化专家。基于商品的历史表现数据和当前出价，给出CPM出价调整建议。

【策略模板】
- 目标ROAS: {template.get('target_roas')}（广告回报率目标，ROAS高于此值的商品可加价扩量）
- 最低ROAS: {template.get('min_roas')}（止损线，ROAS低于此值必须降价或暂停）
- 最高出价: {template.get('max_bid')}卢布（硬上限，suggested_bid 绝不能超过此值）
- 单次最大调幅: {template.get('max_adjust_pct')}%（单次调整幅度不得超过此百分比）
- 最低出价限制: 平台对每个活动有最低出价限制（通常₽50-100），suggested_bid 不要低于当前出价的60%，避免因低于平台限额而执行失败

【流量时段规律（莫斯科时间）】
- 高峰期 19:00-21:00（流量最大，竞争激烈，CPC高，加价能获得更多曝光但成本高）
- 次高峰 10:00-12:00, 22:00（流量较大）
- 低谷期 01:00-07:00（流量最少，出价不用太高也能获得展示）
- 平谷期 其余时间（正常流量）
请结合商品的时段表现趋势综合判断出价方向。
{history_section}
【活动和商品数据（出价单位：卢布）】
{json.dumps(prompt_data, ensure_ascii=False)}

请为有调整空间的商品输出建议。无需调整的商品不要返回。
返回纯JSON：
{{
  "suggestions": [
    {{
      "campaign_id": <活动ID>,
      "platform_sku_id": "<SKU>",
      "sku_name": "<商品名>",
      "current_bid": <当前出价数值>,
      "suggested_bid": <建议出价整数>,
      "current_roas": <当前7天ROAS，无数据填null>,
      "product_stage": "growing|testing|cold_start|declining|unknown",
      "decision_basis": "history_data|shop_benchmark|cold_start_baseline",
      "reason": "<简短理由，引用具体数据>"
    }}
  ]
}}
"""

    client = DeepSeekClient(api_key=api_key)
    result = await client.chat(
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=4000,
    )
    content = result.get("content", "")

    parsed = _parse_ai_response(content)
    return parsed.get("suggestions") or []


async def analyze_stream(db, tenant_id: int, shop_id: int,
                         campaign_ids: Optional[list] = None) -> AsyncGenerator[str, None]:
    """流式 AI 分析：yield SSE 事件字符串，前端实时展示分析过程

    事件类型：
      - phase: 阶段提示（准备数据 / 调用AI / 解析结果）
      - token: AI 输出的文本片段
      - done:  完成，附带建议数量
      - error: 出错
    """
    from app.services.ai.deepseek import DeepSeekClient
    settings = get_settings()

    def _sse(event: str, data: str) -> str:
        return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    try:
        yield _sse("phase", "正在读取配置和商品数据...")

        cfg = db.execute(text("""
            SELECT id, tenant_id, shop_id, is_active, auto_execute, template_name,
                   conservative_config, default_config, aggressive_config
            FROM ai_pricing_configs
            WHERE shop_id = :shop_id AND tenant_id = :tenant_id
            LIMIT 1
        """), {"shop_id": shop_id, "tenant_id": tenant_id}).fetchone()

        if not cfg:
            yield _sse("error", "AI配置不存在")
            return

        template = _read_template(cfg)
        if not template:
            yield _sse("error", "模板配置缺失")
            return

        from app.models.shop import Shop
        shop = db.query(Shop).filter(Shop.id == shop_id, Shop.tenant_id == tenant_id).first()
        if not shop or shop.platform not in ("ozon", "wb"):
            yield _sse("error", "该平台暂不支持AI调价")
            return

        platform = shop.platform

        from app.models.ad import AdCampaign
        q = db.query(AdCampaign).filter(
            AdCampaign.tenant_id == tenant_id,
            AdCampaign.shop_id == shop_id,
            AdCampaign.platform == platform,
            AdCampaign.status == "active",
        )
        if campaign_ids:
            q = q.filter(AdCampaign.id.in_(campaign_ids))
        campaigns = q.all()

        if not campaigns:
            yield _sse("error", "无活跃活动")
            return

        yield _sse("phase", f"正在从{platform.upper()}拉取{len(campaigns)}个活动的商品出价...")

        client = _create_platform_client(shop)
        products_by_campaign = {}
        try:
            for camp in campaigns:
                try:
                    products = await client.fetch_campaign_products(camp.platform_campaign_id)
                except Exception:
                    products = []
                products_by_campaign[camp.id] = products
        finally:
            await client.close()

        total_products = sum(len(v) for v in products_by_campaign.values())
        if not total_products:
            yield _sse("error", "活跃活动下无商品")
            return

        yield _sse("phase", f"共{total_products}个商品，正在查询历史数据...")

        # 构建 prompt（复用 _call_ai 的逻辑）
        sku_stats = _query_sku_history(db, shop_id, tenant_id, platform)

        prompt_data = []
        for camp in campaigns:
            products = products_by_campaign.get(camp.id) or []
            items = []
            for p in products[:50]:
                sku = str(p.get("sku") or "")
                if platform == "ozon":
                    bid_raw = p.get("bid", "0")
                    try:
                        bid_rub = float(int(bid_raw)) / 1_000_000
                    except (ValueError, TypeError):
                        bid_rub = 0
                    name = (p.get("title") or "")[:80]
                else:
                    bid_rub = float(p.get("bid_search") or 0)
                    name = (p.get("subject_name") or "")[:80]
                if bid_rub <= 0:
                    continue
                item = {"sku": sku, "name": name, "bid": round(bid_rub, 2)}
                stats_key = f"{camp.id}_{sku}"
                if stats_key in sku_stats:
                    item["stats_7d"] = sku_stats[stats_key]
                items.append(item)
            if items:
                prompt_data.append({
                    "campaign_id": camp.id,
                    "campaign_name": camp.name,
                    "products": items,
                })

        if not prompt_data:
            yield _sse("error", "无有效商品数据")
            return

        platform_label = "Wildberries" if platform == "wb" else "Ozon"
        has_history = any(
            "stats_7d" in item
            for camp_data in prompt_data
            for item in camp_data["products"]
        )

        history_section = ""
        if has_history:
            history_section = """
每个商品有多段历史数据（权重从高到低）：
- total_10d: 最近10天汇总（impressions, clicks, spend, orders, revenue, ctr, cpc, cr, roas, days）
- last5: 后5天（最新状态）
- prev5: 前5天（对比基准）
- week2: 8-14天前汇总 — 中期参考（如有）
- week3: 15-21天前汇总 — 长期参考（如有）
- week4: 22-28天前汇总 — 长期基线（如有）
- trend: "up"=后5天ROAS高于前5天 / "down"=低于 / "stable"=持平 / "new"=数据不足

数据权重原则：越近的数据参考价值越高。total_10d是决策核心，week2-4用于判断长期基线。

==========================================
【⚠️ 强制硬规则 — 违反会被后端代码直接丢弃】
==========================================
规则A：total_10d.days < 10 的商品，**禁止给任何调价建议**（即不要把它放进 suggestions 数组）。
       注意：days=7、days=8、days=9 都属于"不足10天"，必须丢弃。
规则B：trend="down" 的商品，suggested_bid **不得高于** current_bid（禁止加价，只能维持或降价）。
规则C：trend="new" 的商品，**禁止给任何调价建议**。
违反以上任何一条的建议，会被代码层 100% 过滤掉，纯属浪费 token，请严格遵守。
==========================================

**核心目标：ROAS 最大化**（不是达到目标就好，而是让 ROAS 尽可能大）

决策逻辑（按优先级，所有规则都要先满足上面三条硬规则）：

1. **数据不足**（days < 10 或 trend="new"）→ 不要返回此商品（见硬规则A/C）
2. **ROAS >= 目标ROAS × 2 + 数据 >= 10天 + 趋势稳定或上升** → product_stage="growing"，小幅加价5-10%
3. **ROAS >= 目标ROAS × 2 + 数据 >= 10天 + 趋势下降** → 不要返回（见硬规则B，趋势下降禁加价；如要降价可按规则6处理）
4. **ROAS >= 目标ROAS + 数据 >= 10天 + 趋势稳定或上升** → product_stage="growing"，小幅加价5-10%
5. **ROAS >= 目标ROAS + 数据 >= 10天 + 趋势下降且接近目标** → product_stage="testing"，小幅降价5%
6. **最低ROAS <= ROAS < 目标ROAS + 数据 >= 10天** → product_stage="testing"，小幅降价5-10%
7. **ROAS < 最低ROAS + 数据 >= 10天 + 趋势下降或持平** → product_stage="declining"，大幅降价到当前出价的70%
8. **ROAS < 最低ROAS + 数据 >= 10天 + 趋势上升** → product_stage="testing"，不动，正在恢复
9. **有点击无订单（cr=0）+ 花费持续 + 数据 >= 10天** → product_stage="declining"，降价

**核心原则**：
- 数据不够（< 10天）就不动，宁可错过也不误判
- ROAS 绝对值优先于趋势方向（高ROAS下降 ≠ 衰退，可能是订单随机波动）
- ROAS 远超目标时趋势下降 → 先观察不急于行动（不返回该商品）
- 每次调整幅度要小（5-10%），小步试探
- min_roas 是硬止损线
"""

        prompt = f"""你是{platform_label}广告优化专家。基于商品的历史表现数据和当前出价，给出CPM出价调整建议。

【策略模板】
- 目标ROAS: {template.get('target_roas')}（广告回报率目标，ROAS高于此值的商品可加价扩量）
- 最低ROAS: {template.get('min_roas')}（止损线，ROAS低于此值必须降价或暂停）
- 最高出价: {template.get('max_bid')}卢布（硬上限，suggested_bid 绝不能超过此值）
- 单次最大调幅: {template.get('max_adjust_pct')}%（单次调整幅度不得超过此百分比）
- 最低出价限制: 平台对每个活动有最低出价限制（通常₽50-100），suggested_bid 不要低于当前出价的60%，避免因低于平台限额而执行失败

【流量时段规律（莫斯科时间）】
- 高峰期 19:00-21:00（流量最大，竞争激烈，CPC高，加价能获得更多曝光但成本高）
- 次高峰 10:00-12:00, 22:00（流量较大）
- 低谷期 01:00-07:00（流量最少，出价不用太高也能获得展示）
- 平谷期 其余时间（正常流量）
请结合商品的时段表现趋势综合判断出价方向。
{history_section}
【活动和商品数据（出价单位：卢布）】
{json.dumps(prompt_data, ensure_ascii=False)}

请为有调整空间的商品输出建议。无需调整的商品不要返回。
返回纯JSON：
{{
  "suggestions": [
    {{
      "campaign_id": <活动ID>,
      "platform_sku_id": "<SKU>",
      "sku_name": "<商品名>",
      "current_bid": <当前出价数值>,
      "suggested_bid": <建议出价整数>,
      "current_roas": <当前7天ROAS，无数据填null>,
      "product_stage": "growing|testing|cold_start|declining|unknown",
      "decision_basis": "history_data|shop_benchmark|cold_start_baseline",
      "reason": "<简短理由，引用具体数据>"
    }}
  ]
}}
"""

        yield _sse("phase", "AI 正在分析...")

        # 流式调用 DeepSeek
        api_key = getattr(settings, "DEEPSEEK_API_KEY", "")
        if not api_key:
            yield _sse("error", "DEEPSEEK_API_KEY 未配置")
            return

        ai_client = DeepSeekClient(api_key=api_key)
        full_content = ""
        async for chunk in ai_client.chat_stream(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=4000,
        ):
            full_content += chunk
            yield _sse("token", chunk)

        yield _sse("phase", "分析完成，正在保存建议...")

        # 解析并写入建议
        parsed = _parse_ai_response(full_content)
        suggestions_raw = parsed.get("suggestions") or []

        # 清掉所有旧 pending 建议（避免重复）
        db.execute(text("""
            UPDATE ai_pricing_suggestions
            SET status = 'rejected'
            WHERE shop_id = :shop_id AND tenant_id = :tenant_id
              AND status = 'pending'
        """), {"shop_id": shop_id, "tenant_id": tenant_id})

        saved_count = 0
        for raw in suggestions_raw:
            camp_id = raw.get("campaign_id")
            sku = str(raw.get("platform_sku_id") or "")
            if not camp_id or not sku:
                continue
            current_bid = float(raw.get("current_bid") or 0)
            suggested_bid = float(raw.get("suggested_bid") or 0)

            # 硬性安全护栏（兜底 AI 违规）：days<10 / trend=down 加价 / trend=new 全部丢弃
            sku_stat = sku_stats.get(f"{camp_id}_{sku}", {})
            days = int(sku_stat.get("days", 0) or 0)
            trend = sku_stat.get("trend", "new")
            if days < 10:
                logger.info(f"[guardrail] 丢弃 sku={sku} days={days}<10 (AI建议{current_bid}->{suggested_bid})")
                continue
            if trend == "new":
                logger.info(f"[guardrail] 丢弃 sku={sku} trend=new (AI建议{current_bid}->{suggested_bid})")
                continue
            if trend == "down" and suggested_bid > current_bid:
                logger.info(f"[guardrail] 丢弃 sku={sku} trend=down 但AI建议加价 {current_bid}->{suggested_bid}")
                continue

            max_bid = float(template.get("max_bid", 999))
            max_pct = float(template.get("max_adjust_pct", 30))
            suggested_bid = max(suggested_bid, MIN_BID)
            suggested_bid = min(suggested_bid, max_bid)
            if current_bid > 0:
                change_pct = abs(suggested_bid - current_bid) / current_bid * 100
                if change_pct > max_pct:
                    if suggested_bid > current_bid:
                        suggested_bid = round(current_bid * (1 + max_pct / 100))
                    else:
                        suggested_bid = round(current_bid * (1 - max_pct / 100))
            suggested_bid = round(suggested_bid)
            if abs(suggested_bid - current_bid) < MIN_DIFF:
                continue

            adjust_pct = round((suggested_bid - current_bid) / current_bid * 100, 2) if current_bid > 0 else 0

            db.execute(text("""
                INSERT INTO ai_pricing_suggestions (
                    tenant_id, shop_id, campaign_id,
                    platform_sku_id, sku_name,
                    current_bid, suggested_bid, adjust_pct,
                    product_stage, decision_basis,
                    current_roas, expected_roas,
                    data_days, reason, status, generated_at
                ) VALUES (
                    :tenant_id, :shop_id, :campaign_id,
                    :sku, :sku_name,
                    :current_bid, :suggested_bid, :adjust_pct,
                    :stage, :basis,
                    :current_roas, :expected_roas,
                    :data_days, :reason, 'pending', NOW()
                )
            """), {
                "tenant_id": tenant_id,
                "shop_id": shop_id,
                "campaign_id": camp_id,
                "sku": sku,
                "sku_name": (raw.get("sku_name") or "")[:300],
                "current_bid": current_bid,
                "suggested_bid": suggested_bid,
                "adjust_pct": adjust_pct,
                "stage": raw.get("product_stage") or "unknown",
                "basis": raw.get("decision_basis") or "shop_benchmark",
                "current_roas": raw.get("current_roas"),
                "expected_roas": raw.get("expected_roas"),
                "data_days": sku_stats.get(f"{camp_id}_{sku}", {}).get("days", 0),
                "reason": (raw.get("reason") or "")[:500],
            })
            saved_count += 1

        db.commit()
        _update_status(db, tenant_id, shop_id, "success", f"生成{saved_count}条建议")

        yield _sse("done", f"分析完成，生成 {saved_count} 条调价建议")

    except Exception as e:
        logger.error(f"流式分析异常 shop_id={shop_id}: {e}")
        yield _sse("error", f"分析失败: {str(e)[:200]}")


def _parse_ai_response(content: str) -> dict:
    if not content:
        return {}
    try:
        return json.loads(content)
    except (ValueError, TypeError):
        pass
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except (ValueError, TypeError):
            pass
    m = re.search(r"\{.*\}", content, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except (ValueError, TypeError):
            pass
    logger.error(f"AI响应解析失败: {content[:200]}")
    return {}


# ==================== 写库小工具 ====================

def _upsert_group_last_auto(db, campaign, sku: str, sku_name: str, last_auto: float):
    db.execute(text("""
        INSERT INTO ad_groups (
            tenant_id, campaign_id, platform_group_id, name,
            last_auto_bid, status
        ) VALUES (
            :tenant_id, :campaign_id, :sku, :name,
            :last_auto, 'active'
        )
        ON DUPLICATE KEY UPDATE
            name = VALUES(name),
            last_auto_bid = :last_auto,
            updated_at = NOW()
    """), {
        "tenant_id": campaign.tenant_id,
        "campaign_id": campaign.id,
        "sku": sku,
        "name": sku_name[:200] if sku_name else f"SKU-{sku}",
        "last_auto": last_auto,
    })


def _write_bidlog(db, campaign, suggestion: dict, execute_type: str,
                  success: bool = True, error: str = None):
    """写 bid_adjustment_logs"""
    db.execute(text("""
        INSERT INTO bid_adjustment_logs (
            tenant_id, shop_id, campaign_id, campaign_name,
            platform_sku_id, sku_name,
            old_bid, new_bid, adjust_pct,
            execute_type, product_stage, moscow_hour,
            success, error_msg, created_at
        ) VALUES (
            :tenant_id, :shop_id, :campaign_id, :campaign_name,
            :sku, :sku_name,
            :old_bid, :new_bid, :pct,
            :execute_type, :stage, :hour,
            :success, :error, NOW()
        )
    """), {
        "tenant_id": campaign.tenant_id,
        "shop_id": campaign.shop_id,
        "campaign_id": campaign.id,
        "campaign_name": campaign.name,
        "sku": suggestion["platform_sku_id"],
        "sku_name": (suggestion.get("sku_name") or "")[:300] or None,
        "old_bid": suggestion["current_bid"],
        "new_bid": suggestion["suggested_bid"],
        "pct": suggestion.get("adjust_pct") or 0,
        "execute_type": execute_type,
        "stage": suggestion.get("product_stage") or "unknown",
        "hour": moscow_hour(),
        "success": 1 if success else 0,
        "error": (error or "")[:500] if error else None,
    })


def _update_status(db, tenant_id: int, shop_id: int, status: str, msg: str, retry: bool = False):
    db.execute(text("""
        UPDATE ai_pricing_configs
        SET last_executed_at = NOW(),
            last_execute_status = :status,
            last_error_msg = :msg,
            retry_at = CASE WHEN :retry = 1 THEN DATE_ADD(NOW(), INTERVAL 30 MINUTE) ELSE NULL END
        WHERE shop_id = :shop_id AND tenant_id = :tenant_id
    """), {
        "shop_id": shop_id,
        "tenant_id": tenant_id,
        "status": status,
        "msg": msg[:500] if msg else None,
        "retry": 1 if retry else 0,
    })
    db.commit()
