"""出价管理 API 路由（按老林审查报告 V2 修复版）

修复点（对照 docs/daily/2026-04-11_审查报告_出价管理_老林.md）：
  - #1-#6 路由层多租户隔离：所有 {shop_id} 路径参数路由统一使用 Depends(get_owned_shop)
  - service 层 tenant_id 透传

路径前缀: /api/v1/bid-management
"""

import json
from io import BytesIO
from datetime import datetime, timezone

from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_owned_shop, get_tenant_id
from app.models.shop import Shop
from app.utils.errors import ErrorCode
from app.utils.logger import setup_logger
from app.utils.moscow_time import EXECUTE_MINUTE, get_dashboard_info, now_moscow
from app.utils.response import error, success

logger = setup_logger("api.bid_management")
router = APIRouter()


# ==================== Pydantic Models ====================

class TimePricingUpdate(BaseModel):
    peak_hours: list = Field(default_factory=list)
    peak_ratio: int = 120
    mid_hours: list = Field(default_factory=list)
    mid_ratio: int = 100
    low_hours: list = Field(default_factory=list)
    low_ratio: int = 60


class AIConfigUpdate(BaseModel):
    template_name: str = "default"
    auto_execute: bool = False
    conservative_config: dict = Field(default_factory=dict)
    default_config: dict = Field(default_factory=dict)
    aggressive_config: dict = Field(default_factory=dict)


class AITemplateRowUpdate(BaseModel):
    """前端 v2 策略模板表：单行编辑（保守/默认/激进 之一）"""
    template_type: Optional[str] = None
    gross_margin: Optional[float] = None
    default_client_price: Optional[float] = None
    max_bid: Optional[float] = None
    max_adjust_pct: Optional[float] = None
    auto_remove_losing_sku: Optional[int] = None
    losing_days_threshold: Optional[int] = None
    auto_execute: Optional[bool] = None


class EnableAIRequest(BaseModel):
    auto_execute: bool = False


class RestoreSkuRequest(BaseModel):
    platform_sku_id: str


class BatchIdsRequest(BaseModel):
    ids: list


class AnalyzeRequest(BaseModel):
    campaign_ids: list = Field(default_factory=list)


# ==================== §1 状态栏 ====================

@router.get("/dashboard/{shop_id}")
def get_dashboard(
    shop: Shop = Depends(get_owned_shop),
    db: Session = Depends(get_db),
):
    """状态栏：莫斯科时间 + 当前时段 + 下次执行 + 最后执行"""
    data = get_dashboard_info(db, shop.id, shop.tenant_id)
    return success(data)


# ==================== §2 分时调价 ====================

@router.get("/time-pricing/{shop_id}")
def get_time_pricing(
    shop: Shop = Depends(get_owned_shop),
    db: Session = Depends(get_db),
):
    row = db.execute(text("""
        SELECT id, tenant_id, shop_id, is_active,
               peak_hours, peak_ratio, mid_hours, mid_ratio,
               low_hours, low_ratio,
               last_executed_at, last_execute_result,
               updated_at
        FROM time_pricing_rules
        WHERE shop_id = :shop_id AND tenant_id = :tenant_id
    """), {"shop_id": shop.id, "tenant_id": shop.tenant_id}).fetchone()

    if not row:
        return success({
            "shop_id": shop.id,
            "is_active": False,
            "peak_hours": [10, 11, 12, 13, 19, 20, 21, 22],
            "peak_ratio": 120,
            "mid_hours": [7, 8, 9, 14, 15, 16, 17, 18],
            "mid_ratio": 100,
            "low_hours": [0, 1, 2, 3, 4, 5, 6, 23],
            "low_ratio": 60,
            "last_executed_at": None,
            "last_execute_result": None,
            "updated_at": None,
        })

    return success({
        "id": row.id,
        "tenant_id": row.tenant_id,
        "shop_id": row.shop_id,
        "is_active": bool(row.is_active),
        "peak_hours": _safe_json(row.peak_hours, []),
        "peak_ratio": row.peak_ratio,
        "mid_hours": _safe_json(row.mid_hours, []),
        "mid_ratio": row.mid_ratio,
        "low_hours": _safe_json(row.low_hours, []),
        "low_ratio": row.low_ratio,
        "last_executed_at": row.last_executed_at.isoformat() if row.last_executed_at else None,
        "last_execute_result": row.last_execute_result,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    })


@router.put("/time-pricing/{shop_id}")
def update_time_pricing(
    req: TimePricingUpdate,
    shop: Shop = Depends(get_owned_shop),
    db: Session = Depends(get_db),
):
    from app.services.bid.time_pricing_executor import update_rule
    result = update_rule(db, shop.tenant_id, shop.id, req.model_dump())
    if result.get("code") != 0:
        return error(result["code"], result.get("msg") or "")
    return get_time_pricing(shop=shop, db=db)


