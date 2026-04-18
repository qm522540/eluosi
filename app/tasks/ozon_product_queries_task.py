"""Ozon SKU × 搜索词数据同步

每日凌晨 莫斯科 05:30（UTC 02:30）拉过去 7 天数据
- 遍历所有 active Ozon 店铺
- 拉店铺所有商品 SKU（platform_listings.platform_sku_id）
- 分批 50 个 SKU 调 fetch_product_queries_details
- upsert 到 ozon_product_queries
- 清理 90 天前数据

无 Premium 订阅的店铺会跳过（fetch_product_queries_details 抛 SubscriptionRequiredError）
"""

import asyncio
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import text

from app.tasks.celery_app import celery_app
from app.database import SessionLocal
from app.models.shop import Shop
from app.models.product import PlatformListing
from app.models.ozon_product_query import OzonProductQuery
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


async def _sync_one_shop(db, shop, days: int = 7) -> dict:
    """对单个 Ozon 店铺拉过去 N 天数据"""
    from app.services.platform.ozon import OzonClient, SubscriptionRequiredError

    today = date.today()
    date_to = today
    date_from = today - timedelta(days=days)

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
    total_inserted = 0
    total_skus_with_data = 0
    try:
        # 分批 50 个 SKU
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

            # upsert
            seen_skus = set()
            for r in rows:
                sku = str(r.get("sku") or "").strip()
                query = (r.get("query") or "").strip()[:500]
                if not sku or not query:
                    continue

                existing = db.query(OzonProductQuery).filter(
                    OzonProductQuery.tenant_id == shop.tenant_id,
                    OzonProductQuery.shop_id == shop.id,
                    OzonProductQuery.sku == sku,
                    OzonProductQuery.query == query,
                    OzonProductQuery.stat_date == today,
                ).first()
                fields = {
                    "impressions": int(r.get("impressions") or 0),
                    "clicks": int(r.get("clicks") or 0),
                    "add_to_cart": int(r.get("add_to_cart") or 0),
                    "orders": int(r.get("orders") or 0),
                    "revenue": float(r.get("revenue") or 0),
                    "frequency": int(r.get("frequency") or 0),
                    "view_conversion": float(r.get("view_conversion") or 0),
                    "date_from": date_from,
                    "date_to": date_to,
                }
                if existing:
                    for k, v in fields.items():
                        setattr(existing, k, v)
                else:
                    db.add(OzonProductQuery(
                        tenant_id=shop.tenant_id, shop_id=shop.id,
                        sku=sku, query=query, stat_date=today, **fields,
                    ))
                    total_inserted += 1
                seen_skus.add(sku)
            db.commit()
            total_skus_with_data += len(seen_skus)
    finally:
        await client.close()

    return {
        "shop_id": shop.id, "total_skus": len(skus),
        "skus_with_data": total_skus_with_data, "inserted": total_inserted,
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

        # 清理 90 天前数据
        cutoff = (date.today() - timedelta(days=90))
        deleted = db.query(OzonProductQuery).filter(
            OzonProductQuery.stat_date < cutoff,
        ).delete()
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
