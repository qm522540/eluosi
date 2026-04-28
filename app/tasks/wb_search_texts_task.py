"""WB 商品搜索词（search-texts）每日同步 — 搜索词洞察 SEO 流量

每日莫斯科 MSK 04:00（Celery `timezone="Europe/Moscow"` → crontab 按 MSK 直解）
- 遍历所有 active WB 店铺（有 api_key）
- 复用 search_insights.service.refresh_shop → 批量 nmIds + 限流间隔
- 写入 product_search_queries（platform='wb'）—— 与 Ozon 共用底表
- 清理 90 天前 WB 数据

无 Jam 订阅的店铺 refresh_shop 返回 code=93001 → 本任务记 skipped，继续下一个店。

实测 2026-04-23：WB search-texts 端点限流严（估 3-5 rpm），refresh_shop WB 分支
每 50 nmIds 一批 + 批间 15s sleep。单店 609 nmIds ≈ 12 批 × 15s = 3 min。
"""

from datetime import timedelta

from sqlalchemy import text

from app.tasks.celery_app import celery_app
from app.database import SessionLocal
from app.models.shop import Shop
from app.services.data_source.service import is_data_source_enabled, record_sync_run
from app.services.search_insights.service import refresh_shop
from app.utils.logger import setup_logger
from app.utils.moscow_time import moscow_today, utc_now_naive

import asyncio

logger = setup_logger("tasks.wb_search_texts")


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(
    name="app.tasks.wb_search_texts_task.sync_wb_search_texts",
    bind=True, max_retries=1, default_retry_delay=600,
)
def sync_wb_search_texts(self):
    """每日扫所有 WB 店铺 → 拉过去 7 天 SKU × 搜索词数据（SEO 流量）"""
    db = SessionLocal()
    try:
        shops = db.query(Shop).filter(
            Shop.platform == "wb", Shop.status == "active",
            Shop.api_key.isnot(None),
        ).all()
        results = []
        for shop in shops:
            # 数据源开关 hook
            enabled, skip_reason = is_data_source_enabled(
                db, shop.tenant_id, shop.id, "wb_search_texts",
            )
            if not enabled:
                logger.info(f"shop_id={shop.id} wb_search_texts 跳过: {skip_reason}")
                record_sync_run(db, shop.tenant_id, shop.id, "wb_search_texts",
                               status="skipped", msg=skip_reason or "")
                results.append({"shop_id": shop.id, "skipped": skip_reason})
                continue

            t0 = utc_now_naive()
            try:
                r = _run_async(refresh_shop(db, shop.tenant_id, shop, days=7))
                code = r.get("code", 0)
                data = r.get("data") or {}
                dur_ms = int((utc_now_naive() - t0).total_seconds() * 1000)
                if code == 93001:
                    logger.info(f"shop_id={shop.id} {shop.name} 未开通 Jam，跳过")
                    record_sync_run(db, shop.tenant_id, shop.id, "wb_search_texts",
                                   status="skipped", msg="未开通 Jam 订阅", duration_ms=dur_ms)
                    results.append({"shop_id": shop.id, "skipped": "no_jam"})
                    continue
                if code != 0:
                    logger.warning(f"shop_id={shop.id} refresh 失败 code={code} msg={r.get('msg')}")
                    record_sync_run(db, shop.tenant_id, shop.id, "wb_search_texts",
                                   status="failed",
                                   msg=f"code={code} {r.get('msg', '')}"[:500],
                                   duration_ms=dur_ms)
                    results.append({"shop_id": shop.id, "error_code": code})
                    continue
                # quota 冷却 skip（refresh_shop 顶层 pre-check 命中）
                if data.get("skipped"):
                    logger.info(
                        f"shop_id={shop.id} {shop.name} skipped reason={data.get('reason')} "
                        f"cooldown={data.get('cooldown_seconds')}s"
                    )
                    record_sync_run(db, shop.tenant_id, shop.id, "wb_search_texts",
                                   status="skipped",
                                   msg=f"{data.get('reason', '')} cooldown={data.get('cooldown_seconds')}s"[:500],
                                   duration_ms=dur_ms)
                    results.append({
                        "shop_id": shop.id,
                        "skipped": data.get("reason"),
                        "cooldown_seconds": data.get("cooldown_seconds"),
                    })
                    continue
                synced = int(data.get("synced_queries") or 0)
                errs = data.get("errors") or []
                rec_status = "partial" if errs else "success"
                rec_msg = "; ".join(errs)[:500] if errs else f"range={data.get('date_range')}"
                record_sync_run(db, shop.tenant_id, shop.id, "wb_search_texts",
                               status=rec_status, rows=synced, duration_ms=dur_ms,
                               msg=rec_msg)
                logger.info(
                    f"shop_id={shop.id} {shop.name} synced_queries={synced} "
                    f"range={data.get('date_range')}"
                )
                results.append({
                    "shop_id": shop.id,
                    "synced_queries": synced,
                    "errors": errs,
                })
            except Exception as e:
                dur_ms = int((utc_now_naive() - t0).total_seconds() * 1000)
                record_sync_run(db, shop.tenant_id, shop.id, "wb_search_texts",
                               status="failed", msg=str(e)[:500], duration_ms=dur_ms)
                logger.error(f"shop_id={shop.id} 同步异常: {e}", exc_info=True)
                results.append({"shop_id": shop.id, "error": str(e)[:200]})

        # 清理 90 天前 WB 数据（共用表，限定 platform='wb'）
        cutoff = (moscow_today() - timedelta(days=90))
        deleted = db.execute(text("""
            DELETE FROM product_search_queries
            WHERE platform='wb' AND stat_date < :cutoff
        """), {"cutoff": cutoff}).rowcount
        db.commit()
        if deleted:
            logger.info(f"清理 {deleted} 条 90 天前 WB SKU×query 数据")
        return {"shops": len(shops), "results": results, "cleaned": deleted}
    except Exception as e:
        logger.error(f"WB search-texts 全局任务异常: {e}", exc_info=True)
        db.rollback()
        raise self.retry(exc=e)
    finally:
        db.close()


@celery_app.task(
    name="app.tasks.wb_search_texts_task.sync_wb_search_texts_for_shop",
    bind=True,
)
def sync_wb_search_texts_for_shop(self, shop_id: int, tenant_id: int, days: int = 7):
    """单店铺手动触发（前端立即同步按钮/Celery 异步化入口）"""
    db = SessionLocal()
    try:
        shop = db.query(Shop).filter(
            Shop.id == shop_id, Shop.tenant_id == tenant_id, Shop.platform == "wb",
        ).first()
        if not shop:
            return {"error": "店铺不存在或非 WB"}
        return _run_async(refresh_shop(db, tenant_id, shop, days=days))
    finally:
        db.close()