@router.post("/time-pricing/{shop_id}/enable")
async def enable_time_pricing(
    shop: Shop = Depends(get_owned_shop),
    db: Session = Depends(get_db),
):
    from app.services.bid.time_pricing_executor import enable, execute
    result = enable(db, shop.tenant_id, shop.id)
    if result.get("code") != 0:
        return error(result["code"], result.get("msg") or "")
    # 启用后立即执行一次（填充 ad_groups + original_bid）
    try:
        exec_result = await execute(db, shop.id, shop.tenant_id)
        logger.info(f"分时调价启用后立即执行: {exec_result}")
    except Exception as e:
        logger.warning(f"分时调价启用后执行失败（不影响启用）: {e}")
    return success({"shop_id": shop.id, "is_active": True, "next_execute_at": _next_execute_str()})


@router.post("/time-pricing/{shop_id}/disable")
async def disable_time_pricing(
    shop: Shop = Depends(get_owned_shop),
    db: Session = Depends(get_db),
):
    from app.services.bid.time_pricing_executor import disable
    result = await disable(db, shop.tenant_id, shop.id)
    if result.get("code") != 0:
        return error(result["code"], result.get("msg") or "")
    data = result.get("data") or {}
    return success({
        "shop_id": shop.id,
        "is_active": False,
        "restored": data.get("restored", 0),
        "failed": data.get("failed", 0),
        "errors": data.get("errors", []),
    })


@router.post("/time-pricing/{shop_id}/restore-sku")
async def restore_sku(
    req: RestoreSkuRequest,
    shop: Shop = Depends(get_owned_shop),
    db: Session = Depends(get_db),
):
    from app.services.bid.time_pricing_executor import restore_sku as restore_fn
    result = await restore_fn(db, shop.tenant_id, shop.id, req.platform_sku_id)
    if result.get("code") != 0:
        return error(result["code"], result.get("msg") or "")
    return success(result.get("data") or {})


@router.get("/time-pricing/{shop_id}/status")
async def get_time_pricing_status(
    campaign_id: int = Query(None),
    keyword: str = Query(None),
    shop: Shop = Depends(get_owned_shop),
    db: Session = Depends(get_db),
):
    from app.services.bid.time_pricing_executor import get_sku_status
    return success(await get_sku_status(db, shop.tenant_id, shop.id,
                                         campaign_id=campaign_id, keyword=keyword))


# ==================== §3 AI调价 ====================

@router.get("/ai-pricing/{shop_id}")
def get_ai_pricing(
    shop: Shop = Depends(get_owned_shop),
    db: Session = Depends(get_db),
):
    row = db.execute(text("""
        SELECT id, tenant_id, shop_id, is_active, auto_execute, template_name,
               conservative_config, default_config, aggressive_config,
               last_executed_at, last_execute_status, last_error_msg, retry_at
        FROM ai_pricing_configs
        WHERE shop_id = :shop_id AND tenant_id = :tenant_id
        LIMIT 1
    """), {"shop_id": shop.id, "tenant_id": shop.tenant_id}).fetchone()

    if not row:
        return success({
            "shop_id": shop.id,
            "is_active": False,
            "auto_execute": False,
            "template_name": "default",
        })

    return success({
        "id": row.id,
        "tenant_id": row.tenant_id,
        "shop_id": row.shop_id,
        "is_active": bool(row.is_active),
        "auto_execute": bool(row.auto_execute),
        "template_name": row.template_name,
        "conservative_config": _safe_json(row.conservative_config, {}),
        "default_config": _safe_json(row.default_config, {}),
        "aggressive_config": _safe_json(row.aggressive_config, {}),
        "last_executed_at": row.last_executed_at.isoformat() if row.last_executed_at else None,
        "last_execute_status": row.last_execute_status,
        "last_error_msg": row.last_error_msg,
        "retry_at": row.retry_at.isoformat() if row.retry_at else None,
    })


@router.put("/ai-pricing/{shop_id}")
def update_ai_pricing(
    req: AIConfigUpdate,
    shop: Shop = Depends(get_owned_shop),
    db: Session = Depends(get_db),
):
    from app.services.bid.ai_pricing_executor import update_config
    result = update_config(db, shop.tenant_id, shop.id, req.model_dump())
    if result.get("code") != 0:
        return error(result["code"], result.get("msg") or "")
    return get_ai_pricing(shop=shop, db=db)


# ==================== §3.x 前端 v2 策略模板兼容接口 ====================
# 前端把 ai_pricing_configs 当作 3 行模板表渲染（保守/默认/激进）
# 后端把单行 3 嵌套 JSON 摊平成数组；写回时按 template_type 回填

_TEMPLATE_TYPES = ("conservative", "default", "aggressive")
_TEMPLATE_LABELS = {"conservative": "保守", "default": "默认", "aggressive": "激进"}


