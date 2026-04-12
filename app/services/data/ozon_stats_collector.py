"""Ozon广告数据采集服务

智能同步逻辑（2026-04-12 重构）：
  点击"更新数据源" → smart_sync()
    ├─ 服务器无数据 → 拉最近 30 天
    ├─ 服务器有数据，最新日期 D → 拉 D+1 到昨天（D=昨天则提示已最新）
    └─ 清理超过 90 天的旧数据

不再有"首次进入自动触发"的逻辑。
"""

import asyncio
from datetime import datetime, timedelta, date, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.ad import AdCampaign, AdStat
from app.models.shop import Shop
from app.models.shop_data_init import ShopDataInitStatus
from app.services.platform.ozon import OzonClient
from app.utils.logger import setup_logger

logger = setup_logger("data.ozon_collector")

SYNC_DAYS = 7        # 每次最多拉 7 天
MAX_KEEP_DAYS = 90   # 超过 90 天的旧数据清理


async def smart_sync(db: Session, shop_id: int, tenant_id: int) -> dict:
    """智能数据同步（"更新数据源"按钮唯一入口）

    Returns:
        {
          "synced": int,       # 本次写入/更新的记录数
          "date_from": str,    # 本次拉取起始日期
          "date_to": str,      # 本次拉取截止日期
          "cleaned": int,      # 清理的过期记录数
          "already_latest": bool,  # 是否已是最新（无需拉取）
          "data_days": int,    # 同步后服务器有多少天数据
        }
    """
    shop = db.query(Shop).filter(Shop.id == shop_id, Shop.tenant_id == tenant_id).first()
    if not shop:
        raise ValueError("店铺不存在")

    yesterday = date.today() - timedelta(days=1)

    # 1. 查服务器最新数据日期
    latest_row = db.execute(text("""
        SELECT MAX(s.stat_date) AS latest_date
        FROM ad_stats s
        JOIN ad_campaigns c ON s.campaign_id = c.id
        WHERE c.shop_id = :shop_id AND c.tenant_id = :tenant_id AND s.platform = 'ozon'
    """), {"shop_id": shop_id, "tenant_id": tenant_id}).fetchone()

    latest_date = latest_row.latest_date if latest_row else None

    # 2. 决定拉取范围
    if not latest_date:
        date_from = yesterday - timedelta(days=SYNC_DAYS - 1)
        date_to = yesterday
        logger.info(f"shop_id={shop_id} 无历史数据，拉取最近{SYNC_DAYS}天 {date_from}~{date_to}")
    elif latest_date >= yesterday:
        # 数据已是最新
        cleaned = _clean_old_data(db, shop_id, tenant_id)
        data_days = _count_data_days(db, shop_id, tenant_id)
        _update_init_status(db, shop_id, tenant_id, yesterday, data_days)
        return {
            "synced": 0,
            "date_from": None,
            "date_to": None,
            "cleaned": cleaned,
            "already_latest": True,
            "data_days": data_days,
        }
    else:
        date_from = latest_date + timedelta(days=1)
        date_to = yesterday
        if (date_to - date_from).days >= SYNC_DAYS:
            date_from = date_to - timedelta(days=SYNC_DAYS - 1)
        logger.info(f"shop_id={shop_id} 增量同步 {date_from}~{date_to}")

    # 3. 拉取数据
    campaigns = db.query(AdCampaign).filter(
        AdCampaign.shop_id == shop_id,
        AdCampaign.tenant_id == tenant_id,
        AdCampaign.platform == "ozon",
    ).all()

    if not campaigns:
        raise ValueError("无Ozon广告活动，请先同步广告活动列表")

    ozon_client = _build_ozon_client(shop)
    total_synced = 0

    try:
        for campaign in campaigns:
            try:
                synced = await _fetch_and_save_stats(
                    db, ozon_client, campaign, date_from, date_to,
                )
                total_synced += synced
                await asyncio.sleep(0.3)
            except Exception as e:
                logger.error(f"活动 {campaign.name}(id={campaign.id}) 数据拉取失败: {e}")
    finally:
        await ozon_client.close()

    # 4. 清理 90 天前的旧数据
    cleaned = _clean_old_data(db, shop_id, tenant_id)

    # 5. 更新 shop_data_init_status
    data_days = _count_data_days(db, shop_id, tenant_id)
    _update_init_status(db, shop_id, tenant_id, date_to, data_days)

    logger.info(
        f"shop_id={shop_id} 智能同步完成: "
        f"{date_from}~{date_to} 写入{total_synced}条 清理{cleaned}条 共{data_days}天数据"
    )
    return {
        "synced": total_synced,
        "date_from": str(date_from),
        "date_to": str(date_to),
        "cleaned": cleaned,
        "already_latest": False,
        "data_days": data_days,
    }


