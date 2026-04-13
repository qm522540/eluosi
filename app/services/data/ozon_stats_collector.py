"""Ozon 数据采集服务

双 API 组合策略（2026-04-13 v4）：
  点击"更新数据源" → smart_sync()
    ├─ Seller API /v1/analytics/data 同步拉 revenue+orders（秒回）
    ├─ 后台线程：Performance API /api/client/statistics/json 拉广告数据
    │   （impressions/clicks/spend，异步轮询约1-2分钟）
    └─ 清理超过 90 天的旧数据

用户立即看到订单和收入，广告指标几分钟后自动补上。
"""

import asyncio
import threading
import httpx
from datetime import datetime, timedelta, date, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.ad import AdCampaign, AdStat
from app.models.shop import Shop
from app.models.shop_data_init import ShopDataInitStatus
from app.services.platform.ozon import OzonClient
from app.utils.logger import setup_logger

logger = setup_logger("data.ozon_collector")

SYNC_DAYS = 7
MAX_KEEP_DAYS = 90
SELLER_API = "https://api-seller.ozon.ru"
PERF_API = "https://api-performance.ozon.ru"


async def smart_sync(db: Session, shop_id: int, tenant_id: int) -> dict:
    """智能数据同步（同步部分：Seller API 拉 revenue/orders）"""
    shop = db.query(Shop).filter(Shop.id == shop_id, Shop.tenant_id == tenant_id).first()
    if not shop:
        raise ValueError("店铺不存在")
    if not shop.client_id or not shop.api_key:
        raise ValueError("Ozon Seller API 凭证未配置")

    yesterday = date.today() - timedelta(days=1)

    latest_row = db.execute(text("""
        SELECT MAX(s.stat_date) AS latest_date
        FROM ad_stats s
        JOIN ad_campaigns c ON s.campaign_id = c.id
        WHERE c.shop_id = :shop_id AND c.tenant_id = :tenant_id AND s.platform = 'ozon'
    """), {"shop_id": shop_id, "tenant_id": tenant_id}).fetchone()

    latest_date = latest_row.latest_date if latest_row else None

    if not latest_date:
        date_from = yesterday - timedelta(days=SYNC_DAYS - 1)
        date_to = yesterday
    elif latest_date >= yesterday:
        cleaned = _clean_old_data(db, shop_id, tenant_id)
        data_days = _count_data_days(db, shop_id, tenant_id)
        _update_init_status(db, shop_id, tenant_id, yesterday, data_days)
        return {
            "synced": 0, "date_from": None, "date_to": None,
            "cleaned": cleaned, "already_latest": True, "data_days": data_days,
        }
    else:
        date_from = latest_date + timedelta(days=1)
        date_to = yesterday
        if (date_to - date_from).days >= SYNC_DAYS:
            date_from = date_to - timedelta(days=SYNC_DAYS - 1)

    logger.info(f"shop_id={shop_id} 同步 {date_from}~{date_to}")

    # ① Seller API 同步拉 revenue + orders（秒回）
    campaigns = db.query(AdCampaign).filter(
        AdCampaign.shop_id == shop_id,
        AdCampaign.tenant_id == tenant_id,
        AdCampaign.platform == "ozon",
    ).all()
    if not campaigns:
        raise ValueError("无Ozon广告活动，请先同步广告活动列表")

    default_campaign = campaigns[0]
    total_synced = await _fetch_seller_data(
        db, shop, default_campaign, date_from, date_to, tenant_id,
    )

    # ② 后台线程拉广告数据（Performance API，慢但不阻塞用户）
    camp_map = {str(c.platform_campaign_id): c.id for c in campaigns}
    _start_perf_background(shop, camp_map, date_from, date_to, tenant_id)

    cleaned = _clean_old_data(db, shop_id, tenant_id)
    data_days = _count_data_days(db, shop_id, tenant_id)
    _update_init_status(db, shop_id, tenant_id, date_to, data_days)

    logger.info(f"shop_id={shop_id} Seller API 完成: {total_synced}条 + Performance API 后台补充中")
    return {
        "synced": total_synced,
        "date_from": str(date_from),
        "date_to": str(date_to),
        "cleaned": cleaned,
        "already_latest": False,
        "data_days": data_days,
    }


# ==================== Seller API（同步，秒回） ====================