def _flatten_template_rows(row) -> list:
    """店铺级单策略：只返回 default 档一行，表示"店铺策略"。
    conservative/aggressive JSON 字段保留不动，便于未来恢复多档。
    """
    if row is None:
        return []
    cfg = _safe_json(getattr(row, "default_config", None), {})
    return [{
        "id": f"{row.id}:default",
        "shop_id": row.shop_id,
        "tenant_id": row.tenant_id,
        "template_type": "default",
        "template_name": "店铺策略",
        "gross_margin": cfg.get("gross_margin"),
        "default_client_price": float(row.default_client_price or 600.0),
        "max_bid": cfg.get("max_bid"),
        "max_adjust_pct": cfg.get("max_adjust_pct"),
        "auto_remove_losing_sku": int(row.auto_remove_losing_sku or 0),
        "losing_days_threshold": int(row.losing_days_threshold or 21),
        "auto_execute": bool(row.auto_execute),
        "is_current": True,
    }]


@router.get("/ai-pricing/configs/{shop_id}")
def list_ai_pricing_templates(
    shop: Shop = Depends(get_owned_shop),
    db: Session = Depends(get_db),
):
    """返回 3 行虚拟模板数组（保守/默认/激进），供前端 v2 策略模板表渲染"""
    row = db.execute(text("""
        SELECT id, tenant_id, shop_id, is_active, auto_execute, template_name,
               conservative_config, default_config, aggressive_config,
               default_client_price, auto_remove_losing_sku, losing_days_threshold
        FROM ai_pricing_configs
        WHERE shop_id = :shop_id AND tenant_id = :tenant_id
        LIMIT 1
    """), {"shop_id": shop.id, "tenant_id": shop.tenant_id}).fetchone()

    if not row:
        # 无配置行：返回 1 行兜底默认值，用户编辑后首次 PUT 会 INSERT
        from app.services.bid.ai_pricing_executor import _DEFAULT_DEFAULT
        return success([{
            "id": "new:default",
            "shop_id": shop.id,
            "tenant_id": shop.tenant_id,
            "template_type": "default",
            "template_name": "店铺策略",
            "gross_margin": _DEFAULT_DEFAULT.get("gross_margin"),
            "default_client_price": 600.0,
            "max_bid": _DEFAULT_DEFAULT.get("max_bid"),
            "max_adjust_pct": _DEFAULT_DEFAULT.get("max_adjust_pct"),
            "auto_remove_losing_sku": 0,
            "losing_days_threshold": 21,
            "auto_execute": False,
            "is_current": True,
        }])

    return success(_flatten_template_rows(row))


@router.put("/ai-pricing/configs/{shop_id}")
def update_ai_pricing_template(
    req: AITemplateRowUpdate,
    shop: Shop = Depends(get_owned_shop),
    db: Session = Depends(get_db),
):
    """前端 v2 单行模板编辑：按 template_type 回写到对应 *_config JSON
    + top-level 字段（default_client_price/auto_remove_losing_sku/losing_days_threshold）
    因为 top-level 字段在 3 档模板之间共享，编辑任何一行都会同步更新
    """
    from app.services.bid.ai_pricing_executor import update_config

    ttype = req.template_type or "default"
    if ttype not in _TEMPLATE_TYPES:
        return error(ErrorCode.PARAM_ERROR,
                     "template_type 必须是 conservative/default/aggressive")

    # 先读当前行，缺失字段用现值兜底（update_config 对 top-level 字段是无条件覆盖）
    cur = db.execute(text("""
        SELECT template_name, auto_execute, default_client_price,
               auto_remove_losing_sku, losing_days_threshold,
               conservative_config, default_config, aggressive_config
        FROM ai_pricing_configs
        WHERE shop_id = :shop_id AND tenant_id = :tenant_id
        LIMIT 1
    """), {"shop_id": shop.id, "tenant_id": shop.tenant_id}).fetchone()

    # 构造传给 update_config 的 payload：目标模板的 JSON + 共享字段
    cur_template_json = _safe_json(getattr(cur, f"{ttype}_config", None), {}) if cur else {}
    template_json = dict(cur_template_json)
    if req.gross_margin is not None:
        template_json["gross_margin"] = float(req.gross_margin)
    if req.max_bid is not None:
        template_json["max_bid"] = float(req.max_bid)
    if req.max_adjust_pct is not None:
        template_json["max_adjust_pct"] = float(req.max_adjust_pct)

    payload = {
        f"{ttype}_config": template_json,
        "template_name": cur.template_name if cur else "default",
        "auto_execute": bool(cur.auto_execute) if cur else False,
        "default_client_price": float(cur.default_client_price) if cur else 600.0,
        "auto_remove_losing_sku": bool(cur.auto_remove_losing_sku) if cur else False,
        "losing_days_threshold": int(cur.losing_days_threshold) if cur else 21,
    }
    if req.default_client_price is not None:
        payload["default_client_price"] = float(req.default_client_price)
    if req.auto_remove_losing_sku is not None:
        payload["auto_remove_losing_sku"] = bool(req.auto_remove_losing_sku)
    if req.losing_days_threshold is not None:
        payload["losing_days_threshold"] = int(req.losing_days_threshold)
    if req.auto_execute is not None:
        payload["auto_execute"] = bool(req.auto_execute)

    result = update_config(db, shop.tenant_id, shop.id, payload)
    if result.get("code") != 0:
        return error(result["code"], result.get("msg") or "")

    # 返回更新后的摊平数组
    return list_ai_pricing_templates(shop=shop, db=db)