def _clean_old_data(db: Session, shop_id: int, tenant_id: int) -> int:
    """清理超过 MAX_KEEP_DAYS 天的旧数据"""
    cutoff = date.today() - timedelta(days=MAX_KEEP_DAYS)
    result = db.execute(text("""
        DELETE s FROM ad_stats s
        JOIN ad_campaigns c ON s.campaign_id = c.id
        WHERE c.shop_id = :shop_id
          AND c.tenant_id = :tenant_id
          AND s.platform = 'ozon'
          AND s.stat_date < :cutoff
    """), {"shop_id": shop_id, "tenant_id": tenant_id, "cutoff": cutoff})
    db.commit()
    return result.rowcount


def _count_data_days(db: Session, shop_id: int, tenant_id: int) -> int:
    """统计服务器有多少天数据"""
    row = db.execute(text("""
        SELECT COUNT(DISTINCT s.stat_date) AS cnt
        FROM ad_stats s
        JOIN ad_campaigns c ON s.campaign_id = c.id
        WHERE c.shop_id = :shop_id AND c.tenant_id = :tenant_id AND s.platform = 'ozon'
    """), {"shop_id": shop_id, "tenant_id": tenant_id}).fetchone()
    return row.cnt if row else 0


def _update_init_status(db: Session, shop_id: int, tenant_id: int,
                        last_sync_date: date, data_days: int):
    """更新 shop_data_init_status"""
    now = datetime.now(timezone.utc)
    status = db.query(ShopDataInitStatus).filter(
        ShopDataInitStatus.shop_id == shop_id,
    ).first()
    if status:
        status.is_initialized = 1
        status.initialized_at = status.initialized_at or now
        status.last_sync_date = last_sync_date
        status.last_sync_at = now
        status.data_days = data_days
    else:
        status = ShopDataInitStatus(
            shop_id=shop_id,
            tenant_id=tenant_id,
            is_initialized=1,
            initialized_at=now,
            last_sync_date=last_sync_date,
            last_sync_at=now,
            data_days=data_days,
        )
        db.add(status)
    db.commit()


async def _fetch_and_save_stats(
    db: Session,
    ozon_client: OzonClient,
    campaign: AdCampaign,
    start_date: date,
    end_date: date,
) -> int:
    """从Ozon API拉取数据并写入ad_stats表"""
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
        if spend == 0 and impressions == 0:
            continue

        existing = db.query(AdStat).filter(
            AdStat.campaign_id == campaign.id,
            AdStat.stat_date == stat_date,
            AdStat.platform == "ozon",
        ).first()

        stat_data = {
            "impressions": impressions,
            "clicks": int(day_stat.get("clicks", 0)),
            "spend": spend,
            "orders": int(day_stat.get("orders", 0)),
            "revenue": float(day_stat.get("revenue", 0)),
            "ctr": float(day_stat.get("ctr", 0)),
            "cpc": float(day_stat.get("cpc", 0)),
            "acos": float(day_stat.get("acos", 0)),
            "roas": float(day_stat.get("roas", 0)),
        }

        if existing:
            for k, v in stat_data.items():
                setattr(existing, k, v)
        else:
            new_stat = AdStat(
                tenant_id=campaign.tenant_id,
                campaign_id=campaign.id,
                platform="ozon",
                stat_date=stat_date,
                **stat_data,
            )
            db.add(new_stat)
            inserted += 1

    db.commit()
    return inserted


def _build_ozon_client(shop: Shop) -> OzonClient:
    return OzonClient(
        shop_id=shop.id,
        api_key=shop.api_key,
        client_id=shop.client_id,
        perf_client_id=getattr(shop, 'perf_client_id', None) or '',
        perf_client_secret=getattr(shop, 'perf_client_secret', None) or '',
    )
