"""AI智能调价定时任务

触发机制：每10分钟Celery Beat检查一次，由时段策略决定是否真正执行
- 高峰期（10-14、19-23莫斯科时间）：每30分钟执行
- 平稳期/低谷期：每2小时执行
- 冷却时间：同一活动20分钟内不重复调价

Redis key设计：
- ai_pricing:last_run:{shop_id} — 店铺上次AI分析执行时间
- ai_pricing:cooldown:{campaign_id} — 活动调价冷却时间
"""

import asyncio
from datetime import datetime, timezone

import redis as redis_lib

from app.tasks.celery_app import celery_app
from app.config import get_settings
from app.database import SessionLocal
from app.models.shop import Shop
from app.models.task_log import TaskLog
from app.services.ai.time_strategy import (
    get_current_moscow_strategy, should_run_now,
)
from app.services.ad.ai_pricing import run_ai_analysis
from app.utils.logger import setup_logger

logger = setup_logger("tasks.ai_pricing")
settings = get_settings()

# Redis key 模板
LAST_RUN_KEY = "ai_pricing:last_run:{shop_id}"
LAST_RUN_TTL = 10800  # 3小时过期


def _run_async(coro):
    """在同步Celery任务中执行异步代码"""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _get_redis():
    """获取同步Redis客户端"""
    return redis_lib.from_url(settings.REDIS_URL, decode_responses=True)


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
    name="app.tasks.ai_pricing_task.check_and_run_ai_pricing",
    bind=True,
    max_retries=3,
    default_retry_delay=300,
)
def check_and_run_ai_pricing(self):
    """每10分钟触发，根据莫斯科时段策略决定是否执行AI调价

    高峰期（30分钟间隔）→ 加价抢量
    平稳期（2小时间隔）→ ROI优化
    低谷期（2小时间隔）→ 大幅降价省预算
    """
    db = SessionLocal()
    log_id = None
    r = _get_redis()

    try:
        moscow_hour, strategy = get_current_moscow_strategy()
        logger.info(
            f"AI调价检查 莫斯科时间={moscow_hour}点 "
            f"时段={strategy.name} "
            f"巡检间隔={strategy.check_interval_minutes}分钟 "
            f"方向={strategy.bid_adjust_direction}"
        )

        # 查找所有active的Ozon店铺
        shops = db.query(Shop).filter(
            Shop.status == "active",
            Shop.platform == "ozon",
        ).all()

        if not shops:
            logger.info("无active的Ozon店铺，跳过")
            return {"msg": "no_active_shops", "time_slot": strategy.name}

        # 检查每个店铺是否到了执行时间
        shops_to_run = []
        for shop in shops:
            last_run_key = LAST_RUN_KEY.format(shop_id=shop.id)
            last_run_iso = r.get(last_run_key)

            if should_run_now(last_run_iso, strategy):
                shops_to_run.append(shop)
            else:
                logger.debug(
                    f"店铺 {shop.name}(id={shop.id}) 未到巡检间隔，跳过"
                )

        if not shops_to_run:
            logger.info(f"所有店铺均未到巡检间隔，跳过 (时段={strategy.name})")
            return {"msg": "all_skipped", "time_slot": strategy.name}

        # 记录任务开始
        log_id = _log_task_start(
            db, f"ai_pricing_{strategy.slot_key}", self.request.id,
            params={
                "trigger": "celery_beat",
                "time_slot": strategy.name,
                "moscow_hour": moscow_hour,
                "direction": strategy.bid_adjust_direction,
                "shops_count": len(shops_to_run),
            }
        )

        logger.info(
            f"开始AI调价: {len(shops_to_run)}/{len(shops)}个店铺需执行 "
            f"时段={strategy.name}"
        )

        total_suggestions = 0
        total_executed = 0
        shop_results = []

        for shop in shops_to_run:
            try:
                result = _run_async(
                    run_ai_analysis(
                        db, shop.tenant_id, shop.id,
                        time_strategy=strategy,
                        moscow_hour=moscow_hour,
                    )
                )
                data = result.get("data", {})
                count = data.get("suggestion_count", 0)
                executed = data.get("auto_executed_count", 0)
                total_suggestions += count
                total_executed += executed

                shop_results.append({
                    "shop_id": shop.id,
                    "shop_name": shop.name,
                    "analyzed": data.get("analyzed_count", 0),
                    "suggestions": count,
                    "auto_executed": executed,
                    "time_slot": strategy.name,
                })

                # 记录本次执行时间到Redis
                r.setex(
                    LAST_RUN_KEY.format(shop_id=shop.id),
                    LAST_RUN_TTL,
                    datetime.now(timezone.utc).isoformat(),
                )

                logger.info(
                    f"店铺 {shop.name}(id={shop.id}) 分析完成: "
                    f"{count}条建议, {executed}条自动执行 "
                    f"(时段={strategy.name})"
                )

            except Exception as e:
                logger.error(f"店铺 {shop.name}(id={shop.id}) AI分析失败: {e}")
                shop_results.append({
                    "shop_id": shop.id,
                    "shop_name": shop.name,
                    "error": str(e)[:200],
                })

        final_result = {
            "time_slot": strategy.name,
            "moscow_hour": moscow_hour,
            "direction": strategy.bid_adjust_direction,
            "shops_checked": len(shops),
            "shops_executed": len(shops_to_run),
            "total_suggestions": total_suggestions,
            "total_auto_executed": total_executed,
            "details": shop_results,
        }
        _log_task_end(db, log_id, "success", result=final_result)
        logger.info(
            f"AI调价任务完成: 时段={strategy.name} "
            f"{len(shops_to_run)}个店铺 "
            f"{total_suggestions}条建议 "
            f"{total_executed}条自动执行"
        )
        return final_result

    except Exception as e:
        logger.error(f"AI调价任务异常: {e}")
        if log_id:
            _log_task_end(db, log_id, "failed", error=str(e))
        db.rollback()
        raise self.retry(exc=e)
    finally:
        db.close()
        r.close()
