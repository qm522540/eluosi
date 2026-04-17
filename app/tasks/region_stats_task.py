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


def _upsert_region_stats(db, tenant_id, shop_id, platform, stat_date, items,
                         returns_by_region=None):
    """写入/更新地区日销售。
    - items: [{region_name, orders, revenue, returns?}] 来自 region-sale API
    - returns_by_region: {region_name: returns_count} 来自 sales API 补退货数
    """
    returns_map = returns_by_region or {}
    n = 0
    for it in items:
        region = (it.get("region_name") or "")[:200]
        if not region:
            continue
        # 退货：优先 sales API 聚合值，其次 items 自带
        returns_val = returns_map.get(region, it.get("returns") or 0)
        existing = db.query(RegionDailyStat).filter(
            RegionDailyStat.tenant_id == tenant_id,
            RegionDailyStat.shop_id == shop_id,
            RegionDailyStat.region_name == region,
            RegionDailyStat.stat_date == stat_date,
        ).first()
        if existing:
            existing.orders = it.get("orders", 0)
            existing.revenue = it.get("revenue", 0)
            existing.returns = returns_val
        else:
            db.add(RegionDailyStat(
                tenant_id=tenant_id, shop_id=shop_id, platform=platform,
                region_name=region, stat_date=stat_date,
                orders=it.get("orders", 0),
                revenue=it.get("revenue", 0),
                returns=returns_val,
            ))
            n += 1
    db.commit()
    return n


async def _sync_wb_region(db, shop, date_from, date_to):
    """同步一个时间段（date_from~date_to）的 WB 地区销售 + 按地区退货。
    - 销售：region-sale API（按 regionName 聚合 orders/revenue），日维度合并到 date_to 这一天
    - 退货：sales API（按 regionName + date 聚合），按 stat_date 分别回填
    """
    from app.services.platform.wb import WBClient
    client = WBClient(shop_id=shop.id, api_key=shop.api_key)
    try:
        items = await client.fetch_region_sales(date_from, date_to)
        returns_map = await client.fetch_sales_returns_by_region(date_from, date_to)

        stat_date = date.fromisoformat(date_to)
        # 如果只同步单日，退货直接按该日 region 聚合；多日时退货按每日分别写入，主销售仍合并到 date_to
        daily_returns = {}
        for (region, d_str), cnt in returns_map.items():
            daily_returns.setdefault(d_str, {})[region] = cnt

        # 销售合并到 date_to，退货取 date_to 当天（和 date_to 对齐）
        return_for_date_to = daily_returns.get(date_to, {})
        n = _upsert_region_stats(
            db, shop.tenant_id, shop.id, "wb", stat_date, items,
            returns_by_region=return_for_date_to,
        )

        # 多日情形：其它日期的退货独立回写（orders/revenue 为 0，只改 returns）
        extra_dates = [d for d in daily_returns.keys() if d != date_to]
        extra_updated = 0
        for d_str in extra_dates:
            sd = date.fromisoformat(d_str)
            for region, cnt in daily_returns[d_str].items():
                row = db.query(RegionDailyStat).filter(
                    RegionDailyStat.tenant_id == shop.tenant_id,
                    RegionDailyStat.shop_id == shop.id,
                    RegionDailyStat.region_name == region[:200],
                    RegionDailyStat.stat_date == sd,
                ).first()
                if row:
                    row.returns = cnt
                    extra_updated += 1
        if extra_updated:
            db.commit()

        return {
            "regions": len(items), "inserted": n,
            "returns_rows": len(returns_map),
            "extra_returns_updated": extra_updated,
        }
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
            # WB region-sale API 返回的是【日期段汇总】（无 date 字段），所以按天逐日回填，
            # 保证 orders/revenue/returns 都对齐到正确的 stat_date。
            total = 0
            total_returns = 0
            today = date.today()
            for i in range(1, days + 1):
                d = today - timedelta(days=i)
                d_str = d.isoformat()
                try:
                    r = _run_async(_sync_wb_region(db, shop, d_str, d_str))
                except Exception as e:
                    logger.warning(f"WB 地区回填 {d_str} 失败: {e}")
                    continue
                total += r.get("inserted", 0)
                total_returns += r.get("returns_rows", 0)
                logger.info(
                    f"WB 地区回填 {d_str}: 地区 {r.get('regions', 0)} / +{r.get('inserted', 0)} / "
                    f"退货 {r.get('returns_rows', 0)}"
                )
            return {
                "shop_id": shop_id, "platform": "wb",
                "inserted": total, "returns_rows": total_returns,
            }
        return {"shop_id": shop_id, "platform": shop.platform, "msg": "暂不支持"}
    except Exception as e:
        logger.error(f"地区回填异常: {e}")
        db.rollback()
        raise self.retry(exc=e)
    finally:
        db.close()
