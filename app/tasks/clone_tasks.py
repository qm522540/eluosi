"""店铺克隆 Celery beat 任务

详细规范: docs/api/store_clone.md §6

两个 beat:
- daily_scan_all_tasks  (MSK 03:30): 扫所有 is_active=1 任务, 含跟价
- publish_approved_pending (every 5 min): 已批准的待上架批量推 A 平台
"""

import asyncio

from app.tasks.celery_app import celery_app
from app.database import SessionLocal
from app.models.clone import CloneTask, ClonePendingProduct
from app.models.task_log import TaskLog
from app.utils.logger import setup_logger
from app.utils.moscow_time import utc_now_naive

logger = setup_logger("tasks.clone")


def _run_async(coro):
    """同步 task 跑 async 函数 (项目惯例, 与 daily_sync_task / ad_auto_exclude_task 一致)"""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError("event loop closed")
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


# ==================== 1. daily_scan_all_tasks (MSK 03:30) ====================

@celery_app.task(name="app.tasks.clone_tasks.daily_scan_all_tasks")
def daily_scan_all_tasks():
    """扫所有 is_active=1 的克隆任务

    全租户扫描 (规则 4 例外, 不传 tenant_id)。单 task 失败异常隔离, 不影响其他。
    """
    from app.services.clone.scan_engine import _run_scan
    # 跟价复用 scan_engine: scan_engine 内自带 follow_price_change 分支处理
    # (Phase 1 简化: scan + price_sync 走同一入口, Phase 2 拆开)

    t0 = utc_now_naive()
    db = SessionLocal()
    try:
        active_tasks = db.query(CloneTask).filter(CloneTask.is_active == 1).all()
        total = len(active_tasks)
        ok = failed = 0

        for task in active_tasks:
            try:
                r = _run_async(_run_scan(db, task.id, task.tenant_id))
                if r.get("code") == 0:
                    ok += 1
                    logger.info(
                        f"clone scan ok task={task.id} tenant={task.tenant_id} "
                        f"new={r['data'].get('new')} found={r['data'].get('found')}"
                    )
                else:
                    failed += 1
                    logger.error(
                        f"clone scan failed task={task.id} tenant={task.tenant_id}: "
                        f"{r.get('msg')}"
                    )
            except Exception as e:
                failed += 1
                logger.error(f"clone scan 异常 task={task.id}: {e}", exc_info=True)

        dur_ms = int((utc_now_naive() - t0).total_seconds() * 1000)
        log_msg = f"扫 {total} 任务, ok={ok} failed={failed}"
        try:
            db.add(TaskLog(
                task_name="clone-daily-scan",
                started_at=t0, finished_at=utc_now_naive(),
                duration_ms=dur_ms,
                status="success" if failed == 0 else ("partial" if ok > 0 else "failed"),
                msg=log_msg,
            ))
            db.commit()
        except Exception as e:
            logger.warning(f"写 task_log 失败: {e}")

        return {"total": total, "ok": ok, "failed": failed, "duration_ms": dur_ms}
    finally:
        db.close()


# ==================== 2. publish_approved_pending (every 5 min) ====================

@celery_app.task(name="app.tasks.clone_tasks.publish_approved_pending")
def publish_approved_pending():
    """扫所有 status='approved' 的 pending, 批量推 A 平台上架

    每 5 分钟跑一次, 单次最多 50 条防爆。
    全租户扫描 (规则 4 例外)。
    """
    from app.services.clone.publish_engine import _publish_pending

    t0 = utc_now_naive()
    db = SessionLocal()
    try:
        # 方案 A: JOIN clone_tasks 过滤 is_active=1
        # — 删任务后已 approved 的 pending 不再被推上架 (避免幽灵上架到 Ozon)
        approved = db.query(ClonePendingProduct).join(
            CloneTask, ClonePendingProduct.task_id == CloneTask.id,
        ).filter(
            ClonePendingProduct.status == "approved",
            CloneTask.is_active == 1,
        ).limit(50).all()
        total = len(approved)
        ok = failed = 0

        for pending in approved:
            try:
                r = _run_async(_publish_pending(db, pending.id))
                if r.get("code") == 0:
                    ok += 1
                else:
                    failed += 1
            except Exception as e:
                failed += 1
                logger.error(
                    f"clone publish 异常 pending={pending.id}: {e}", exc_info=True,
                )

        dur_ms = int((utc_now_naive() - t0).total_seconds() * 1000)
        if total > 0:
            try:
                db.add(TaskLog(
                    task_name="clone-publish-pending",
                    started_at=t0, finished_at=utc_now_naive(),
                    duration_ms=dur_ms,
                    status="success" if failed == 0 else ("partial" if ok > 0 else "failed"),
                    msg=f"上架 {total} 条, ok={ok} failed={failed}",
                ))
                db.commit()
            except Exception as e:
                logger.warning(f"写 task_log 失败: {e}")

        return {"total": total, "ok": ok, "failed": failed, "duration_ms": dur_ms}
    finally:
        db.close()