async def _fetch_seller_data(
    db: Session, shop: Shop, campaign: AdCampaign,
    date_from: date, date_to: date, tenant_id: int,
) -> int:
    """Seller API /v1/analytics/data 拉 SKU 级运营数据（revenue + orders）"""
    headers = {
        "Client-Id": shop.client_id,
        "Api-Key": shop.api_key,
        "Content-Type": "application/json",
    }
    total = 0
    offset = 0

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
                        "limit": 100,
                        "offset": offset,
                    },
                )
                if resp.status_code == 429:
                    await asyncio.sleep(3)
                    continue
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                logger.error(f"Seller API 失败: {e}")
                break

            rows = data.get("result", {}).get("data", [])
            if not rows:
                break

            for row in rows:
                dims = row.get("dimensions", [])
                metrics = row.get("metrics", [])
                if len(dims) < 2 or len(metrics) < 2:
                    continue
                sku_id = dims[0].get("id", "")
                stat_date = dims[1].get("id", "")[:10]
                revenue = float(metrics[0]) if metrics[0] else 0
                orders = int(metrics[1]) if metrics[1] else 0
                if not stat_date or not sku_id or (revenue == 0 and orders == 0):
                    continue

                total += _upsert_stat(db, campaign, tenant_id, sku_id, stat_date, {
                    "orders": orders, "revenue": round(revenue, 2),
                })

            db.commit()
            if len(rows) < 100:
                break
            offset += 100

    logger.info(f"Seller API: {total} 条新数据")
    return total


# ==================== Performance API（后台异步） ====================

def _start_perf_background(shop: Shop, camp_map: dict,
                           date_from: date, date_to: date, tenant_id: int):
    """在后台线程中拉广告数据（独立数据库连接，避免跨线程连接池冲突）"""
    def _run():
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.config import get_settings

        settings = get_settings()
        engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True, pool_size=2)
        Session = sessionmaker(bind=engine)
        new_db = Session()
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(
                _fetch_perf_data(new_db, shop, camp_map, date_from, date_to, tenant_id)
            )
        except Exception as e:
            logger.error(f"Performance API 后台拉取失败: {e}")
        finally:
            new_db.close()
            engine.dispose()
            loop.close()

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    logger.info("Performance API 后台线程已启动")


async def _fetch_perf_data(
    db: Session, shop: Shop, camp_map: dict,
    date_from: date, date_to: date, tenant_id: int,
):
    """Performance API 拉广告数据（impressions/clicks/spend）"""
    ozon = OzonClient(
        shop_id=shop.id, api_key=shop.api_key,
        client_id=shop.client_id or '',
        perf_client_id=getattr(shop, 'perf_client_id', None) or '',
        perf_client_secret=getattr(shop, 'perf_client_secret', None) or '',
    )

    try:
        await ozon._ensure_perf_token()

        # 分批提交（每批5个活动）
        all_ids = list(camp_map.keys())
        batches = [all_ids[i:i+5] for i in range(0, len(all_ids), 5)]

        for batch_idx, batch in enumerate(batches):
            logger.info(f"Performance API batch {batch_idx+1}/{len(batches)}: {batch}")
            try:
                submit = await ozon._request("POST",
                    f"{PERF_API}/api/client/statistics/json",
                    use_perf=True,
                    json={
                        "campaigns": batch,
                        "dateFrom": date_from.strftime("%Y-%m-%d"),
                        "dateTo": date_to.strftime("%Y-%m-%d"),
                    },
                )
                uuid = submit.get("UUID")
                if not uuid:
                    continue

                # 轮询（最多90秒）
                report = None
                for _ in range(18):
                    await asyncio.sleep(5)
                    data = await ozon._request("GET",
                        f"{PERF_API}/api/client/statistics/{uuid}",
                        use_perf=True,
                    )
                    if data.get("state") == "OK":
                        link = data.get("link", "")
                        if link:
                            report = await ozon._request("GET",
                                f"{PERF_API}{link}", use_perf=True,
                            )
                        break

                if not report:
                    continue

                # 解析并更新 ad_stats
                updated = 0
                for cid, cdata in report.items():
                    if not isinstance(cdata, dict):
                        continue
                    rows = cdata.get("report", {}).get("rows", [])
                    # 找到内部 campaign_id
                    internal_cid = camp_map.get(cid)
                    if not internal_cid:
                        continue

                    for row in rows:
                        sku = row.get("sku", "")
                        stat_date = (row.get("createdAt") or "")[:10]
                        if not sku or not stat_date:
                            continue

                        views = _parse_num(row.get("views"), True)
                        clicks = _parse_num(row.get("clicks"), True)
                        spend = _parse_num(row.get("moneySpent"))
                        orders = _parse_num(row.get("orders"), True)
                        revenue = _parse_num(row.get("ordersMoney"))

                        ctr = round(clicks / views * 100, 4) if views > 0 else 0
                        cpc = round(spend / clicks, 2) if clicks > 0 else 0
                        roas = round(revenue / spend, 4) if spend > 0 else 0

                        # 更新已有记录的广告字段
                        db.execute(text("""
                            UPDATE ad_stats SET
                                impressions = :views, clicks = :clicks,
                                spend = :spend, ctr = :ctr, cpc = :cpc,
                                roas = CASE WHEN :roas > 0 THEN :roas ELSE roas END,
                                orders = CASE WHEN :orders > 0 THEN :orders ELSE orders END,
                                revenue = CASE WHEN :revenue > 0 THEN :revenue ELSE revenue END,
                                updated_at = NOW()
                            WHERE campaign_id = :cid AND ad_group_id = :sku
                              AND stat_date = :sd AND platform = 'ozon'
                        """), {
                            "cid": internal_cid, "sku": sku, "sd": stat_date,
                            "views": views, "clicks": clicks, "spend": spend,
                            "ctr": ctr, "cpc": cpc, "roas": roas,
                            "orders": orders, "revenue": revenue,
                        })

                        # 如果没匹配到已有记录（Seller API 没这个SKU），插入新记录
                        if db.execute(text("SELECT ROW_COUNT()")).scalar() == 0:
                            db.execute(text("""
                                INSERT INTO ad_stats (
                                    tenant_id, campaign_id, ad_group_id,
                                    platform, stat_date,
                                    impressions, clicks, spend, orders, revenue,
                                    ctr, cpc, acos, roas, created_at, updated_at
                                ) VALUES (
                                    :tid, :cid, :sku, 'ozon', :sd,
                                    :views, :clicks, :spend, :orders, :revenue,
                                    :ctr, :cpc, 0, :roas, NOW(), NOW()
                                )
                            """), {
                                "tid": tenant_id, "cid": internal_cid, "sku": sku,
                                "sd": stat_date,
                                "views": views, "clicks": clicks, "spend": spend,
                                "orders": orders, "revenue": revenue,
                                "ctr": ctr, "cpc": cpc, "roas": roas,
                            })
                        updated += 1

                db.commit()
                logger.info(f"Performance API batch {batch_idx+1}: 更新 {updated} 条广告数据")

            except Exception as e:
                logger.error(f"Performance API batch {batch_idx+1} 失败: {e}")

            await asyncio.sleep(2)  # 批次间等待

    finally:
        await ozon.close()

    # 更新 data_days
    data_days = _count_data_days(db, shop.id, tenant_id)
    _update_init_status(db, shop.id, tenant_id,
                        date.today() - timedelta(days=1), data_days)
    logger.info(f"Performance API 后台完成，共 {data_days} 天数据")


