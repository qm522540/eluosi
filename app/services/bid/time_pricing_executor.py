"""分时调价执行器（按老林规范 docs/api/bid_management.md §2 + §9）

数据流：
  time_pricing_rules.is_active=1 触发执行
  → 遍历 ad_campaigns(status='active', platform=shop.platform)
    → 遍历商品/SKU
      → 跳过 user_managed=1
      → first run：original_bid 为空时写入当前价
      → new_bid = original_bid * ratio / 100
      → 调平台 API 改价 → 写 bid_adjustment_logs(execute_type='time_pricing')
      → 更新 last_auto_bid

支持平台：Ozon（自动执行）、WB（自动执行）
约束：
  - 项目用 sync SessionLocal，db.execute/commit 不带 await
  - 平台 client 通过 _create_platform_client 统一创建
  - 出价单位统一用卢布，_execute_bid_update 内部处理 Ozon micro / WB kopecks 换算
  - 互斥校验用 SELECT ... FOR UPDATE
"""

from sqlalchemy import text

from app.utils.errors import ErrorCode
from app.utils.logger import setup_logger
from app.utils.moscow_time import get_current_period, moscow_hour, now_moscow

logger = setup_logger("bid.time_pricing_executor")

MIN_BID = 3.0
MIN_DIFF = 1.0


# ==================== 主入口（Celery 调用） ====================

async def execute(db, shop_id: int, tenant_id: int = None) -> dict:
    """Celery 触发的分时调价主流程

    Args:
        tenant_id: 手动触发时由路由透传；Celery 不传，从 shops 表反查。

    Returns:
        {checked, adjusted, skipped, errors, period}
    """
    counters = {"checked": 0, "adjusted": 0, "skipped": 0, "errors": 0, "period": None}

    # Celery 路径未传 tenant_id 时反查
    if tenant_id is None:
        from app.models.shop import Shop
        s = db.query(Shop).filter(Shop.id == shop_id).first()
        if not s:
            return counters
        tenant_id = s.tenant_id

    rule = db.execute(text("""
        SELECT id, tenant_id, shop_id, is_active,
               peak_hours, peak_ratio, mid_hours, mid_ratio,
               low_hours, low_ratio
        FROM time_pricing_rules
        WHERE shop_id = :shop_id
          AND tenant_id = :tenant_id
          AND is_active = 1
        LIMIT 1
    """), {"shop_id": shop_id, "tenant_id": tenant_id}).fetchone()

    if not rule:
        logger.info(f"shop_id={shop_id} 分时调价未启用，跳过")
        return counters

    period = get_current_period(rule)
    if not period:
        # 平谷期：当前小时不在 peak/mid/low 任一档里 → 保持原价不动，整个店铺跳过
        logger.info(
            f"shop_id={shop_id} 当前莫斯科{moscow_hour()}点为平谷期，本次不调价"
        )
        counters["period"] = "base"
        _save_result(db, shop_id, tenant_id, counters, f"平谷期({moscow_hour()}:00) 不调价")
        return counters

    ratio = {"peak": rule.peak_ratio, "mid": rule.mid_ratio, "low": rule.low_ratio}[period]
    counters["period"] = period

    from app.models.shop import Shop
    shop = db.query(Shop).filter(
        Shop.id == shop_id, Shop.tenant_id == tenant_id
    ).first()
    if not shop or shop.platform not in ("ozon", "wb"):
        return counters

    platform = shop.platform

    logger.info(
        f"shop={shop.name} 分时调价 莫斯科{moscow_hour()}点 时段={period} 系数={ratio}%"
    )

    from app.models.ad import AdCampaign
    campaigns = db.query(AdCampaign).filter(
        AdCampaign.tenant_id == tenant_id,
        AdCampaign.shop_id == shop_id,
        AdCampaign.platform == platform,
        AdCampaign.status == "active",
    ).all()

    if not campaigns:
        _save_result(db, shop_id, tenant_id, counters, "无active活动")
        return counters

    from app.services.bid.ai_pricing_executor import _create_platform_client
    client = _create_platform_client(shop)

    try:
        for camp in campaigns:
            await _process_campaign(db, client, camp, period, ratio, counters)
        db.commit()
    finally:
        await client.close()

    _save_result(
        db, shop_id, tenant_id, counters,
        f"{period}时段 调整{counters['adjusted']}个 跳过{counters['skipped']}个 失败{counters['errors']}个"
    )
    logger.info(
        f"shop={shop.name} 分时调价完成 "
        f"checked={counters['checked']} adjusted={counters['adjusted']} "
        f"skipped={counters['skipped']} errors={counters['errors']}"
    )
    return counters


