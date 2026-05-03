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
        "follow_status_change": bool(task.follow_status_change),  # 11.3.2
        "category_strategy": task.category_strategy,
        "target_brand": task.target_brand,  # migration 064
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
        follow_status_change=1 if data.get("follow_status_change") else 0,  # 11.3.2
        category_strategy=data.get("category_strategy", "use_local_map"),
        target_brand=(data.get("target_brand") or None),  # migration 064; 空串归一为 NULL
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
        "default_stock", "follow_price_change", "follow_status_change",
        "category_strategy", "target_brand",
    }
    for k, v in data.items():
        if k not in mutable:
            continue
        if k in ("follow_price_change", "follow_status_change"):
            # bool 字段允许 False, 不能用 v is not None 之外的判空
            if v is None:
                continue
            v = 1 if v else 0
        elif k == "target_brand":
            # 空串显式存 NULL; 用户清空 = 关闭品牌替换
            v = (v.strip() if isinstance(v, str) else v) or None
        elif v is None:
            continue
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

async def scan_now(db: Session, tenant_id: int, task_id: int,
                   selected_skus: Optional[list] = None,
                   local_sku_overrides: Optional[dict] = None) -> dict:
    """POST /tasks/{task_id}/scan-now — 同步触发一次扫描

    Args:
        selected_skus: None = 全量立项 (兼容旧逻辑); list = 只立项 preview 阶段勾选的
        local_sku_overrides: dict[source_sku_id → 自定义 A 店 SKU];
            preview 行用户可改"本地 SKU" 输入框, 提交时带过来.

    Phase 1 简化: 不加 Redis 分布式锁 (TODO: 高并发下补 clone:scan:lock:{task_id})。
    """
    from app.services.clone.scan_engine import _run_scan

    task = db.query(CloneTask).filter(
        CloneTask.id == task_id, CloneTask.tenant_id == tenant_id,
    ).first()
    if not task:
        return {"code": ErrorCode.CLONE_TASK_NOT_FOUND, "msg": "克隆任务不存在"}

    selected_set = set(selected_skus) if selected_skus else None
    return await _run_scan(
        db, task_id, tenant_id,
        selected_skus=selected_set,
        local_sku_overrides=local_sku_overrides,
    )


async def scan_preview(db: Session, tenant_id: int, task_id: int) -> dict:
    """POST /tasks/{task_id}/scan-preview — 11.2 干跑预览, 不写库

    用户通过返回的 candidates 清单勾选后, 再调 scan-now(selected_skus) 真立项.
    """
    from app.services.clone.scan_engine import _scan_preview

    task = db.query(CloneTask).filter(
        CloneTask.id == task_id, CloneTask.tenant_id == tenant_id,
    ).first()
    if not task:
        return {"code": ErrorCode.CLONE_TASK_NOT_FOUND, "msg": "克隆任务不存在"}

    return await _scan_preview(db, task_id, tenant_id)


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

    # 方案 A v2: task 不存在拦截 (理论上 FK 保证不会发生, 但防御性);
    # is_active=0 不再拦截 approve — 用户手动操作不存在"幽灵"问题.
    # publish-pending beat 端仍 JOIN is_active=1, 任务停用 → approved 暂存 →
    # 重新启用后下次 beat 自动接管上架. 这是合理的"暂存"语义.
    task = db.query(CloneTask).filter(
        CloneTask.id == p.task_id, CloneTask.tenant_id == tenant_id,
    ).first()
    if not task:
        return {"code": ErrorCode.CLONE_TASK_NOT_FOUND,
                "msg": "克隆任务不存在"}

    p.status = "approved"
    p.reviewed_at = utc_now_naive()
    p.reviewed_by = user_id
    db.commit()

    # 写日志
    db.add(CloneLog(
        tenant_id=tenant_id, task_id=p.task_id,
        log_type="review", status="success",
        detail={
            "action": "approve", "pending_id": pending_id,
            "task_inactive": not bool(task.is_active),  # 用于前端给"暂存"提示
        },
    ))
    db.commit()
    return {"code": 0, "data": {
        "id": p.id, "status": "approved",
        "queued_at": p.reviewed_at.isoformat() + "Z",
        # 任务停用时, pending 进 approved 但 publish beat 不会拉, 等启用后才上架
        "task_inactive": not bool(task.is_active),
    }}


