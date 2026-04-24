"""搜索词洞察业务逻辑（SEO 流量分析）

数据来源：product_search_queries 表（Celery 每日增量 + 手动 refresh）
接口：list_shop / list_product / refresh_shop

标签规则（基于店铺均值派生）：
  🔥 opportunity  —— 曝光 ≥ 店铺均值 1.5x 且未投广告（本店 ad_keywords 无此词）
  💎 high_convert —— orders/frequency 高于店铺均值 2x
  ⚠️ low_ctr     —— 曝光 ≥ 均值但 clicks/frequency < 店铺均值 0.3x
  normal         —— 其他
"""

from datetime import date, timedelta
from decimal import Decimal
from typing import Optional
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.platform.base import SubscriptionRequiredError
from app.services.platform.wb import (
    WBClient, WBSellerQuotaExhausted,
    _get_redis_client, quota_circuit_key_for_shop, quota_circuit_key_for_seller,
)
from app.services.platform.ozon import OzonClient
from app.utils.errors import ErrorCode
from app.utils.logger import logger
from app.utils.moscow_time import moscow_today


def _default_dates(date_from: Optional[str], date_to: Optional[str]):
    # 规则 6：业务"昨天/今天"判断一律 MSK，OS 切 UTC 后 date.today() 可能落到上一天
    if not date_to:
        date_to = (moscow_today() - timedelta(days=1)).isoformat()
    if not date_from:
        date_from = (date.fromisoformat(date_to) - timedelta(days=29)).isoformat()
    return date_from, date_to


def _float(v):
    if isinstance(v, Decimal):
        return float(v)
    return float(v) if v is not None else 0.0


def _tag_query(row: dict, avg_freq: float, avg_orders_per_freq: float, avg_clicks_per_freq: float,
               invested_keywords: set) -> tuple:
    """返回 (tag, invested) ，tag ∈ opportunity/high_convert/low_ctr/normal"""
    freq = row.get("frequency") or 0
    orders = row.get("orders") or 0
    clicks = row.get("clicks") or row.get("impressions") or 0  # WB 无 clicks 时用 openCard 代理
    invested = (row.get("query_text") or "").lower() in invested_keywords

    if freq >= avg_freq * 1.5 and not invested:
        return "opportunity", invested
    if freq > 0 and orders / max(freq, 1) >= avg_orders_per_freq * 2:
        return "high_convert", invested
    if freq >= avg_freq and clicks / max(freq, 1) < avg_clicks_per_freq * 0.3:
        return "low_ctr", invested
    return "normal", invested


def _load_invested_keywords(db: Session, tenant_id: int, shop_id: int) -> set:
    """查店铺下广告活动里已投放的关键词（小写归一化），用于判断"未投"机会词"""
    sql = """
        SELECT LOWER(ak.keyword) AS kw
        FROM ad_keywords ak
        JOIN ad_groups ag ON ag.id = ak.ad_group_id
        JOIN ad_campaigns ac ON ac.id = ag.campaign_id
        WHERE ac.tenant_id = :tid AND ac.shop_id = :sid
    """
    rows = db.execute(text(sql), {"tid": tenant_id, "sid": shop_id}).fetchall()
    return {r.kw for r in rows if r.kw}