async def _process_campaign(db, client, campaign, period: str, ratio: int, counters: dict):
    """遍历活动下所有商品"""
    try:
        products = await client.fetch_campaign_products(campaign.platform_campaign_id)
    except Exception as e:
        logger.error(f"读取活动商品失败 campaign={campaign.name} ({campaign.id}): {e}")
        counters["errors"] += 1
        return

    platform = campaign.platform
    for product in products or []:
        sku = str(product.get("sku") or "")
        if not sku:
            continue
        if platform == "ozon":
            bid_raw = product.get("bid", "0")
            try:
                current_bid = float(int(bid_raw)) / 1_000_000
            except (ValueError, TypeError):
                current_bid = 0.0
            sku_name = (product.get("title") or "")[:300]
        else:
            # WB: bid_search 已经是卢布
            current_bid = float(product.get("bid_search") or 0)
            sku_name = (product.get("subject_name") or "")[:300]

        counters["checked"] += 1
        try:
            outcome = await _process_sku(
                db, client, campaign, sku, sku_name,
                current_bid, period, ratio
            )
            if outcome == "adjusted":
                counters["adjusted"] += 1
            elif outcome == "error":
                counters["errors"] += 1
            else:
                counters["skipped"] += 1
        except Exception as e:
            counters["errors"] += 1
            logger.error(f"SKU {sku} 处理异常: {e}")


async def _process_sku(db, client, campaign, sku: str, sku_name: str,
                      current_bid: float, period: str, ratio: int) -> str:
    """处理单个 SKU。返回 adjusted | skipped | error"""
    # 1. 取 ad_groups 行（platform_group_id 当作 SKU）
    row = db.execute(text("""
        SELECT id, user_managed, original_bid, last_auto_bid
        FROM ad_groups
        WHERE campaign_id = :cid AND platform_group_id = :sku
        LIMIT 1
    """), {"cid": campaign.id, "sku": sku}).fetchone()

    if row and row.user_managed:
        return "skipped"

    last_auto = float(row.last_auto_bid) if (row and row.last_auto_bid) else None
    original = float(row.original_bid) if (row and row.original_bid) else None

    # 2. 检测系统外手改：last_auto_bid 与平台当前价偏差 > MIN_DIFF
    if last_auto is not None and current_bid > 0:
        if abs(current_bid - last_auto) > MIN_DIFF:
            logger.info(
                f"SKU {sku} 检测系统外手改 last_auto={last_auto} platform={current_bid}"
                f" → 标记 user_managed"
            )
            db.execute(text("""
                UPDATE ad_groups
                SET user_managed = 1, user_managed_at = NOW()
                WHERE campaign_id = :cid AND platform_group_id = :sku
            """), {"cid": campaign.id, "sku": sku})
            return "skipped"

    # 3. first run：original_bid 为空时写入当前价
    base = original if (original and original > 0) else current_bid
    if base <= 0:
        return "skipped"

    # 4. 计算目标出价
    target = max(base * ratio / 100.0, MIN_BID)
    target = round(target)  # Ozon 只接受整数卢布

    # 5. 差值 < MIN_DIFF 跳过 API
    if abs(target - current_bid) < MIN_DIFF:
        # 仍然要确保 ad_groups 行存在并写入 original_bid（首次）
        if not row or not row.original_bid:
            _upsert_group(db, campaign, sku, sku_name, base_bid=base, last_auto=current_bid)
        return "skipped"

    # 6. 调用平台 API（Ozon / WB 自动适配）
    from app.services.bid.ai_pricing_executor import _execute_bid_update
    api_result = await _execute_bid_update(
        client, campaign.platform, campaign.platform_campaign_id, sku, target,
    )
    if not api_result.get("ok"):
        err = api_result.get("error") or "unknown"
        logger.error(f"SKU {sku} 出价修改失败: {err}")
        _write_log(
            db, campaign, sku, sku_name,
            old_bid=current_bid, new_bid=target,
            execute_type="time_pricing", time_period=period, period_ratio=ratio,
            success=False, error_msg=err,
        )
        return "error"

    # 7. 更新 ad_groups
    _upsert_group(db, campaign, sku, sku_name, base_bid=base, last_auto=target)

    # 8. 写日志
    _write_log(
        db, campaign, sku, sku_name,
        old_bid=current_bid, new_bid=target,
        execute_type="time_pricing", time_period=period, period_ratio=ratio,
        success=True,
    )

    logger.info(
        f"SKU {sku} 调价 {current_bid:.0f}→{target:.0f}卢布 ({period}{ratio}%)"
    )
    return "adjusted"


