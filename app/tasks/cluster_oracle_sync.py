"""WB 顶级搜索集群 oracle 每日同步任务

遍历有 wb_cmp_authorizev3 + wb_cmp_supplierid 的 WB 店铺，对每个活动下的 SKU
调 cmp.wildberries.ru 内部 API 拉 6 簇 + 词映射，upsert 到 wb_cluster_oracle*。

JWT 过期（401/403）会被 WBCmpClient 抛成 CmpAuthExpired：任务捕获后只跳过
该店铺剩余 SKU，不影响其他店铺；前端根据 wb_cmp_token_exp_at 或标记字段展示
banner 提示用户刷新 token。

Celery beat：莫斯科每日 03:30（错开已有任务）。
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import Optional

from sqlalchemy import text

from app.database import SessionLocal
from app.models.ad import AdCampaign
from app.models.shop import Shop
from app.services.platform.wb_cmp import WBCmpClient, CmpAuthExpired
from app.services.ad.cluster_oracle_service import upsert_from_cmp
from app.tasks.celery_app import celery_app
from app.utils.logger import logger
from app.utils.moscow_time import moscow_today, utc_now_naive


async def _sync_one_shop(shop: Shop, db) -> dict:
    """同步一个店铺下全部 WB 活动的 oracle 数据"""
    stats = {"shop_id": shop.id, "skus_ok": 0, "skus_fail": 0, "expired": False}
    if not shop.wb_cmp_authorizev3 or not shop.wb_cmp_supplierid:
        stats["skipped_reason"] = "no_cmp_credentials"
        return stats

    # 查该店铺下全部活跃 WB 活动
    camps = db.query(AdCampaign).filter(
        AdCampaign.tenant_id == shop.tenant_id,
        AdCampaign.shop_id   == shop.id,
        AdCampaign.platform  == "wb",
    ).all()
    if not camps:
        stats["skipped_reason"] = "no_campaigns"
        return stats

    client = WBCmpClient(
        authorizev3=shop.wb_cmp_authorizev3,
        supplierid=shop.wb_cmp_supplierid,
    )
    date_to   = moscow_today() - timedelta(days=1)
    date_from = date_to - timedelta(days=6)

    try:
        for camp in camps:
            # 每个活动有多个 SKU（通过 WB placement API 能拉，但我们已有 ad_groups
            # 表存了 listing_id → platform_listings.platform_sku_id）
            sku_rows = db.execute(text("""
                SELECT DISTINCT pl.platform_sku_id
                FROM ad_groups ag
                JOIN platform_listings pl ON ag.listing_id = pl.id
                WHERE ag.tenant_id = :tid AND ag.campaign_id = :cid
                  AND pl.platform_sku_id IS NOT NULL
            """), {"tid": shop.tenant_id, "cid": camp.id}).fetchall()

            for (sku_str,) in sku_rows:
                try:
                    nm_id = int(sku_str)
                except (TypeError, ValueError):
                    continue
                try:
                    cmp_res = await client.fetch_cluster_oracle_full(
                        advert_id=int(camp.platform_campaign_id),
                        nm_id=nm_id,
                        date_from=date_from, date_to=date_to,
                    )
                    if not cmp_res["summary"]:
                        # 无簇数据（可能该 SKU 本周未投放），跳过
                        continue
                    upsert_from_cmp(
                        db=db, tenant_id=shop.tenant_id, shop_id=shop.id,
                        advert_id=int(camp.platform_campaign_id), nm_id=nm_id,
                        cmp_result=cmp_res,
                    )
                    stats["skus_ok"] += 1
                except CmpAuthExpired as e:
                    logger.warning(
                        f"[cluster_oracle_sync] shop={shop.id} JWT 过期: {e}，"
                        f"跳过该店铺剩余 SKU"
                    )
                    stats["expired"] = True
                    # 清空 exp_at 让前端立即提示（精确过期时间已无意义）
                    db.execute(text("""
                        UPDATE shops SET wb_cmp_token_exp_at = :now_utc
                        WHERE id = :sid
                    """), {"now_utc": utc_now_naive(), "sid": shop.id})
                    db.commit()
                    raise  # 跳出 SKU 循环 → 外层 try 捕
                except Exception as e:
                    logger.warning(
                        f"[cluster_oracle_sync] shop={shop.id} adv={camp.platform_campaign_id} "
                        f"nm={nm_id} 同步失败: {e}"
                    )
                    stats["skus_fail"] += 1
    except CmpAuthExpired:
        pass  # 已记 log + exp_at，本店铺剩余 SKU 不再尝试
    finally:
        await client.close()

    return stats


async def _sync_all_shops_async():
    db = SessionLocal()
    try:
        shops = db.query(Shop).filter(
            Shop.platform == "wb",
            Shop.status == "active",
            Shop.wb_cmp_authorizev3.isnot(None),
            Shop.wb_cmp_supplierid.isnot(None),
        ).all()
        logger.info(f"[cluster_oracle_sync] 开始同步 {len(shops)} 家 WB 店铺")

        totals = {"shops_total": len(shops), "skus_ok": 0, "skus_fail": 0, "shops_expired": 0}
        for shop in shops:
            res = await _sync_one_shop(shop, db)
            totals["skus_ok"]   += res.get("skus_ok", 0)
            totals["skus_fail"] += res.get("skus_fail", 0)
            if res.get("expired"):
                totals["shops_expired"] += 1

        logger.info(f"[cluster_oracle_sync] 完成: {totals}")
        return totals
    finally:
        db.close()


@celery_app.task(name="app.tasks.cluster_oracle_sync.sync_wb_cluster_oracle")
def sync_wb_cluster_oracle():
    """Celery beat 入口：每日同步全部有 JWT 的 WB 店铺"""
    return asyncio.run(_sync_all_shops_async())


async def sync_one_nm_async(
    tenant_id: int, shop_id: int, advert_id: int, nm_id: int,
    date_from: Optional[date] = None, date_to: Optional[date] = None,
) -> dict:
    """手动触发：前端"立即同步"按钮调用"""
    db = SessionLocal()
    try:
        shop = db.query(Shop).filter(Shop.id == shop_id, Shop.tenant_id == tenant_id).first()
        if not shop:
            return {"ok": False, "msg": "店铺不存在"}
        if not shop.wb_cmp_authorizev3 or not shop.wb_cmp_supplierid:
            return {"ok": False, "msg": "该店铺未配置 WB CMP JWT，请先在店铺设置填写"}

        client = WBCmpClient(
            authorizev3=shop.wb_cmp_authorizev3,
            supplierid=shop.wb_cmp_supplierid,
        )
        try:
            cmp_res = await client.fetch_cluster_oracle_full(
                advert_id=advert_id, nm_id=nm_id,
                date_from=date_from, date_to=date_to,
            )
        except CmpAuthExpired as e:
            db.execute(text("""
                UPDATE shops SET wb_cmp_token_exp_at = :now_utc WHERE id = :sid
            """), {"now_utc": utc_now_naive(), "sid": shop_id})
            db.commit()
            return {"ok": False, "expired": True, "msg": f"JWT 过期: {e}"}
        finally:
            await client.close()

        if not cmp_res["summary"]:
            return {"ok": True, "cluster_count": 0, "keyword_count": 0,
                    "msg": "该 SKU 近 7 天无集群数据"}

        stats = upsert_from_cmp(
            db=db, tenant_id=tenant_id, shop_id=shop_id,
            advert_id=advert_id, nm_id=nm_id, cmp_result=cmp_res,
        )
        return {
            "ok": True,
            "cluster_count": stats["summary"],
            "keyword_count": stats["mapping"],
            "date_from": cmp_res["date_from"].strftime("%Y-%m-%d"),
            "date_to":   cmp_res["date_to"].strftime("%Y-%m-%d"),
        }
    finally:
        db.close()
