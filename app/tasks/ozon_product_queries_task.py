"""Ozon SKU × 搜索词数据同步

每日凌晨 莫斯科 05:30（UTC 02:30）拉过去 7 天数据
- 遍历所有 active Ozon 店铺
- 拉店铺所有商品 SKU（platform_listings.platform_sku_id）
- 分批 50 个 SKU 调 fetch_product_queries_details
- upsert 到 product_search_queries（platform='ozon'）—— 与老张的搜索词洞察共用底表
- 清理 90 天前 Ozon 数据

无 Premium 订阅的店铺会跳过（fetch_product_queries_details 抛 SubscriptionRequiredError）

历史：2026-04-19 合并到 product_search_queries 共用表（原 ozon_product_queries 已废弃，
047 迁移会 DROP）。
"""

import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.tasks.celery_app import celery_app
from app.database import SessionLocal
from app.models.shop import Shop
from app.models.product import PlatformListing
from app.utils.logger import setup_logger

logger = setup_logger("tasks.ozon_product_queries")


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _chunked(lst, size):
    for i in range(0, len(lst), size):
        yield lst[i:i + size]


_UPSERT_SQL = text("""
    INSERT INTO product_search_queries
        (tenant_id, shop_id, platform, platform_sku_id, query_text, stat_date,
         frequency, impressions, clicks, add_to_cart, orders, revenue,
         view_conversion, extra, created_at)
    VALUES
        (:tenant_id, :shop_id, 'ozon', :sku, :query, :stat_date,
         :frequency, :impressions, :clicks, :add_to_cart, :orders, :revenue,
         :view_conversion, :extra, :created_at)
    ON DUPLICATE KEY UPDATE
        tenant_id      = VALUES(tenant_id),
        frequency      = VALUES(frequency),
        impressions    = VALUES(impressions),
        clicks         = VALUES(clicks),
        add_to_cart    = VALUES(add_to_cart),
        orders         = VALUES(orders),
        revenue        = VALUES(revenue),
        view_conversion= VALUES(view_conversion),
        extra          = VALUES(extra)
""")


async def _sync_one_shop(db, shop, days: int = 7) -> dict:
    """对单个 Ozon 店铺拉过去 N 天数据"""
    from app.services.platform.ozon import OzonClient
    from app.services.platform.base import SubscriptionRequiredError
    import json

    today = datetime.now(timezone.utc).date()
    date_to = today
    date_from = today - timedelta(days=days)
    now_utc = datetime.now(timezone.utc)

    # 拉店铺所有 active 商品的 platform_sku_id（=Ozon SKU）
    listings = db.query(PlatformListing.platform_sku_id).filter(
        PlatformListing.tenant_id == shop.tenant_id,
        PlatformListing.shop_id == shop.id,
        PlatformListing.platform == "ozon",
        PlatformListing.platform_sku_id.isnot(None),
    ).all()
    skus = [str(r.platform_sku_id) for r in listings if r.platform_sku_id]
    if not skus:
        return {"shop_id": shop.id, "skipped": "no_skus"}

    client = OzonClient(
        shop_id=shop.id, api_key=shop.api_key, client_id=shop.client_id,
        perf_client_id=shop.perf_client_id, perf_client_secret=shop.perf_client_secret,
    )
    total_upserted = 0
    total_skus_with_data = 0
    extra_blob = json.dumps({
        "date_from": date_from.isoformat(), "date_to": date_to.isoformat(),
    })
    try:
        for batch in _chunked(skus, 50):
            try:
                rows = await client.fetch_product_queries_details(
                    skus=batch,
                    date_from=date_from.strftime("%Y-%m-%d"),
                    date_to=date_to.strftime("%Y-%m-%d"),
                    limit_by_sku=15,
                )
            except SubscriptionRequiredError:
                logger.warning(f"shop_id={shop.id} 未开通 Ozon Premium，跳过")
                return {"shop_id": shop.id, "skipped": "no_premium"}
            except Exception as e:
                logger.warning(f"shop_id={shop.id} batch 失败: {e}")
                continue

            if not rows:
                continue

            seen_skus = set()
            for r in rows:
                sku = str(r.get("sku") or "").strip()
                query = (r.get("query") or "").strip()[:500]
                if not sku or not query:
                    continue
                db.execute(_UPSERT_SQL, {
                    "tenant_id": shop.tenant_id, "shop_id": shop.id,
                    "sku": sku, "query": query, "stat_date": today,
                    "frequency": int(r.get("frequency") or 0),
                    "impressions": int(r.get("impressions") or 0),
                    "clicks": int(r.get("clicks") or 0),
                    "add_to_cart": int(r.get("add_to_cart") or 0),
                    "orders": int(r.get("orders") or 0),
                    "revenue": float(r.get("revenue") or 0),
                    "view_conversion": float(r.get("view_conversion") or 0),
                    "extra": extra_blob,
                    "created_at": now_utc,
                })
                total_upserted += 1
                seen_skus.add(sku)
            db.commit()
            total_skus_with_data += len(seen_skus)
    finally:
        await client.close()

    return {
        "shop_id": shop.id, "total_skus": len(skus),
        "skus_with_data": total_skus_with_data, "upserted": total_upserted,
    }


@celery_app.task(
    name="app.tasks.ozon_product_queries_task.sync_ozon_product_queries",
    bind=True, max_retries=1, default_retry_delay=600,
)
def sync_ozon_product_queries(self):
    """每日扫所有 Ozon 店铺 → 拉过去 7 天 SKU × 搜索词数据"""
    db = SessionLocal()
    try:
        shops = db.query(Shop).filter(
            Shop.platform == "ozon", Shop.status == "active",
            Shop.api_key.isnot(None),
        ).all()
        results = []
        for shop in shops:
            try:
                r = _run_async(_sync_one_shop(db, shop, days=7))
                results.append(r)
                logger.info(f"Ozon SKU × query 同步: {r}")
            except Exception as e:
                logger.error(f"shop_id={shop.id} 同步异常: {e}", exc_info=True)
                results.append({"shop_id": shop.id, "error": str(e)[:200]})

        # 清理 90 天前 Ozon 数据（共用表，不能 DELETE 全部，限定 platform='ozon'）
        cutoff = (datetime.now(timezone.utc).date() - timedelta(days=90))
        deleted = db.execute(text("""
            DELETE FROM product_search_queries
            WHERE platform='ozon' AND stat_date < :cutoff
        """), {"cutoff": cutoff}).rowcount
        db.commit()
        if deleted:
            logger.info(f"清理 {deleted} 条 90 天前 Ozon SKU×query 数据")
        return {"shops": len(shops), "results": results, "cleaned": deleted}
    except Exception as e:
        logger.error(f"Ozon SKU×query 全局任务异常: {e}", exc_info=True)
        db.rollback()
        raise self.retry(exc=e)
    finally:
        db.close()


@celery_app.task(
    name="app.tasks.ozon_product_queries_task.sync_ozon_product_queries_for_shop",
    bind=True,
)
def sync_ozon_product_queries_for_shop(self, shop_id: int, tenant_id: int, days: int = 7):
    """单店铺手动触发（"立即同步"按钮专用）"""
    db = SessionLocal()
    try:
        shop = db.query(Shop).filter(
            Shop.id == shop_id, Shop.tenant_id == tenant_id, Shop.platform == "ozon",
        ).first()
        if not shop:
            return {"error": "店铺不存在或非 Ozon"}
        r = _run_async(_sync_one_shop(db, shop, days=days))
        return r
    finally:
        db.close()
