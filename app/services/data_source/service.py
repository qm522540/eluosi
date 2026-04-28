"""数据源管理 service — 替代 WB quota 静默期的"硬注释 MANUAL HOLD"模式

两层权限模型:
  Level 1: shops.api_enabled — 关 = 该店所有 API 类数据源全部 skip
  Level 2: data_source_config.enabled — 单数据源开关

核心入口:
  - is_data_source_enabled(): celery beat task 顶部 hook,3 行接入即可
  - get_shop_status(): UI 查该店所有数据源状态
  - update_data_source(): UI 改单源开关
  - update_shop_api_switch(): UI 改店铺 API 总开关 (紧急止血)
  - record_sync_run(): beat task 跑完写回最近同步状态

规则 1 多租户: 所有 SQL 都带 tenant_id 过滤
规则 4 shop_id: 路由层 get_owned_shop 守卫,这里 service 层签名带 tenant_id+shop_id 双重防御
规则 6 时间: 写 DB 全部走 utc_now_naive()
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.data_source.catalog import (
    DATA_SOURCES, is_api_source, is_shared_source,
)
from app.utils.errors import ErrorCode
from app.utils.logger import logger
from app.utils.moscow_time import utc_now_naive


# ==================== beat task hook ====================

def is_data_source_enabled(
    db: Session, tenant_id: int, shop_id: Optional[int], source_key: str,
) -> tuple[bool, Optional[str]]:
    """beat task 顶部检查: 该 (店 × 数据源) 是否启用。

    返回 (enabled, skip_reason):
        (True, None) → 继续跑
        (False, "原因") → skip 并记 log

    检查顺序:
        1. source_key 是否在 catalog (防 typo)
        2. 共享数据源 (shop_id=None / category=local) → 只查 Level 2
        3. API 类: Level 1 店铺 API 总开关 — 关闭则直接 skip
        4. Level 2 单数据源开关 — 关闭则 skip
        5. 都通过 → enabled
    """
    src = DATA_SOURCES.get(source_key)
    if not src:
        return True, None  # 未在 catalog 的 task 不 gate (向前兼容,新 task 加目录前能跑)

    # Level 1: 店铺 API 总开关 (仅 API 类生效, 共享类跳过)
    if is_api_source(source_key) and shop_id and not is_shared_source(source_key):
        shop = db.execute(text("""
            SELECT api_enabled, api_disabled_reason, api_disabled_until
            FROM shops WHERE id = :sid AND tenant_id = :tid
        """), {"sid": shop_id, "tid": tenant_id}).first()
        if shop and not shop.api_enabled:
            # 检查是否到自动恢复时间 (api_disabled_until)
            if shop.api_disabled_until and shop.api_disabled_until <= utc_now_naive():
                # 到期自动启用
                db.execute(text("""
                    UPDATE shops SET api_enabled = 1, api_disabled_reason = NULL,
                        api_disabled_at = NULL, api_disabled_until = NULL
                    WHERE id = :sid AND tenant_id = :tid
                """), {"sid": shop_id, "tid": tenant_id})
                db.commit()
                logger.info(f"shop_id={shop_id} api_disabled_until 到期,自动启用")
            else:
                reason = shop.api_disabled_reason or "未填写"
                return False, f"店铺 API 总开关已关闭: {reason}"

    # Level 2: 单数据源开关
    cfg = db.execute(text("""
        SELECT enabled, manual_hold_reason FROM data_source_config
        WHERE tenant_id = :tid AND shop_id = :sid AND source_key = :sk
    """), {"tid": tenant_id, "sid": shop_id or 0, "sk": source_key}).first()
    if cfg and not cfg.enabled:
        reason = cfg.manual_hold_reason or "未填写"
        return False, f"数据源已暂停: {reason}"

    return True, None


def record_sync_run(
    db: Session, tenant_id: int, shop_id: Optional[int], source_key: str,
    *, status: str, msg: str = "", rows: int = 0, duration_ms: Optional[int] = None,
) -> None:
    """beat task / 手动同步入口 跑完写回最近同步状态。

    status: success / partial / failed / skipped
    同时写两张表:
      1. data_source_config — 给 UI 看 (只保留最新状态)
      2. task_logs          — 给全系统观测看 (保留全部历史; 老林 4-28 建议)

    task_logs.task_name 用 "data_source.{source_key}" 前缀,避免跟 daily_sync 等
    原生写 task_logs 的 task 行混淆,grep 时一眼区分。
    """
    now = utc_now_naive()

    # ===== 1. data_source_config (UI 最新状态) =====
    try:
        db.execute(text("""
            INSERT INTO data_source_config (
                tenant_id, shop_id, source_key, enabled,
                last_sync_at, last_sync_status, last_sync_msg, last_sync_rows,
                last_sync_duration_ms, created_at, updated_at
            ) VALUES (
                :tid, :sid, :sk, 1,
                :now, :status, :msg, :rows, :dur, :now, :now
            )
            ON DUPLICATE KEY UPDATE
                tenant_id = :tid,
                last_sync_at = :now, last_sync_status = :status,
                last_sync_msg = :msg, last_sync_rows = :rows,
                last_sync_duration_ms = :dur, updated_at = :now
        """), {
            "tid": tenant_id, "sid": shop_id or 0, "sk": source_key,
            "now": now, "status": status, "msg": msg[:500],
            "rows": int(rows or 0), "dur": duration_ms,
        })
        db.commit()
    except Exception as e:
        logger.warning(f"record_sync_run data_source_config 失败 shop={shop_id} source={source_key}: {e}")

    # ===== 2. task_logs (全系统观测面) =====
    # task_logs.status enum 只有 success/failed/... 没有 partial/skipped,
    # 把 partial 当 success(任务完成,部分行失败), skipped 当 success(主动跳过非异常)
    # 真实 sub_status 放 result.json 里完整保留
    try:
        tl_status = "failed" if status == "failed" else "success"
        result_json = json.dumps({
            "sub_status": status,
            "shop_id": shop_id,
            "source_key": source_key,
            "rows": int(rows or 0),
        }, ensure_ascii=False)
        # started_at 反推: now - duration
        started_at = now - timedelta(milliseconds=duration_ms) if duration_ms else now
        db.execute(text("""
            INSERT INTO task_logs (
                tenant_id, task_name, status, result, error_message,
                started_at, finished_at, duration_ms, created_at, updated_at
            ) VALUES (
                :tid, :tn, :status, :result, :err,
                :start, :finish, :dur, :now, :now
            )
        """), {
            "tid": tenant_id,
            "tn": f"data_source.{source_key}",
            "status": tl_status,
            "result": result_json,
            "err": msg[:500] if status == "failed" else None,
            "start": started_at,
            "finish": now,
            "dur": duration_ms,
            "now": now,
        })
        db.commit()
    except Exception as e:
        logger.warning(f"record_sync_run task_logs 失败 shop={shop_id} source={source_key}: {e}")


# ==================== UI 查询入口 ====================

def get_shop_status(db: Session, tenant_id: int, shop_id: int) -> dict:
    """UI 数据源管理 Tab — 查单店所有数据源状态。

    返回:
    {
        shop: {id, name, platform, api_enabled, api_disabled_reason, ...},
        data_sources: [
            {key, label, category, schedule_desc, depends, enabled, manual_hold_reason,
             last_sync_at, last_sync_status, last_sync_msg, last_sync_rows,
             effective_enabled (考虑 Level 1+2 的实际状态)}
        ]
    }
    """
    shop = db.execute(text("""
        SELECT id, name, platform, status,
               api_enabled, api_disabled_reason, api_disabled_at, api_disabled_until
        FROM shops WHERE id = :sid AND tenant_id = :tid
    """), {"sid": shop_id, "tid": tenant_id}).first()
    if not shop:
        return {"code": ErrorCode.NOT_FOUND, "msg": "店铺不存在或不属于当前租户"}

    cfgs = db.execute(text("""
        SELECT source_key, enabled, manual_hold_reason, disabled_at,
               last_sync_at, last_sync_status, last_sync_msg, last_sync_rows,
               last_sync_duration_ms
        FROM data_source_config
        WHERE tenant_id = :tid AND shop_id = :sid
    """), {"tid": tenant_id, "sid": shop_id}).fetchall()
    cfg_by_key = {c.source_key: c for c in cfgs}

    items = []
    for key, meta in DATA_SOURCES.items():
        # 共享类不属于任何 shop, 跳过 (在专门接口返)
        if meta.get("platform") == "shared":
            continue
        # 平台不匹配跳过
        if meta.get("platform") not in (shop.platform, "shared"):
            continue
        cfg = cfg_by_key.get(key)
        enabled = cfg.enabled if cfg else 1  # 没记录默认启用
        # 计算 effective: API 类要叠加 Level 1
        effective = bool(enabled)
        if is_api_source(key) and not shop.api_enabled:
            effective = False
        items.append({
            "key": key,
            "label": meta["label"],
            "category": meta["category"],
            "schedule_desc": meta["schedule_desc"],
            "manual_only": bool(meta.get("manual_only", False)),
            "depends": meta.get("depends", []),
            "enabled": bool(enabled),
            "effective_enabled": effective,
            "manual_hold_reason": (cfg.manual_hold_reason if cfg else None),
            "disabled_at": (cfg.disabled_at.isoformat() + "Z" if cfg and cfg.disabled_at else None),
            "last_sync_at": (cfg.last_sync_at.isoformat() + "Z" if cfg and cfg.last_sync_at else None),
            "last_sync_status": (cfg.last_sync_status if cfg else None),
            "last_sync_msg": (cfg.last_sync_msg if cfg else None),
            "last_sync_rows": (int(cfg.last_sync_rows) if cfg and cfg.last_sync_rows else 0),
            "last_sync_duration_ms": (cfg.last_sync_duration_ms if cfg else None),
        })

    return {
        "code": ErrorCode.SUCCESS,
        "data": {
            "shop": {
                "id": int(shop.id),
                "name": shop.name,
                "platform": shop.platform,
                "status": shop.status,
                "api_enabled": bool(shop.api_enabled),
                "api_disabled_reason": shop.api_disabled_reason,
                "api_disabled_at": shop.api_disabled_at.isoformat() + "Z" if shop.api_disabled_at else None,
                "api_disabled_until": shop.api_disabled_until.isoformat() + "Z" if shop.api_disabled_until else None,
            },
            "data_sources": items,
        },
    }


def get_shared_data_sources(db: Session, tenant_id: int) -> dict:
    """跨店共享的数据源 (如 SEO 引擎),不属于任何 shop。"""
    cfgs = db.execute(text("""
        SELECT source_key, enabled, manual_hold_reason, disabled_at,
               last_sync_at, last_sync_status, last_sync_msg, last_sync_rows,
               last_sync_duration_ms
        FROM data_source_config
        WHERE tenant_id = :tid AND shop_id = 0
    """), {"tid": tenant_id}).fetchall()
    cfg_by_key = {c.source_key: c for c in cfgs}

    items = []
    for key, meta in DATA_SOURCES.items():
        if meta.get("platform") != "shared":
            continue
        cfg = cfg_by_key.get(key)
        enabled = cfg.enabled if cfg else 1
        items.append({
            "key": key,
            "label": meta["label"],
            "category": meta["category"],
            "schedule_desc": meta["schedule_desc"],
            "manual_only": bool(meta.get("manual_only", False)),
            "depends": meta.get("depends", []),
            "enabled": bool(enabled),
            "effective_enabled": bool(enabled),
            "manual_hold_reason": (cfg.manual_hold_reason if cfg else None),
            "last_sync_at": (cfg.last_sync_at.isoformat() + "Z" if cfg and cfg.last_sync_at else None),
            "last_sync_status": (cfg.last_sync_status if cfg else None),
            "last_sync_msg": (cfg.last_sync_msg if cfg else None),
            "last_sync_rows": (int(cfg.last_sync_rows) if cfg and cfg.last_sync_rows else 0),
        })

    return {"code": ErrorCode.SUCCESS, "data": {"data_sources": items}}


# ==================== UI 写入入口 ====================

def update_shop_api_switch(
    db: Session, tenant_id: int, shop_id: int, *,
    enabled: bool, reason: Optional[str] = None,
    auto_resume_hours: Optional[int] = None, user_id: Optional[int] = None,
) -> dict:
    """改店铺 API 总开关 (Level 1, 紧急止血)。

    enabled=False 必须传 reason (展示给所有人看为啥关)
    auto_resume_hours: 几小时后自动启用 (None = 手动启用前一直禁用)
    """
    if not enabled and not reason:
        return {"code": ErrorCode.PARAM_ERROR, "msg": "禁用 API 必须填写原因"}

    now = utc_now_naive()
    until = None
    if not enabled and auto_resume_hours and auto_resume_hours > 0:
        from datetime import timedelta
        until = now + timedelta(hours=int(auto_resume_hours))

    if enabled:
        # 启用: 清掉所有禁用相关字段
        db.execute(text("""
            UPDATE shops SET api_enabled = 1,
                api_disabled_reason = NULL, api_disabled_at = NULL,
                api_disabled_until = NULL, api_disabled_by = NULL
            WHERE id = :sid AND tenant_id = :tid
        """), {"sid": shop_id, "tid": tenant_id})
    else:
        db.execute(text("""
            UPDATE shops SET api_enabled = 0,
                api_disabled_reason = :reason, api_disabled_at = :now,
                api_disabled_until = :until, api_disabled_by = :uid
            WHERE id = :sid AND tenant_id = :tid
        """), {"sid": shop_id, "tid": tenant_id,
               "reason": reason[:500], "now": now, "until": until, "uid": user_id})
    db.commit()
    logger.info(
        f"shop_id={shop_id} API 总开关 → {'启用' if enabled else '禁用'} "
        f"by user={user_id} reason={reason!r} auto_resume={auto_resume_hours}h"
    )
    return {"code": ErrorCode.SUCCESS, "data": {"enabled": enabled,
                                                  "auto_resume_until": until.isoformat() + "Z" if until else None}}


def update_data_source(
    db: Session, tenant_id: int, shop_id: int, source_key: str, *,
    enabled: bool, reason: Optional[str] = None, user_id: Optional[int] = None,
) -> dict:
    """改单数据源开关 (Level 2)。"""
    if source_key not in DATA_SOURCES:
        return {"code": ErrorCode.PARAM_ERROR, "msg": f"未知数据源: {source_key}"}
    if not enabled and not reason:
        return {"code": ErrorCode.PARAM_ERROR, "msg": "暂停数据源必须填写原因"}

    now = utc_now_naive()
    # UPSERT
    db.execute(text("""
        INSERT INTO data_source_config (
            tenant_id, shop_id, source_key, enabled,
            manual_hold_reason, disabled_at, disabled_by,
            created_at, updated_at
        ) VALUES (
            :tid, :sid, :sk, :enabled,
            :reason, :disabled_at, :disabled_by,
            :now, :now
        )
        ON DUPLICATE KEY UPDATE
            enabled = :enabled,
            manual_hold_reason = :reason,
            disabled_at = :disabled_at,
            disabled_by = :disabled_by,
            updated_at = :now
    """), {
        "tid": tenant_id, "sid": shop_id, "sk": source_key,
        "enabled": 1 if enabled else 0,
        "reason": reason[:500] if reason else None,
        "disabled_at": now if not enabled else None,
        "disabled_by": user_id if not enabled else None,
        "now": now,
    })
    db.commit()
    logger.info(
        f"shop_id={shop_id} source={source_key} → {'启用' if enabled else '暂停'} "
        f"by user={user_id} reason={reason!r}"
    )
    return {"code": ErrorCode.SUCCESS, "data": {"enabled": enabled, "source_key": source_key}}
