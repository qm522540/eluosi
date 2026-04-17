"""地区销售数据采集任务"""

import asyncio
from datetime import date, timedelta, datetime, timezone

from app.tasks.celery_app import celery_app
from app.database import SessionLocal
from app.models.shop import Shop
from app.models.region_stat import RegionDailyStat
from app.utils.logger import setup_logger

logger = setup_logger("tasks.region_stats")


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _upsert_region_stats(db, tenant_id, shop_id, platform, stat_date, items):
    n = 0
    for it in items:
        region = (it.get("region_name") or "")[:200]
        if not region:
            continue
        existing = db.query(RegionDailyStat).filter(
            RegionDailyStat.tenant_id == tenant_id,
            RegionDailyStat.shop_id == shop_id,
            RegionDailyStat.region_name == region,
            RegionDailyStat.stat_date == stat_date,
        ).first()
        if existing:
            existing.orders = it.get("orders", 0)
            existing.revenue = it.get("revenue", 0)
            existing.returns = it.get("returns", 0)
        else:
            db.add(RegionDailyStat(
                tenant_id=tenant_id, shop_id=shop_id, platform=platform,
                region_name=region, stat_date=stat_date,
                orders=it.get("orders", 0),
                revenue=it.get("revenue", 0),
                returns=it.get("returns", 0),
            ))
            n += 1
    db.commit()
    return n


async def _sync_wb_region(db, shop, date_from, date_to):
    from app.services.platform.wb import WBClient
    client = WBClient(shop_id=shop.id, api_key=shop.api_key)
    try:
        items = await client.fetch_region_sales(date_from, date_to)
        stat_date = date.fromisoformat(date_to)
        n = _upsert_region_stats(db, shop.tenant_id, shop.id, "wb", stat_date, items)
        return {"regions": len(items), "inserted": n}
    finally:
        await client.close()


@celery_app.task(
    name="app.tasks.region_stats_task.sync_region_stats",
    bind=True, max_retries=2, default_retry_delay=120,
)
def sync_region_stats(self):
    db = SessionLocal()
    try:
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        shops = db.query(Shop).filter(Shop.status == "active", Shop.api_key.isnot(None)).all()
        results = {}
        for shop in shops:
            if shop.platform == "wb":
                r = _run_async(_sync_wb_region(db, shop, yesterday, yesterday))
                results[shop.id] = r
                logger.info(f"WB 地区销售同步 shop={shop.id}: {r}")
        # 清理 90 天前
        cutoff = (date.today() - timedelta(days=90)).isoformat()
        deleted = db.query(RegionDailyStat).filter(RegionDailyStat.stat_date < cutoff).delete()
        db.commit()
        if deleted:
            logger.info(f"清理 {deleted} 条过期地区数据")
        return results
    except Exception as e:
        logger.error(f"地区销售同步异常: {e}")
        db.rollback()
        raise self.retry(exc=e)
    finally:
        db.close()


@celery_app.task(
    name="app.tasks.region_stats_task.backfill_region_stats",
    bind=True, max_retries=1,
)
def backfill_region_stats(self, shop_id, tenant_id, days=90):
    db = SessionLocal()
    try:
        shop = db.query(Shop).filter(Shop.id == shop_id).first()
        if not shop:
            return {"error": "店铺不存在"}
        if shop.platform == "wb":
            total = 0
            today = date.today()
            # WB 单次最多 31 天
            for i in range(0, days, 31):
                d_to = today - timedelta(days=i + 1)
                d_from = today - timedelta(days=min(i + 31, days))
                if d_from > d_to:
                    continue
                r = _run_async(_sync_wb_region(db, shop, d_from.isoformat(), d_to.isoformat()))
                total += r.get("inserted", 0)
                logger.info(f"WB 地区回填 {d_from}~{d_to}: +{r.get('inserted', 0)}")
            return {"shop_id": shop_id, "platform": "wb", "inserted": total}
        return {"shop_id": shop_id, "platform": shop.platform, "msg": "暂不支持"}
    except Exception as e:
        logger.error(f"地区回填异常: {e}")
        db.rollback()
        raise self.retry(exc=e)
    finally:
        db.close()
