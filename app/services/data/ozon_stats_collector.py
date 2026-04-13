"""Ozon 数据采集服务

智能同步逻辑（2026-04-13 v3）：
  点击"更新数据源" → smart_sync()
    ├─ 服务器无数据 → 拉最近 7 天
    ├─ 服务器有数据，最新日期 D → 拉 D+1 到昨天
    └─ 清理超过 90 天的旧数据

数据来源：Performance API /api/client/statistics/json（SKU级广告数据）
  + Seller API /v1/analytics/data（补充运营数据：收入/订单）

广告数据包含：曝光、点击、CTR、花费、出价、订单、订单金额
"""

import asyncio
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
    """智能数据同步"""
    shop = db.query(Shop).filter(Shop.id == shop_id, Shop.tenant_id == tenant_id).first()
    if not shop:
        raise ValueError("店铺不存在")

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
        logger.info(f"shop_id={shop_id} 无历史数据，拉取最近{SYNC_DAYS}天 {date_from}~{date_to}")
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
        logger.info(f"shop_id={shop_id} 增量同步 {date_from}~{date_to}")

    # 拉取广告数据（Performance API）
    campaigns = db.query(AdCampaign).filter(
        AdCampaign.shop_id == shop_id,
        AdCampaign.tenant_id == tenant_id,
        AdCampaign.platform == "ozon",
    ).all()

    if not campaigns:
        raise ValueError("无Ozon广告活动，请先同步广告活动列表")

    camp_map = {str(c.platform_campaign_id): c for c in campaigns}
    total_synced = 0

    # 逐活动拉取（Performance API 每次查一个活动返回 SKU 级明细）
    ozon_client = _build_ozon_client(shop)
    try:
        for platform_cid, campaign in camp_map.items():
            try:
                stats = await _fetch_perf_stats_json(
                    ozon_client, platform_cid,
                    date_from.strftime("%Y-%m-%d"),
                    date_to.strftime("%Y-%m-%d"),
                )
                for stat in stats:
                    total_synced += _save_one_stat(db, campaign, stat)
                if stats:
                    logger.info(f"活动 {campaign.name}(id={platform_cid}): {len(stats)} 条SKU数据")
            except Exception as e:
                logger.error(f"活动 {campaign.name}(id={platform_cid}) 拉取失败: {e}")
            await asyncio.sleep(1)  # 避免429
    finally:
        await ozon_client.close()

    cleaned = _clean_old_data(db, shop_id, tenant_id)
    data_days = _count_data_days(db, shop_id, tenant_id)
    _update_init_status(db, shop_id, tenant_id, date_to, data_days)

    logger.info(
        f"shop_id={shop_id} 同步完成: "
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


async def _fetch_perf_stats_json(
    client: OzonClient, campaign_id: str,
    date_from: str, date_to: str,
) -> list:
    """通过 Performance API 拉取单个活动的 SKU 级广告统计

    流程：
    1. POST /api/client/statistics/json → UUID
    2. 轮询 GET /api/client/statistics/{UUID} → state=OK 得到 link
    3. GET /api/client/statistics/report?UUID= → JSON 报告（含 views/clicks/spend 等）
    """
    await client._ensure_perf_token()

    # Step 1: 提交
    try:
        submit = await client._request("POST",
            f"{PERF_API}/api/client/statistics/json",
            use_perf=True,
            json={
                "campaigns": [campaign_id],
                "dateFrom": date_from,
                "dateTo": date_to,
            },
        )
    except Exception as e:
        logger.warning(f"统计提交失败 campaign={campaign_id}: {e}")
        return []

    uuid = submit.get("UUID")
    if not uuid:
        return []

    # Step 2: 轮询（最多90秒）
    link = None
    for _ in range(18):
        await asyncio.sleep(5)
        try:
            data = await client._request("GET",
                f"{PERF_API}/api/client/statistics/{uuid}",
                use_perf=True,
            )
        except Exception:
            continue
        state = data.get("state", "")
        if state == "OK":
            link = data.get("link", "")
            break
        elif state in ("ERROR", "FAILED"):
            return []

    if not link:
        logger.warning(f"统计超时或无数据 campaign={campaign_id} UUID={uuid}")
        return []

    # Step 3: 下载 JSON 报告
    report_url = f"{PERF_API}{link}" if link.startswith("/") else link
    try:
        report = await client._request("GET", report_url, use_perf=True)
    except Exception as e:
        logger.error(f"报告下载失败 campaign={campaign_id}: {e}")
        return []

    # 解析报告（按活动ID分组，每个活动下有 rows 列表）
    stats = []
    for camp_id, camp_data in report.items():
        rows = camp_data.get("report", {}).get("rows", []) if isinstance(camp_data, dict) else []
        for row in rows:
            stat = _parse_perf_row(row)
            if stat:
                stats.append(stat)

    return stats


def _parse_perf_row(row: dict) -> dict:
    """解析 Performance API JSON 报告的一行"""
    sku = row.get("sku", "")
    created_at = row.get("createdAt", "")[:10]
    if not sku or not created_at:
        return None

    # 数值字段可能带逗号（俄语格式）
    def _num(v, is_int=False):
        if not v:
            return 0
        v = str(v).replace(",", ".").replace("\xa0", "").strip()
        try:
            return int(float(v)) if is_int else round(float(v), 2)
        except (ValueError, TypeError):
            return 0

    views = _num(row.get("views"), is_int=True)
    clicks = _num(row.get("clicks"), is_int=True)
    spend = _num(row.get("moneySpent"))
    orders = _num(row.get("orders"), is_int=True)
    revenue = _num(row.get("ordersMoney"))

    ctr = round(clicks / views * 100, 4) if views > 0 else 0
    cpc = round(spend / clicks, 2) if clicks > 0 else 0
    roas = round(revenue / spend, 4) if spend > 0 else 0
    acos = round(spend / revenue * 100, 4) if revenue > 0 else 0

    return {
        "ad_group_id": sku,
        "sku_name": row.get("title", "")[:200],
        "stat_date": created_at,
        "impressions": views,
        "clicks": clicks,
        "spend": spend,
        "orders": orders,
        "revenue": revenue,
        "ctr": ctr,
        "cpc": cpc,
        "acos": acos,
        "roas": roas,
    }


def _save_one_stat(db: Session, campaign: AdCampaign, stat: dict) -> int:
    """将一条统计写入 ad_stats，返回 0（更新）或 1（新增）"""
    stat_date = stat.get("stat_date", "")
    sku = stat.get("ad_group_id", "")
    if not stat_date:
        return 0

    existing = db.execute(text("""
        SELECT id FROM ad_stats
        WHERE campaign_id = :cid AND stat_date = :sd AND platform = 'ozon'
          AND ad_group_id = :sku
    """), {"cid": campaign.id, "sd": stat_date, "sku": sku or None}).fetchone()

    if existing:
        db.execute(text("""
            UPDATE ad_stats SET
                impressions = :impressions, clicks = :clicks, spend = :spend,
                orders = :orders, revenue = :revenue,
                ctr = :ctr, cpc = :cpc, acos = :acos, roas = :roas,
                updated_at = NOW()
            WHERE id = :id
        """), {"id": existing.id, **{k: stat[k] for k in
            ["impressions", "clicks", "spend", "orders", "revenue", "ctr", "cpc", "acos", "roas"]}})
        db.commit()
        return 0
    else:
        db.execute(text("""
            INSERT INTO ad_stats (
                tenant_id, campaign_id, ad_group_id,
                platform, stat_date,
                impressions, clicks, spend, orders, revenue,
                ctr, cpc, acos, roas,
                created_at, updated_at
            ) VALUES (
                :tenant_id, :cid, :sku, 'ozon', :sd,
                :impressions, :clicks, :spend, :orders, :revenue,
                :ctr, :cpc, :acos, :roas, NOW(), NOW()
            )
        """), {
            "tenant_id": campaign.tenant_id,
            "cid": campaign.id,
            "sku": sku or None,
            "sd": stat_date,
            **{k: stat[k] for k in
                ["impressions", "clicks", "spend", "orders", "revenue", "ctr", "cpc", "acos", "roas"]},
        })
        db.commit()
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
