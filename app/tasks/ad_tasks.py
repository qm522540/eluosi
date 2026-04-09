"""广告数据采集任务

定时从 WB/Ozon/Yandex 三平台拉取广告数据，写入 ad_campaigns + ad_stats 表。
调度频率：每小时执行一次（见 celery_app.py beat_schedule）。
"""

import asyncio
from datetime import datetime, date, timedelta

from app.tasks.celery_app import celery_app
from app.database import SessionLocal
from app.models.shop import Shop
from app.models.ad import AdCampaign, AdStat
from app.models.task_log import TaskLog
from app.services.platform.wb import WBClient
from app.services.platform.ozon import OzonClient
from app.services.platform.yandex import YandexClient
from app.utils.logger import setup_logger

logger = setup_logger("tasks.ad")


def _run_async(coro):
    """在同步Celery任务中执行异步代码"""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _log_task_start(db, task_name: str, celery_task_id: str, params: dict = None) -> int:
    """记录任务开始到task_logs表"""
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


# ==================== WB 广告采集 ====================

@celery_app.task(
    name="app.tasks.ad_tasks.fetch_wb_ad_stats",
    bind=True,
    max_retries=3,
    default_retry_delay=300,
)
def fetch_wb_ad_stats(self):
    """每小时拉取所有WB店铺的广告数据

    流程：
    1. 查询所有 active 的 WB 店铺
    2. 遍历每个店铺，同步广告活动列表到 ad_campaigns
    3. 拉取每个活动的最近2小时统计数据，写入 ad_stats
    4. 记录执行日志到 task_logs
    """
    db = SessionLocal()
    log_id = None

    try:
        log_id = _log_task_start(
            db, "fetch_wb_ad_stats", self.request.id
        )

        # 获取所有active的WB店铺
        shops = db.query(Shop).filter(
            Shop.platform == "wb",
            Shop.status == "active",
            Shop.api_key.isnot(None),
        ).all()

        if not shops:
            logger.info("没有找到active的WB店铺，跳过采集")
            _log_task_end(db, log_id, "success", {"message": "无WB店铺"})
            return {"status": "skip", "reason": "no_wb_shops"}

        total_campaigns = 0
        total_stats = 0
        errors = []

        for shop in shops:
            try:
                shop_campaigns, shop_stats = _run_async(
                    _fetch_single_wb_shop(db, shop)
                )
                total_campaigns += shop_campaigns
                total_stats += shop_stats

                # 更新最后同步时间
                shop.last_sync_at = datetime.utcnow()
                db.commit()

            except Exception as e:
                error_msg = f"shop_id={shop.id} 采集失败: {str(e)}"
                logger.error(error_msg)
                errors.append(error_msg)
                db.rollback()

        result = {
            "shops_processed": len(shops),
            "campaigns_synced": total_campaigns,
            "stats_inserted": total_stats,
            "errors": errors,
        }

        status = "success" if not errors else "failed" if len(errors) == len(shops) else "success"
        _log_task_end(db, log_id, status, result)

        logger.info(
            f"WB广告数据采集完成: {len(shops)}个店铺, "
            f"{total_campaigns}个活动, {total_stats}条统计"
        )
        return result

    except Exception as e:
        logger.error(f"WB广告采集任务异常: {e}")
        if log_id:
            _log_task_end(db, log_id, "failed", error=str(e))
        db.rollback()
        raise self.retry(exc=e)

    finally:
        db.close()