# ==================== 启用 / 停用 ====================

def update_rule(db, tenant_id: int, shop_id: int, data: dict) -> dict:
    """更新分时调价规则（PUT /time-pricing/{shop_id}）

    4 档时段语义（用户对齐 2026-04-11，违反老林规范 §2.2 24小时全覆盖约束）：
      - 高峰 / 次高峰 / 低谷：用户配置的小时，按对应 ratio 调价
      - 平谷期：未配置的小时，保持原价不动（ratio=100% 隐式）
    校验：三档之间不重叠 + 每个小时在 [0,23] + ratio∈[10,500]
    """
    import json

    peak = data.get("peak_hours") or []
    mid = data.get("mid_hours") or []
    low = data.get("low_hours") or []
    peak_ratio = int(data.get("peak_ratio") or 130)
    mid_ratio = int(data.get("mid_ratio") or 120)
    low_ratio = int(data.get("low_ratio") or 50)

    # 校验1：每个小时在 [0,23] 范围
    for arr_name, arr in [("peak", peak), ("mid", mid), ("low", low)]:
        for h in arr:
            if not isinstance(h, int) or not 0 <= h <= 23:
                return {"code": ErrorCode.BID_INVALID_HOURS_CONFIG,
                        "msg": f"{arr_name}_hours 包含非法小时值: {h}"}

    # 校验2：三档之间两两不相交
    total = len(peak) + len(mid) + len(low)
    union = set(peak) | set(mid) | set(low)
    if total != len(union):
        return {"code": ErrorCode.BID_INVALID_HOURS_CONFIG,
                "msg": "时段不能重叠（同一小时不能同时属于多档）"}

    # 校验3：ratio 范围
    for r in (peak_ratio, mid_ratio, low_ratio):
        if not 0 <= r <= 200:
            return {"code": ErrorCode.BID_INVALID_RATIO, "msg": "出价系数必须在 0-200 范围内"}

    # 先检查是否已有该 shop 的规则（必须 tenant_id 匹配，防 ON DUPLICATE 跨租户覆盖）
    existing = db.execute(text("""
        SELECT id, tenant_id FROM time_pricing_rules WHERE shop_id = :shop_id
    """), {"shop_id": shop_id}).fetchone()

    if existing and existing.tenant_id != tenant_id:
        # UNIQUE KEY 是 shop_id 但实际属于其他租户 — 拒绝（理论上 get_owned_shop 已防住）
        return {"code": ErrorCode.SHOP_NOT_FOUND, "msg": "店铺不存在或无权限"}

    db.execute(text("""
        INSERT INTO time_pricing_rules (
            tenant_id, shop_id,
            peak_hours, peak_ratio,
            mid_hours, mid_ratio,
            low_hours, low_ratio,
            is_active
        ) VALUES (
            :tenant_id, :shop_id,
            :peak_hours, :peak_ratio,
            :mid_hours, :mid_ratio,
            :low_hours, :low_ratio,
            0
        )
        ON DUPLICATE KEY UPDATE
            tenant_id = VALUES(tenant_id),
            peak_hours = VALUES(peak_hours),
            peak_ratio = VALUES(peak_ratio),
            mid_hours = VALUES(mid_hours),
            mid_ratio = VALUES(mid_ratio),
            low_hours = VALUES(low_hours),
            low_ratio = VALUES(low_ratio),
            updated_at = NOW()
    """), {
        "tenant_id": tenant_id,
        "shop_id": shop_id,
        "peak_hours": json.dumps(peak),
        "peak_ratio": peak_ratio,
        "mid_hours": json.dumps(mid),
        "mid_ratio": mid_ratio,
        "low_hours": json.dumps(low),
        "low_ratio": low_ratio,
    })
    db.commit()
    return {"code": 0}