def list_shop(
    db: Session, tenant_id: int, shop_id: int,
    date_from: str = None, date_to: str = None,
    tag: str = None, keyword: str = None,
    sort_by: str = "frequency", sort_order: str = "desc",
    page: int = 1, size: int = 50,
) -> dict:
    """店铺汇总：按 query_text 聚合多天 + 标签分类 + 分页

    响应：{totals, items, invested_count, uninvested_count}
    """
    date_from, date_to = _default_dates(date_from, date_to)
    params = {"tid": tenant_id, "sid": shop_id, "df": date_from, "dt": date_to}

    where = """WHERE tenant_id = :tid AND shop_id = :sid
               AND stat_date BETWEEN :df AND :dt"""
    if keyword:
        where += " AND query_text LIKE :kw"
        params["kw"] = f"%{keyword}%"

    # 聚合
    agg_sql = f"""
        SELECT query_text,
               SUM(frequency) AS frequency,
               SUM(impressions) AS impressions,
               SUM(clicks) AS clicks,
               SUM(add_to_cart) AS add_to_cart,
               SUM(orders) AS orders,
               SUM(revenue) AS revenue,
               AVG(median_position) AS median_position,
               COUNT(DISTINCT platform_sku_id) AS sku_count
        FROM product_search_queries
        {where}
        GROUP BY query_text
    """
    rows = db.execute(text(agg_sql), params).fetchall()
    items = [{
        "query_text": r.query_text,
        "frequency": int(r.frequency or 0),
        "impressions": int(r.impressions or 0),
        "clicks": int(r.clicks or 0),
        "add_to_cart": int(r.add_to_cart or 0),
        "orders": int(r.orders or 0),
        "revenue": _float(r.revenue),
        "median_position": _float(r.median_position) or None,
        "sku_count": int(r.sku_count or 0),
    } for r in rows]

    # 总览
    total_freq = sum(i["frequency"] for i in items)
    total_clk = sum(i["clicks"] for i in items)
    total_orders = sum(i["orders"] for i in items)
    total_revenue = sum(i["revenue"] for i in items)
    n = len(items) or 1
    avg_freq = total_freq / n
    avg_orders_per_freq = (total_orders / total_freq) if total_freq > 0 else 0
    avg_clicks_per_freq = (total_clk / total_freq) if total_freq > 0 else 0

    # 标签
    invested_set = _load_invested_keywords(db, tenant_id, shop_id)
    for it in items:
        t, inv = _tag_query(it, avg_freq, avg_orders_per_freq, avg_clicks_per_freq, invested_set)
        it["tag"] = t
        it["invested"] = inv

    # tag 过滤
    if tag and tag in {"opportunity", "high_convert", "low_ctr", "normal", "invested", "uninvested"}:
        if tag == "invested":
            items = [i for i in items if i["invested"]]
        elif tag == "uninvested":
            items = [i for i in items if not i["invested"]]
        else:
            items = [i for i in items if i["tag"] == tag]

    # 排序
    allowed_sorts = {"frequency", "impressions", "clicks", "add_to_cart", "orders", "revenue"}
    sort_col = sort_by if sort_by in allowed_sorts else "frequency"
    items.sort(key=lambda x: x.get(sort_col, 0), reverse=(sort_order == "desc"))

    # 分页
    total = len(items)
    start = (page - 1) * size
    paged = items[start:start + size]

    return {
        "code": 0,
        "data": {
            "totals": {
                "query_count": total,
                "frequency": total_freq,
                "clicks": total_clk,
                "orders": total_orders,
                "revenue": round(total_revenue, 2),
                "date_from": date_from,
                "date_to": date_to,
            },
            "items": paged,
            "total": total,
            "page": page,
            "size": size,
        },
    }


def list_by_product(
    db: Session, tenant_id: int, product_id: int,
    date_from: str = None, date_to: str = None,
    page: int = 1, size: int = 50,
) -> dict:
    """单商品维度：返回该商品被哪些词搜到。

    用于编辑 Drawer 的"搜索词洞察" Tab，结果不做标签分类
    （单品视角关心的是词本身+频次，不是店铺相对热度）。

    防御：JOIN products 强制 q.shop_id = p.shop_id，防 product_search_queries
    被错误 shop_id 写入时的跨店数据泄漏。
    """
    date_from, date_to = _default_dates(date_from, date_to)

    # 先校验 product 属租户
    row = db.execute(text(
        "SELECT id, shop_id FROM products WHERE id = :pid AND tenant_id = :tid"
    ), {"pid": product_id, "tid": tenant_id}).fetchone()
    if not row:
        return {"code": ErrorCode.PRODUCT_NOT_FOUND, "msg": "商品不存在或无访问权限"}

    agg_sql = """
        SELECT q.query_text,
               SUM(q.frequency) AS frequency,
               SUM(q.impressions) AS impressions,
               SUM(q.clicks) AS clicks,
               SUM(q.add_to_cart) AS add_to_cart,
               SUM(q.orders) AS orders,
               SUM(q.revenue) AS revenue,
               AVG(q.median_position) AS median_position
        FROM product_search_queries q
        JOIN products p ON p.id = q.product_id
                       AND p.tenant_id = q.tenant_id
                       AND p.shop_id = q.shop_id
        WHERE q.tenant_id = :tid AND q.product_id = :pid
          AND q.stat_date BETWEEN :df AND :dt
        GROUP BY q.query_text
        ORDER BY frequency DESC
        LIMIT :size OFFSET :offset
    """
    rows = db.execute(text(agg_sql), {
        "tid": tenant_id, "pid": product_id,
        "df": date_from, "dt": date_to,
        "size": size, "offset": (page - 1) * size,
    }).fetchall()

    items = [{
        "query_text": r.query_text,
        "frequency": int(r.frequency or 0),
        "impressions": int(r.impressions or 0),
        "clicks": int(r.clicks or 0),
        "add_to_cart": int(r.add_to_cart or 0),
        "orders": int(r.orders or 0),
        "revenue": _float(r.revenue),
        "median_position": _float(r.median_position) or None,
    } for r in rows]

    return {
        "code": 0,
        "data": {
            "product_id": product_id,
            "date_from": date_from,
            "date_to": date_to,
            "items": items,
            "page": page,
            "size": size,
        },
    }