async def _fetch_single_wb_shop(db, shop: Shop) -> tuple:
    """采集单个WB店铺的广告数据，返回 (活动数, 统计数)"""
    client = WBClient(shop_id=shop.id, api_key=shop.api_key)

    try:
        # 1. 同步广告活动列表
        campaigns_data = await client.fetch_ad_campaigns()
        campaigns_synced = 0

        for camp_data in campaigns_data:
            campaigns_synced += _upsert_campaign(
                db, shop.tenant_id, shop.id, "wb", camp_data
            )

        db.commit()

        # 2. 拉取广告统计数据（最近2天，覆盖当前小时）
        today = date.today()
        yesterday = today - timedelta(days=1)
        date_from = yesterday.isoformat()
        date_to = today.isoformat()

        # 获取该店铺所有active的campaign
        active_campaigns = db.query(AdCampaign).filter(
            AdCampaign.shop_id == shop.id,
            AdCampaign.tenant_id == shop.tenant_id,
            AdCampaign.platform == "wb",
            AdCampaign.status.in_(["active", "paused"]),
        ).all()

        stats_inserted = 0
        for campaign in active_campaigns:
            try:
                stats_data = await client.fetch_ad_stats(
                    campaign.platform_campaign_id, date_from, date_to
                )
                for stat in stats_data:
                    stats_inserted += _upsert_stat(
                        db, shop.tenant_id, campaign.id, stat
                    )
                db.commit()
            except Exception as e:
                logger.warning(
                    f"拉取活动 {campaign.platform_campaign_id} 统计失败: {e}"
                )
                db.rollback()

        logger.info(
            f"WB shop_id={shop.id}: 同步{campaigns_synced}个活动, "
            f"写入{stats_inserted}条统计"
        )
        return campaigns_synced, stats_inserted

    finally:
        await client.close()


def _upsert_campaign(db, tenant_id: int, shop_id: int, platform: str, data: dict) -> int:
    """同步广告活动：存在则更新，不存在则新建"""
    platform_id = data.get("platform_campaign_id", "")
    if not platform_id:
        return 0

    existing = db.query(AdCampaign).filter(
        AdCampaign.shop_id == shop_id,
        AdCampaign.platform_campaign_id == platform_id,
    ).first()

    if existing:
        new_name = data.get("name", "")
        # 只有API返回了真实名称时才更新，避免覆盖用户手动设置的名称
        if new_name and new_name.strip():
            existing.name = new_name
        existing.ad_type = data.get("ad_type", existing.ad_type)
        # 更新预算（如果有新值）
        if data.get("daily_budget") is not None:
            existing.daily_budget = data.get("daily_budget")
        existing.status = data.get("status", existing.status)
        return 0  # 更新不计数
    else:
        campaign = AdCampaign(
            tenant_id=tenant_id,
            shop_id=shop_id,
            platform=platform,
            platform_campaign_id=platform_id,
            name=data.get("name", f"{platform}活动-{platform_id}"),
            ad_type=data.get("ad_type", "search"),
            daily_budget=data.get("daily_budget"),
            total_budget=data.get("total_budget"),
            status=data.get("status", "active"),
            start_date=data.get("start_date"),
            end_date=data.get("end_date"),
        )
        db.add(campaign)
        return 1


def _upsert_stat(db, tenant_id: int, campaign_id: int, data: dict) -> int:
    """写入广告统计：按 campaign_id + stat_date + stat_hour 去重"""
    stat_date_str = data.get("stat_date", "")
    if not stat_date_str:
        return 0

    stat_date = date.fromisoformat(stat_date_str)
    stat_hour = data.get("stat_hour")

    # 检查是否已存在
    query = db.query(AdStat).filter(
        AdStat.campaign_id == campaign_id,
        AdStat.stat_date == stat_date,
    )
    if stat_hour is not None:
        query = query.filter(AdStat.stat_hour == stat_hour)
    else:
        query = query.filter(AdStat.stat_hour.is_(None))

    existing = query.first()

    platform = data.get("platform", "wb")

    if existing:
        # 更新已有记录
        existing.impressions = data.get("impressions", 0)
        existing.clicks = data.get("clicks", 0)
        existing.spend = data.get("spend", 0)
        existing.orders = data.get("orders", 0)
        existing.revenue = data.get("revenue", 0)
        existing.ctr = data.get("ctr")
        existing.cpc = data.get("cpc")
        existing.acos = data.get("acos")
        existing.roas = data.get("roas")
        return 0  # 更新不计新增数
    else:
        stat = AdStat(
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            platform=platform,
            stat_date=stat_date,
            stat_hour=stat_hour,
            impressions=data.get("impressions", 0),
            clicks=data.get("clicks", 0),
            spend=data.get("spend", 0),
            orders=data.get("orders", 0),
            revenue=data.get("revenue", 0),
            ctr=data.get("ctr"),
            cpc=data.get("cpc"),
            acos=data.get("acos"),
            roas=data.get("roas"),
        )
        db.add(stat)
        return 1


# ==================== Ozon 广告采集 ====================

