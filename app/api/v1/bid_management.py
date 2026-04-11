"""出价管理 API 路由（按 docs/api/bid_management.md 规范实现）

路径前缀: /api/v1/bid-management
"""

import json
from io import BytesIO

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db, get_tenant_id
from app.utils.errors import ErrorCode
from app.utils.logger import setup_logger
from app.utils.moscow_time import (
    EXECUTE_MINUTE, MOSCOW_TZ, get_dashboard_info, moscow_today, now_moscow,
)
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
    shop_id: int,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """状态栏：莫斯科时间 + 当前时段 + 下次执行 + 最后执行"""
    data = get_dashboard_info(db, shop_id)
    return success(data)


# ==================== §2 分时调价 ====================

@router.get("/time-pricing/{shop_id}")
def get_time_pricing(
    shop_id: int,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    row = db.execute(text("""
        SELECT id, tenant_id, shop_id, is_active,
               peak_hours, peak_ratio, mid_hours, mid_ratio,
               low_hours, low_ratio,
               last_executed_at, last_execute_result,
               updated_at
        FROM time_pricing_rules
        WHERE shop_id = :shop_id
    """), {"shop_id": shop_id}).fetchone()

    if not row:
        return success({
            "shop_id": shop_id,
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
    shop_id: int,
    req: TimePricingUpdate,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    from app.services.bid.time_pricing_executor import update_rule
    result = update_rule(db, tenant_id, shop_id, req.model_dump())
    if result.get("code") != 0:
        return error(result["code"], result.get("msg") or "")
    # 返回更新后的完整对象
    return get_time_pricing(shop_id, db, tenant_id)


@router.post("/time-pricing/{shop_id}/enable")
def enable_time_pricing(
    shop_id: int,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    from app.services.bid.time_pricing_executor import enable
    result = enable(db, tenant_id, shop_id)
    if result.get("code") != 0:
        return error(result["code"], result.get("msg") or "")
    next_str = _next_execute_str()
    return success({"shop_id": shop_id, "is_active": True, "next_execute_at": next_str})


@router.post("/time-pricing/{shop_id}/disable")
def disable_time_pricing(
    shop_id: int,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    from app.services.bid.time_pricing_executor import disable
    disable(db, shop_id)
    return success({"shop_id": shop_id, "is_active": False})


@router.post("/time-pricing/{shop_id}/restore-sku")
async def restore_sku(
    shop_id: int,
    req: RestoreSkuRequest,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    from app.services.bid.time_pricing_executor import restore_sku as restore_fn
    result = await restore_fn(db, shop_id, req.platform_sku_id)
    if result.get("code") != 0:
        return error(result["code"], result.get("msg") or "")
    return success(result.get("data") or {})


@router.get("/time-pricing/{shop_id}/status")
def get_time_pricing_status(
    shop_id: int,
    campaign_id: int = Query(None),
    keyword: str = Query(None),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    from app.services.bid.time_pricing_executor import get_sku_status
    return success(get_sku_status(db, shop_id, campaign_id=campaign_id, keyword=keyword))


# ==================== §3 AI调价 ====================

@router.get("/ai-pricing/{shop_id}")
def get_ai_pricing(
    shop_id: int,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    row = db.execute(text("""
        SELECT id, tenant_id, shop_id, is_active, auto_execute, template_name,
               conservative_config, default_config, aggressive_config,
               last_executed_at, last_execute_status, last_error_msg, retry_at
        FROM ai_pricing_configs
        WHERE shop_id = :shop_id
        LIMIT 1
    """), {"shop_id": shop_id}).fetchone()

    if not row:
        return success({
            "shop_id": shop_id,
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
    shop_id: int,
    req: AIConfigUpdate,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    from app.services.bid.ai_pricing_executor import update_config
    result = update_config(db, tenant_id, shop_id, req.model_dump())
    if result.get("code") != 0:
        return error(result["code"], result.get("msg") or "")
    return get_ai_pricing(shop_id, db, tenant_id)


@router.post("/ai-pricing/{shop_id}/enable")
def enable_ai_pricing(
    shop_id: int,
    req: EnableAIRequest,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    from app.services.bid.ai_pricing_executor import enable
    result = enable(db, tenant_id, shop_id, auto_execute=req.auto_execute)
    if result.get("code") != 0:
        return error(result["code"], result.get("msg") or "")
    return success({"shop_id": shop_id, "is_active": True, "auto_execute": req.auto_execute})


@router.post("/ai-pricing/{shop_id}/disable")
def disable_ai_pricing(
    shop_id: int,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    from app.services.bid.ai_pricing_executor import disable
    disable(db, shop_id)
    return success({"shop_id": shop_id, "is_active": False})


@router.post("/ai-pricing/{shop_id}/analyze")
async def manual_analyze(
    shop_id: int,
    req: AnalyzeRequest = None,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    from app.services.bid.ai_pricing_executor import analyze_now
    campaign_ids = req.campaign_ids if req else None
    result = await analyze_now(db, shop_id, force=True, campaign_ids=campaign_ids)
    if result.get("status") == "failed":
        return error(ErrorCode.AI_MODEL_ERROR, result.get("message") or "")
    return success({
        "shop_id": shop_id,
        "analyzed_count": result.get("analyzed_count", 0),
        "suggestion_count": result.get("suggestion_count", 0),
        "auto_executed_count": result.get("auto_executed_count", 0),
        "time_cost_ms": result.get("time_cost_ms", 0),
        "suggestions": result.get("suggestions", []),
    })


# ==================== §4 建议列表 ====================

@router.get("/suggestions/{shop_id}")
def get_suggestions(
    shop_id: int,
    status: str = Query("pending"),
    campaign_id: int = Query(None),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """按活动分组返回今日 status 状态的建议"""
    today = moscow_today()
    where = ["s.shop_id = :shop_id", "DATE(s.generated_at) = :today"]
    params = {"shop_id": shop_id, "today": today}
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
    from app.services.bid.ai_pricing_executor import approve_suggestion as approve_fn
    result = await approve_fn(db, suggestion_id)
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
    result = reject_fn(db, suggestion_id)
    return success(result.get("data") or {})


@router.post("/suggestions/approve-batch")
async def approve_batch(
    req: BatchIdsRequest,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    from app.services.bid.ai_pricing_executor import approve_batch as approve_fn
    result = await approve_fn(db, req.ids)
    return success(result.get("data") or {})


@router.post("/suggestions/reject-batch")
def reject_batch(
    req: BatchIdsRequest,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    from app.services.bid.ai_pricing_executor import reject_batch as reject_fn
    result = reject_fn(db, req.ids)
    return success(result.get("data") or {})


# ==================== §5 冲突检测 ====================

@router.get("/conflict-check/{shop_id}")
def conflict_check(
    shop_id: int,
    enabling: str = Query(..., description="time_pricing | ai_auto"),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    row = db.execute(text("""
        SELECT
            (SELECT is_active FROM time_pricing_rules WHERE shop_id = :sid LIMIT 1) AS time_active,
            (SELECT is_active FROM ai_pricing_configs WHERE shop_id = :sid LIMIT 1) AS ai_active
    """), {"sid": shop_id}).fetchone()

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
    shop_id: int,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    execute_type: str = Query("all"),
    campaign_id: int = Query(None),
    start_date: str = Query(None),
    end_date: str = Query(None),
    success_filter: bool = Query(None, alias="success"),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    where = ["shop_id = :shop_id"]
    params = {"shop_id": shop_id}
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
    shop_id: int,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    row = db.execute(text("""
        SELECT is_initialized, initialized_at, last_sync_at, last_sync_date,
               COALESCE(data_days, 0) AS data_days
        FROM shop_data_init_status
        WHERE shop_id = :shop_id
    """), {"shop_id": shop_id}).fetchone()

    if not row:
        return success({
            "shop_id": shop_id,
            "is_initialized": False,
            "initialized_at": None,
            "last_sync_at": None,
            "last_sync_date": None,
            "data_days": 0,
        })

    return success({
        "shop_id": shop_id,
        "is_initialized": bool(row.is_initialized),
        "initialized_at": row.initialized_at.isoformat() if row.initialized_at else None,
        "last_sync_at": row.last_sync_at.isoformat() if row.last_sync_at else None,
        "last_sync_date": row.last_sync_date.isoformat() if row.last_sync_date else None,
        "data_days": row.data_days,
    })


@router.post("/data-sync/{shop_id}")
async def sync_data(
    shop_id: int,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """手动触发数据同步：清理90天前数据 + 同步昨日"""
    from app.services.data.ozon_stats_collector import sync_yesterday_stats

    db.execute(text("""
        DELETE s FROM ad_stats s
        JOIN ad_campaigns c ON s.campaign_id = c.id
        WHERE c.shop_id = :shop_id
          AND s.stat_date < DATE_SUB(CURDATE(), INTERVAL 90 DAY)
    """), {"shop_id": shop_id})
    db.commit()

    try:
        result = await sync_yesterday_stats(db, shop_id)
        return success({
            "shop_id": shop_id,
            "task_id": "sync-immediate",
            "msg": "数据同步完成",
            **(result if isinstance(result, dict) else {}),
        })
    except Exception as e:
        logger.error(f"数据同步失败 shop_id={shop_id}: {e}")
        return error(ErrorCode.AD_STATS_FETCH_FAILED, f"同步失败: {e}")


@router.get("/data-download/{shop_id}")
def download_data(
    shop_id: int,
    days: int = Query(30, ge=1, le=180),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
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
            s.stat_date, s.stat_hour,
            s.impressions, s.clicks, s.ctr,
            s.cpc, s.spend, s.orders,
            s.revenue, s.acos, s.roas
        FROM ad_stats s
        JOIN ad_campaigns c ON s.campaign_id = c.id
        WHERE c.shop_id = :shop_id
          AND s.stat_date >= DATE_SUB(CURDATE(), INTERVAL :days DAY)
        ORDER BY c.name, s.stat_date DESC
    """), {"shop_id": shop_id, "days": days}).fetchall()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "广告数据"
    ws.append([
        "活动名称", "平台活动ID", "日期", "小时",
        "曝光", "点击", "CTR",
        "CPC", "花费", "订单",
        "收入", "ACOS", "ROAS",
    ])
    for r in rows:
        ws.append([
            r.campaign_name, r.platform_campaign_id,
            r.stat_date.isoformat() if r.stat_date else "", r.stat_hour,
            r.impressions or 0, r.clicks or 0, float(r.ctr or 0),
            float(r.cpc or 0), float(r.spend or 0), r.orders or 0,
            float(r.revenue or 0), float(r.acos or 0), float(r.roas or 0),
        ])

    output = BytesIO()
    wb.save(output)
    output.seek(0)
    today = now_moscow().strftime("%Y%m%d")
    filename = f"shop_{shop_id}_bid_data_{today}.xlsx"
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
