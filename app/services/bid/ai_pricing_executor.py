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
from typing import Optional

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
          AND DATE(generated_at) < :today
    """), {"shop_id": shop_id, "tenant_id": tenant_id, "today": moscow_today()})

    # 写入新建议
    saved = []
    for raw in suggestions_raw:
        camp_id = raw.get("campaign_id")
        sku = str(raw.get("platform_sku_id") or "")
        if not camp_id or not sku:
            continue
        current_bid = float(raw.get("current_bid") or 0)
        suggested_bid = float(raw.get("suggested_bid") or 0)

        # 安全护栏
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
            "data_days": raw.get("data_days") or 0,
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

async def approve_suggestion(db, tenant_id: int, suggestion_id: int) -> dict:
    """单条 approve（POST /suggestions/{id}/approve）

    多租户隔离：必须 WHERE s.tenant_id = :tenant_id
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

    client = _create_platform_client(shop)
    try:
        api_result = await _execute_bid_update(
            client, shop.platform, row.platform_campaign_id,
            row.platform_sku_id, float(row.suggested_bid),
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
    _upsert_group_last_auto(db, campaign, row.platform_sku_id, row.sku_name or "", float(row.suggested_bid))

    _write_bidlog(
        db, campaign,
        {
            "platform_sku_id": row.platform_sku_id,
            "sku_name": row.sku_name,
            "current_bid": float(row.current_bid),
            "suggested_bid": float(row.suggested_bid),
            "adjust_pct": float(row.adjust_pct),
            "product_stage": row.product_stage,
        },
        "ai_manual", success=True
    )
    db.commit()

    return {
        "code": 0,
        "data": {
            "id": suggestion_id,
            "status": "approved",
            "executed_at": now_utc.isoformat() + "Z",
            "old_bid": float(row.current_bid),
            "new_bid": float(row.suggested_bid),
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
    """查询最近 7 天每个 SKU 的汇总数据

    WB: ad_group_id = nm_id（SKU 级）
    Ozon: ad_group_id 可能为 NULL（活动级），key 用 campaign_id_0

    Returns:
        {"campaign_id_sku": {impressions, clicks, spend, orders, revenue, ctr, roas, days}, ...}
    """
    from datetime import date, timedelta
    cutoff = date.today() - timedelta(days=7)

    if platform == "wb":
        # WB 有 SKU 级数据（ad_group_id = nm_id）
        rows = db.execute(text("""
            SELECT
                s.campaign_id,
                s.ad_group_id AS sku_id,
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
              AND s.stat_date >= :cutoff
              AND s.ad_group_id IS NOT NULL
            GROUP BY s.campaign_id, s.ad_group_id
        """), {
            "shop_id": shop_id, "tenant_id": tenant_id,
            "platform": platform, "cutoff": cutoff,
        }).fetchall()
    else:
        # Ozon 目前只有活动级数据，key 用 campaign_id + "0"
        rows = db.execute(text("""
            SELECT
                s.campaign_id,
                0 AS sku_id,
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
              AND s.stat_date >= :cutoff
            GROUP BY s.campaign_id
        """), {
            "shop_id": shop_id, "tenant_id": tenant_id,
            "platform": platform, "cutoff": cutoff,
        }).fetchall()

    result = {}
    for r in rows:
        impressions = int(r.impressions or 0)
        clicks = int(r.clicks or 0)
        spend = float(r.spend or 0)
        orders = int(r.orders or 0)
        revenue = float(r.revenue or 0)
        ctr = round(clicks / impressions * 100, 2) if impressions > 0 else 0
        roas = round(revenue / spend, 2) if spend > 0 else 0
        cpc = round(spend / clicks, 2) if clicks > 0 else 0
        cr = round(orders / clicks * 100, 2) if clicks > 0 else 0

        key = f"{r.campaign_id}_{r.sku_id}"
        result[key] = {
            "impressions": impressions,
            "clicks": clicks,
            "spend": round(spend, 2),
            "orders": orders,
            "revenue": round(revenue, 2),
            "ctr": ctr,
            "cpc": cpc,
            "cr": cr,
            "roas": roas,
            "days": int(r.days),
        }

    logger.info(f"shop_id={shop_id} SKU 历史数据: {len(result)} 条 (platform={platform})")
    return result


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
            # 附加历史数据（按 campaign_id + sku 查，WB 用 ad_group_id=nm_id）
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
每个商品的 stats_7d 字段是最近7天汇总数据：
- impressions: 展示次数
- clicks: 点击次数
- spend: 花费（卢布）
- orders: 订单数
- revenue: 收入（卢布）
- ctr: 点击率(%)
- cpc: 单次点击成本（卢布），spend/clicks
- cr: 转化率(%)，orders/clicks
- roas: 广告回报率（收入/花费）
- days: 有数据的天数

请基于历史数据判断商品阶段和调价方向：
- ROAS > 目标ROAS 且 cr 稳定 → growing，可适当加价扩量
- ROAS < 最低ROAS 且 spend 持续 → declining，应降价止损
- cpc 过高但 cr 尚可 → 出价偏高，适当降价控成本
- 有展示无点击（ctr极低） → 素材/相关性问题，不建议加价
- 有点击无订单（cr=0）且数据天数少 → cold_start 或 testing
- 无 stats_7d 的商品按 cold_start_baseline 处理
"""

    prompt = f"""你是{platform_label}广告优化专家。基于商品的历史表现数据和当前出价，给出CPM出价调整建议。

【策略模板】
- 目标ROAS: {template.get('target_roas')}（广告回报率目标，ROAS高于此值的商品可加价扩量）
- 最低ROAS: {template.get('min_roas')}（止损线，ROAS低于此值必须降价或暂停）
- 最高出价: {template.get('max_bid')}卢布（硬上限，suggested_bid 绝不能超过此值）
- 单次最大调幅: {template.get('max_adjust_pct')}%（单次调整幅度不得超过此百分比）
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
