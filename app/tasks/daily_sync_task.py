"""每日数据同步任务

每天凌晨2点同步所有Ozon店铺昨日广告数据。
"""

import asyncio
from datetime import datetime

from app.tasks.celery_app import celery_app
from app.database import SessionLocal
from app.models.shop import Shop
from app.models.task_log import TaskLog
from app.services.data.ozon_stats_collector import sync_yesterday_stats
from app.utils.logger import setup_logger

logger = setup_logger("tasks.daily_sync")


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
    """每天凌晨2点：同步所有Ozon店铺昨日数据"""
    db = SessionLocal()

    try:
        # 记录任务开始
        task_log = TaskLog(
            task_name="daily_sync_all_shops",
            celery_task_id=self.request.id,
            status="running",
            started_at=datetime.utcnow(),
        )
        db.add(task_log)
        db.commit()
        db.refresh(task_log)

        shops = db.query(Shop).filter(
            Shop.status == "active",
            Shop.platform == "ozon",
        ).all()

        if not shops:
            logger.info("无active的Ozon店铺，跳过每日同步")
            task_log.status = "success"
            task_log.result = {"msg": "no_shops"}
            task_log.finished_at = datetime.utcnow()
            db.commit()
            return

        logger.info(f"开始每日数据同步，共{len(shops)}个Ozon店铺")

        from app.services.inventory.linkage_engine import run_linkage_check
        from app.services.inventory.stock_syncer import sync_ozon_platform_stocks

        results = []
        for shop in shops:
            try:
                result = _run_async(sync_yesterday_stats(db, shop.id))
                shop_entry = {
                    "shop_id": shop.id,
                    "shop_name": shop.name,
                    "synced": result.get("synced", 0),
                }
                logger.info(f"店铺 {shop.name} 数据同步完成: {result.get('synced', 0)}条")

                # 库存同步 + 联动检查（失败不影响数据同步结果）
                try:
                    synced_skus = _run_async(sync_ozon_platform_stocks(db, shop))
                    linkage = _run_async(run_linkage_check(db, shop.id))
                    shop_entry["inventory_skus"] = synced_skus
                    shop_entry["linkage"] = linkage
                    logger.info(
                        f"店铺 {shop.name} 库存联动完成: "
                        f"SKU={synced_skus} linkage={linkage}"
                    )
                except Exception as ie:
                    logger.error(f"店铺 {shop.name} 库存联动失败: {ie}")
                    shop_entry["inventory_error"] = str(ie)[:200]

                results.append(shop_entry)
            except Exception as e:
                logger.error(f"店铺 {shop.name} 同步失败: {e}")
                results.append({
                    "shop_id": shop.id,
                    "shop_name": shop.name,
                    "error": str(e)[:200],
                })

        task_log.status = "success"
        task_log.result = {"shops": len(shops), "details": results}
        task_log.finished_at = datetime.utcnow()
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