def enable(db, tenant_id: int, shop_id: int) -> dict:
    """启用分时调价（FOR UPDATE 互斥校验 + 多租户隔离）"""
    time_row = db.execute(text("""
        SELECT id, is_active FROM time_pricing_rules
        WHERE shop_id = :shop_id AND tenant_id = :tenant_id
        FOR UPDATE
    """), {"shop_id": shop_id, "tenant_id": tenant_id}).fetchone()

    if not time_row:
        return {"code": ErrorCode.BID_TIME_RULE_NOT_FOUND, "msg": "分时调价规则不存在"}

    ai_row = db.execute(text("""
        SELECT id, is_active FROM ai_pricing_configs
        WHERE shop_id = :shop_id AND tenant_id = :tenant_id
        FOR UPDATE
    """), {"shop_id": shop_id, "tenant_id": tenant_id}).fetchone()

    if ai_row and ai_row.is_active:
        return {"code": ErrorCode.BID_CONFLICT_TIME_AI, "msg": "AI调价已启用，请先停用"}

    db.execute(text("""
        UPDATE time_pricing_rules SET is_active = 1, updated_at = NOW()
        WHERE shop_id = :shop_id AND tenant_id = :tenant_id
    """), {"shop_id": shop_id, "tenant_id": tenant_id})
    db.commit()
    return {"code": 0}


