"""WB广告数据采集服务（SKU 级别）

智能同步逻辑：
  点击"更新数据源" → smart_sync()
    ├─ 服务器无数据 → 拉最近 30 天
    ├─ 服务器有数据，最新日期 D → 拉 D+1 到昨天
    └─ 清理超过 90 天的旧数据

WB fullstats 接口天然返回 SKU 级别数据（nm[] 数组），
每条 ad_stats 记录对应一个 nm_id 在某天的表现。
ad_group_id 字段存 nm_id，实现商品级别精度。
"""

import asyncio
from datetime import datetime, timedelta, date, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.ad import AdCampaign, AdStat
from app.models.shop import Shop
from app.models.shop_data_init import ShopDataInitStatus
from app.services.platform.wb import WBClient
from app.utils.logger import setup_logger

logger = setup_logger("data.wb_collector")

SYNC_DAYS = 7        # 每次最多拉 7 天（首次也是 7 天）
MAX_KEEP_DAYS = 90


async def smart_sync(db: Session, shop_id: int, tenant_id: int) -> dict:
    """WB 智能数据同步（"更新数据源"按钮入口）"""
    shop = db.query(Shop).filter(Shop.id == shop_id, Shop.tenant_id == tenant_id).first()
    if not shop:
        raise ValueError("店铺不存在")

    yesterday = date.today() - timedelta(days=1)

    # 1. 查服务器最新数据日期
    latest_row = db.execute(text("""
        SELECT MAX(s.stat_date) AS latest_date
        FROM ad_stats s
        JOIN ad_campaigns c ON s.campaign_id = c.id
        WHERE c.shop_id = :shop_id AND c.tenant_id = :tenant_id AND s.platform = 'wb'
    """), {"shop_id": shop_id, "tenant_id": tenant_id}).fetchone()

    latest_date = latest_row.latest_date if latest_row else None

    # 2. 决定拉取范围（每次最多 SYNC_DAYS 天）
    if not latest_date:
        date_from = yesterday - timedelta(days=SYNC_DAYS - 1)
        date_to = yesterday
        logger.info(f"shop_id={shop_id} WB 无历史数据，拉取最近{SYNC_DAYS}天 {date_from}~{date_to}")
    elif latest_date >= yesterday:
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
        # 增量也最多拉 SYNC_DAYS 天，避免长时间未更新时一次拉太多
        if (date_to - date_from).days >= SYNC_DAYS:
            date_from = date_to - timedelta(days=SYNC_DAYS - 1)
        logger.info(f"shop_id={shop_id} WB 增量同步 {date_from}~{date_to}")

    # 3. 拉取数据
    campaigns = db.query(AdCampaign).filter(
        AdCampaign.shop_id == shop_id,
        AdCampaign.tenant_id == tenant_id,
        AdCampaign.platform == "wb",
    ).all()

    if not campaigns:
        raise ValueError("无WB广告活动，请先同步广告活动列表")

    client = WBClient(shop_id=shop.id, api_key=shop.api_key)
    total_synced = 0

    try:
        for campaign in campaigns:
            try:
                stats = await client.fetch_ad_stats(
                    campaign_id=campaign.platform_campaign_id,
                    date_from=date_from.strftime("%Y-%m-%d"),
                    date_to=date_to.strftime("%Y-%m-%d"),
                )
                synced = _save_sku_stats(db, campaign, stats)
                total_synced += synced
                await asyncio.sleep(0.3)
            except Exception as e:
                logger.error(f"WB 活动 {campaign.name}(id={campaign.id}) 数据拉取失败: {e}")
                db.rollback()
    finally:
        await client.close()

    # 4. 清理旧数据
    cleaned = _clean_old_data(db, shop_id, tenant_id)

    # 5. 更新状态
    data_days = _count_data_days(db, shop_id, tenant_id)
    _update_init_status(db, shop_id, tenant_id, date_to, data_days)

    logger.info(
        f"shop_id={shop_id} WB 智能同步完成: "
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


def _save_sku_stats(db: Session, campaign: AdCampaign, stats: list) -> int:
    """把 SKU 级别的统计数据写入 ad_stats 表

    ad_group_id = nm_id（WB 商品 ID），实现 SKU 级精度。
    """
    if not stats:
        return 0

    inserted = 0
    for s in stats:
        nm_id = s.get("nm_id")
        stat_date = s.get("stat_date")
        if not nm_id or not stat_date:
            continue

        existing = db.query(AdStat).filter(
            AdStat.campaign_id == campaign.id,
            AdStat.ad_group_id == nm_id,
            AdStat.stat_date == stat_date,
            AdStat.platform == "wb",
        ).first()

        stat_data = {
            "impressions": s.get("impressions", 0),
            "clicks": s.get("clicks", 0),
            "spend": s.get("spend", 0),
            "orders": s.get("orders", 0),
            "revenue": s.get("revenue", 0),
            "ctr": s.get("ctr"),
            "cpc": s.get("cpc"),
            "acos": s.get("acos"),
            "roas": s.get("roas"),
        }

        if existing:
            for k, v in stat_data.items():
                setattr(existing, k, v)
        else:
            new_stat = AdStat(
                tenant_id=campaign.tenant_id,
                campaign_id=campaign.id,
                ad_group_id=nm_id,
                platform="wb",
                stat_date=stat_date,
                **stat_data,
            )
            db.add(new_stat)
            inserted += 1

    db.commit()
    return inserted


def _clean_old_data(db: Session, shop_id: int, tenant_id: int) -> int:
    cutoff = date.today() - timedelta(days=MAX_KEEP_DAYS)
    result = db.execute(text("""
        DELETE s FROM ad_stats s
        JOIN ad_campaigns c ON s.campaign_id = c.id
        WHERE c.shop_id = :shop_id
          AND c.tenant_id = :tenant_id
          AND s.platform = 'wb'
          AND s.stat_date < :cutoff
    """), {"shop_id": shop_id, "tenant_id": tenant_id, "cutoff": cutoff})
    db.commit()
    return result.rowcount


def _count_data_days(db: Session, shop_id: int, tenant_id: int) -> int:
    row = db.execute(text("""
        SELECT COUNT(DISTINCT s.stat_date) AS cnt
        FROM ad_stats s
        JOIN ad_campaigns c ON s.campaign_id = c.id
        WHERE c.shop_id = :shop_id AND c.tenant_id = :tenant_id AND s.platform = 'wb'
    """), {"shop_id": shop_id, "tenant_id": tenant_id}).fetchone()
    return row.cnt if row else 0


def _update_init_status(db: Session, shop_id: int, tenant_id: int,
                        last_sync_date: date, data_days: int):
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
