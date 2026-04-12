"""每日数据同步任务

每天凌晨2点同步所有店铺（Ozon + WB）昨日广告数据。
调用各平台的 smart_sync()，逻辑：查最新日期 → 补拉到昨天 → 清理90天前旧数据。
"""

import asyncio
from datetime import datetime, timezone

from app.tasks.celery_app import celery_app
from app.database import SessionLocal
from app.models.shop import Shop
from app.models.task_log import TaskLog
from app.services.data.ozon_stats_collector import smart_sync as ozon_smart_sync
from app.services.data.wb_stats_collector import smart_sync as wb_smart_sync
from app.utils.logger import setup_logger

logger = setup_logger("tasks.daily_sync")

PLATFORM_SYNC = {
    "ozon": ozon_smart_sync,
    "wb": wb_smart_sync,
}


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(
    name="app.tasks.daily_sync_task.daily_sync_all_shops",
    bind=True,
    max_retries=3,
    default_retry_delay=600,
)
def daily_sync_all_shops(self):
    """每天凌晨2点：同步所有 Ozon + WB 店铺昨日数据"""
    db = SessionLocal()

    try:
        task_log = TaskLog(
            task_name="daily_sync_all_shops",
            celery_task_id=self.request.id,
            status="running",
            started_at=datetime.now(timezone.utc),
        )
        db.add(task_log)
        db.commit()
        db.refresh(task_log)

        shops = db.query(Shop).filter(
            Shop.status == "active",
            Shop.platform.in_(list(PLATFORM_SYNC.keys())),
        ).all()

        if not shops:
            logger.info("无active的Ozon/WB店铺，跳过每日同步")
            task_log.status = "success"
            task_log.result = {"msg": "no_shops"}
            task_log.finished_at = datetime.now(timezone.utc)
            db.commit()
            return

        logger.info(f"开始每日数据同步，共{len(shops)}个店铺")

        results = []
        for shop in shops:
            sync_fn = PLATFORM_SYNC.get(shop.platform)
            if not sync_fn:
                continue
            try:
                result = _run_async(sync_fn(db, shop.id, shop.tenant_id))
                results.append({
                    "shop_id": shop.id,
                    "shop_name": shop.name,
                    "platform": shop.platform,
                    "synced": result.get("synced", 0),
                })
                logger.info(f"店铺 {shop.name}({shop.platform}) 同步完成: {result.get('synced', 0)}条")
            except Exception as e:
                logger.error(f"店铺 {shop.name}({shop.platform}) 同步失败: {e}")
                results.append({
                    "shop_id": shop.id,
                    "shop_name": shop.name,
                    "platform": shop.platform,
                    "error": str(e)[:200],
                })

        task_log.status = "success"
        task_log.result = {"shops": len(shops), "details": results}
        task_log.finished_at = datetime.now(timezone.utc)
        if task_log.started_at:
            delta = task_log.finished_at - task_log.started_at
            task_log.duration_ms = int(delta.total_seconds() * 1000)
        db.commit()

        logger.info(f"每日数据同步完成: {len(shops)}个店铺")

    except Exception as e:
        logger.error(f"每日同步任务异常: {e}")
        db.rollback()
        raise self.retry(exc=e)
    finally:
        db.close()