async def disable(db, tenant_id: int, shop_id: int) -> dict:
    """停用分时调价：
    1. 立刻 is_active=0，停掉 Celery executor
    2. 遍历所有 last_auto_bid IS NOT NULL 的 SKU → 调 Ozon API 恢复 original_bid
    3. 成功的清空 last_auto_bid + 写日志（execute_type='user_manual'）
    4. 失败的保留 last_auto_bid，让用户能在状态表里看到、手动 restore_sku 重试

    多租户隔离：所有 SQL 都带 tenant_id
    Returns: {code, data: {restored, failed, errors[]}}
    """
    from app.models.shop import Shop
    from app.services.bid.ai_pricing_executor import _create_platform_client, _execute_bid_update

    # 1. 先停 executor（避免回弹途中被并发执行覆盖）
    db.execute(text("""
        UPDATE time_pricing_rules SET is_active = 0, updated_at = NOW()
        WHERE shop_id = :shop_id AND tenant_id = :tenant_id
    """), {"shop_id": shop_id, "tenant_id": tenant_id})
    db.commit()

    shop = db.query(Shop).filter(
        Shop.id == shop_id, Shop.tenant_id == tenant_id
    ).first()
    if not shop:
        return {"code": ErrorCode.SHOP_NOT_FOUND, "msg": "店铺不存在"}

    # 2. 找出所有需要回弹的 SKU（不限平台）
    rows = db.execute(text("""
        SELECT
            ag.id, ag.platform_group_id, ag.original_bid, ag.last_auto_bid,
            c.id AS campaign_id, c.platform_campaign_id, c.platform,
            c.name AS campaign_name
        FROM ad_groups ag
        JOIN ad_campaigns c ON ag.campaign_id = c.id
        WHERE c.shop_id = :shop_id
          AND c.tenant_id = :tenant_id
          AND c.platform = :platform
          AND ag.last_auto_bid IS NOT NULL
          AND ag.original_bid IS NOT NULL
    """), {"shop_id": shop_id, "tenant_id": tenant_id, "platform": shop.platform}).fetchall()

    if not rows:
        return {"code": 0, "data": {"restored": 0, "failed": 0, "errors": []}}

    client = _create_platform_client(shop)

    restored = 0
    failed = 0
    errors: list[str] = []

    try:
        for row in rows:
            target_bid = max(round(float(row.original_bid)), int(MIN_BID))
            try:
                api_result = await _execute_bid_update(
                    client, row.platform, row.platform_campaign_id,
                    row.platform_group_id, target_bid,
                )
            except Exception as e:
                logger.warning(
                    f"disable 回弹 sku={row.platform_group_id} "
                    f"活动={row.campaign_id} 异常: {e}"
                )
                failed += 1
                errors.append(f"SKU {row.platform_group_id}: {e}")
                continue

            if not api_result.get("ok"):
                err_msg = api_result.get("error") or "unknown"
                logger.warning(
                    f"disable 回弹 sku={row.platform_group_id} "
                    f"活动={row.campaign_id} API失败: {err_msg}"
                )
                failed += 1
                errors.append(f"SKU {row.platform_group_id}: {err_msg}")
                continue

            # 写调价日志（execute_type='user_manual'，复用现有枚举）
            previous = float(row.last_auto_bid)
            pct = round((target_bid - previous) / previous * 100, 2) if previous > 0 else 0.0
            db.execute(text("""
                INSERT INTO bid_adjustment_logs (
                    tenant_id, shop_id, campaign_id, campaign_name,
                    platform_sku_id, sku_name,
                    old_bid, new_bid, adjust_pct,
                    execute_type, success, created_at
                ) VALUES (
                    :tenant_id, :shop_id, :campaign_id, :campaign_name,
                    :sku, NULL, :old_bid, :new_bid, :pct,
                    'user_manual', 1, NOW()
                )
            """), {
                "tenant_id": tenant_id,
                "shop_id": shop_id,
                "campaign_id": row.campaign_id,
                "campaign_name": row.campaign_name,
                "sku": row.platform_group_id,
                "old_bid": previous,
                "new_bid": target_bid,
                "pct": pct,
            })

            # 清空 last_auto_bid → 该行从"当前执行状态"消失
            db.execute(text("""
                UPDATE ad_groups SET last_auto_bid = NULL, updated_at = NOW()
                WHERE id = :id AND tenant_id = :tenant_id
            """), {"id": row.id, "tenant_id": tenant_id})

            restored += 1

        db.commit()
    finally:
        await client.close()

    return {
        "code": 0,
        "data": {
            "restored": restored,
            "failed": failed,
            "errors": errors[:10],  # 前端最多展示 10 条
        },
    }


