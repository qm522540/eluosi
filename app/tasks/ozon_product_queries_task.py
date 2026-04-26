"""Ozon SKU × 搜索词数据每日同步 — 搜索词洞察 SEO 流量

每日莫斯科 MSK 05:30（Celery `timezone="Europe/Moscow"` → crontab 按 MSK 直解）
- 遍历所有 active Ozon 店铺
- 复用 search_insights.service.refresh_shop（与 WB beat 同模式，统一窗口/stat_date 语义）
- 写入 product_search_queries（platform='ozon'）—— 与 WB 共用底表
- 清理 90 天前 Ozon 数据

无 Premium 订阅的店铺 refresh_shop 返回 code=93001 → 本任务记 skipped。

历史：
- 2026-04-19 合并到 product_search_queries 共用表（原 ozon_product_queries 已废弃）
- 2026-04-26 重构：从自己手写 _sync_one_shop 改为复用 refresh_shop，统一窗口
  date_to=today-2 + 享受幂等保护（避免与手动同步并发烧 quota）+ 修规则 6 时区违规
"""

import asyncio
from datetime import timedelta

from sqlalchemy import text

from app.tasks.celery_app import celery_app
from app.database import SessionLocal
from app.models.shop import Shop
from app.services.search_insights.service import refresh_shop
from app.utils.logger import setup_logger
from app.utils.moscow_time import moscow_today

logger = setup_logger("tasks.ozon_product_queries")


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(
    name="app.tasks.ozon_product_queries_task.sync_ozon_product_queries",
    bind=True, max_retries=1, default_retry_delay=600,
)
def sync_ozon_product_queries(self):
    """每日扫所有 Ozon 店铺 → 拉过去 7 天 SKU × 搜索词数据"""
    db = SessionLocal()
    try:
        shops = db.query(Shop).filter(
            Shop.platform == "ozon", Shop.status == "active",
            Shop.api_key.isnot(None),
        ).all()
        results = []
        for shop in shops:
            try:
                r = _run_async(refresh_shop(db, shop.tenant_id, shop, days=7))
                code = r.get("code", 0)
                data = r.get("data") or {}
                if code == 93001:
                    logger.info(f"shop_id={shop.id} {shop.name} 未开通 Ozon Premium，跳过")
                    results.append({"shop_id": shop.id, "skipped": "no_premium"})
                    continue
                if code != 0:
                    logger.warning(f"shop_id={shop.id} refresh 失败 code={code} msg={r.get('msg')}")
                    results.append({"shop_id": shop.id, "error_code": code})
                    continue
                # 幂等保护命中（已有快照 / 锁占用）
                if data.get("skipped"):
                    logger.info(
                        f"shop_id={shop.id} {shop.name} skipped reason={data.get('reason')}"
                    )
                    results.append({
                        "shop_id": shop.id,
                        "skipped": data.get("reason"),
                        "existing_rows": data.get("existing_rows"),
                    })
                    continue
                logger.info(
                    f"shop_id={shop.id} {shop.name} synced_queries={data.get('synced_queries')} "
                    f"range={data.get('date_range')}"
                )
                results.append({
                    "shop_id": shop.id,
                    "synced_queries": data.get("synced_queries"),
                    "errors": data.get("errors"),
                })
            except Exception as e:
                logger.error(f"shop_id={shop.id} 同步异常: {e}", exc_info=True)
                results.append({"shop_id": shop.id, "error": str(e)[:200]})

        # 清理 90 天前 Ozon 数据（共用表，限定 platform='ozon'）
        cutoff = (moscow_today() - timedelta(days=90))
        deleted = db.execute(text("""
            DELETE FROM product_search_queries
            WHERE platform='ozon' AND stat_date < :cutoff
        """), {"cutoff": cutoff}).rowcount
        db.commit()
        if deleted:
            logger.info(f"清理 {deleted} 条 90 天前 Ozon SKU×query 数据")
        return {"shops": len(shops), "results": results, "cleaned": deleted}
    except Exception as e:
        logger.error(f"Ozon SKU×query 全局任务异常: {e}", exc_info=True)
        db.rollback()
        raise self.retry(exc=e)
    finally:
        db.close()


@celery_app.task(
    name="app.tasks.ozon_product_queries_task.sync_ozon_product_queries_for_shop",
    bind=True,
)
def sync_ozon_product_queries_for_shop(self, shop_id: int, tenant_id: int,
                                       days: int = 7, force: bool = False):
    """单店铺手动触发（"立即同步"按钮专用）

    force=True 时跳过当日快照预检（仍受 in-progress 锁约束）
    """
    db = SessionLocal()
    try:
        shop = db.query(Shop).filter(
            Shop.id == shop_id, Shop.tenant_id == tenant_id, Shop.platform == "ozon",
        ).first()
        if not shop:
            return {"error": "店铺不存在或非 Ozon"}
        return _run_async(refresh_shop(db, tenant_id, shop, days=days, force=force))
    finally:
        db.close()