def _upsert_rows(db: Session, tenant_id: int, shop_id: int, platform: str,
                 platform_sku_id: str, product_id: Optional[int], stat_date: str,
                 rows: list) -> int:
    """批量 upsert 到 product_search_queries。返回写入行数。

    规则 1 纵深：INSERT 带 tenant_id，ON DUPLICATE KEY UPDATE 也 SET tenant_id
    （CLAUDE.md 明文要求"哪怕 UNIQUE KEY 是 shop_id 也务必 SET tenant_id"）。
    """
    if not rows:
        return 0
    sql = text("""
        INSERT INTO product_search_queries
          (tenant_id, shop_id, platform, platform_sku_id, product_id,
           query_text, stat_date, frequency, impressions, clicks,
           add_to_cart, orders, revenue, median_position, cart_to_order,
           view_conversion, extra)
        VALUES
          (:tid, :sid, :plat, :psk, :pid,
           :qt, :sd, :freq, :imp, :clk,
           :atc, :orders, :rev, :mp, :c2o,
           :vc, :ex)
        ON DUPLICATE KEY UPDATE
          tenant_id = VALUES(tenant_id),
          frequency = VALUES(frequency),
          impressions = VALUES(impressions),
          clicks = VALUES(clicks),
          add_to_cart = VALUES(add_to_cart),
          orders = VALUES(orders),
          revenue = VALUES(revenue),
          median_position = VALUES(median_position),
          cart_to_order = VALUES(cart_to_order),
          view_conversion = VALUES(view_conversion),
          extra = VALUES(extra)
    """)
    import json
    count = 0
    for r in rows:
        text_ = r.get("text") or r.get("query") or ""
        if not text_:
            continue
        extra = r.get("extra")
        db.execute(sql, {
            "tid": tenant_id, "sid": shop_id, "plat": platform,
            "psk": str(platform_sku_id), "pid": product_id,
            "qt": text_[:500], "sd": stat_date,
            "freq": int(r.get("frequency") or 0),
            "imp": int(r.get("open_card") or r.get("impressions") or 0),
            "clk": int(r.get("clicks") or 0),
            "atc": int(r.get("add_to_cart") or 0),
            "orders": int(r.get("orders") or 0),
            "rev": float(r.get("revenue") or 0),
            "mp": r.get("median_position"),
            "c2o": r.get("cart_to_order"),
            "vc": r.get("view_conversion"),
            "ex": json.dumps(extra, ensure_ascii=False) if extra else None,
        })
        count += 1
    db.commit()
    return count