@router.post("/ai-pricing/{shop_id}/enable")
def enable_ai_pricing(
    req: EnableAIRequest,
    shop: Shop = Depends(get_owned_shop),
    db: Session = Depends(get_db),
):
    from app.services.bid.ai_pricing_executor import enable
    result = enable(db, shop.tenant_id, shop.id, auto_execute=req.auto_execute)
    if result.get("code") != 0:
        return error(result["code"], result.get("msg") or "")
    return success({"shop_id": shop.id, "is_active": True, "auto_execute": req.auto_execute})


@router.post("/ai-pricing/{shop_id}/disable")
def disable_ai_pricing(
    shop: Shop = Depends(get_owned_shop),
    db: Session = Depends(get_db),
):
    from app.services.bid.ai_pricing_executor import disable
    disable(db, shop.tenant_id, shop.id)
    return success({"shop_id": shop.id, "is_active": False})


@router.post("/ai-pricing/{shop_id}/analyze")
async def manual_analyze(
    req: AnalyzeRequest = None,
    shop: Shop = Depends(get_owned_shop),
    db: Session = Depends(get_db),
):
    from app.services.bid.ai_pricing_executor import analyze_now
    campaign_ids = req.campaign_ids if req else None
    result = await analyze_now(db, shop.tenant_id, shop.id, force=True, campaign_ids=campaign_ids)
    if result.get("status") == "failed":
        return error(ErrorCode.AI_MODEL_ERROR, result.get("message") or "")
    return success({
        "shop_id": shop.id,
        "analyzed_count": result.get("analyzed_count", 0),
        "suggestion_count": result.get("suggestion_count", 0),
        "auto_executed_count": result.get("auto_executed_count", 0),
        "time_cost_ms": result.get("time_cost_ms", 0),
        "suggestions": result.get("suggestions", []),
    })


@router.get("/ai-pricing/{shop_id}/diagnostic")
def ai_pricing_diagnostic(
    shop: Shop = Depends(get_owned_shop),
    db: Session = Depends(get_db),
):
    """AI调价诊断概览：按 days 分档展示所有 active 活动下的 SKU 状态

    分档：
      - full_data(>=10天): 可全量决策（加价+降价）
      - short_data(7-9天): 仅可降价（硬规则B）
      - cold_start(<7天): 攒数据中，AI 不动
    """
    platform = shop.platform
    # WB 的 ad_stats 记录 ad_group_id 必须非空; Ozon 老数据可能 NULL (设计所限, 不展示)
    sku_filter = "AND s.ad_group_id IS NOT NULL"

    rows = db.execute(text(f"""
        SELECT c.id AS campaign_id, c.name AS campaign_name,
               s.ad_group_id AS sku_id,
               COUNT(DISTINCT s.stat_date) AS days,
               SUM(s.spend) AS spend,
               SUM(s.revenue) AS revenue,
               SUM(s.orders) AS orders,
               SUM(s.clicks) AS clicks,
               SUM(s.impressions) AS impressions
        FROM ad_stats s
        JOIN ad_campaigns c ON s.campaign_id = c.id
        WHERE c.shop_id = :sid AND c.tenant_id = :tid
          AND s.platform = :p
          AND c.status = 'active'
          AND s.stat_date >= DATE_SUB(CURDATE(), INTERVAL 10 DAY)
          {sku_filter}
        GROUP BY c.id, s.ad_group_id
        ORDER BY days DESC, revenue DESC
    """), {"sid": shop.id, "tid": shop.tenant_id, "p": platform}).fetchall()

    items = []
    cold = short = full = 0
    for r in rows:
        days = int(r.days or 0)
        spend = float(r.spend or 0)
        revenue = float(r.revenue or 0)
        roas = round(revenue / spend, 2) if spend > 0 else 0
        if days < 7:
            bucket = "cold_start"
            cold += 1
        elif days < 10:
            bucket = "short_data"
            short += 1
        else:
            bucket = "full_data"
            full += 1
        items.append({
            "sku": str(r.sku_id),
            "campaign_id": r.campaign_id,
            "campaign_name": r.campaign_name,
            "days": days,
            "roas": roas,
            "spend": round(spend, 2),
            "revenue": round(revenue, 2),
            "orders": int(r.orders or 0),
            "clicks": int(r.clicks or 0),
            "impressions": int(r.impressions or 0),
            "bucket": bucket,
        })

    return success({
        "total": len(items),
        "cold_start_count": cold,
        "short_data_count": short,
        "full_data_count": full,
        "items": items,
    })


