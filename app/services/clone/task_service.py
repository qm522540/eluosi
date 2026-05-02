"""店铺克隆任务 Service — CRUD + approve/reject/restore + 列表查询

详细规范: docs/api/store_clone.md §5 §11
所有函数返回 dict + ErrorCode 风格 (与 ai_pricing/seo 一致)。
"""

from typing import Optional, List
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.clone import (
    CloneTask, ClonePendingProduct, CloneLog, ClonePublishedLink,
)
from app.models.shop import Shop
from app.models.product import PlatformListing, Product
from app.utils.errors import ErrorCode
from app.utils.logger import setup_logger
from app.utils.moscow_time import utc_now_naive

logger = setup_logger("clone.task_service")


# ==================== 内部辅助 ====================

def _task_to_dict(task: CloneTask, db: Optional[Session] = None,
                  include_shop_info: bool = False) -> dict:
    d = {
        "id": task.id,
        "tenant_id": task.tenant_id,
        "target_shop_id": task.target_shop_id,
        "source_shop_id": task.source_shop_id,
        "source_type": task.source_type,
        "is_active": bool(task.is_active),
        "title_mode": task.title_mode,
        "desc_mode": task.desc_mode,
        "price_mode": task.price_mode,
        "price_adjust_pct": float(task.price_adjust_pct) if task.price_adjust_pct is not None else None,
        "default_stock": task.default_stock,
        "follow_price_change": bool(task.follow_price_change),
        "category_strategy": task.category_strategy,
        "last_check_at": task.last_check_at.isoformat() + "Z" if task.last_check_at else None,
        "last_found_count": task.last_found_count,
        "last_publish_count": task.last_publish_count,
        "last_skip_count": task.last_skip_count,
        "last_error_msg": task.last_error_msg,
        "created_at": task.created_at.isoformat() + "Z" if task.created_at else None,
        "updated_at": task.updated_at.isoformat() + "Z" if task.updated_at else None,
    }
    if include_shop_info and db is not None:
        target = db.query(Shop).filter(Shop.id == task.target_shop_id).first()
        source = db.query(Shop).filter(Shop.id == task.source_shop_id).first() if task.source_shop_id else None
        d["target_shop"] = {"id": target.id, "name": target.name, "platform": target.platform} if target else None
        d["source_shop"] = {"id": source.id, "name": source.name, "platform": source.platform} if source else None
    return d


def _pending_to_dict(p: ClonePendingProduct) -> dict:
    return {
        "id": p.id,
        "task_id": p.task_id,
        "source": {
            "platform": p.source_platform,
            "sku_id": p.source_sku_id,
            **(p.source_snapshot or {}),
        },
        "proposed": p.proposed_payload or {},
        "draft_listing_id": p.draft_listing_id,
        "status": p.status,
        "category_mapping_status": p.category_mapping_status,
        "reject_reason": p.reject_reason,
        "publish_error_msg": p.publish_error_msg,
        "detected_at": p.detected_at.isoformat() + "Z" if p.detected_at else None,
        "reviewed_at": p.reviewed_at.isoformat() + "Z" if p.reviewed_at else None,
        "published_at": p.published_at.isoformat() + "Z" if p.published_at else None,
        "target_platform_sku_id": p.target_platform_sku_id,
    }


def _log_to_dict(log: CloneLog) -> dict:
    return {
        "id": log.id,
        "task_id": log.task_id,
        "log_type": log.log_type,
        "status": log.status,
        "rows_affected": log.rows_affected,
        "duration_ms": log.duration_ms,
        "detail": log.detail,
        "error_msg": log.error_msg,
        "created_at": log.created_at.isoformat() + "Z" if log.created_at else None,
    }


# ==================== §5.1 任务管理 ====================

