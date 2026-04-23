"""关键词统计数据采集任务

每日凌晨增量拉取昨天数据 + 手动回填最多 90 天。
"""

import asyncio
import math
from datetime import date, timedelta, datetime, timezone

from app.utils.moscow_time import moscow_today

from app.tasks.celery_app import celery_app
from app.database import SessionLocal
from app.models.shop import Shop
from app.models.ad import AdCampaign
from app.models.keyword_stat import KeywordDailyStat
from app.utils.logger import setup_logger

logger = setup_logger("tasks.keyword_stats")


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _upsert_keyword_stats(db, tenant_id, shop_id, platform, campaign_id,
                          platform_campaign_id, items: list) -> int:
    """批量 upsert 关键词统计"""
    inserted = 0
    for it in items:
        kw = it.get("keyword", "")[:500]
        if not kw:
            continue
        stat_date = it.get("date")
        if isinstance(stat_date, str):
            stat_date = date.fromisoformat(stat_date)
        sku = it.get("sku") or None

        existing = db.query(KeywordDailyStat).filter(
            KeywordDailyStat.tenant_id == tenant_id,
            KeywordDailyStat.shop_id == shop_id,
            KeywordDailyStat.campaign_id == campaign_id,
            KeywordDailyStat.keyword == kw,
            KeywordDailyStat.sku == sku if sku else KeywordDailyStat.sku.is_(None),
            KeywordDailyStat.stat_date == stat_date,
        ).first()

        if existing:
            existing.impressions = it.get("impressions", 0)
            existing.clicks = it.get("clicks", 0)
            existing.spend = it.get("spend", 0)
            existing.ctr = it.get("ctr", 0)
            existing.cpc = it.get("cpc", 0)
        else:
            db.add(KeywordDailyStat(
                tenant_id=tenant_id, shop_id=shop_id, platform=platform,
                campaign_id=campaign_id, platform_campaign_id=platform_campaign_id,
                keyword=kw, sku=sku, stat_date=stat_date,
                impressions=it.get("impressions", 0),
                clicks=it.get("clicks", 0),
                spend=it.get("spend", 0),
                ctr=it.get("ctr", 0),
                cpc=it.get("cpc", 0),
            ))
            inserted += 1
    db.commit()
    return inserted


async def _sync_wb_shop_keywords(db, shop, date_from: str, date_to: str) -> dict:
    """拉一个 WB 店铺指定日期范围的关键词统计"""
    from app.services.platform.wb import WBClient
    campaigns = db.query(AdCampaign).filter(
        AdCampaign.shop_id == shop.id, AdCampaign.tenant_id == shop.tenant_id,
        AdCampaign.platform == "wb", AdCampaign.status.in_(["active", "paused"]),
    ).all()

    client = WBClient(shop_id=shop.id, api_key=shop.api_key)
    total = 0
    errors = []
    try:
        for camp in campaigns:
            try:
                items = await client.fetch_keyword_stats(
                    camp.platform_campaign_id, date_from, date_to,
                )
                n = _upsert_keyword_stats(
                    db, shop.tenant_id, shop.id, "wb",
                    camp.id, camp.platform_campaign_id, items,
                )
                total += n
            except Exception as e:
                errors.append(f"活动 {camp.platform_campaign_id}: {e}")
    finally:
        await client.close()
    return {"campaigns": len(campaigns), "inserted": total, "errors": errors}


@celery_app.task(
    name="app.tasks.keyword_stats_task.sync_keyword_stats",
    bind=True, max_retries=2, default_retry_delay=120,
)
def sync_keyword_stats(self):
    """每日增量拉取昨天的关键词统计"""
    db = SessionLocal()
    try:
        yesterday = (moscow_today() - timedelta(days=1)).isoformat()
        shops = db.query(Shop).filter(
            Shop.status == "active", Shop.api_key.isnot(None),
        ).all()
        results = {}
        for shop in shops:
            if shop.platform == "wb":
                r = _run_async(_sync_wb_shop_keywords(db, shop, yesterday, yesterday))
                results[shop.id] = r
                logger.info(f"WB shop={shop.id} 关键词同步: {r}")
            # OZON: 异步报告，后续补
        # 清理 90 天前数据
        cutoff = (moscow_today() - timedelta(days=90)).isoformat()
        deleted = db.query(KeywordDailyStat).filter(
            KeywordDailyStat.stat_date < cutoff,
        ).delete()
        db.commit()
        if deleted:
            logger.info(f"清理 {deleted} 条 90 天前关键词数据")
        return {"shops": len(shops), "results": results}
    except Exception as e:
        logger.error(f"关键词同步异常: {e}")
        db.rollback()
        raise self.retry(exc=e)
    finally:
        db.close()


@celery_app.task(
    name="app.tasks.keyword_stats_task.backfill_keyword_stats",
    bind=True, max_retries=1,
)
def backfill_keyword_stats(self, shop_id: int, tenant_id: int, days: int = 90):
    """手动回填历史关键词数据（WB 拆 7 天窗口）"""
    db = SessionLocal()
    try:
        shop = db.query(Shop).filter(Shop.id == shop_id).first()
        if not shop:
            return {"error": "店铺不存在"}
        if shop.platform == "wb":
            today = moscow_today()
            total = 0
            # 拆成 7 天窗口
            for i in range(0, days, 7):
                d_to = today - timedelta(days=i + 1)
                d_from = today - timedelta(days=min(i + 7, days))
                if d_from > d_to:
                    continue
                r = _run_async(_sync_wb_shop_keywords(
                    db, shop, d_from.isoformat(), d_to.isoformat(),
                ))
                total += r.get("inserted", 0)
                logger.info(f"WB 回填 {d_from}~{d_to}: +{r.get('inserted', 0)}")
            return {"shop_id": shop_id, "platform": "wb", "days": days, "inserted": total}
        # OZON 后续补
        return {"shop_id": shop_id, "platform": shop.platform, "msg": "暂不支持"}
    except Exception as e:
        logger.error(f"关键词回填异常: {e}")
        db.rollback()
        raise self.retry(exc=e)
    finally:
        db.close()