async def refresh_shop(
    db: Session, tenant_id: int, shop, days: int = 7,
) -> dict:
    """手动触发：按 shop 拉近 N 天搜索词数据 → 写入 product_search_queries

    规则 4：必须按 shop_id 单店铺触发；shop 由路由层 get_owned_shop 校验属租户。
    未开通订阅时返回 93001，调用方前端显示友好提示。
    """
    if shop.platform not in ("wb", "ozon"):
        return {"code": ErrorCode.PARAM_ERROR, "msg": "该平台暂不支持搜索词洞察"}

    # 规则 6：MSK 今天（OS 切 UTC 后 date.today() 可能跨日偏移）
    today = moscow_today()
    date_from = (today - timedelta(days=days + 1)).isoformat()
    date_to = (today - timedelta(days=2)).isoformat()

    # 拉取租户+店铺下的 listing（带 product_id 映射）
    # 规则 1 纵深：pl + p 双表都带 tenant_id
    listings_sql = text("""
        SELECT pl.platform_sku_id AS psk, pl.product_id AS pid
        FROM platform_listings pl
        JOIN products p ON p.id = pl.product_id
        WHERE pl.tenant_id = :tid AND pl.shop_id = :sid AND pl.platform = :plat
          AND p.tenant_id = :tid AND pl.platform_sku_id IS NOT NULL
          AND (p.status NOT IN ('deleted') OR p.status IS NULL)
    """)
    listings = db.execute(listings_sql, {
        "sid": shop.id, "plat": shop.platform, "tid": tenant_id,
    }).fetchall()
    if not listings:
        return {"code": 0, "data": {"shop_id": shop.id, "synced_queries": 0,
                                    "msg": "店铺下无商品，跳过"}}

    total_rows = 0
    errors = []

    if shop.platform == "wb":
        import asyncio
        # WB seller quota 熔断 pre-check（2026-04-23 晚老林 review 驱动）：
        # quota 是 per-seller-per-endpoint-group 共享池，写端点烧光读端点也 429。
        # 2026-04-24 ab895eb 后 key 主走 seller_{uuid}（同 seller 多 shop 共享冷却），
        # 历史 shop_{id} key 仅作 fallback。两个 key 任一命中就 skip。
        try:
            r = _get_redis_client()
            cooldown = 0
            seller_id = (getattr(shop, "platform_seller_id", None) or "").strip() or None
            if seller_id:
                ttl_seller = r.ttl(quota_circuit_key_for_seller(seller_id))
                if ttl_seller and ttl_seller > 0:
                    cooldown = ttl_seller
            if not cooldown:
                ttl_shop = r.ttl(quota_circuit_key_for_shop(shop.id))
                if ttl_shop and ttl_shop > 0:
                    cooldown = ttl_shop
        except Exception as e:
            logger.warning(f"WB quota circuit pre-check Redis err: {e}")
            cooldown = 0
        if cooldown and cooldown > 0:
            logger.info(
                f"WB seller quota cooldown shop={shop.id} ttl={cooldown}s, skip refresh"
            )
            return {
                "code": 0,
                "data": {
                    "shop_id": shop.id, "synced_queries": 0,
                    "skipped": True, "reason": "wb_seller_quota_cooldown",
                    "cooldown_seconds": int(cooldown),
                    "msg": f"WB seller quota 冷却中，约 {cooldown}s 后自动恢复",
                },
            }

        # WB search-texts 端点实测限流严格（估 3-5 rpm），批量 nmIds 降低调用次数
        # 2026-04-23：WB 对单次 nmIds 数量上限未文档化，保守取 20
        WB_BATCH_SIZE = 20          # 单次调用 nmIds 个数上限
        WB_BATCH_PAUSE_S = 20       # 批间 sleep 秒，抵御 429
        # 2026-04-23 实战：WB 触发 "global limiter per seller" 后整个任务周期挡死，
        # 连续 3 批全空 = quota 耗尽，early exit 避免 30 批 × 20s = 10min 空跑
        EMPTY_BATCH_ABORT = 3

        nm_to_pid = {}
        for l in listings:
            if str(l.psk).isdigit():
                nm_to_pid[int(l.psk)] = l.pid
        all_nm_ids = list(nm_to_pid.keys())
        batches_total = (len(all_nm_ids) + WB_BATCH_SIZE - 1) // WB_BATCH_SIZE

        consecutive_empty = 0
        wb = WBClient(shop_id=shop.id, api_key=shop.api_key)
        try:
            for bi in range(batches_total):
                batch = all_nm_ids[bi * WB_BATCH_SIZE : (bi + 1) * WB_BATCH_SIZE]
                if bi > 0:
                    await asyncio.sleep(WB_BATCH_PAUSE_S)
                try:
                    items = await wb.fetch_product_search_texts(
                        nm_ids=batch, date_from=date_from, date_to=date_to,
                    )
                except SubscriptionRequiredError as e:
                    return {
                        "code": ErrorCode.SEARCH_INSIGHTS_SUBSCRIPTION_REQUIRED,
                        "msg": f"WB 店铺未开通 Jam 订阅：{e.detail[:80]}",
                    }
                except WBSellerQuotaExhausted as e:
                    # 跑到一半被上游端点（AI 调价/PATCH bids）触发熔断 → 立即 break，
                    # 不要 continue 再 sleep 20s 重试 N 批白烧。
                    logger.info(
                        f"WB quota tripped mid-refresh shop={shop.id} batch={bi+1}/{batches_total}: {e}"
                    )
                    errors.append({"type": "quota", "quota_exhausted": True,
                                   "at_batch": bi + 1, "reason": str(e)[:200]})
                    break
                except Exception as e:
                    errors.append({"type": "batch_error",
                                   "batch": batch[:3], "error": str(e)[:200]})
                    logger.warning(f"WB fetch_product_search_texts batch={len(batch)} 失败: {e}")
                    continue
                if not items:
                    consecutive_empty += 1
                    if consecutive_empty >= EMPTY_BATCH_ABORT:
                        logger.warning(
                            f"WB 连续 {EMPTY_BATCH_ABORT} 批返回空（疑似 global limiter 触发 quota 耗尽），"
                            f"已完成 {bi + 1}/{batches_total} 批，early exit 节省时间"
                        )
                        errors.append({"type": "early_exit", "early_exit": True,
                                       "reason": f"{EMPTY_BATCH_ABORT} 批连续空（WB 限流/quota）"})
                        break
                else:
                    consecutive_empty = 0
                # items 每条含 nm_id → 按 nm_id 分组 upsert
                grouped = {}
                for it in items or []:
                    nm = it.get("nm_id")
                    if nm is None:
                        continue
                    grouped.setdefault(int(nm), []).append(it)
                for nm_id, rows in grouped.items():
                    pid = nm_to_pid.get(nm_id)
                    total_rows += _upsert_rows(
                        db, tenant_id, shop.id, "wb",
                        str(nm_id), pid, date_to, rows,
                    )
        finally:
            await wb.close()

    elif shop.platform == "ozon":
        oz = OzonClient(shop_id=shop.id, api_key=shop.api_key,
                        client_id=getattr(shop, "client_id", None))
        try:
            # 正向映射：传入的 sku (=platform_sku_id) → product_id
            sku_to_pid = {str(l.psk): l.pid for l in listings if l.psk}
            all_skus = list(sku_to_pid.keys())

            # 反查兜底：Ozon 返回的 sku 可能是"平台全局 SKU"，与 platform_sku_id /
            # platform_product_id 都不一定相等。补一张全 platform_* 字段映射表。
            fallback_sql = text("""
                SELECT pl.platform_sku_id AS psk, pl.platform_product_id AS ppd,
                       pl.product_id AS pid
                FROM platform_listings pl
                WHERE pl.shop_id = :sid AND pl.platform = 'ozon'
                  AND pl.tenant_id = :tid
            """)
            fallback_rows = db.execute(
                fallback_sql, {"sid": shop.id, "tid": tenant_id}
            ).fetchall()
            pid_lookup = {}
            for r in fallback_rows:
                if r.psk:
                    pid_lookup[str(r.psk)] = r.pid
                if r.ppd:
                    pid_lookup.setdefault(str(r.ppd), r.pid)

            for i in range(0, len(all_skus), 50):
                batch = all_skus[i:i + 50]
                try:
                    items = await oz.fetch_product_queries_details(
                        skus=batch, date_from=date_from, date_to=date_to,
                    )
                except SubscriptionRequiredError as e:
                    return {
                        "code": ErrorCode.SEARCH_INSIGHTS_SUBSCRIPTION_REQUIRED,
                        "msg": f"Ozon 店铺未开通 Premium 订阅：{e.detail[:80]}",
                    }
                except Exception as e:
                    errors.append({"type": "batch_error",
                                   "skus": batch[:5], "error": str(e)[:200]})
                    logger.warning(f"Ozon fetch_product_queries_details batch={len(batch)} 失败: {e}")
                    continue
                # 按 sku 分组写入；product_id 反查不到就留 NULL（不阻塞写入）
                grouped = {}
                for it in items or []:
                    grouped.setdefault(it.get("sku"), []).append(it)
                for sku, rows in grouped.items():
                    sku_str = str(sku)
                    pid = sku_to_pid.get(sku_str) or pid_lookup.get(sku_str)
                    total_rows += _upsert_rows(
                        db, tenant_id, shop.id, "ozon",
                        sku_str, pid, date_to,
                        [{"text": r.get("query"), **r} for r in rows],
                    )
        finally:
            await oz.close()

    return {
        "code": 0,
        "data": {
            "shop_id": shop.id,
            "platform": shop.platform,
            "synced_queries": total_rows,
            "date_range": f"{date_from} ~ {date_to}",
            "errors": errors or None,
        },
    }