def create_task(db: Session, tenant_id: int, data: dict) -> dict:
    """POST /tasks — 创建任务

    业务校验 (schemas/clone.py CloneTaskCreate 已 Pydantic 校验过基本约束):
    - target_shop_id 属于 tenant (路由层 get_owned_shop 已守卫, 这里再确认)
    - source_shop_id 属于同 tenant (service 层校验)
    - target != source (Pydantic model_validator 已校验)
    - (target, source) 唯一 (UNIQUE 约束 + 显式查重报友好错误)
    """
    target_id = data["target_shop_id"]
    source_id = data["source_shop_id"]

    # source_shop 必须属于同 tenant
    source = db.query(Shop).filter(
        Shop.id == source_id, Shop.tenant_id == tenant_id,
    ).first()
    if not source:
        return {"code": ErrorCode.CLONE_TASK_SOURCE_INVALID,
                "msg": "源店铺不存在或不属于本租户"}
    if source.status != "active":
        return {"code": ErrorCode.CLONE_TASK_SOURCE_INVALID,
                "msg": "源店铺未激活,不能作为克隆源"}

    # target_shop 已由 get_owned_shop 守卫,这里冗余兜底
    target = db.query(Shop).filter(
        Shop.id == target_id, Shop.tenant_id == tenant_id,
    ).first()
    if not target:
        return {"code": ErrorCode.SHOP_NOT_FOUND, "msg": "目标店铺不存在"}
    if target.status != "active":
        return {"code": ErrorCode.CLONE_TARGET_SHOP_INACTIVE, "msg": "目标店铺未激活"}

    # 查重 (UNIQUE 兜底但提前给友好错误)
    exists = db.query(CloneTask).filter(
        CloneTask.tenant_id == tenant_id,
        CloneTask.target_shop_id == target_id,
        CloneTask.source_shop_id == source_id,
    ).first()
    if exists:
        return {"code": ErrorCode.CLONE_TASK_DUPLICATE,
                "msg": f"该 A/B 店组合已存在克隆任务 (id={exists.id})"}

    task = CloneTask(
        tenant_id=tenant_id,
        target_shop_id=target_id,
        source_shop_id=source_id,
        source_type=data.get("source_type", "seller_api"),
        is_active=1 if data.get("is_active") else 0,
        title_mode=data.get("title_mode", "original"),
        desc_mode=data.get("desc_mode", "original"),
        price_mode=data.get("price_mode", "same"),
        price_adjust_pct=data.get("price_adjust_pct"),
        default_stock=data.get("default_stock", 999),
        follow_price_change=1 if data.get("follow_price_change") else 0,
        category_strategy=data.get("category_strategy", "use_local_map"),
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    logger.info(f"create clone_task id={task.id} tenant={tenant_id} target={target_id} source={source_id}")
    return {"code": 0, "data": _task_to_dict(task, db, include_shop_info=True)}


def list_tasks(db: Session, tenant_id: int,
               target_shop_id: Optional[int] = None,
               is_active: Optional[bool] = None,
               page: int = 1, size: int = 20) -> dict:
    """GET /tasks — 任务列表"""
    q = db.query(CloneTask).filter(CloneTask.tenant_id == tenant_id)
    if target_shop_id is not None:
        q = q.filter(CloneTask.target_shop_id == target_shop_id)
    if is_active is not None:
        q = q.filter(CloneTask.is_active == (1 if is_active else 0))

    total = q.count()
    items = (
        q.order_by(CloneTask.id.desc())
        .offset((page - 1) * size).limit(size).all()
    )

    # 拼接 pending/published 计数
    items_dict = []
    for t in items:
        d = _task_to_dict(t, db, include_shop_info=True)
        # 实时统计 pending / published 数 (规则 1: tenant + task 双过滤)
        d["pending_count"] = db.query(ClonePendingProduct).filter(
            ClonePendingProduct.tenant_id == tenant_id,
            ClonePendingProduct.task_id == t.id,
            ClonePendingProduct.status == "pending",
        ).count()
        d["published_count"] = db.query(ClonePendingProduct).filter(
            ClonePendingProduct.tenant_id == tenant_id,
            ClonePendingProduct.task_id == t.id,
            ClonePendingProduct.status == "published",
        ).count()
        items_dict.append(d)

    return {"code": 0, "data": {
        "total": total, "page": page, "size": size,
        "items": items_dict,
    }}


def get_task_detail(db: Session, tenant_id: int, task_id: int) -> dict:
    """GET /tasks/{task_id} — 单任务详情 + 近 10 条日志"""
    task = db.query(CloneTask).filter(
        CloneTask.id == task_id, CloneTask.tenant_id == tenant_id,
    ).first()
    if not task:
        return {"code": ErrorCode.CLONE_TASK_NOT_FOUND, "msg": "克隆任务不存在"}

    recent_logs = (
        db.query(CloneLog)
        .filter(CloneLog.tenant_id == tenant_id, CloneLog.task_id == task_id)
        .order_by(CloneLog.id.desc()).limit(10).all()
    )
    d = _task_to_dict(task, db, include_shop_info=True)
    d["recent_logs"] = [_log_to_dict(l) for l in recent_logs]
    return {"code": 0, "data": d}


def update_task(db: Session, tenant_id: int, task_id: int, data: dict) -> dict:
    """PUT /tasks/{task_id} — 更新配置 (target_shop_id / source_shop_id 不可改)"""
    task = db.query(CloneTask).filter(
        CloneTask.id == task_id, CloneTask.tenant_id == tenant_id,
    ).first()
    if not task:
        return {"code": ErrorCode.CLONE_TASK_NOT_FOUND, "msg": "克隆任务不存在"}

    # 仅更新传入的字段
    mutable = {
        "title_mode", "desc_mode", "price_mode", "price_adjust_pct",
        "default_stock", "follow_price_change", "category_strategy",
    }
    for k, v in data.items():
        if k in mutable and v is not None:
            if k == "follow_price_change":
                v = 1 if v else 0
            setattr(task, k, v)
    db.commit()
    db.refresh(task)
    return {"code": 0, "data": _task_to_dict(task, db, include_shop_info=True)}


def enable_task(db: Session, tenant_id: int, task_id: int) -> dict:
    """POST /tasks/{task_id}/enable"""
    task = db.query(CloneTask).filter(
        CloneTask.id == task_id, CloneTask.tenant_id == tenant_id,
    ).first()
    if not task:
        return {"code": ErrorCode.CLONE_TASK_NOT_FOUND, "msg": "克隆任务不存在"}

    # 启用前再核 source/target 仍 active
    target = db.query(Shop).filter(Shop.id == task.target_shop_id).first()
    source = db.query(Shop).filter(Shop.id == task.source_shop_id).first() if task.source_shop_id else None
    if not target or target.status != "active":
        return {"code": ErrorCode.CLONE_TARGET_SHOP_INACTIVE, "msg": "目标店铺已停用,无法启用任务"}
    if task.source_shop_id and (not source or source.status != "active"):
        return {"code": ErrorCode.CLONE_TASK_SOURCE_INVALID, "msg": "源店铺已停用,无法启用任务"}

    task.is_active = 1
    db.commit()
    return {"code": 0, "data": {"id": task.id, "is_active": True}}


def disable_task(db: Session, tenant_id: int, task_id: int) -> dict:
    """POST /tasks/{task_id}/disable"""
    task = db.query(CloneTask).filter(
        CloneTask.id == task_id, CloneTask.tenant_id == tenant_id,
    ).first()
    if not task:
        return {"code": ErrorCode.CLONE_TASK_NOT_FOUND, "msg": "克隆任务不存在"}
    task.is_active = 0
    db.commit()
    return {"code": 0, "data": {"id": task.id, "is_active": False}}


def delete_task(db: Session, tenant_id: int, task_id: int) -> dict:
    """DELETE /tasks/{task_id} — 软删 (is_active=0 + 历史记录保留)"""
    task = db.query(CloneTask).filter(
        CloneTask.id == task_id, CloneTask.tenant_id == tenant_id,
    ).first()
    if not task:
        return {"code": ErrorCode.CLONE_TASK_NOT_FOUND, "msg": "克隆任务不存在"}
    task.is_active = 0
    db.commit()
    # pending / logs / published_links 历史保留 (业务约定)
    return {"code": 0, "data": {"id": task.id, "deleted": True}}


# ==================== scan-now (调 scan_engine) ====================

async def scan_now(db: Session, tenant_id: int, task_id: int) -> dict:
    """POST /tasks/{task_id}/scan-now — 同步触发一次扫描

    Phase 1 简化: 不加 Redis 分布式锁 (TODO: 高并发下补 clone:scan:lock:{task_id})。
    """
    from app.services.clone.scan_engine import _run_scan

    # 校验任务存在 + 启用
    task = db.query(CloneTask).filter(
        CloneTask.id == task_id, CloneTask.tenant_id == tenant_id,
    ).first()
    if not task:
        return {"code": ErrorCode.CLONE_TASK_NOT_FOUND, "msg": "克隆任务不存在"}

    return await _run_scan(db, task_id, tenant_id)


# ==================== §5.2 待审核商品 ====================

def list_pending(db: Session, tenant_id: int,
                 task_id: Optional[int] = None,
                 status: str = "pending",
                 category_mapping_status: Optional[str] = None,
                 keyword: Optional[str] = None,
                 page: int = 1, size: int = 20) -> dict:
    """GET /pending — 待审核列表"""
    q = db.query(ClonePendingProduct).filter(
        ClonePendingProduct.tenant_id == tenant_id,
    )
    if task_id is not None:
        q = q.filter(ClonePendingProduct.task_id == task_id)
    if status:
        q = q.filter(ClonePendingProduct.status == status)
    if category_mapping_status:
        q = q.filter(ClonePendingProduct.category_mapping_status == category_mapping_status)
    if keyword:
        like = f"%{keyword}%"
        q = q.filter(ClonePendingProduct.source_sku_id.like(like))

    total = q.count()
    items = (
        q.order_by(ClonePendingProduct.id.desc())
        .offset((page - 1) * size).limit(size).all()
    )
    return {"code": 0, "data": {
        "total": total, "page": page, "size": size,
        "items": [_pending_to_dict(p) for p in items],
    }}


def approve_pending(db: Session, tenant_id: int, pending_id: int,
                    user_id: Optional[int] = None) -> dict:
    """POST /pending/{id}/approve — 等 publish_engine beat 异步处理"""
    p = db.query(ClonePendingProduct).filter(
        ClonePendingProduct.id == pending_id,
        ClonePendingProduct.tenant_id == tenant_id,
    ).first()
    if not p:
        return {"code": ErrorCode.CLONE_PENDING_NOT_FOUND, "msg": "待审核记录不存在"}
    if p.status not in ("pending", "failed"):
        return {"code": ErrorCode.CLONE_PENDING_INVALID_STATUS,
                "msg": f"当前状态 {p.status} 不允许 approve"}

    p.status = "approved"
    p.reviewed_at = utc_now_naive()
    p.reviewed_by = user_id
    db.commit()

    # 写日志
    db.add(CloneLog(
        tenant_id=tenant_id, task_id=p.task_id,
        log_type="review", status="success",
        detail={"action": "approve", "pending_id": pending_id},
    ))
    db.commit()
    return {"code": 0, "data": {
        "id": p.id, "status": "approved",
        "queued_at": p.reviewed_at.isoformat() + "Z",
    }}


def reject_pending(db: Session, tenant_id: int, pending_id: int,
                   reject_reason: Optional[str] = None,
                   user_id: Optional[int] = None) -> dict:
    """POST /pending/{id}/reject — 永久跳过 (UNIQUE 约束保障)"""
    p = db.query(ClonePendingProduct).filter(
        ClonePendingProduct.id == pending_id,
        ClonePendingProduct.tenant_id == tenant_id,
    ).first()
    if not p:
        return {"code": ErrorCode.CLONE_PENDING_NOT_FOUND, "msg": "待审核记录不存在"}
    if p.status != "pending":
        return {"code": ErrorCode.CLONE_PENDING_INVALID_STATUS,
                "msg": f"当前状态 {p.status} 不允许 reject"}

    p.status = "rejected"
    p.reject_reason = reject_reason
    p.reviewed_at = utc_now_naive()
    p.reviewed_by = user_id

    # 草稿 listing + product 同步标 deleted (规范文档 §3.3 状态机)
    if p.draft_listing_id:
        listing = db.query(PlatformListing).filter(
            PlatformListing.id == p.draft_listing_id,
            PlatformListing.tenant_id == tenant_id,
        ).first()
        if listing:
            listing.status = "deleted"
            if listing.product_id:
                product = db.query(Product).filter(
                    Product.id == listing.product_id,
                    Product.tenant_id == tenant_id,
                ).first()
                if product:
                    product.status = "deleted"

    db.commit()
    db.add(CloneLog(
        tenant_id=tenant_id, task_id=p.task_id,
        log_type="review", status="success",
        detail={"action": "reject", "pending_id": pending_id, "reason": reject_reason},
    ))
    db.commit()
    return {"code": 0, "data": {"id": p.id, "status": "rejected"}}


def restore_pending(db: Session, tenant_id: int, pending_id: int,
                    user_id: Optional[int] = None) -> dict:
    """POST /pending/{id}/restore — 误拒恢复 (规范 §5.2.4)"""
    p = db.query(ClonePendingProduct).filter(
        ClonePendingProduct.id == pending_id,
        ClonePendingProduct.tenant_id == tenant_id,
    ).first()
    if not p:
        return {"code": ErrorCode.CLONE_PENDING_NOT_FOUND, "msg": "待审核记录不存在"}
    if p.status != "rejected":
        return {"code": ErrorCode.CLONE_PENDING_NOT_REJECTED,
                "msg": "仅可恢复已拒绝的记录"}

    p.status = "pending"
    p.reject_reason = None
    p.reviewed_at = utc_now_naive()
    p.reviewed_by = user_id

    # 草稿 listing + product 从 deleted 恢复 inactive
    if p.draft_listing_id:
        listing = db.query(PlatformListing).filter(
            PlatformListing.id == p.draft_listing_id,
            PlatformListing.tenant_id == tenant_id,
        ).first()
        if listing:
            listing.status = "inactive"
            if listing.product_id:
                product = db.query(Product).filter(
                    Product.id == listing.product_id,
                    Product.tenant_id == tenant_id,
                ).first()
                if product:
                    product.status = "inactive"

    db.commit()
    db.add(CloneLog(
        tenant_id=tenant_id, task_id=p.task_id,
        log_type="review", status="success",
        detail={"action": "restore", "pending_id": pending_id},
    ))
    db.commit()
    return {"code": 0, "data": {
        "id": p.id, "status": "pending",
        "restored_at": p.reviewed_at.isoformat() + "Z",
    }}


def update_pending_payload(db: Session, tenant_id: int, pending_id: int,
                           proposed_payload_patch: dict) -> dict:
    """PUT /pending/{id} — 审核前修改 proposed_payload (merge,非替换)"""
    p = db.query(ClonePendingProduct).filter(
        ClonePendingProduct.id == pending_id,
        ClonePendingProduct.tenant_id == tenant_id,
    ).first()
    if not p:
        return {"code": ErrorCode.CLONE_PENDING_NOT_FOUND, "msg": "待审核记录不存在"}
    if p.status != "pending":
        return {"code": ErrorCode.CLONE_PENDING_INVALID_STATUS,
                "msg": f"当前状态 {p.status} 不允许编辑"}

    merged = dict(p.proposed_payload or {})
    merged.update(proposed_payload_patch or {})
    p.proposed_payload = merged

    # 同步更新草稿 listing 对应字段 (title_ru / description_ru)
    if p.draft_listing_id:
        listing = db.query(PlatformListing).filter(
            PlatformListing.id == p.draft_listing_id,
            PlatformListing.tenant_id == tenant_id,
        ).first()
        if listing:
            if "title_ru" in proposed_payload_patch:
                listing.title_ru = proposed_payload_patch["title_ru"]
            if "description_ru" in proposed_payload_patch:
                listing.description_ru = proposed_payload_patch["description_ru"]

    db.commit()
    return {"code": 0, "data": _pending_to_dict(p)}


def batch_approve(db: Session, tenant_id: int, ids: List[int],
                  user_id: Optional[int] = None) -> dict:
    """POST /pending/approve-batch — 部分成功语义"""
    results = []
    success = failed = 0
    for pid in ids:
        r = approve_pending(db, tenant_id, pid, user_id)
        if r["code"] == 0:
            success += 1
            results.append({"id": pid, "status": "approved"})
        else:
            failed += 1
            results.append({"id": pid, "status": "failed",
                            "error_code": r["code"], "error_msg": r.get("msg")})
    return {"code": 0, "data": {
        "total": len(ids), "success": success, "failed": failed,
        "results": results,
    }}


def batch_reject(db: Session, tenant_id: int, ids: List[int],
                 reject_reason: Optional[str] = None,
                 user_id: Optional[int] = None) -> dict:
    """POST /pending/reject-batch"""
    results = []
    success = failed = 0
    for pid in ids:
        r = reject_pending(db, tenant_id, pid, reject_reason, user_id)
        if r["code"] == 0:
            success += 1
            results.append({"id": pid, "status": "rejected"})
        else:
            failed += 1
            results.append({"id": pid, "status": "failed",
                            "error_code": r["code"], "error_msg": r.get("msg")})
    return {"code": 0, "data": {
        "total": len(ids), "success": success, "failed": failed,
        "results": results,
    }}


# ==================== §5.3 日志 ====================

def list_logs(db: Session, tenant_id: int,
              task_id: Optional[int] = None,
              log_type: Optional[str] = None,
              status: Optional[str] = None,
              start_date: Optional[str] = None,
              end_date: Optional[str] = None,
              page: int = 1, size: int = 20) -> dict:
    """GET /logs"""
    q = db.query(CloneLog).filter(CloneLog.tenant_id == tenant_id)
    if task_id is not None:
        q = q.filter(CloneLog.task_id == task_id)
    if log_type:
        q = q.filter(CloneLog.log_type == log_type)
    if status:
        q = q.filter(CloneLog.status == status)
    if start_date:
        q = q.filter(CloneLog.created_at >= start_date)
    if end_date:
        q = q.filter(CloneLog.created_at <= end_date + " 23:59:59")

    total = q.count()
    items = (
        q.order_by(CloneLog.id.desc())
        .offset((page - 1) * size).limit(size).all()
    )
    return {"code": 0, "data": {
        "total": total, "page": page, "size": size,
        "items": [_log_to_dict(l) for l in items],
    }}


# ==================== §5.4 配置辅助 ====================

def list_available_shops(db: Session, tenant_id: int) -> dict:
    """GET /available-shops — 当前 tenant 下所有 active 店铺 + 平台 + 是否有 token"""
    shops = db.query(Shop).filter(
        Shop.tenant_id == tenant_id,
        Shop.status == "active",
    ).all()
    items = []
    for s in shops:
        # has_seller_token 简化判断: 平台-specific 凭证字段非空
        has_token = bool(getattr(s, "api_key", None) or getattr(s, "wb_seller_token", None)
                         or getattr(s, "ozon_seller_api_key", None))
        items.append({
            "id": s.id, "name": s.name, "platform": s.platform,
            "has_seller_token": has_token,
            "is_active": s.status == "active",
        })
    return {"code": 0, "data": {"items": items}}


def check_category_coverage(db: Session, tenant_id: int, task_id: int,
                            sample_size: int = 100) -> dict:
    """GET /category-coverage/{task_id}

    扫描 source_shop 近 sample_size 商品, 统计哪些 B 平台分类无映射到 A 平台。
    Phase 1 简化: 只查现有 platform_listings 表统计 (不实际调 B 店 API),
    跑过 scan-now 至少一次后才有意义。
    """
    task = db.query(CloneTask).filter(
        CloneTask.id == task_id, CloneTask.tenant_id == tenant_id,
    ).first()
    if not task:
        return {"code": ErrorCode.CLONE_TASK_NOT_FOUND, "msg": "克隆任务不存在"}

    # 统计本任务下 category_mapping_status='missing' 的 SKU 数 (实际拉过的)
    missing_rows = db.execute(text("""
        SELECT JSON_UNQUOTE(JSON_EXTRACT(source_snapshot, '$.platform_category_id')) AS cat_id,
               JSON_UNQUOTE(JSON_EXTRACT(source_snapshot, '$.platform_category_name')) AS cat_name,
               COUNT(*) AS sku_count
        FROM clone_pending_products
        WHERE tenant_id = :tid AND task_id = :task_id
          AND category_mapping_status = 'missing'
        GROUP BY cat_id, cat_name
        ORDER BY sku_count DESC
        LIMIT 50
    """), {"tid": tenant_id, "task_id": task_id}).fetchall()

    total_checked = db.query(ClonePendingProduct).filter(
        ClonePendingProduct.tenant_id == tenant_id,
        ClonePendingProduct.task_id == task_id,
    ).count()

    missing_categories = [
        {"platform_category_id": r.cat_id or "",
         "platform_category_name": r.cat_name,
         "sku_count": int(r.sku_count)}
        for r in missing_rows
    ]
    ready_pct = 0
    if total_checked > 0:
        missing_total = sum(c["sku_count"] for c in missing_categories)
        ready_pct = int((total_checked - missing_total) * 100 / total_checked)

    return {"code": 0, "data": {
        "checked": total_checked,
        "missing_categories": missing_categories,
        "ready_pct": ready_pct,
    }}
