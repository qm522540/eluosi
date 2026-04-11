"""平台仓库存同步服务

从Ozon拉取各SKU的平台仓库存，写入 inventory_platform_stocks 表。

流程：
1. 遍历店铺下所有active/paused的Ozon广告活动
2. 对每个活动调 fetch_campaign_products 获取SKU列表及名称
3. 按SKU批量查询Ozon Seller API获取库存数量（/v3/product/info/list）
4. upsert到 inventory_platform_stocks 表（一个SKU一条，按shop_id+sku唯一）

注意：
- 项目使用sync SessionLocal，db.execute/db.commit无await
- OzonClient是统一客户端（不是OzonSellerAPI/OzonPerformanceAPI）
- 一个SKU可能出现在多个活动中，按首次出现的活动记录campaign_id
"""

from sqlalchemy import text

from app.utils.logger import setup_logger

logger = setup_logger("inventory.stock_syncer")


async def sync_ozon_platform_stocks(db, shop) -> int:
    """同步指定Ozon店铺下所有广告活动中商品的平台仓库存。

    Args:
        db: sync Session (SessionLocal)
        shop: Shop 模型对象

    Returns:
        更新的SKU数量
    """
    from app.models.ad import AdCampaign
    from app.services.platform.ozon import OzonClient

    if shop.platform != "ozon":
        logger.info(f"shop_id={shop.id} 非Ozon店铺，跳过库存同步")
        return 0

    # 1. 查询本店铺所有active/paused的Ozon活动
    campaigns = db.query(AdCampaign).filter(
        AdCampaign.shop_id == shop.id,
        AdCampaign.platform == "ozon",
        AdCampaign.status.in_(["active", "paused"]),
    ).all()

    if not campaigns:
        logger.info(f"shop_id={shop.id} 无active/paused的Ozon活动，跳过")
        return 0

    client = OzonClient(
        shop_id=shop.id,
        api_key=shop.api_key,
        client_id=shop.client_id,
        perf_client_id=shop.perf_client_id or "",
        perf_client_secret=shop.perf_client_secret or "",
    )

    try:
        # 2. 遍历活动收集 (sku -> campaign_id, title) 映射
        sku_to_campaign = {}
        for camp in campaigns:
            try:
                products = await client.fetch_campaign_products(
                    camp.platform_campaign_id
                )
            except Exception as e:
                logger.warning(
                    f"shop_id={shop.id} campaign={camp.id} 拉取商品失败: {e}"
                )
                continue

            for p in products or []:
                sku = str(p.get("sku") or "")
                if not sku:
                    continue
                # 一个SKU只记录首次出现的活动
                if sku not in sku_to_campaign:
                    sku_to_campaign[sku] = (
                        camp.id,
                        p.get("title") or "",
                    )

        if not sku_to_campaign:
            logger.info(f"shop_id={shop.id} 广告活动下未找到商品SKU")
            return 0

        logger.info(
            f"shop_id={shop.id} 从{len(campaigns)}个活动收集到{len(sku_to_campaign)}个SKU"
        )

        # 3. 批量查询SKU库存
        skus = list(sku_to_campaign.keys())
        stock_map = await _fetch_stocks_by_skus(client, skus)

        if not stock_map:
            logger.warning(
                f"shop_id={shop.id} 平台仓库存查询返回空，跳过写入"
            )
            return 0

        # 4. upsert到inventory_platform_stocks
        updated = 0
        for sku, (campaign_id, title) in sku_to_campaign.items():
            qty = stock_map.get(sku, 0)
            db.execute(text("""
                INSERT INTO inventory_platform_stocks (
                    tenant_id, shop_id, campaign_id,
                    platform_sku_id, sku_name,
                    quantity, last_synced_at
                ) VALUES (
                    :tenant_id, :shop_id, :campaign_id,
                    :sku, :name, :qty, NOW()
                )
                ON DUPLICATE KEY UPDATE
                    campaign_id = VALUES(campaign_id),
                    sku_name = IF(VALUES(sku_name) != '', VALUES(sku_name), sku_name),
                    quantity = VALUES(quantity),
                    last_synced_at = NOW()
            """), {
                "tenant_id": shop.tenant_id,
                "shop_id": shop.id,
                "campaign_id": campaign_id,
                "sku": sku,
                "name": title,
                "qty": int(qty),
            })
            updated += 1

        db.commit()
        logger.info(
            f"shop_id={shop.id} ({shop.name}) 库存同步完成 "
            f"活动{len(campaigns)}个 SKU{updated}个"
        )
        return updated

    except Exception as e:
        logger.error(f"shop_id={shop.id} 库存同步失败: {e}")
        db.rollback()
        return 0
    finally:
        await client.close()


async def _fetch_stocks_by_skus(client, skus: list) -> dict:
    """按SKU列表批量查询Ozon平台仓库存

    Ozon API: POST /v3/product/info/list（支持sku过滤）
    响应: {result: {items: [{sku, stocks: {present, reserved, coming}}]}}

    Args:
        client: OzonClient 实例
        skus: SKU字符串列表

    Returns:
        {sku_str: total_present_quantity}
    """
    if not skus:
        return {}

    from app.services.platform.ozon import OZON_SELLER_API

    # Ozon SKU 是整数
    sku_ints = []
    for s in skus:
        try:
            sku_ints.append(int(s))
        except (ValueError, TypeError):
            continue

    if not sku_ints:
        return {}

    result_map = {}
    batch_size = 100  # Ozon v3/product/info/list 单次最多支持100个

    for i in range(0, len(sku_ints), batch_size):
        batch = sku_ints[i:i + batch_size]
        try:
            url = f"{OZON_SELLER_API}/v3/product/info/list"
            payload = {"sku": batch, "offer_id": [], "product_id": []}
            resp = await client._request("POST", url, json=payload)
        except Exception as e:
            logger.warning(f"Ozon SKU库存查询批次失败 size={len(batch)}: {e}")
            continue

        # 兼容多种响应格式
        items = []
        if isinstance(resp, dict):
            if isinstance(resp.get("result"), dict):
                items = resp["result"].get("items") or []
            elif isinstance(resp.get("items"), list):
                items = resp["items"]

        for item in items:
            sku = str(item.get("sku") or item.get("fbo_sku") or item.get("fbs_sku") or "")
            if not sku or sku == "0":
                # 尝试从 sources 里拿
                for src in item.get("sources") or []:
                    alt = str(src.get("sku") or "")
                    if alt and alt != "0":
                        sku = alt
                        break
            if not sku or sku == "0":
                continue

            # stocks 可能是 dict 或 list
            stocks_field = item.get("stocks")
            total = 0
            if isinstance(stocks_field, dict):
                total = int(stocks_field.get("present", 0) or 0)
            elif isinstance(stocks_field, list):
                for s in stocks_field:
                    total += int(s.get("present", 0) or 0)
            result_map[sku] = total

    logger.info(
        f"Ozon SKU库存查询完成 请求{len(sku_ints)}个 返回{len(result_map)}个"
    )
    return result_map
