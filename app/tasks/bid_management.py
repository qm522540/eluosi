"""出价管理统一 Celery 任务

调度：莫斯科时间每小时:05分触发（celery_app.beat_schedule + timezone=Europe/Moscow）

执行流程（docs/api/bid_management.md §9.3）：
  1. 遍历所有 active Ozon 店铺
  2. 对每个店铺：
     a. 查 time_pricing_rules.is_active 和 ai_pricing_configs.is_active
     b. 互斥（API 层 FOR UPDATE 保证）
     c. is_active=true → 派发到对应 executor
     d. 失败时写 last_execute_status='failed' + retry_at=now+30min
  3. 多店铺间隔 60 秒（避免同时打 Ozon API）
"""

import asyncio
import time

from sqlalchemy import text

from app.database import SessionLocal
from app.models.shop import Shop
from app.tasks.celery_app import celery_app
from app.utils.logger import setup_logger

logger = setup_logger("tasks.bid_management")


def _run_async(coro):
    """项目标准 async 包装器"""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(
    name="app.tasks.bid_management.run_bid_management",
    bind=True,
    max_retries=2,
    default_retry_delay=300,
)
def run_bid_management(self):
    """每小时:05莫斯科时间触发的统一出价管理入口"""
    db = SessionLocal()
    try:
        shops = db.query(Shop).filter(
            Shop.platform == "ozon",
            Shop.status == "active",
        ).all()

        if not shops:
            logger.info("出价管理：无active的Ozon店铺")
            return {"shops": 0}

        logger.info(f"出价管理：开始执行 共{len(shops)}个店铺")

        results = []
        for i, shop in enumerate(shops):
            try:
                result = _process_shop(db, shop)
                results.append({
                    "shop_id": shop.id,
                    "shop_name": shop.name,
                    **(result or {}),
                })
            except Exception as e:
                logger.error(f"店铺 {shop.name} 出价管理异常: {e}")
                results.append({
                    "shop_id": shop.id,
                    "shop_name": shop.name,
                    "error": str(e)[:200],
                })

            if i < len(shops) - 1:
                logger.info("等待60秒执行下一个店铺...")
                time.sleep(60)

        logger.info(f"出价管理：本次执行完成 {len(results)}个店铺")
        return {"shops": len(results), "results": results}

    except Exception as e:
        logger.error(f"出价管理任务异常: {e}")
        raise self.retry(exc=e)
    finally:
        db.close()


def _process_shop(db, shop) -> dict:
    """处理单个店铺：分时调价 vs AI 调价 二选一"""
    row = db.execute(text("""
        SELECT
            (SELECT is_active FROM time_pricing_rules WHERE shop_id = :sid LIMIT 1) AS time_active,
            (SELECT is_active FROM ai_pricing_configs WHERE shop_id = :sid LIMIT 1) AS ai_active
    """), {"sid": shop.id}).fetchone()

    time_active = bool(row and row.time_active)
    ai_active = bool(row and row.ai_active)

    if time_active and ai_active:
        # 理论不应发生（API 层互斥），但运行期容错
        logger.warning(f"店铺 {shop.name} 互斥违例: 分时和AI都启用，按分时优先")

    if time_active:
        from app.services.bid.time_pricing_executor import execute as exec_time
        logger.info(f"店铺 {shop.name} 执行分时调价")
        return {"mode": "time_pricing", **(_run_async(exec_time(db, shop.id)) or {})}

    if ai_active:
        from app.services.bid.ai_pricing_executor import execute as exec_ai
        logger.info(f"店铺 {shop.name} 执行AI调价")
        return {"mode": "ai", **(_run_async(exec_ai(db, shop.id)) or {})}

    logger.info(f"店铺 {shop.name} 未启用任何模式，跳过")
    return {"mode": "none"}
