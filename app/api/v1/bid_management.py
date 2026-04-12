"""出价管理 API 路由（按老林审查报告 V2 修复版）

修复点（对照 docs/daily/2026-04-11_审查报告_出价管理_老林.md）：
  - #1-#6 路由层多租户隔离：所有 {shop_id} 路径参数路由统一使用 Depends(get_owned_shop)
  - service 层 tenant_id 透传

路径前缀: /api/v1/bid-management
"""

import json
from io import BytesIO
from datetime import datetime, timezone

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
def enable_time_pricing(
    shop: Shop = Depends(get_owned_shop),
    db: Session = Depends(get_db),
):
    from app.services.bid.time_pricing_executor import enable
    result = enable(db, shop.tenant_id, shop.id)
    if result.get("code") != 0:
        return error(result["code"], result.get("msg") or "")
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
    where = ["s.shop_id = :shop_id", "s.tenant_id = :tenant_id", "DATE(s.generated_at) = :today"]
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
            c.name AS campaign_name, c.platform_campaign_id
        FROM ai_pricing_suggestions s
        JOIN ad_campaigns c ON s.campaign_id = c.id
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
        })

    return success({
        "date_moscow": today.isoformat(),
        "campaigns": list(groups.values()),
    })


@router.post("/suggestions/{suggestion_id}/approve")
async def approve_suggestion(
    suggestion_id: int,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """注：按建议ID操作，不带 shop_id；service 层用 tenant_id 校验"""
    from app.services.bid.ai_pricing_executor import approve_suggestion as approve_fn
    result = await approve_fn(db, tenant_id, suggestion_id)
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
    """智能数据同步：无数据拉30天，有数据增量补齐，清理90天前旧数据（按平台分流）"""
    if shop.platform == "wb":
        from app.services.data.wb_stats_collector import smart_sync
    else:
        from app.services.data.ozon_stats_collector import smart_sync

    try:
        result = await smart_sync(db, shop.id, shop.tenant_id)
        if result.get("already_latest"):
            return success({
                "shop_id": shop.id,
                "msg": "数据已是最新，无需更新",
                **result,
            })
        return success({
            "shop_id": shop.id,
            "msg": f"同步完成：拉取 {result['date_from']}~{result['date_to']}，"
                   f"写入 {result['synced']} 条，清理 {result['cleaned']} 条过期数据",
            **result,
        })
    except ValueError as e:
        return error(ErrorCode.AD_STATS_FETCH_FAILED, str(e))
    except Exception as e:
        logger.error(f"数据同步失败 shop_id={shop.id}: {e}")
        return error(ErrorCode.AD_STATS_FETCH_FAILED, f"同步失败: {e}")


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
            c.name AS campaign_name,
            c.platform_campaign_id,
            c.platform AS platform,
            s.ad_group_id AS sku_id,
            s.stat_date, s.stat_hour,
            s.impressions, s.clicks, s.ctr,
            s.cpc, s.spend, s.orders,
            s.revenue, s.acos, s.roas
        FROM ad_stats s
        JOIN ad_campaigns c ON s.campaign_id = c.id
        WHERE c.shop_id = :shop_id
          AND c.tenant_id = :tenant_id
          AND c.platform = :platform
          AND s.stat_date >= DATE_SUB(CURDATE(), INTERVAL :days DAY)
        ORDER BY c.name, s.stat_date DESC, s.ad_group_id
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
        "活动名称", "平台活动ID", "商品SKU", "日期", "小时",
        "曝光", "点击", "CTR(%)",
        "CPC(₽)", "花费(₽)", "订单数",
        "收入(₽)", "ACOS(%)", "ROAS",
    ])
    for r in rows:
        ws.append([
            r.campaign_name, r.platform_campaign_id,
            r.sku_id or "",
            r.stat_date.isoformat() if r.stat_date else "", r.stat_hour,
            r.impressions or 0, r.clicks or 0, float(r.ctr or 0),
            float(r.cpc or 0), float(r.spend or 0), r.orders or 0,
            float(r.revenue or 0), float(r.acos or 0), float(r.roas or 0),
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
