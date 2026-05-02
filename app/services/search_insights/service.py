"""搜索词洞察业务逻辑（SEO 流量分析）

数据来源：product_search_queries 表（Celery 每日增量 + 手动 refresh）
接口：list_shop / list_product / refresh_shop

标签规则（基于店铺均值派生）：
  🔥 opportunity  —— 曝光 ≥ 店铺均值 1.5x 且未投广告（本店 ad_keywords 无此词）
  💎 high_convert —— orders/frequency 高于店铺均值 2x
  ⚠️ low_ctr     —— 曝光 ≥ 均值但 clicks/frequency < 店铺均值 0.3x
  normal         —— 其他
"""

import asyncio
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


def list_shop(
    db: Session, tenant_id: int, shop_id: int,
    date_from: str = None, date_to: str = None,
    tag: str = None, keyword: str = None,  # tag 参数保留以兼容旧调用，已不再使用
    sort_by: str = "frequency", sort_order: str = "desc",
    page: int = 1, size: int = 50,
) -> dict:
    """店铺汇总：按 query_text 跨 (sku, day) 聚合 + 分页

    2026-04-26 重构后语义：
    - Ozon: 每条 stat_date 是 1 天真实数据（refresh_shop 按天补缺失），
      跨日 SUM 等于真实 N 天总量
    - WB: 仍为 N 天聚合（API 限流没法按天拉），跨日 SUM 会有重叠偏差，
      但 WB quota 静默期暂无新数据，偏差有限。WB quota 恢复后再迁移。
    前端 `date_from / date_to` 决定回看几天，默认 30 天。
    """
    date_from, date_to = _default_dates(date_from, date_to)
    params = {"tid": tenant_id, "sid": shop_id, "df": date_from, "dt": date_to}

    where = """WHERE tenant_id = :tid AND shop_id = :sid
               AND stat_date BETWEEN :df AND :dt"""
    if keyword:
        where += " AND query_text LIKE :kw"
        params["kw"] = f"%{keyword}%"

    # 2026-05-02 修：frequency 不能直接 SUM 跨 (sku, day) — 同一关键词同一天
    # 不同 SKU 行存的 frequency 是相同的"平台总搜索数"（per-keyword-per-day），
    # 直接 SUM 等于膨胀 N 倍（N = 该天命中 SKU 数）。
    # 跟 c12a996 修店级 TOP 同款 bug，同款修法：先 (query, date) MAX 去重再 SUM 跨天。
    # 其他指标（impressions/clicks/orders/revenue）是 per-(sku,day) 真分项，
    # 跨 (sku, day) SUM 正确，保持原写法。
    agg_sql = f"""
        SELECT main.query_text,
               COALESCE(freq.frequency, 0) AS frequency,
               main.impressions, main.clicks, main.add_to_cart, main.orders, main.revenue,
               main.median_position, main.sku_count, main.day_count
        FROM (
            SELECT query_text,
                   SUM(impressions) AS impressions,
                   SUM(clicks) AS clicks,
                   SUM(add_to_cart) AS add_to_cart,
                   SUM(orders) AS orders,
                   SUM(revenue) AS revenue,
                   AVG(median_position) AS median_position,
                   COUNT(DISTINCT platform_sku_id) AS sku_count,
                   COUNT(DISTINCT stat_date) AS day_count
            FROM product_search_queries
            {where}
            GROUP BY query_text
        ) main
        LEFT JOIN (
            SELECT query_text, SUM(daily_freq) AS frequency
            FROM (
                SELECT query_text, stat_date,
                       MAX(frequency) AS daily_freq
                FROM product_search_queries
                {where}
                GROUP BY query_text, stat_date
            ) t
            GROUP BY query_text
        ) freq ON freq.query_text = main.query_text
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
        "day_count": int(r.day_count or 0),
    } for r in rows]

    total_freq = sum(i["frequency"] for i in items)
    total_clk = sum(i["clicks"] for i in items)
    total_orders = sum(i["orders"] for i in items)
    total_revenue = sum(i["revenue"] for i in items)

    # 查范围内实际覆盖的天数（用于前端展示"数据覆盖 N 天 / N 天"）
    cover_row = db.execute(text("""
        SELECT COUNT(DISTINCT stat_date) AS days_covered,
               MIN(stat_date) AS first_day, MAX(stat_date) AS last_day
        FROM product_search_queries
        WHERE tenant_id = :tid AND shop_id = :sid
          AND stat_date BETWEEN :df AND :dt
    """), {"tid": tenant_id, "sid": shop_id, "df": date_from, "dt": date_to}).fetchone()

    allowed_sorts = {"frequency", "impressions", "clicks", "add_to_cart", "orders", "revenue"}
    sort_col = sort_by if sort_by in allowed_sorts else "frequency"
    items.sort(key=lambda x: x.get(sort_col, 0), reverse=(sort_order == "desc"))

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
                "days_covered": int(cover_row.days_covered or 0) if cover_row else 0,
                "first_day": str(cover_row.first_day) if cover_row and cover_row.first_day else None,
                "last_day": str(cover_row.last_day) if cover_row and cover_row.last_day else None,
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

    # 跨日 SUM（refresh_shop 按天补缺失模式后，每条 stat_date 是 1 天真实数据）
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


REFRESH_LOCK_TTL = 600  # 单店同步进行中锁 TTL（秒），覆盖 WB 单店 ~3min 实测峰值


def _refresh_lock_key(shop_id: int) -> str:
    return f"search_insights:refresh_lock:shop_{shop_id}"


async def refresh_shop(
    db: Session, tenant_id: int, shop, days: int = 7, force: bool = False,
) -> dict:
    """手动触发：按 shop 拉近 N 天搜索词数据 → 写入 product_search_queries

    规则 4：必须按 shop_id 单店铺触发；shop 由路由层 get_owned_shop 校验属租户。
    未开通订阅时返回 93001，调用方前端显示友好提示。

    模式（2026-04-28 起 WB/Ozon 双平台统一为"按天补缺失"）：
    - 计算窗口 [start_date, end_date]，查 DB 已有的 stat_date
    - 只对缺失的天调 API（每个 stat_date 装"那一天的真实数字"，非 N 天聚合）
    - 跨日 SUM = 真实 N 天总量, list_shop 按 days 切换不会膨胀也不会双计
    - force=True 时清掉窗口内已有重拉

    幂等保护：
    1. Redis SETNX in-progress 锁：连点 3 次只跑第 1 次
    2. WB seller quota pre-check（per-seller-per-endpoint 共享池冷却中直接 skip）
    3. missing_dates 为 0 直接返"已是最新"
    """
    if shop.platform not in ("wb", "ozon"):
        return {"code": ErrorCode.PARAM_ERROR, "msg": "该平台暂不支持搜索词洞察"}

    # 规则 6：MSK 今天（OS 切 UTC 后 date.today() 可能跨日偏移）
    today = moscow_today()
    date_from = (today - timedelta(days=days + 1)).isoformat()
    date_to = (today - timedelta(days=2)).isoformat()

    # —— 幂等保护 1：In-progress 锁（防连点 3 次并发烧 quota）——
    redis_client = None
    lock_key = _refresh_lock_key(shop.id)
    try:
        redis_client = _get_redis_client()
        # SETNX：仅当 key 不存在时设置，TTL 防 worker crash 死锁
        acquired = redis_client.set(lock_key, "1", nx=True, ex=REFRESH_LOCK_TTL)
        if not acquired:
            ttl = redis_client.ttl(lock_key) or REFRESH_LOCK_TTL
            logger.info(f"refresh_shop shop={shop.id} 已有同步进行中，跳过（剩余 {ttl}s）")
            return {
                "code": 0,
                "data": {
                    "shop_id": shop.id, "synced_queries": 0,
                    "skipped": True, "reason": "another_refresh_running",
                    "lock_ttl_seconds": int(ttl),
                    "msg": f"另一个同步任务正在运行中，约 {ttl}s 后可重试",
                },
            }
    except Exception as e:
        logger.warning(f"refresh_shop redis lock 获取失败 shop={shop.id}: {e}")
        redis_client = None  # 降级：Redis 不可用时不阻塞业务

    # WB 跟 Ozon 现在都走"按天补缺失"模式 —— 幂等检查在分支内做（看 missing_dates）

    # —— 主流程 try/finally：保证 lock 在所有 return 路径都释放 ——
    try:
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
            # —— 2026-04-28 重构：按天补缺失模式（参考 Ozon 写法）——
            # 实测 WB /api/v2/search-report/product/search-texts 接受 currentPeriod
            # start=end 单日窗口，所以 stat_date 装"那一天的真实数字"非 N 天聚合。
            # 跨日 SUM = 真实 N 天总量,list_shop 可任意 days 切换不膨胀 / 不双计。
            # end_date = today-2: WB 没保护期, today-2 OK
            end_date = today - timedelta(days=2)
            start_date = end_date - timedelta(days=days - 1)

            # WB seller quota 熔断 pre-check（quota 是 per-seller-per-endpoint-group 共享池，
            # 写端点烧光读端点也 429。key 主走 seller_{uuid}，老 shop_{id} 作 fallback）
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

            # 1. 查 DB 已有的 stat_date
            existing_rows = db.execute(text("""
                SELECT DISTINCT stat_date FROM product_search_queries
                WHERE tenant_id = :tid AND shop_id = :sid AND platform = 'wb'
                  AND stat_date BETWEEN :sd AND :ed
            """), {"tid": tenant_id, "sid": shop.id,
                   "sd": start_date, "ed": end_date}).fetchall()
            existing_dates = {r.stat_date for r in existing_rows}

            # 2. force=True：清掉窗口内已有重拉；否则只补缺失
            if force and existing_dates:
                db.execute(text("""
                    DELETE FROM product_search_queries
                    WHERE tenant_id = :tid AND shop_id = :sid AND platform = 'wb'
                      AND stat_date BETWEEN :sd AND :ed
                """), {"tid": tenant_id, "sid": shop.id,
                       "sd": start_date, "ed": end_date})
                db.commit()
                existing_dates = set()
                logger.info(f"force=True WB shop={shop.id} 已清窗口内 {len(existing_rows)} 行准备重拉")

            # 3. 计算缺失天列表
            missing_dates = []
            d = start_date
            while d <= end_date:
                if d not in existing_dates:
                    missing_dates.append(d)
                d += timedelta(days=1)

            if not missing_dates:
                return {
                    "code": 0,
                    "data": {
                        "shop_id": shop.id, "synced_queries": 0,
                        "skipped": True, "reason": "no_missing_dates",
                        "existing_dates": [str(x) for x in sorted(existing_dates)],
                        "msg": f"[{start_date}, {end_date}] 范围内 {len(existing_dates)} 天已有数据，无缺失",
                    },
                }

            logger.info(
                f"WB shop={shop.id} 按天补齐 missing={len(missing_dates)} 天 "
                f"(已有 {len(existing_dates)} 天) 范围[{start_date}, {end_date}]"
            )

            # 4. 按天循环 + 内层 nm_id 分批
            # WB search-texts 实测限流严格（估 3-5 rpm），批量 nmIds 降低调用次数
            WB_BATCH_SIZE = 20          # 单次调用 nmIds 个数上限
            WB_BATCH_PAUSE_S = 20       # 批间 sleep 秒，抵御 429
            EMPTY_DAYS_ABORT = 3        # 连续 N 整天 0 行 → 推断 quota 真烧光，整体退出
            # —— 2026-05-02 silent rate-limit detector（老林拍业务层方案）——
            # WB 第二种限流物种：HTTP 200 + 0 行 + 无 429 + Redis 静默；
            # 04-28 那套 trip cooldown 抓不到，必须看 input/output ratio。
            # 文档：memory/reference_wb_silent_rate_limit.md
            WB_SILENT_BATCH_THRESHOLD = 3   # 连续 N 批 0 行 → 进入 silent 模式
            WB_SILENT_PAUSE_S = 120         # silent 模式下批间 sleep（30 → 120s 退避）
            WB_SILENT_DAY_TRIGGER_LIMIT = 5  # 当天 silent 触发累计 N 次 → 放弃当天

            nm_to_pid = {}
            for l in listings:
                if str(l.psk).isdigit():
                    nm_to_pid[int(l.psk)] = l.pid
            all_nm_ids = list(nm_to_pid.keys())
            batches_per_day = (len(all_nm_ids) + WB_BATCH_SIZE - 1) // WB_BATCH_SIZE

            synced_per_day = {}
            consecutive_empty_days = 0  # 跨天累计：当天 0 行 +1，写入 reset
            quota_break = False
            wb = WBClient(shop_id=shop.id, api_key=shop.api_key)
            try:
                for d in missing_dates:
                    if quota_break:
                        break
                    # 单天 reset（silent_mode/trigger 不跨天累计：晚上的 silent 跟今早的没关系）
                    consecutive_empty = 0
                    silent_mode = False
                    silent_day_triggers = 0
                    d_str = d.isoformat()
                    day_total = 0
                    day_silent_aborted = False
                    for bi in range(batches_per_day):
                        batch = all_nm_ids[bi * WB_BATCH_SIZE : (bi + 1) * WB_BATCH_SIZE]
                        # 批间 + 跨天都要 sleep 抵御 429；silent 模式下 30s → 120s 退避
                        pause_s = WB_SILENT_PAUSE_S if silent_mode else WB_BATCH_PAUSE_S
                        if bi > 0 or d != missing_dates[0]:
                            await asyncio.sleep(pause_s)
                        try:
                            items = await wb.fetch_product_search_texts(
                                nm_ids=batch,
                                date_from=d_str, date_to=d_str,  # 单日窗口
                            )
                        except SubscriptionRequiredError as e:
                            return {
                                "code": ErrorCode.SEARCH_INSIGHTS_SUBSCRIPTION_REQUIRED,
                                "msg": f"WB 店铺未开通 Jam 订阅：{e.detail[:80]}",
                            }
                        except WBSellerQuotaExhausted as e:
                            logger.info(
                                f"WB quota tripped mid-refresh shop={shop.id} "
                                f"date={d_str} batch={bi+1}/{batches_per_day}: {e}"
                            )
                            errors.append({"type": "quota", "quota_exhausted": True,
                                           "date": d_str, "at_batch": bi + 1,
                                           "reason": str(e)[:200]})
                            quota_break = True
                            break
                        except Exception as e:
                            errors.append({"type": "batch_error", "date": d_str,
                                           "batch": batch[:3], "error": str(e)[:200]})
                            logger.warning(
                                f"WB shop={shop.id} date={d_str} batch={len(batch)} 失败: {e}"
                            )
                            continue
                        if not items:
                            consecutive_empty += 1
                            # silent rate-limit detector：连续 N 批 0 行 → 进入 silent 模式
                            # 不直接 break 当天（区别于旧 EMPTY_BATCH_ABORT），先延长 sleep 试试
                            if consecutive_empty >= WB_SILENT_BATCH_THRESHOLD:
                                silent_day_triggers += 1
                                consecutive_empty = 0  # 计数后 reset，避免每批都触发
                                if not silent_mode:
                                    silent_mode = True
                                    logger.warning(
                                        f"WB silent rate-limit suspected shop={shop.id} "
                                        f"date={d_str} batch={bi+1}/{batches_per_day} "
                                        f"连续 {WB_SILENT_BATCH_THRESHOLD} 批 0 行，进入 silent 模式 "
                                        f"(sleep {WB_BATCH_PAUSE_S}→{WB_SILENT_PAUSE_S}s)"
                                    )
                                else:
                                    logger.warning(
                                        f"WB silent rate-limit re-triggered shop={shop.id} "
                                        f"date={d_str} batch={bi+1} silent_count={silent_day_triggers}"
                                    )
                                errors.append({
                                    "type": "silent_rate_limit",
                                    "silent_quota": True,
                                    "date": d_str, "at_batch": bi + 1,
                                    "trigger_count": silent_day_triggers,
                                    "input_nm_ids": len(all_nm_ids),
                                    "returned_rows_so_far": day_total,
                                })
                                # 当天累计 silent 触发达限 → 放弃当天（不自动重试，清晰报告）
                                if silent_day_triggers >= WB_SILENT_DAY_TRIGGER_LIMIT:
                                    logger.warning(
                                        f"WB silent rate-limit confirmed shop={shop.id} "
                                        f"date={d_str}: 当天累计 {silent_day_triggers} 次 silent "
                                        f"触发，放弃当天 (批 {bi+1}/{batches_per_day})"
                                    )
                                    errors.append({
                                        "type": "silent_rate_limit_day_abort",
                                        "silent_quota": True,
                                        "date": d_str,
                                        "trigger_count": silent_day_triggers,
                                    })
                                    day_silent_aborted = True
                                    break  # 退当天 inner loop
                        else:
                            # 拿到数据：退出 silent 模式
                            if silent_mode:
                                logger.info(
                                    f"WB silent mode exited shop={shop.id} date={d_str} "
                                    f"batch={bi+1} 拿到 {len(items)} 行，恢复正常 sleep"
                                )
                                silent_mode = False
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
                            day_total += _upsert_rows(
                                db, tenant_id, shop.id, "wb",
                                str(nm_id), pid, d_str, rows,
                            )
                    synced_per_day[d_str] = day_total
                    total_rows += day_total

                    # 跨天兜底（保留）：连续 N 整天 0 行 → 整体退出
                    # silent 当天放弃也算"当天 0 行"，会进这个累计；如果连续 3 天全被 silent
                    # 限制，停手等下个 beat
                    if day_total == 0:
                        consecutive_empty_days += 1
                        if consecutive_empty_days >= EMPTY_DAYS_ABORT:
                            reason = (
                                f"{consecutive_empty_days} 整天连续 0 行"
                                + ("（含 silent rate-limit）" if day_silent_aborted else "")
                            )
                            logger.warning(
                                f"WB shop={shop.id} {reason}，整体 early exit"
                            )
                            errors.append({"type": "early_exit", "early_exit": True,
                                           "reason": reason})
                            quota_break = True
                    else:
                        consecutive_empty_days = 0
                logger.info(f"WB shop={shop.id} 按天写入完成 per_day={synced_per_day}")
            finally:
                await wb.close()

        elif shop.platform == "ozon":
            # —— 2026-04-26 重构：按天补缺失模式（days=1 拉每个缺失日）——
            # 实测 Ozon /v1/analytics/product-queries/details 支持 1 天窗口，
            # 每个 stat_date 装的是"那一天的真实数字"（非 N 天聚合），
            # 跨日 SUM 等于真实 N 天总量，list_shop 可任意 days 切换不膨胀。
            # end_date = today-3：实测普通 Premium 看不到 today-2 那天的数据
            # （403 "available starting from premium subscription" 实为订阅级别
            # 保护期，需 Premium Plus 才能看 1-2 天前的数据）。多留 1 天 buffer。
            end_date = today - timedelta(days=3)
            start_date = end_date - timedelta(days=days - 1)

            # 1. 查 DB 已有的 stat_date
            existing_rows = db.execute(text("""
                SELECT DISTINCT stat_date FROM product_search_queries
                WHERE tenant_id = :tid AND shop_id = :sid AND platform = 'ozon'
                  AND stat_date BETWEEN :sd AND :ed
            """), {"tid": tenant_id, "sid": shop.id,
                   "sd": start_date, "ed": end_date}).fetchall()
            existing_dates = {r.stat_date for r in existing_rows}

            # 2. 计算缺失天列表
            missing_dates = []
            d = start_date
            while d <= end_date:
                if d not in existing_dates:
                    missing_dates.append(d)
                d += timedelta(days=1)

            # 3. force=True：清掉窗口内已有，全部重拉；否则只补缺失天
            if force and existing_dates:
                db.execute(text("""
                    DELETE FROM product_search_queries
                    WHERE tenant_id = :tid AND shop_id = :sid AND platform = 'ozon'
                      AND stat_date BETWEEN :sd AND :ed
                """), {"tid": tenant_id, "sid": shop.id,
                       "sd": start_date, "ed": end_date})
                db.commit()
                missing_dates = []
                d = start_date
                while d <= end_date:
                    missing_dates.append(d)
                    d += timedelta(days=1)
                logger.info(f"force=True shop={shop.id} 已清窗口内 {len(existing_dates)} 天数据准备重拉")

            if not missing_dates:
                return {
                    "code": 0,
                    "data": {
                        "shop_id": shop.id, "synced_queries": 0,
                        "skipped": True, "reason": "no_missing_dates",
                        "existing_dates": [str(x) for x in sorted(existing_dates)],
                        "msg": f"[{start_date}, {end_date}] 范围内 {len(existing_dates)} 天已有数据，无缺失",
                    },
                }

            logger.info(
                f"shop={shop.id} 按天补齐 missing={len(missing_dates)} 天 "
                f"(已有 {len(existing_dates)} 天) 范围[{start_date}, {end_date}]"
            )

            oz = OzonClient(shop_id=shop.id, api_key=shop.api_key,
                            client_id=getattr(shop, "client_id", None))
            try:
                # 正向映射：传入的 sku (=platform_sku_id) → product_id
                sku_to_pid = {str(l.psk): l.pid for l in listings if l.psk}
                all_skus = list(sku_to_pid.keys())

                # 反查兜底：Ozon 返回的 sku 可能是"平台全局 SKU"
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

                synced_per_day = {}
                # 第一天 403 = 真没订阅，立即报错；中途 403 = Ozon 按天保护期，跳过该天继续
                first_day = True
                for d in missing_dates:
                    d_str = d.isoformat()
                    # Ozon API 要 RFC3339 24h 跨度，date_from=date_to=YYYY-MM-DD 会
                    # 被 OzonClient 转成 T00:00:00Z ~ T00:00:00Z（0 秒跨度）API 返空
                    # 所以这里显式传 24h 跨度
                    df_iso = f"{d_str}T00:00:00Z"
                    dt_iso = f"{d_str}T23:59:59Z"
                    day_total = 0
                    day_blocked = False
                    # 每天的所有 SKU 分批 50 调 API
                    for i in range(0, len(all_skus), 50):
                        batch = all_skus[i:i + 50]
                        try:
                            items = await oz.fetch_product_queries_details(
                                skus=batch, date_from=df_iso, date_to=dt_iso,
                            )
                        except SubscriptionRequiredError as e:
                            # 第一天就 403：基本可以判定整店没订阅（或所有窗口都过保护期）
                            if first_day:
                                return {
                                    "code": ErrorCode.SEARCH_INSIGHTS_SUBSCRIPTION_REQUIRED,
                                    "msg": f"Ozon 店铺未开通 Premium 订阅：{e.detail[:80]}",
                                }
                            # 中途某天 403 = Ozon 订阅级别保护期（普通 Premium 看不到 1-2 天前
                            # 数据，要 Premium Plus）。跳过该天，记 errors，继续别的天。
                            errors.append({"type": "day_blocked_premium_plus",
                                           "date": d_str, "reason": "需 Premium Plus 才能看该日数据"})
                            logger.warning(f"shop={shop.id} date={d_str} Premium 保护期 403,跳过该天")
                            day_blocked = True
                            break
                        except Exception as e:
                            errors.append({"type": "batch_error", "date": d_str,
                                           "skus": batch[:5], "error": str(e)[:200]})
                            logger.warning(
                                f"Ozon batch shop={shop.id} date={d_str} batch={len(batch)} 失败: {e}"
                            )
                            continue
                        grouped = {}
                        for it in items or []:
                            grouped.setdefault(it.get("sku"), []).append(it)
                        for sku, rows in grouped.items():
                            sku_str = str(sku)
                            pid = sku_to_pid.get(sku_str) or pid_lookup.get(sku_str)
                            day_total += _upsert_rows(
                                db, tenant_id, shop.id, "ozon",
                                sku_str, pid, d_str,
                                [{"text": r.get("query"), **r} for r in rows],
                            )
                    synced_per_day[d_str] = day_total
                    total_rows += day_total
                    # 跑过第一天 → 后续 SubscriptionRequiredError 视为单天保护期
                    first_day = False
                    # 友好限速：每天间隔 0.5s
                    await asyncio.sleep(0.5)
                logger.info(f"shop={shop.id} 按天写入完成 per_day={synced_per_day}")
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
    finally:
        # —— 释放 in-progress 锁（无论成功/失败/异常都要释放）——
        if redis_client:
            try:
                redis_client.delete(lock_key)
            except Exception as e:
                logger.warning(f"refresh_shop 释放锁失败 shop={shop.id}: {e}")
