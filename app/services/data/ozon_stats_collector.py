"""Ozon 数据采集服务

智能同步逻辑（2026-04-13 重构）：
  点击"更新数据源" → smart_sync()
    ├─ 服务器无数据 → 拉最近 7 天
    ├─ 服务器有数据，最新日期 D → 拉 D+1 到昨天（D=昨天则提示已最新）
    └─ 清理超过 90 天的旧数据

数据来源：Seller API /v1/analytics/data（SKU级运营数据：收入/订单/流量/转化）
Performance API 的广告统计接口被WAF拦截或无数据，改用 Seller API 获取历史数据。
"""

import httpx
from datetime import datetime, timedelta, date, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.ad import AdCampaign, AdStat
from app.models.shop import Shop
from app.models.shop_data_init import ShopDataInitStatus
from app.utils.logger import setup_logger

logger = setup_logger("data.ozon_collector")

SYNC_DAYS = 7        # 每次最多拉 7 天
MAX_KEEP_DAYS = 90   # 超过 90 天的旧数据清理
SELLER_API = "https://api-seller.ozon.ru"


async def smart_sync(db: Session, shop_id: int, tenant_id: int) -> dict:
    """智能数据同步（"更新数据源"按钮唯一入口）"""
    shop = db.query(Shop).filter(Shop.id == shop_id, Shop.tenant_id == tenant_id).first()
    if not shop:
        raise ValueError("店铺不存在")

    if not shop.client_id or not shop.api_key:
        raise ValueError("Ozon Seller API 凭证未配置（需要 Client-Id 和 Api-Key）")

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

    # 3. 用 Seller API 拉 SKU 级运营数据
    total_synced = await _fetch_seller_analytics(
        db, shop, date_from, date_to, tenant_id,
    )

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


async def _fetch_seller_analytics(
    db: Session, shop: Shop,
    date_from: date, date_to: date,
    tenant_id: int,
) -> int:
    """通过 Seller API /v1/analytics/data 拉取 SKU 级运营数据

    指标：revenue（收入）、ordered_units（订单量）
    注：hits_view/session_view/adv_* 等流量和广告指标已被Ozon废弃(deprecated)
    维度：sku + day
    """
    headers = {
        "Client-Id": shop.client_id,
        "Api-Key": shop.api_key,
        "Content-Type": "application/json",
    }

    # Ozon 运营数据不区分活动，挂到第一个活动下
    campaign = db.query(AdCampaign).filter(
        AdCampaign.shop_id == shop.id,
        AdCampaign.tenant_id == tenant_id,
        AdCampaign.platform == "ozon",
    ).first()

    if not campaign:
        logger.warning(f"shop_id={shop.id} 无 Ozon 活动，跳过")
        return 0

    total_synced = 0
    offset = 0
    limit = 100

    async with httpx.AsyncClient(timeout=60) as client:
        while True:
            try:
                resp = await client.post(
                    f"{SELLER_API}/v1/analytics/data",
                    headers=headers,
                    json={
                        "date_from": date_from.strftime("%Y-%m-%d"),
                        "date_to": date_to.strftime("%Y-%m-%d"),
                        "metrics": ["revenue", "ordered_units"],
                        "dimension": ["sku", "day"],
                        "limit": limit,
                        "offset": offset,
                    },
                )

                if resp.status_code == 429:
                    logger.warning("Ozon Seller API 限速，等待3秒")
                    import asyncio
                    await asyncio.sleep(3)
                    continue

                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                logger.error(f"Ozon Seller API 调用失败: {e}")
                break

            rows = data.get("result", {}).get("data", [])
            if not rows:
                break

            for row in rows:
                dims = row.get("dimensions", [])
                metrics_val = row.get("metrics", [])
                if len(dims) < 2 or len(metrics_val) < 2:
                    continue

                sku_id = dims[0].get("id", "")
                stat_date = dims[1].get("id", "")[:10]
                if not stat_date or not sku_id:
                    continue

                revenue = float(metrics_val[0]) if metrics_val[0] else 0
                orders = int(metrics_val[1]) if metrics_val[1] else 0

                if revenue == 0 and orders == 0:
                    continue

                # 广告指标暂不可用（Ozon API 已废弃流量指标，等活动恢复投放后走 Performance API）
                impressions = 0
                clicks = 0
                spend = 0
                ctr = 0
                cpc = 0
                roas = 0
                acos = 0

                existing = db.execute(text("""
                    SELECT id FROM ad_stats
                    WHERE campaign_id = :cid AND stat_date = :sd
                      AND platform = 'ozon' AND ad_group_id = :sku
                """), {"cid": campaign.id, "sd": stat_date, "sku": sku_id}).fetchone()

                if existing:
                    db.execute(text("""
                        UPDATE ad_stats SET
                            impressions = :impressions, clicks = :clicks,
                            orders = :orders, revenue = :revenue,
                            ctr = :ctr, updated_at = NOW()
                        WHERE id = :id
                    """), {
                        "id": existing.id,
                        "impressions": impressions,
                        "clicks": clicks,
                        "orders": orders,
                        "revenue": round(revenue, 2),
                        "ctr": ctr,
                    })
                else:
                    db.execute(text("""
                        INSERT INTO ad_stats (
                            tenant_id, campaign_id, ad_group_id,
                            platform, stat_date,
                            impressions, clicks, spend,
                            orders, revenue, ctr, cpc, acos, roas,
                            created_at, updated_at
                        ) VALUES (
                            :tenant_id, :cid, :sku,
                            'ozon', :sd,
                            :impressions, :clicks, :spend,
                            :orders, :revenue, :ctr, :cpc, :acos, :roas,
                            NOW(), NOW()
                        )
                    """), {
                        "tenant_id": tenant_id,
                        "cid": campaign.id,
                        "sku": sku_id,
                        "sd": stat_date,
                        "impressions": impressions,
                        "clicks": clicks,
                        "spend": spend,
                        "orders": orders,
                        "revenue": round(revenue, 2),
                        "ctr": ctr,
                        "cpc": cpc,
                        "acos": acos,
                        "roas": roas,
                    })
                    total_synced += 1

            db.commit()

            if len(rows) < limit:
                break
            offset += limit
            logger.info(f"shop_id={shop.id} 已拉取 {offset} 条，继续...")

    logger.info(f"shop_id={shop.id} Seller API 拉取完成: {total_synced} 条新数据")
    return total_synced


def _clean_old_data(db: Session, shop_id: int, tenant_id: int) -> int:
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
    row = db.execute(text("""
        SELECT COUNT(DISTINCT s.stat_date) AS cnt
        FROM ad_stats s
        JOIN ad_campaigns c ON s.campaign_id = c.id
        WHERE c.shop_id = :shop_id AND c.tenant_id = :tenant_id AND s.platform = 'ozon'
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