async def restore_sku(db, tenant_id: int, shop_id: int, sku: str) -> dict:
    """单SKU恢复到 original_bid（遍历该 SKU 在所有活动里的所有 ad_group 都恢复）

    多租户：必须校验 c.tenant_id = :tenant_id
    #17 修复：不再 LIMIT 1，遍历所有匹配
    """
    from app.models.shop import Shop

    rows = db.execute(text("""
        SELECT
            ag.id, ag.platform_group_id, ag.original_bid,
            ag.user_managed, ag.last_auto_bid,
            c.id AS campaign_id, c.platform_campaign_id, c.name AS campaign_name,
            c.tenant_id, c.shop_id
        FROM ad_groups ag
        JOIN ad_campaigns c ON ag.campaign_id = c.id
        WHERE c.shop_id = :shop_id
          AND c.tenant_id = :tenant_id
          AND ag.platform_group_id = :sku
          AND ag.original_bid IS NOT NULL
    """), {"shop_id": shop_id, "tenant_id": tenant_id, "sku": sku}).fetchall()

    if not rows:
        return {"code": ErrorCode.LISTING_NOT_FOUND, "msg": "SKU或原始出价不存在"}

    shop = db.query(Shop).filter(
        Shop.id == shop_id, Shop.tenant_id == tenant_id
    ).first()
    if not shop:
        return {"code": ErrorCode.SHOP_NOT_FOUND, "msg": "店铺不存在"}

    from app.services.bid.ai_pricing_executor import _create_platform_client, _execute_bid_update
    client = _create_platform_client(shop)

    restored_count = 0
    last_target = 0
    last_previous = 0
    sku_name_returned = None

    try:
        for row in rows:
            target = max(round(float(row.original_bid)), 3)
            try:
                api_result = await _execute_bid_update(
                    client, shop.platform, row.platform_campaign_id,
                    row.platform_group_id, target,
                )
            except Exception as e:
                logger.warning(f"恢复 sku={sku} 活动={row.campaign_id} 失败: {e}")
                continue
            if not api_result.get("ok"):
                logger.warning(
                    f"恢复 sku={sku} 活动={row.campaign_id} API失败: {api_result.get('error')}"
                )
                continue

            previous = float(row.last_auto_bid or row.original_bid)
            db.execute(text("""
                INSERT INTO bid_adjustment_logs (
                    tenant_id, shop_id, campaign_id, campaign_name,
                    platform_sku_id, sku_name,
                    old_bid, new_bid, adjust_pct,
                    execute_type, success, created_at
                ) VALUES (
                    :tenant_id, :shop_id, :campaign_id, :campaign_name,
                    :sku, NULL, :old_bid, :new_bid,
                    :pct, 'user_manual', 1, NOW()
                )
            """), {
                "tenant_id": row.tenant_id,
                "shop_id": row.shop_id,
                "campaign_id": row.campaign_id,
                "campaign_name": row.campaign_name,
                "sku": row.platform_group_id,
                "old_bid": previous,
                "new_bid": target,
                "pct": round((target - previous) / previous * 100, 2) if previous > 0 else 0,
            })
            restored_count += 1
            last_target = target
            last_previous = previous
            sku_name_returned = sku_name_returned or row.platform_group_id
    finally:
        await client.close()

    db.commit()

    if restored_count == 0:
        return {"code": ErrorCode.BID_EXECUTION_FAILED, "msg": "Ozon API 全部调用失败"}

    return {
        "code": 0,
        "data": {
            "platform_sku_id": sku,
            "restored_bid": last_target,
            "previous_bid": last_previous,
            "restored_count": restored_count,
        }
    }


# ==================== 状态查询 ====================

async def get_sku_status(db, tenant_id: int, shop_id: int,
                         campaign_id: int = None, keyword: str = None) -> dict:
    """获取分时调价当前各 SKU 状态（按活动分组），多租户隔离

    语义：只返回真正被分时调价处理过的 SKU（last_auto_bid IS NOT NULL）。
    平谷期 / 从未执行过 / 店铺无活动 → 返回空 campaigns 列表。
    """
    rows = _query_status_rows(db, tenant_id, shop_id, campaign_id, keyword)
    groups = _rows_to_groups(rows)
    return {"campaigns": list(groups.values())}


def _query_status_rows(db, tenant_id, shop_id, campaign_id, keyword):
    """只查 last_auto_bid IS NOT NULL 的行 → 仅返回真正被分时调价处理过的 SKU。
    使用 INNER JOIN：未被处理过的活动不会出现在结果里。
    """
    where = [
        "c.shop_id = :shop_id",
        "c.tenant_id = :tenant_id",
        "c.platform IN ('ozon', 'wb')",
        "ag.last_auto_bid IS NOT NULL",
    ]
    params = {"shop_id": shop_id, "tenant_id": tenant_id}
    if campaign_id:
        where.append("c.id = :cid")
        params["cid"] = campaign_id
    if keyword:
        where.append("(c.name LIKE :kw OR ag.name LIKE :kw OR ag.platform_group_id LIKE :kw)")
        params["kw"] = f"%{keyword}%"

    where_sql = " AND ".join(where)
    return db.execute(text(f"""
        SELECT
            c.id AS campaign_id, c.name AS campaign_name, c.status AS campaign_status,
            ag.platform_group_id AS sku, ag.name AS sku_name,
            ag.original_bid, ag.bid AS current_bid, ag.last_auto_bid,
            ag.user_managed, ag.user_managed_at, ag.updated_at
        FROM ad_campaigns c
        JOIN ad_groups ag ON ag.campaign_id = c.id
            AND ag.platform_group_id IS NOT NULL
        WHERE {where_sql}
        ORDER BY c.name, ag.platform_group_id
    """), params).fetchall()