def _parse_num(v, is_int=False):
    if not v:
        return 0
    v = str(v).replace(",", ".").replace("\xa0", "").strip()
    try:
        return int(float(v)) if is_int else round(float(v), 2)
    except (ValueError, TypeError):
        return 0


# ==================== 通用工具 ====================

def _upsert_stat(db: Session, campaign: AdCampaign, tenant_id: int,
                 sku_id: str, stat_date: str, data: dict) -> int:
    """插入或更新 ad_stats，返回 1（新增）或 0（更新）"""
    existing = db.execute(text("""
        SELECT id FROM ad_stats
        WHERE campaign_id = :cid AND stat_date = :sd AND platform = 'ozon'
          AND ad_group_id = :sku
    """), {"cid": campaign.id, "sd": stat_date, "sku": sku_id}).fetchone()

    if existing:
        sets = ", ".join(f"{k} = :{k}" for k in data)
        db.execute(text(f"UPDATE ad_stats SET {sets}, updated_at = NOW() WHERE id = :id"),
                   {"id": existing.id, **data})
        return 0
    else:
        db.execute(text("""
            INSERT INTO ad_stats (
                tenant_id, campaign_id, ad_group_id, platform, stat_date,
                impressions, clicks, spend, orders, revenue,
                ctr, cpc, acos, roas, created_at, updated_at
            ) VALUES (
                :tid, :cid, :sku, 'ozon', :sd,
                0, 0, 0, :orders, :revenue,
                0, 0, 0, 0, NOW(), NOW()
            )
        """), {
            "tid": tenant_id, "cid": campaign.id, "sku": sku_id, "sd": stat_date,
            **data,
        })
        return 1


def _clean_old_data(db: Session, shop_id: int, tenant_id: int) -> int:
    cutoff = date.today() - timedelta(days=MAX_KEEP_DAYS)
    result = db.execute(text("""
        DELETE s FROM ad_stats s
        JOIN ad_campaigns c ON s.campaign_id = c.id
        WHERE c.shop_id = :shop_id AND c.tenant_id = :tenant_id
          AND s.platform = 'ozon' AND s.stat_date < :cutoff
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
            shop_id=shop_id, tenant_id=tenant_id,
            is_initialized=1, initialized_at=now,
            last_sync_date=last_sync_date, last_sync_at=now,
            data_days=data_days,
        )
        db.add(status)
    db.commit()


def _build_ozon_client(shop: Shop) -> OzonClient:
    return OzonClient(
        shop_id=shop.id,
        api_key=shop.api_key,
        client_id=shop.client_id,
        perf_client_id=getattr(shop, 'perf_client_id', None) or '',
        perf_client_secret=getattr(shop, 'perf_client_secret', None) or '',
    )