@celery_app.task(
    name="app.tasks.ad_tasks.fetch_ozon_ad_stats",
    bind=True,
    max_retries=3,
    default_retry_delay=300,
)
def fetch_ozon_ad_stats(self):
    """每小时拉取所有Ozon店铺的广告数据"""
    db = SessionLocal()
    log_id = None

    try:
        log_id = _log_task_start(db, "fetch_ozon_ad_stats", self.request.id)

        shops = db.query(Shop).filter(
            Shop.platform == "ozon",
            Shop.status == "active",
            Shop.api_key.isnot(None),
            Shop.client_id.isnot(None),
        ).all()

        if not shops:
            logger.info("没有找到active的Ozon店铺，跳过采集")
            _log_task_end(db, log_id, "success", {"message": "无Ozon店铺"})
            return {"status": "skip", "reason": "no_ozon_shops"}

        total_campaigns = 0
        total_stats = 0
        errors = []

        for shop in shops:
            try:
                c, s = _run_async(_fetch_single_ozon_shop(db, shop))
                total_campaigns += c
                total_stats += s
                shop.last_sync_at = datetime.utcnow()
                db.commit()
            except Exception as e:
                error_msg = f"shop_id={shop.id} Ozon采集失败: {str(e)}"
                logger.error(error_msg)
                errors.append(error_msg)
                db.rollback()

        result = {
            "shops_processed": len(shops),
            "campaigns_synced": total_campaigns,
            "stats_inserted": total_stats,
            "errors": errors,
        }
        status = "success" if not errors else "failed" if len(errors) == len(shops) else "success"
        _log_task_end(db, log_id, status, result)

        logger.info(f"Ozon广告数据采集完成: {result}")
        return result

    except Exception as e:
        logger.error(f"Ozon广告采集任务异常: {e}")
        if log_id:
            _log_task_end(db, log_id, "failed", error=str(e))
        db.rollback()
        raise self.retry(exc=e)
    finally:
        db.close()


async def _fetch_single_ozon_shop(db, shop: Shop) -> tuple:
    """采集单个Ozon店铺的广告数据"""
    client = OzonClient(
        shop_id=shop.id, api_key=shop.api_key, client_id=shop.client_id
    )

    try:
        # 1. 同步广告活动
        campaigns_data = await client.fetch_ad_campaigns()
        campaigns_synced = 0
        for camp_data in campaigns_data:
            campaigns_synced += _upsert_campaign(
                db, shop.tenant_id, shop.id, "ozon", camp_data
            )
        db.commit()

        # 2. 拉取统计
        today = date.today()
        yesterday = today - timedelta(days=1)

        active_campaigns = db.query(AdCampaign).filter(
            AdCampaign.shop_id == shop.id,
            AdCampaign.tenant_id == shop.tenant_id,
            AdCampaign.platform == "ozon",
            AdCampaign.status.in_(["active", "paused"]),
        ).all()

        stats_inserted = 0
        for campaign in active_campaigns:
            try:
                stats_data = await client.fetch_ad_stats(
                    campaign.platform_campaign_id,
                    yesterday.isoformat(), today.isoformat()
                )
                for stat in stats_data:
                    stats_inserted += _upsert_stat(
                        db, shop.tenant_id, campaign.id, stat
                    )
                db.commit()
            except Exception as e:
                logger.warning(
                    f"Ozon活动 {campaign.platform_campaign_id} 统计失败: {e}"
                )
                db.rollback()

        logger.info(
            f"Ozon shop_id={shop.id}: 同步{campaigns_synced}个活动, "
            f"写入{stats_inserted}条统计"
        )
        return campaigns_synced, stats_inserted

    finally:
        await client.close()


# ==================== Yandex 广告采集 ====================

