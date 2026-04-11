"""Ozon广告数据采集服务

三种场景：
1. 首次初始化：拉取过去90天数据
2. 每日同步：拉取昨日数据
3. 按需触发：首次进入AI调价功能时检测并初始化

适配：同步SQLAlchemy Session + async OzonClient
"""

import asyncio
from datetime import datetime, timedelta, date, timezone

from sqlalchemy.orm import Session

from app.models.ad import AdCampaign, AdStat
from app.models.shop import Shop
from app.models.shop_data_init import ShopDataInitStatus
from app.services.platform.ozon import OzonClient
from app.utils.logger import setup_logger

logger = setup_logger("data.ozon_collector")


def check_shop_init_status(db: Session, shop_id: int) -> dict:
    """检查店铺数据是否已初始化（同步版，供API调用）"""
    status = db.query(ShopDataInitStatus).filter(
        ShopDataInitStatus.shop_id == shop_id,
    ).first()

    if status and status.is_initialized:
        return {
            "initialized": True,
            "last_sync_date": str(status.last_sync_date) if status.last_sync_date else None,
            "message": "数据已就绪",
        }

    return {
        "initialized": False,
        "message": "数据未初始化，请调用初始化接口",
    }


async def init_shop_history(db: Session, shop_id: int, days: int = 90) -> dict:
    """首次初始化：拉取过去N天历史数据

    同步Session + async OzonClient 混合使用。
    """
    shop = db.query(Shop).filter(Shop.id == shop_id).first()
    if not shop:
        return {"error": "店铺不存在"}

    # 获取该店铺所有Ozon活动
    campaigns = db.query(AdCampaign).filter(
        AdCampaign.shop_id == shop_id,
        AdCampaign.platform == "ozon",
    ).all()

    if not campaigns:
        return {"error": "无Ozon广告活动"}

    end_date = date.today() - timedelta(days=1)
    start_date = end_date - timedelta(days=days)

    ozon_client = _build_ozon_client(shop)
    total_inserted = 0

    for campaign in campaigns:
        try:
            inserted = await _fetch_and_save_stats(
                db, ozon_client, campaign, start_date, end_date,
            )
            total_inserted += inserted
            await asyncio.sleep(0.3)  # 避免API限流
        except Exception as e:
            logger.error(f"活动 {campaign.name}(id={campaign.id}) 历史数据拉取失败: {e}")

    # 更新初始化状态
    status = db.query(ShopDataInitStatus).filter(
        ShopDataInitStatus.shop_id == shop_id,
    ).first()
    if status:
        status.is_initialized = 1
        status.initialized_at = datetime.now(timezone.utc)
        status.last_sync_date = end_date
        status.last_sync_at = datetime.now(timezone.utc)
    else:
        status = ShopDataInitStatus(
            shop_id=shop_id,
            tenant_id=shop.tenant_id,
            is_initialized=1,
            initialized_at=datetime.now(timezone.utc),
            last_sync_date=end_date,
            last_sync_at=datetime.now(timezone.utc),
        )
        db.add(status)
    db.commit()

    logger.info(f"shop_id={shop_id} 历史数据初始化完成: {days}天 {total_inserted}条记录")
    return {
        "initialized": True,
        "days": days,
        "total_inserted": total_inserted,
        "message": f"初始化完成，共写入{total_inserted}条记录",
    }


async def sync_yesterday_stats(db: Session, shop_id: int) -> dict:
    """每日同步：拉取昨日数据"""
    yesterday = date.today() - timedelta(days=1)

    shop = db.query(Shop).filter(Shop.id == shop_id).first()
    if not shop:
        return {"error": "店铺不存在"}

    campaigns = db.query(AdCampaign).filter(
        AdCampaign.shop_id == shop_id,
        AdCampaign.platform == "ozon",
        AdCampaign.status == "active",
    ).all()

    if not campaigns:
        return {"synced": 0}

    ozon_client = _build_ozon_client(shop)
    total_inserted = 0

    for campaign in campaigns:
        try:
            inserted = await _fetch_and_save_stats(
                db, ozon_client, campaign, yesterday, yesterday,
            )
            total_inserted += inserted
            await asyncio.sleep(0.2)
        except Exception as e:
            logger.error(f"活动 {campaign.name} 昨日数据同步失败: {e}")

    # 更新最后同步时间
    status = db.query(ShopDataInitStatus).filter(
        ShopDataInitStatus.shop_id == shop_id,
    ).first()
    if status:
        status.last_sync_date = yesterday
        status.last_sync_at = datetime.now(timezone.utc)
        db.commit()

    logger.info(f"shop_id={shop_id} 昨日数据同步完成: {yesterday} {total_inserted}条")
    return {"synced": total_inserted, "date": str(yesterday)}


async def _fetch_and_save_stats(
    db: Session,
    ozon_client: OzonClient,
    campaign: AdCampaign,
    start_date: date,
    end_date: date,
) -> int:
    """从Ozon API拉取数据并写入ad_stats表

    使用INSERT ... ON DUPLICATE KEY UPDATE避免重复。
    """
    try:
        stats = await ozon_client.fetch_ad_stats(
            campaign_id=campaign.platform_campaign_id,
            date_from=start_date.strftime("%Y-%m-%d"),
            date_to=end_date.strftime("%Y-%m-%d"),
        )
    except Exception as e:
        logger.error(f"Ozon API调用失败 campaign={campaign.platform_campaign_id}: {e}")
        return 0

    if not stats:
        return 0

    inserted = 0
    for day_stat in stats:
        stat_date = day_stat.get("stat_date", "")
        if not stat_date:
            continue

        spend = float(day_stat.get("spend", 0))
        impressions = int(day_stat.get("impressions", 0))

        # 跳过完全无数据的天
        if spend == 0 and impressions == 0:
            continue

        # 检查是否已存在
        existing = db.query(AdStat).filter(
            AdStat.campaign_id == campaign.id,
            AdStat.stat_date == stat_date,
            AdStat.platform == "ozon",
        ).first()

        if existing:
            # 更新已有数据
            existing.impressions = impressions
            existing.clicks = int(day_stat.get("clicks", 0))
            existing.spend = spend
            existing.orders = int(day_stat.get("orders", 0))
            existing.revenue = float(day_stat.get("revenue", 0))
            existing.ctr = float(day_stat.get("ctr", 0))
            existing.cpc = float(day_stat.get("cpc", 0))
            existing.acos = float(day_stat.get("acos", 0))
            existing.roas = float(day_stat.get("roas", 0))
        else:
            new_stat = AdStat(
                tenant_id=campaign.tenant_id,
                campaign_id=campaign.id,
                platform="ozon",
                stat_date=stat_date,
                impressions=impressions,
                clicks=int(day_stat.get("clicks", 0)),
                spend=spend,
                orders=int(day_stat.get("orders", 0)),
                revenue=float(day_stat.get("revenue", 0)),
                ctr=float(day_stat.get("ctr", 0)),
                cpc=float(day_stat.get("cpc", 0)),
                acos=float(day_stat.get("acos", 0)),
                roas=float(day_stat.get("roas", 0)),
            )
            db.add(new_stat)
            inserted += 1

    db.commit()
    return inserted


def _build_ozon_client(shop: Shop) -> OzonClient:
    """从shop构建OzonClient"""
    return OzonClient(
        shop_id=shop.id,
        api_key=shop.api_key,
        client_id=shop.client_id,
        perf_client_id=getattr(shop, 'perf_client_id', None) or '',
        perf_client_secret=getattr(shop, 'perf_client_secret', None) or '',
    )