def _rows_to_groups(rows) -> dict:
    groups = {}
    for r in rows:
        cid = r.campaign_id
        if cid not in groups:
            groups[cid] = {
                "campaign_id": cid,
                "campaign_name": r.campaign_name,
                "campaign_status": r.campaign_status,
                "skus": [],
            }
        if r.sku:
            groups[cid]["skus"].append({
                "platform_sku_id": r.sku,
                "sku_name": r.sku_name,
                "original_bid": float(r.original_bid or r.last_auto_bid or r.current_bid or 0),
                "current_bid": float(r.last_auto_bid or r.current_bid or r.original_bid or 0),
                "last_auto_bid": float(r.last_auto_bid or 0),
                "period": None,
                "ratio": None,
                "user_managed": bool(r.user_managed),
                "last_adjusted_at": r.updated_at.isoformat() if r.updated_at else None,
            })
    return groups


# ==================== 内部工具 ====================

def _upsert_group(db, campaign, sku: str, sku_name: str,
                  base_bid: float, last_auto: float):
    """ad_groups upsert：first run 写 original_bid，每次更新 last_auto_bid"""
    db.execute(text("""
        INSERT INTO ad_groups (
            tenant_id, campaign_id, platform_group_id, name,
            original_bid, last_auto_bid, status
        ) VALUES (
            :tenant_id, :campaign_id, :sku, :name,
            :original, :last_auto, 'active'
        )
        ON DUPLICATE KEY UPDATE
            name = VALUES(name),
            original_bid = COALESCE(original_bid, VALUES(original_bid)),
            last_auto_bid = VALUES(last_auto_bid),
            updated_at = NOW()
    """), {
        "tenant_id": campaign.tenant_id,
        "campaign_id": campaign.id,
        "sku": sku,
        "name": sku_name[:200] if sku_name else f"SKU-{sku}",
        "original": base_bid,
        "last_auto": last_auto,
    })


def _write_log(db, campaign, sku: str, sku_name: str,
               old_bid: float, new_bid: float,
               execute_type: str, time_period: str = None, period_ratio: int = None,
               success: bool = True, error_msg: str = None):
    """写 bid_adjustment_logs（统一调价日志，新表）"""
    pct = 0.0
    if old_bid > 0:
        pct = round((new_bid - old_bid) / old_bid * 100, 2)
    db.execute(text("""
        INSERT INTO bid_adjustment_logs (
            tenant_id, shop_id, campaign_id, campaign_name,
            platform_sku_id, sku_name,
            old_bid, new_bid, adjust_pct,
            execute_type, time_period, period_ratio,
            moscow_hour, success, error_msg, created_at
        ) VALUES (
            :tenant_id, :shop_id, :campaign_id, :campaign_name,
            :sku, :sku_name,
            :old_bid, :new_bid, :pct,
            :execute_type, :period, :ratio,
            :hour, :success, :error_msg, NOW()
        )
    """), {
        "tenant_id": campaign.tenant_id,
        "shop_id": campaign.shop_id,
        "campaign_id": campaign.id,
        "campaign_name": campaign.name,
        "sku": sku,
        "sku_name": sku_name[:300] if sku_name else None,
        "old_bid": old_bid,
        "new_bid": new_bid,
        "pct": pct,
        "execute_type": execute_type,
        "period": time_period,
        "ratio": period_ratio,
        "hour": moscow_hour(),
        "success": 1 if success else 0,
        "error_msg": (error_msg or "")[:500] if error_msg else None,
    })


def _save_result(db, shop_id: int, tenant_id: int, counters: dict, summary: str):
    """保存最后一次执行结果摘要到 time_pricing_rules（多租户过滤）"""
    db.execute(text("""
        UPDATE time_pricing_rules
        SET last_executed_at = NOW(), last_execute_result = :summary
        WHERE shop_id = :shop_id AND tenant_id = :tenant_id
    """), {"shop_id": shop_id, "tenant_id": tenant_id, "summary": summary[:200]})
    db.commit()