@celery_app.task(
    name="app.tasks.ad_tasks.fetch_yandex_ad_stats",
    bind=True,
    max_retries=3,
    default_retry_delay=300,
)
def fetch_yandex_ad_stats(self):
    """每小时拉取所有Yandex店铺的广告数据"""
    db = SessionLocal()
    log_id = None

    try:
        log_id = _log_task_start(db, "fetch_yandex_ad_stats", self.request.id)

        shops = db.query(Shop).filter(
            Shop.platform == "yandex",
            Shop.status == "active",
            Shop.oauth_token.isnot(None),
        ).all()

        if not shops:
            logger.info("没有找到active的Yandex店铺，跳过采集")
            _log_task_end(db, log_id, "success", {"message": "无Yandex店铺"})
            return {"status": "skip", "reason": "no_yandex_shops"}

        total_campaigns = 0
        total_stats = 0
        errors = []

        for shop in shops:
            try:
                c, s = _run_async(_fetch_single_yandex_shop(db, shop))
                total_campaigns += c
                total_stats += s
                shop.last_sync_at = datetime.utcnow()
                db.commit()
            except Exception as e:
                error_msg = f"shop_id={shop.id} Yandex采集失败: {str(e)}"
                logger.error(error_msg)
                errors.append(error_msg)
                db.rollback()

        result = {
            "shops_processed": len(shops),
            "campaigns_synced": total_campaigns,
            "stats_inserted": total_stats,
            "errors": errors,
        }
        status = "success" if not errors else "failed" if len(errors) == len(shops) else "success"
        _log_task_end(db, log_id, status, result)

        logger.info(f"Yandex广告数据采集完成: {result}")
        return result

    except Exception as e:
        logger.error(f"Yandex广告采集任务异常: {e}")
        if log_id:
            _log_task_end(db, log_id, "failed", error=str(e))
        db.rollback()
        raise self.retry(exc=e)
    finally:
        db.close()


# ==================== 自动化规则执行 ====================

@celery_app.task(
    name="app.tasks.ad_tasks.run_automation_rules",
    bind=True,
    max_retries=1,
    default_retry_delay=60,
)
def run_automation_rules(self):
    """执行所有租户的广告自动化规则"""
    db = SessionLocal()
    try:
        from app.models.ad import AdAutomationRule
        from app.services.ad.service import execute_automation_rules

        # 获取所有有启用规则的租户
        tenant_ids = [row[0] for row in db.query(
            AdAutomationRule.tenant_id
        ).filter(
            AdAutomationRule.enabled == 1
        ).distinct().all()]

        results = {}
        for tid in tenant_ids:
            result = execute_automation_rules(db, tid)
            results[tid] = result.get("data", {})
            logger.info(f"租户 {tid} 自动化规则执行完成: {result.get('data', {}).get('rules_checked', 0)} 条规则")

        return {"tenants_processed": len(tenant_ids), "results": results}
    except Exception as e:
        logger.error(f"自动化规则执行任务异常: {e}")
        raise self.retry(exc=e)
    finally:
        db.close()


async def _fetch_single_yandex_shop(db, shop: Shop) -> tuple:
    """采集单个Yandex店铺的广告数据"""
    client = YandexClient(
        shop_id=shop.id,
        api_key=shop.oauth_token,
        campaign_id=shop.platform_seller_id or "",
    )

    try:
        # 1. 同步广告活动
        campaigns_data = await client.fetch_ad_campaigns()
        campaigns_synced = 0
        for camp_data in campaigns_data:
            campaigns_synced += _upsert_campaign(
                db, shop.tenant_id, shop.id, "yandex", camp_data
            )
        db.commit()

        # 2. 拉取统计
        today = date.today()
        yesterday = today - timedelta(days=1)

        active_campaigns = db.query(AdCampaign).filter(
            AdCampaign.shop_id == shop.id,
            AdCampaign.tenant_id == shop.tenant_id,
            AdCampaign.platform == "yandex",
            AdCampaign.status.in_(["active", "paused"]),
        ).all()

        stats_inserted = 0
        for campaign in active_campaigns:
            try:
                stats_data = await client.fetch_ad_stats(
                    campaign.platform_campaign_id,
                    yesterday.isoformat(), today.isoformat()
                )
                for stat in stats_data:
                    stats_inserted += _upsert_stat(
                        db, shop.tenant_id, campaign.id, stat
                    )
                db.commit()
            except Exception as e:
                logger.warning(
                    f"Yandex活动 {campaign.platform_campaign_id} 统计失败: {e}"
                )
                db.rollback()

        logger.info(
            f"Yandex shop_id={shop.id}: 同步{campaigns_synced}个活动, "
            f"写入{stats_inserted}条统计"
        )
        return campaigns_synced, stats_inserted

    finally:
        await client.close()