def publish_pending_now(db: Session, tenant_id: int, pending_id: int,
                        user_id: Optional[int] = None) -> dict:
    """POST /pending/{id}/publish — 用户在待审核页直接点"发布",
    pending 标 approved 后立即触发 Celery, 不等 beat 周期.

    简化设计 (老板拍): 砍掉 batch_approve / batch_reject 的中间环节.
    "待审核" 就是决策中心 — 点发布 = 上架; 不点 = 留着; 想重抓 = 批量彻底删.
    """
    p = db.query(ClonePendingProduct).filter(
        ClonePendingProduct.id == pending_id,
        ClonePendingProduct.tenant_id == tenant_id,
    ).first()
    if not p:
        return {"code": ErrorCode.CLONE_PENDING_NOT_FOUND, "msg": "待审核记录不存在"}
    if p.status not in ("pending", "failed"):
        return {"code": ErrorCode.CLONE_PENDING_INVALID_STATUS,
                "msg": f"当前状态 {p.status} 不允许发布"}

    task = db.query(CloneTask).filter(
        CloneTask.id == p.task_id, CloneTask.tenant_id == tenant_id,
    ).first()
    if not task:
        return {"code": ErrorCode.CLONE_TASK_NOT_FOUND, "msg": "克隆任务不存在"}
    if not task.is_active:
        return {"code": ErrorCode.CLONE_TASK_NOT_FOUND,
                "msg": "克隆任务已停用 — 请到「克隆任务」启用后再发布"}

    p.status = "approved"
    p.reviewed_at = utc_now_naive()
    p.reviewed_by = user_id
    db.commit()

    # 立即触发 Celery (不等 beat 周期); beat 仍兜底处理批量积压
    try:
        from app.tasks.clone_tasks import publish_approved_pending
        publish_approved_pending.delay()
    except Exception as e:
        logger.warning(f"publish 触发 Celery 失败 pending={pending_id}: {e}, 等 beat 兜底")

    db.add(CloneLog(
        tenant_id=tenant_id, task_id=p.task_id,
        log_type="review", status="success",
        detail={"action": "publish_now", "pending_id": pending_id},
    ))
    db.commit()
    return {"code": 0, "data": {
        "id": p.id, "status": "approved",
        "queued_at": p.reviewed_at.isoformat() + "Z",
        "msg": "已加入上架队列, 1 分钟内完成",
    }}


async def publish_pending_sync(db: Session, tenant_id: int, pending_id: int,
                               user_id: Optional[int] = None) -> dict:
    """同步发布 — 直接 await _publish_pending, 不走 Celery 排队.

    老板拍: 单条点"确认发布"就要立刻看到结果, 不接受"几秒后才执行"的体感.
    单条 publish 含 OSS 下图 ≈ 20-30 秒, 在 nginx 60s timeout 内.
    批量发布 (N 件 × 30s) 必然超 timeout, 仍走 Celery 异步.
    """
    p = db.query(ClonePendingProduct).filter(
        ClonePendingProduct.id == pending_id,
        ClonePendingProduct.tenant_id == tenant_id,
    ).first()
    if not p:
        return {"code": ErrorCode.CLONE_PENDING_NOT_FOUND, "msg": "待审核记录不存在"}
    if p.status not in ("pending", "failed"):
        return {"code": ErrorCode.CLONE_PENDING_INVALID_STATUS,
                "msg": f"当前状态 {p.status} 不允许发布"}

    task = db.query(CloneTask).filter(
        CloneTask.id == p.task_id, CloneTask.tenant_id == tenant_id,
    ).first()
    if not task:
        return {"code": ErrorCode.CLONE_TASK_NOT_FOUND, "msg": "克隆任务不存在"}
    if not task.is_active:
        return {"code": ErrorCode.CLONE_TASK_NOT_FOUND,
                "msg": "克隆任务已停用 — 请到「克隆任务」启用后再发布"}

    # 标 approved 后直接 await publish_engine, 不经 Celery
    p.status = "approved"
    p.reviewed_at = utc_now_naive()
    p.reviewed_by = user_id
    db.commit()

    db.add(CloneLog(
        tenant_id=tenant_id, task_id=p.task_id,
        log_type="review", status="success",
        detail={"action": "publish_sync", "pending_id": pending_id},
    ))
    db.commit()

    from app.services.clone.publish_engine import _publish_pending
    r = await _publish_pending(db, pending_id)
    return r


