"""库存联动检查引擎

店铺级规则，遍历所有SKU库存执行pause/resume动作。

规则判断：
  - quantity <= pause_threshold  且 status != paused → 执行pause（出价改3卢布）
  - quantity >= resume_threshold 且 status == paused → 执行resume（还原原出价）
  - pause_threshold < quantity <= pause_threshold*2 且 status == normal → 标记为alert
  - quantity > pause_threshold*2 且 status == alert → 标记为normal

注意：
  - 出价单位：前端/数据库用卢布，Ozon Performance API用micro单位(字符串)，需转换
  - Ozon最低出价为3卢布
  - sync db session + async OzonClient 混用，遵循项目既有模式
"""

from sqlalchemy import text

from app.utils.logger import setup_logger

logger = setup_logger("inventory.linkage_engine")


async def run_linkage_check(db, shop_id: int) -> dict:
    """执行指定店铺的库存联动检查

    Returns:
        {checked, paused, resumed, alerted, normalized, errors, skipped?}
    """
    # 1. 读取店铺规则
    row = db.execute(text("""
        SELECT id, tenant_id, shop_id, is_active,
               pause_threshold, resume_threshold
        FROM inventory_linkage_rules
        WHERE shop_id = :shop_id
        LIMIT 1
    """), {"shop_id": shop_id}).fetchone()

    counters = {
        "checked": 0, "paused": 0, "resumed": 0,
        "alerted": 0, "normalized": 0, "errors": 0,
    }

    if not row:
        logger.info(f"shop_id={shop_id} 无库存联动规则配置")
        counters["skipped"] = "no_rule"
        return counters

    if not row.is_active:
        logger.info(f"shop_id={shop_id} 库存联动规则未开启")
        counters["skipped"] = "inactive"
        return counters

    rule = {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "pause_threshold": row.pause_threshold,
        "resume_threshold": row.resume_threshold,
    }

    logger.info(
        f"shop_id={shop_id} 开始库存联动检查 "
        f"pause<={rule['pause_threshold']} resume>={rule['resume_threshold']}"
    )

    # 2. 查询所有SKU库存 + 关联活动
    # 仅处理所属活动为active状态的SKU
    # (已暂停的活动不允许调用 Performance API 修改商品出价，Ozon会返回400)
    stocks = db.execute(text("""
        SELECT
            s.id, s.tenant_id, s.shop_id, s.campaign_id,
            s.platform_sku_id, s.sku_name, s.quantity, s.status,
            s.paused_bid,
            c.platform_campaign_id, c.name AS campaign_name
        FROM inventory_platform_stocks s
        JOIN ad_campaigns c ON c.id = s.campaign_id
        WHERE s.shop_id = :shop_id
          AND c.status = 'active'
        ORDER BY s.quantity ASC
    """), {"shop_id": shop_id}).fetchall()

    if not stocks:
        logger.info(f"shop_id={shop_id} 无SKU库存快照数据，跳过")
        return counters

    # 3. 初始化Ozon客户端（只初始化一次）
    from app.models.shop import Shop
    from app.services.platform.ozon import OzonClient

    shop = db.query(Shop).filter(Shop.id == shop_id).first()
    if not shop:
        logger.warning(f"shop_id={shop_id} 店铺不存在")
        counters["skipped"] = "shop_not_found"
        return counters

    client = OzonClient(
        shop_id=shop.id,
        api_key=shop.api_key,
        client_id=shop.client_id,
        perf_client_id=shop.perf_client_id or "",
        perf_client_secret=shop.perf_client_secret or "",
    )

    try:
        for stock in stocks:
            counters["checked"] += 1
            try:
                result = await _check_and_execute(db, stock, rule, client)
                if result in counters:
                    counters[result] += 1
            except Exception as e:
                counters["errors"] += 1
                logger.error(
                    f"联动检查异常 sku={stock.platform_sku_id}: {e}"
                )

        db.commit()
    finally:
        await client.close()

    logger.info(
        f"shop_id={shop_id} 联动检查完成 "
        f"检查={counters['checked']} 暂停={counters['paused']} "
        f"恢复={counters['resumed']} 预警={counters['alerted']} "
        f"错误={counters['errors']}"
    )
    return counters


async def _check_and_execute(db, stock, rule: dict, client) -> str:
    """检查单个SKU并执行对应动作，返回动作名 (paused/resumed/alerted/normalized/no_change)"""
    qty = stock.quantity
    status = stock.status
    pause_t = rule["pause_threshold"]
    resume_t = rule["resume_threshold"]

    # 场景1：库存低于等于暂停阈值 且 当前未暂停 → pause
    if qty <= pause_t and status != "paused":
        return await _do_pause(db, stock, rule, client)

    # 场景2：库存高于等于恢复阈值 且 当前已暂停 → resume
    if qty >= resume_t and status == "paused":
        return await _do_resume(db, stock, rule, client)

    # 场景3：介于两个阈值之间（接近暂停阈值）且当前normal → 标记alert
    if pause_t < qty < resume_t and status == "normal":
        db.execute(text("""
            UPDATE inventory_platform_stocks
            SET status = 'alert'
            WHERE id = :id
        """), {"id": stock.id})
        _write_log(db, stock, rule, "alert",
                   old_bid=None, new_bid=None, success=True)
        logger.info(
            f"库存预警 shop={stock.shop_id} sku={stock.platform_sku_id} qty={qty}"
        )
        return "alerted"

    # 场景4：库存恢复到阈值以上 且 当前是alert → 标记normal
    if qty >= resume_t and status == "alert":
        db.execute(text("""
            UPDATE inventory_platform_stocks
            SET status = 'normal'
            WHERE id = :id
        """), {"id": stock.id})
        return "normalized"

    return "no_change"


