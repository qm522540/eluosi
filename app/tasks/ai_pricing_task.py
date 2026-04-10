"""AI智能调价定时任务

调度：每小时55分执行
逻辑：遍历所有active店铺，对每个Ozon店铺调用AI分析
"""

import asyncio
from datetime import datetime

from app.tasks.celery_app import celery_app
from app.database import SessionLocal
from app.models.shop import Shop
from app.models.task_log import TaskLog
from app.services.ad.ai_pricing import run_ai_analysis
from app.utils.logger import setup_logger

logger = setup_logger("tasks.ai_pricing")


def _run_async(coro):
    """在同步Celery任务中执行异步代码"""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _log_task_start(db, task_name: str, celery_task_id: str, params: dict = None) -> int:
    """记录任务开始"""
    task_log = TaskLog(
        task_name=task_name,
        celery_task_id=celery_task_id,
        params=params,
        status="running",
        started_at=datetime.utcnow(),
    )
    db.add(task_log)
    db.commit()
    db.refresh(task_log)
    return task_log.id


def _log_task_end(db, log_id: int, status: str, result: dict = None, error: str = None):
    """记录任务结束"""
    task_log = db.query(TaskLog).filter(TaskLog.id == log_id).first()
    if task_log:
        task_log.status = status
        task_log.result = result
        task_log.error_message = error[:2000] if error else None
        task_log.finished_at = datetime.utcnow()
        if task_log.started_at:
            delta = task_log.finished_at - task_log.started_at
            task_log.duration_ms = int(delta.total_seconds() * 1000)
        db.commit()


@celery_app.task(
    name="app.tasks.ai_pricing_task.run_ai_pricing_analysis",
    bind=True,
    max_retries=3,
    default_retry_delay=300,  # 失败后5分钟重试
)
def run_ai_pricing_analysis(self):
    """AI智能调价定时任务入口

    遍历所有active的Ozon店铺，对每个店铺执行AI调价分析。
    """
    db = SessionLocal()
    log_id = None

    try:
        log_id = _log_task_start(
            db, "ai_pricing_analysis", self.request.id,
            params={"trigger": "celery_beat"}
        )

        # 查找所有active的Ozon店铺
        shops = db.query(Shop).filter(
            Shop.status == "active",
            Shop.platform == "ozon",
        ).all()

        if not shops:
            logger.info("无active的Ozon店铺，跳过AI分析")
            _log_task_end(db, log_id, "success", result={"msg": "no_active_shops"})
            return

        logger.info(f"开始AI调价分析，共{len(shops)}个Ozon店铺")

        total_suggestions = 0
        shop_results = []

        for shop in shops:
            try:
                result = _run_async(
                    run_ai_analysis(db, shop.tenant_id, shop.id)
                )
                data = result.get("data", {})
                count = data.get("suggestion_count", 0)
                total_suggestions += count
                shop_results.append({
                    "shop_id": shop.id,
                    "shop_name": shop.name,
                    "analyzed": data.get("analyzed_count", 0),
                    "suggestions": count,
                    "auto_executed": data.get("auto_executed_count", 0),
                })
                logger.info(f"店铺 {shop.name}(id={shop.id}) 分析完成: {count}条建议")

            except Exception as e:
                logger.error(f"店铺 {shop.name}(id={shop.id}) AI分析失败: {e}")
                shop_results.append({
                    "shop_id": shop.id,
                    "shop_name": shop.name,
                    "error": str(e)[:200],
                })

        final_result = {
            "shops_processed": len(shops),
            "total_suggestions": total_suggestions,
            "details": shop_results,
        }
        status = "success"
        _log_task_end(db, log_id, status, result=final_result)
        logger.info(f"AI调价任务完成: {len(shops)}个店铺, {total_suggestions}条建议")
        return final_result

    except Exception as e:
        logger.error(f"AI调价任务异常: {e}")
        if log_id:
            _log_task_end(db, log_id, "failed", error=str(e))
        db.rollback()
        raise self.retry(exc=e)
    finally:
        db.close()