@router.get("/ai-pricing/{shop_id}/analyze-stream")
async def analyze_stream_sse(
    shop: Shop = Depends(get_owned_shop),
    db: Session = Depends(get_db),
):
    """流式 AI 分析（SSE），前端实时展示分析过程"""
    from app.services.bid.ai_pricing_executor import analyze_stream
    return StreamingResponse(
        analyze_stream(db, shop.tenant_id, shop.id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ==================== §4 建议列表 ====================

@router.get("/suggestions/{shop_id}")
def get_suggestions(
    status: str = Query("pending"),
    campaign_id: int = Query(None),
    shop: Shop = Depends(get_owned_shop),
    db: Session = Depends(get_db),
):
    """按活动分组返回今日 status 状态的建议"""
    from app.utils.moscow_time import moscow_today
    today = moscow_today()
    where = ["s.shop_id = :shop_id", "s.tenant_id = :tenant_id", "DATE(s.generated_at) = :today", "c.status = 'active'"]
    params = {"shop_id": shop.id, "tenant_id": shop.tenant_id, "today": today}
    if status and status != "all":
        where.append("s.status = :status")
        params["status"] = status
    if campaign_id:
        where.append("s.campaign_id = :campaign_id")
        params["campaign_id"] = campaign_id

    rows = db.execute(text(f"""
        SELECT
            s.id, s.tenant_id, s.shop_id, s.campaign_id,
            s.platform_sku_id, s.sku_name,
            s.current_bid, s.suggested_bid, s.adjust_pct,
            s.product_stage, s.decision_basis,
            s.current_roas, s.expected_roas, s.data_days, s.reason,
            s.status, s.generated_at, s.executed_at,
            c.name AS campaign_name, c.platform_campaign_id,
            pl.url AS product_url,
            pl.platform_product_id AS platform_product_id,
            p.sku AS product_code,
            p.image_url AS image_url,
            COALESCE(ag.user_managed, 0) AS is_ignored
        FROM ai_pricing_suggestions s
        JOIN ad_campaigns c ON s.campaign_id = c.id
        -- Ozon: s.platform_sku_id 存的是广告 SKU，匹配 pl.platform_sku_id（不是 platform_product_id）
        -- WB:   两者相等（nm_id 同时是 platform_sku_id 和 platform_product_id），也能匹配
        LEFT JOIN platform_listings pl
          ON pl.tenant_id = s.tenant_id
         AND pl.shop_id = s.shop_id
         AND pl.platform_sku_id = s.platform_sku_id
        LEFT JOIN products p ON p.id = pl.product_id
        LEFT JOIN ad_groups ag
          ON ag.tenant_id = s.tenant_id
         AND ag.campaign_id = s.campaign_id
         AND ag.platform_group_id = s.platform_sku_id
        WHERE {' AND '.join(where)}
        ORDER BY c.name, s.platform_sku_id
    """), params).fetchall()

    groups = {}
    for r in rows:
        cid = r.campaign_id
        if cid not in groups:
            groups[cid] = {
                "campaign_id": cid,
                "campaign_name": r.campaign_name,
                "platform_campaign_id": r.platform_campaign_id,
                "suggestions": [],
            }
        groups[cid]["suggestions"].append({
            "id": r.id,
            "platform_sku_id": r.platform_sku_id,
            "platform_product_id": r.platform_product_id,
            "product_code": r.product_code,
            "sku_name": r.sku_name,
            "current_bid": float(r.current_bid),
            "suggested_bid": float(r.suggested_bid),
            "adjust_pct": float(r.adjust_pct),
            "product_stage": r.product_stage,
            "decision_basis": r.decision_basis,
            "current_roas": float(r.current_roas) if r.current_roas is not None else None,
            "expected_roas": float(r.expected_roas) if r.expected_roas is not None else None,
            "data_days": r.data_days,
            "reason": r.reason,
            "status": r.status,
            "generated_at": r.generated_at.isoformat() if r.generated_at else None,
            "executed_at": r.executed_at.isoformat() if r.executed_at else None,
            "image_url": r.image_url,
            "product_url": r.product_url,
            "is_ignored": bool(r.is_ignored),
        })

    return success({
        "date_moscow": today.isoformat(),
        "campaigns": list(groups.values()),
    })


class ApproveRequest(BaseModel):
    suggested_bid: Optional[float] = None


@router.post("/suggestions/{suggestion_id}/approve")
async def approve_suggestion(
    suggestion_id: int,
    req: ApproveRequest = None,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """注：按建议ID操作，不带 shop_id；service 层用 tenant_id 校验
    可选 suggested_bid：用户手动修改后的出价，覆盖 AI 建议值"""
    from app.services.bid.ai_pricing_executor import approve_suggestion as approve_fn
    override_bid = req.suggested_bid if req else None
    result = await approve_fn(db, tenant_id, suggestion_id, override_bid=override_bid)
    if result.get("code") != 0:
        return error(result["code"], result.get("msg") or "")
    return success(result.get("data") or {})


@router.post("/suggestions/{suggestion_id}/reject")
def reject_suggestion(
    suggestion_id: int,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    from app.services.bid.ai_pricing_executor import reject_suggestion as reject_fn
    result = reject_fn(db, tenant_id, suggestion_id)
    return success(result.get("data") or {})


@router.post("/suggestions/{suggestion_id}/ignore")
def ignore_suggestion(
    suggestion_id: int,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """忽略建议 → 该 SKU 长期不参与自动调价/删除（set user_managed=1）"""
    row = db.execute(text("""
        SELECT campaign_id, platform_sku_id, sku_name
        FROM ai_pricing_suggestions
        WHERE id = :id AND tenant_id = :tid
    """), {"id": suggestion_id, "tid": tenant_id}).fetchone()
    if not row:
        return error(ErrorCode.BID_SUGGESTION_NOT_FOUND, "建议不存在")

    # upsert ad_groups: 如果没记录就新建，user_managed=1
    db.execute(text("""
        INSERT INTO ad_groups (
            tenant_id, campaign_id, platform_group_id, name,
            user_managed, user_managed_at, status
        ) VALUES (
            :tid, :cid, :sku, :name, 1, NOW(), 'active'
        )
        ON DUPLICATE KEY UPDATE
            user_managed = 1,
            user_managed_at = NOW(),
            updated_at = NOW()
    """), {
        "tid": tenant_id, "cid": row.campaign_id,
        "sku": row.platform_sku_id,
        "name": (row.sku_name or f"SKU-{row.platform_sku_id}")[:200],
    })
    db.commit()
    return success({"id": suggestion_id, "is_ignored": True})


@router.post("/suggestions/{suggestion_id}/restore")
def restore_suggestion(
    suggestion_id: int,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """取消忽略 → 该 SKU 重新参与自动调价（set user_managed=0）"""
    row = db.execute(text("""
        SELECT campaign_id, platform_sku_id
        FROM ai_pricing_suggestions
        WHERE id = :id AND tenant_id = :tid
    """), {"id": suggestion_id, "tid": tenant_id}).fetchone()
    if not row:
        return error(ErrorCode.BID_SUGGESTION_NOT_FOUND, "建议不存在")

    db.execute(text("""
        UPDATE ad_groups
        SET user_managed = 0, user_managed_at = NULL, updated_at = NOW()
        WHERE tenant_id = :tid AND campaign_id = :cid
          AND platform_group_id = :sku
    """), {
        "tid": tenant_id, "cid": row.campaign_id,
        "sku": row.platform_sku_id,
    })
    db.commit()
    return success({"id": suggestion_id, "is_ignored": False})


@router.post("/suggestions/{suggestion_id}/remove-product")
async def remove_product_from_campaign(
    suggestion_id: int,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """从平台活动中移除商品（建议删除）"""
    row = db.execute(text("""
        SELECT s.id, s.shop_id, s.campaign_id, s.platform_sku_id, s.sku_name,
               c.platform_campaign_id, c.name AS campaign_name
        FROM ai_pricing_suggestions s
        JOIN ad_campaigns c ON s.campaign_id = c.id
        WHERE s.id = :id AND s.tenant_id = :tenant_id
    """), {"id": suggestion_id, "tenant_id": tenant_id}).fetchone()

    if not row:
        return error(ErrorCode.BID_SUGGESTION_NOT_FOUND, "建议不存在")

    from app.models.shop import Shop
    shop = db.query(Shop).filter(Shop.id == row.shop_id, Shop.tenant_id == tenant_id).first()
    if not shop:
        return error(ErrorCode.SHOP_NOT_FOUND, "店铺不存在")

    from app.services.bid.ai_pricing_executor import _create_platform_client
    client = _create_platform_client(shop)
    try:
        result = await client.remove_campaign_product(
            str(row.platform_campaign_id), str(row.platform_sku_id)
        )
    finally:
        await client.close()

    if not result.get("ok"):
        return error(ErrorCode.BID_EXECUTION_FAILED, result.get("error") or "移除失败")

    # 标记建议为 rejected
    db.execute(text("""
        UPDATE ai_pricing_suggestions SET status = 'rejected' WHERE id = :id AND tenant_id = :tid
    """), {"id": suggestion_id, "tid": tenant_id})
    # 删除 ad_groups 记录
    db.execute(text("""
        DELETE FROM ad_groups WHERE campaign_id = :cid AND platform_group_id = :sku AND tenant_id = :tid
    """), {"cid": row.campaign_id, "sku": row.platform_sku_id, "tid": tenant_id})
    db.commit()

    logger.info(f"移除商品 campaign={row.campaign_name} sku={row.platform_sku_id}")
    return success({"removed": True, "campaign": row.campaign_name, "sku": row.platform_sku_id})


@router.post("/suggestions/approve-batch")
async def approve_batch(
    req: BatchIdsRequest,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    from app.services.bid.ai_pricing_executor import approve_batch as approve_fn
    result = await approve_fn(db, tenant_id, req.ids)
    return success(result.get("data") or {})


@router.post("/suggestions/reject-batch")
def reject_batch(
    req: BatchIdsRequest,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    from app.services.bid.ai_pricing_executor import reject_batch as reject_fn
    result = reject_fn(db, tenant_id, req.ids)
    return success(result.get("data") or {})


# ==================== §5 冲突检测 ====================

@router.get("/conflict-check/{shop_id}")
def conflict_check(
    enabling: str = Query(..., description="time_pricing | ai_auto"),
    shop: Shop = Depends(get_owned_shop),
    db: Session = Depends(get_db),
):
    row = db.execute(text("""
        SELECT
            (SELECT is_active FROM time_pricing_rules
             WHERE shop_id = :sid AND tenant_id = :tid LIMIT 1) AS time_active,
            (SELECT is_active FROM ai_pricing_configs
             WHERE shop_id = :sid AND tenant_id = :tid LIMIT 1) AS ai_active
    """), {"sid": shop.id, "tid": shop.tenant_id}).fetchone()

    if not row:
        return success({"conflict": False, "message": "可以启用"})

    if enabling == "time_pricing" and row.ai_active:
        return success({
            "conflict": True,
            "current_active": "ai_auto",
            "message": "AI调价已启用，启用分时调价前请先停用AI调价",
            "action": "disable_ai_first",
        })
    if enabling == "ai_auto" and row.time_active:
        return success({
            "conflict": True,
            "current_active": "time_pricing",
            "message": "分时调价已启用，启用AI调价前请先停用分时调价",
            "action": "disable_time_first",
        })
    return success({"conflict": False, "message": "可以启用"})


# ==================== §6 调价历史 ====================

@router.get("/bid-logs/{shop_id}")
def get_bid_logs(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    execute_type: str = Query("all"),
    campaign_id: int = Query(None),
    start_date: str = Query(None),
    end_date: str = Query(None),
    success_filter: bool = Query(None, alias="success"),
    shop: Shop = Depends(get_owned_shop),
    db: Session = Depends(get_db),
):
    where = ["shop_id = :shop_id", "tenant_id = :tenant_id"]
    params = {"shop_id": shop.id, "tenant_id": shop.tenant_id}
    if execute_type and execute_type != "all":
        where.append("execute_type = :execute_type")
        params["execute_type"] = execute_type
    if campaign_id:
        where.append("campaign_id = :campaign_id")
        params["campaign_id"] = campaign_id
    if start_date:
        where.append("DATE(created_at) >= :start_date")
        params["start_date"] = start_date
    if end_date:
        where.append("DATE(created_at) <= :end_date")
        params["end_date"] = end_date
    if success_filter is not None:
        where.append("success = :success")
        params["success"] = 1 if success_filter else 0

    where_sql = " AND ".join(where)
    total = db.execute(
        text(f"SELECT COUNT(*) AS total FROM bid_adjustment_logs WHERE {where_sql}"),
        params,
    ).fetchone().total

    page_params = dict(params)
    page_params["limit"] = size
    page_params["offset"] = (page - 1) * size
    rows = db.execute(text(f"""
        SELECT
            id, tenant_id, shop_id, campaign_id, campaign_name,
            platform_sku_id, sku_name,
            old_bid, new_bid, adjust_pct,
            execute_type, time_period, period_ratio,
            product_stage, moscow_hour, success, error_msg, created_at
        FROM bid_adjustment_logs
        WHERE {where_sql}
        ORDER BY created_at DESC
        LIMIT :limit OFFSET :offset
    """), page_params).fetchall()

    items = [{
        "id": r.id,
        "campaign_id": r.campaign_id,
        "campaign_name": r.campaign_name,
        "platform_sku_id": r.platform_sku_id,
        "sku_name": r.sku_name,
        "old_bid": float(r.old_bid),
        "new_bid": float(r.new_bid),
        "adjust_pct": float(r.adjust_pct),
        "execute_type": r.execute_type,
        "time_period": r.time_period,
        "period_ratio": r.period_ratio,
        "product_stage": r.product_stage,
        "moscow_hour": r.moscow_hour,
        "success": bool(r.success),
        "error_msg": r.error_msg,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    } for r in rows]

    return success({"total": total, "page": page, "size": size, "items": items})


# ==================== §7 数据源 ====================

@router.get("/data-status/{shop_id}")
def get_data_status(
    shop: Shop = Depends(get_owned_shop),
    db: Session = Depends(get_db),
):
    row = db.execute(text("""
        SELECT is_initialized, initialized_at, last_sync_at, last_sync_date,
               COALESCE(data_days, 0) AS data_days
        FROM shop_data_init_status
        WHERE shop_id = :shop_id AND tenant_id = :tenant_id
    """), {"shop_id": shop.id, "tenant_id": shop.tenant_id}).fetchone()

    if not row:
        return success({
            "shop_id": shop.id,
            "is_initialized": False,
            "initialized_at": None,
            "last_sync_at": None,
            "last_sync_date": None,
            "data_days": 0,
        })

    def _iso_utc(dt):
        if dt is None:
            return None
        if hasattr(dt, "tzinfo") and dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()

    return success({
        "shop_id": shop.id,
        "is_initialized": bool(row.is_initialized),
        "initialized_at": _iso_utc(row.initialized_at),
        "last_sync_at": _iso_utc(row.last_sync_at),
        "last_sync_date": row.last_sync_date.isoformat() if row.last_sync_date else None,
        "data_days": row.data_days,
    })


@router.post("/data-sync/{shop_id}")
async def sync_data(
    shop: Shop = Depends(get_owned_shop),
    db: Session = Depends(get_db),
):
    """智能数据同步：先检查是否已最新（秒回），需要拉取时后台执行。"""
    import asyncio as _asyncio
    import threading
    from datetime import date as _date, timedelta as _td

    from app.database import SessionLocal

    platform_label = "Wildberries" if shop.platform == "wb" else "Ozon"
    platform_code = shop.platform

    # 记录本次同步请求时间（前端 /shops/{id} 读取此字段判断是否需要自动同步）
    from datetime import datetime as _dt, timezone as _tz
    shop.last_sync_at = _dt.now(_tz.utc)
    db.commit()

    # 快速检查：45 天窗口内是否全齐
    # 从 sync_helper 复用常量和缺失检测
    if platform_code == "wb":
        from app.services.data.wb_stats_collector import MAX_KEEP_DAYS, FIRST_SYNC_DAYS
    else:
        from app.services.data.ozon_stats_collector import MAX_KEEP_DAYS, FIRST_SYNC_DAYS
    from app.services.data.sync_helper import find_missing_ranges

    ranges, _is_first = find_missing_ranges(
        db, shop.id, shop.tenant_id, platform_code,
        MAX_KEEP_DAYS, FIRST_SYNC_DAYS,
    )

    if not ranges:
        return success({
            "shop_id": shop.id,
            "msg": "数据已是最新，无需更新",
            "synced": 0,
            "already_latest": True,
            "data_days": db.execute(text("""
                SELECT COUNT(DISTINCT s.stat_date) FROM ad_stats s
                JOIN ad_campaigns c ON s.campaign_id = c.id
                WHERE c.shop_id = :sid AND c.tenant_id = :tid AND s.platform = :p
            """), {"sid": shop.id, "tid": shop.tenant_id, "p": platform_code}).scalar() or 0,
        })

    # 需要拉数据：后台执行
    if platform_code == "wb":
        from app.services.data.wb_stats_collector import smart_sync
    else:
        from app.services.data.ozon_stats_collector import smart_sync

    s_id, t_id = shop.id, shop.tenant_id

    def _run_sync():
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.config import get_settings
        settings = get_settings()
        engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True, pool_size=2)
        Session = sessionmaker(bind=engine)
        new_db = Session()
        loop = _asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(smart_sync(new_db, s_id, t_id))
            logger.info(f"{platform_label} 后台同步完成 shop_id={s_id}: {result}")
        except Exception as e:
            logger.error(f"{platform_label} 后台同步失败 shop_id={s_id}: {e}")
        finally:
            new_db.close()
            engine.dispose()
            loop.close()

    thread = threading.Thread(target=_run_sync, daemon=True)
    thread.start()

    return success({
        "shop_id": shop.id,
        "msg": f"{platform_label} 数据同步已在后台启动，预计10-20分钟完成。请稍后刷新查看。",
        "synced": 0,
        "already_latest": False,
        "background": True,
    })


@router.get("/data-download/{shop_id}")
def download_data(
    days: int = Query(30, ge=1, le=180),
    shop: Shop = Depends(get_owned_shop),
    db: Session = Depends(get_db),
):
    """下载 Excel 数据源"""
    try:
        import openpyxl
    except ImportError:
        return error(ErrorCode.UNKNOWN_ERROR, "openpyxl 未安装")

    rows = db.execute(text("""
        SELECT
            c.platform_campaign_id,
            c.platform AS platform,
            s.ad_group_id AS sku_id,
            s.stat_date,
            s.impressions, s.clicks, s.spend,
            s.orders, s.revenue
        FROM ad_stats s
        JOIN ad_campaigns c ON s.campaign_id = c.id
        WHERE c.shop_id = :shop_id
          AND c.tenant_id = :tenant_id
          AND c.platform = :platform
          AND s.stat_date >= DATE_SUB(CURDATE(), INTERVAL :days DAY)
        ORDER BY s.stat_date DESC, c.platform_campaign_id, s.ad_group_id
    """), {
        "shop_id": shop.id,
        "tenant_id": shop.tenant_id,
        "platform": shop.platform,
        "days": days,
    }).fetchall()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "广告数据"
    ws.append([
        "平台活动ID", "商品SKU", "日期",
        "曝光", "点击", "花费(₽)", "订单数", "收入(₽)",
    ])
    for r in rows:
        ws.append([
            r.platform_campaign_id,
            r.sku_id or "",
            r.stat_date.isoformat() if r.stat_date else "",
            r.impressions or 0, r.clicks or 0,
            float(r.spend or 0), r.orders or 0,
            float(r.revenue or 0),
        ])

    output = BytesIO()
    wb.save(output)
    output.seek(0)
    today = now_moscow().strftime("%Y%m%d")
    filename = f"shop_{shop.id}_bid_data_{today}.xlsx"
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ==================== 工具 ====================

def _safe_json(value, default):
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return default
    return default


def _next_execute_str() -> str:
    """计算下次 :05 执行点的 HH:MM"""
    now = now_moscow()
    if now.minute < EXECUTE_MINUTE:
        h = now.hour
    else:
        h = (now.hour + 1) % 24
    return f"{h:02d}:{EXECUTE_MINUTE:02d}"