async def _do_pause(db, stock, rule: dict, client) -> str:
    """暂停SKU出价：记录原出价 → 改为3卢布"""
    platform_campaign_id = stock.platform_campaign_id
    sku = stock.platform_sku_id

    try:
        # 从活动商品列表读取当前出价（Ozon Performance API返回micro单位字符串）
        current_bid_rub = 0.0
        try:
            products = await client.fetch_campaign_products(platform_campaign_id)
            for p in products or []:
                if str(p.get("sku")) == sku:
                    bid_raw = p.get("bid", "0")
                    try:
                        current_bid_rub = float(int(bid_raw) / 1_000_000)
                    except (ValueError, TypeError):
                        current_bid_rub = 0.0
                    break
        except Exception as e:
            logger.warning(f"读取原出价失败 sku={sku}: {e}")

        # 改为3卢布（Ozon最低出价）
        new_bid_micro = str(3 * 1_000_000)
        api_result = await client.update_campaign_bid(
            platform_campaign_id, sku, new_bid_micro
        )

        if not api_result.get("ok"):
            _write_log(db, stock, rule, "pause",
                       old_bid=current_bid_rub, new_bid=3.0,
                       success=False,
                       error_msg=api_result.get("error") or "unknown")
            return "errors"

        # 更新状态 + 保存原出价
        db.execute(text("""
            UPDATE inventory_platform_stocks
            SET status = 'paused',
                paused_at = NOW(),
                paused_bid = :bid
            WHERE id = :id
        """), {
            "id": stock.id,
            "bid": current_bid_rub if current_bid_rub > 0 else None,
        })

        _write_log(db, stock, rule, "pause",
                   old_bid=current_bid_rub, new_bid=3.0, success=True)

        logger.info(
            f"库存联动暂停 shop={stock.shop_id} sku={sku} "
            f"qty={stock.quantity} bid={current_bid_rub}→3"
        )
        return "paused"

    except Exception as e:
        _write_log(db, stock, rule, "pause",
                   old_bid=None, new_bid=None,
                   success=False, error_msg=str(e))
        logger.error(f"暂停出价失败 sku={sku}: {e}")
        return "errors"


async def _do_resume(db, stock, rule: dict, client) -> str:
    """恢复SKU出价：还原paused_bid"""
    platform_campaign_id = stock.platform_campaign_id
    sku = stock.platform_sku_id

    # 没有paused_bid时默认恢复到30卢布（保底值）
    restore_bid = float(stock.paused_bid) if stock.paused_bid else 30.0
    if restore_bid < 3:
        restore_bid = 3.0

    try:
        new_bid_micro = str(int(restore_bid * 1_000_000))
        api_result = await client.update_campaign_bid(
            platform_campaign_id, sku, new_bid_micro
        )

        if not api_result.get("ok"):
            _write_log(db, stock, rule, "resume",
                       old_bid=3.0, new_bid=restore_bid,
                       success=False,
                       error_msg=api_result.get("error") or "unknown")
            return "errors"

        db.execute(text("""
            UPDATE inventory_platform_stocks
            SET status = 'normal',
                paused_at = NULL,
                paused_bid = NULL
            WHERE id = :id
        """), {"id": stock.id})

        _write_log(db, stock, rule, "resume",
                   old_bid=3.0, new_bid=restore_bid, success=True)

        logger.info(
            f"库存联动恢复 shop={stock.shop_id} sku={sku} "
            f"qty={stock.quantity} bid=3→{restore_bid}"
        )
        return "resumed"

    except Exception as e:
        _write_log(db, stock, rule, "resume",
                   old_bid=None, new_bid=None,
                   success=False, error_msg=str(e))
        logger.error(f"恢复出价失败 sku={sku}: {e}")
        return "errors"


def _write_log(db, stock, rule: dict, action: str,
               old_bid=None, new_bid=None,
               success: bool = True, error_msg=None):
    """写联动执行日志（sync db操作）"""
    db.execute(text("""
        INSERT INTO inventory_linkage_logs (
            tenant_id, shop_id, campaign_id,
            platform_sku_id, sku_name, action,
            old_quantity, old_bid, new_bid,
            success, error_msg
        ) VALUES (
            :tenant_id, :shop_id, :campaign_id,
            :sku, :name, :action,
            :qty, :old_bid, :new_bid,
            :success, :error_msg
        )
    """), {
        "tenant_id": rule["tenant_id"],
        "shop_id": stock.shop_id,
        "campaign_id": stock.campaign_id,
        "sku": stock.platform_sku_id,
        "name": stock.sku_name,
        "action": action,
        "qty": stock.quantity,
        "old_bid": old_bid,
        "new_bid": new_bid,
        "success": 1 if success else 0,
        "error_msg": (error_msg or "")[:500] if error_msg else None,
    })