def batch_publish_pending(db: Session, tenant_id: int, ids: List[int],
                          user_id: Optional[int] = None) -> dict:
    """POST /pending/publish-batch — 批量发布"""
    results = []
    success = failed = 0
    for pid in ids:
        r = publish_pending_now(db, tenant_id, pid, user_id)
        if r["code"] == 0:
            success += 1
            results.append({"id": pid, "status": "queued"})
        else:
            failed += 1
            results.append({"id": pid, "status": "failed",
                            "error_code": r["code"], "error_msg": r.get("msg")})
    return {"code": 0, "data": {
        "total": len(ids), "success": success, "failed": failed,
        "results": results,
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
    any_task_inactive = False
    for pid in ids:
        r = approve_pending(db, tenant_id, pid, user_id)
        if r["code"] == 0:
            success += 1
            results.append({"id": pid, "status": "approved"})
            if (r.get("data") or {}).get("task_inactive"):
                any_task_inactive = True
        else:
            failed += 1
            results.append({"id": pid, "status": "failed",
                            "error_code": r["code"], "error_msg": r.get("msg")})
    return {"code": 0, "data": {
        "total": len(ids), "success": success, "failed": failed,
        "results": results,
        # 任一 pending 所属 task 为 is_active=0 时给前端暂存提示
        "any_task_inactive": any_task_inactive,
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


def batch_delete_pending(db: Session, tenant_id: int, ids: List[int]) -> dict:
    """POST /pending/delete-batch — 物理 DELETE 3 张表 (pending + listing + product)

    与 reject (软删 + 永久跳过 + 可恢复) 不同, 此接口是**真删**:
    - 物理 DELETE clone_pending_products / platform_listings / products 三表关联行
    - 删后下次扫描遇到同 SKU 不再被去重跳过, 会重新作为新候选立项 ("重新采")

    限制 (避免破坏正在进行的流程或线上 Ozon 数据):
    - 只允许 status in ('pending', 'rejected', 'failed')
    - 'approved' 不允许 (publish beat 5 分钟内会推上架)
    - 'published' 不允许 (Ozon 上已存在, 物理删本地数据 listing 会变成孤儿)

    OSS 图片暂不清理 (留待 weekly cleanup beat 或 §11.6 daily 重构时统一处理).
    """
    if not ids:
        return {"code": 0, "data": {
            "deleted_pending": 0, "deleted_listing": 0, "deleted_product": 0,
            "skipped": [], "skipped_count": 0,
        }}

    pendings = db.query(ClonePendingProduct).filter(
        ClonePendingProduct.id.in_(ids),
        ClonePendingProduct.tenant_id == tenant_id,
    ).all()

    deleted_pending = deleted_listing = deleted_product = 0
    skipped: list = []
    ALLOWED_STATUSES = {"pending", "rejected", "failed"}

    for p in pendings:
        if p.status not in ALLOWED_STATUSES:
            skipped.append({
                "id": p.id, "status": p.status,
                "reason": "状态不允许删 (仅 pending/rejected/failed 可删)",
            })
            continue

        # 收集关联 listing + product (按依赖反向删)
        product_id = None
        if p.draft_listing_id:
            listing = db.query(PlatformListing).filter(
                PlatformListing.id == p.draft_listing_id,
                PlatformListing.tenant_id == tenant_id,
            ).first()
            if listing:
                product_id = listing.product_id
                db.delete(listing)
                deleted_listing += 1
        if product_id:
            product = db.query(Product).filter(
                Product.id == product_id,
                Product.tenant_id == tenant_id,
            ).first()
            if product:
                db.delete(product)
                deleted_product += 1
        db.delete(p)
        deleted_pending += 1

    db.commit()

    # 写日志 (审计可追溯)
    if deleted_pending > 0:
        first_p = pendings[0] if pendings else None
        task_id_for_log = first_p.task_id if first_p else None
        db.add(CloneLog(
            tenant_id=tenant_id, task_id=task_id_for_log,
            log_type="review", status="success",
            rows_affected=deleted_pending,
            detail={
                "action": "batch_delete",
                "deleted_pending": deleted_pending,
                "deleted_listing": deleted_listing,
                "deleted_product": deleted_product,
                "skipped_count": len(skipped),
                "ids": ids[:100],
            },
        ))
        db.commit()

    return {"code": 0, "data": {
        "deleted_pending": deleted_pending,
        "deleted_listing": deleted_listing,
        "deleted_product": deleted_product,
        "skipped": skipped,
        "skipped_count": len(skipped),
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
