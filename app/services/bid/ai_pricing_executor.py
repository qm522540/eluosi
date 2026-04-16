"""AI调价执行器 v2（2026-04-16 规则重构）

出价公式：
  WB  → 目标CPM = target_cpa × CTR × CR × 1000 × 小时系数 × 星期系数
  Ozon → 目标CPC = target_cpa × CR × 小时系数 × 星期系数

计算链路：
  net_margin   优先读 products.net_margin，兜底读 ai_pricing_configs.gross_margin
  client_price 优先读 platform_listings.discount_price，其次 price，兜底 default_client_price
  max_cpa      = client_price × net_margin  ← 保本线
  breakeven_roas = 1 / net_margin           ← 保本ROAS
  target_cpa   = max_cpa × cpa_ratio        ← 甜蜜点

CTR/CR 取值（按数据天数）：
  Day 0      → shop_avg × 40% / 20%（冷启动）
  Day 1-6    → 初始系数 × 1.1^growth_count（棘轮，SKU级impressions环比增长才计数）
  Day 7-13   → 均值60% + 自身40%，cpa_ratio=0.55
  Day 14-20  → 自身70% + 均值30%，cpa_ratio=0.58
               A'保护：偏离>50% + ROAS<保本线 → 回退60/40
  ≥21天      → 纯自身，cpa_ratio动态试探（起步0.60，每3天±0.05，范围0.35-0.85）
               ROAS门控：加价前查last3/prev3疗效
               利润试探：spend×(ROAS×net_margin-1) 最大化

时段系数（莫斯科时间）：
  00-04 → 50%  05-06 → 60%  07-09 → 105%
  10-13 → 110% 14-18 → 100% 19-22 → 120%  23 → 65%

星期系数：
  周一-周四 → 100%  周五 → 105%  周六-周日 → 110%

生命周期管理（亏损检测永远执行）：
  auto_remove ON  → 自动删除 + 写日志
  auto_remove OFF → 写建议列表（建议删除，用户确认）
"""

import asyncio as _asyncio
import json
import re
from datetime import datetime, timezone, date, timedelta
from typing import Optional

from sqlalchemy import text

from app.config import get_settings
from app.utils.errors import ErrorCode
from app.utils.logger import setup_logger
from app.utils.moscow_time import moscow_hour, moscow_today, now_moscow

logger = setup_logger("bid.ai_pricing_executor")
settings = get_settings()

MIN_BID = 3
MIN_DIFF = 1
ANALYZE_LOCK_TTL = 60

# 时段系数表（莫斯科时间，24小时）
TIME_SLOT_MULTIPLIERS = {
    0: 0.50, 1: 0.50, 2: 0.50, 3: 0.50, 4: 0.50,
    5: 0.60, 6: 0.60,
    7: 1.05, 8: 1.05, 9: 1.05,
    10: 1.10, 11: 1.10, 12: 1.10, 13: 1.10,
    14: 1.00, 15: 1.00, 16: 1.00, 17: 1.00, 18: 1.00,
    19: 1.20, 20: 1.20, 21: 1.20, 22: 1.20,
    23: 0.65,
}

# 星期系数表（0=周一，6=周日）
DAY_OF_WEEK_MULTIPLIERS = {
    0: 1.00, 1: 1.00, 2: 1.00, 3: 1.00,  # 周一-周四
    4: 1.05,                                # 周五
    5: 1.10, 6: 1.10,                       # 周六-周日
}

# target_cpa系数（按数据天数）
CPA_RATIO_BY_DAYS = {
    "0_6":   0.50,
    "7_13":  0.55,
    "14_20": 0.58,
    "21p":   0.60,
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _get_time_slot_multiplier() -> float:
    h = moscow_hour()
    return TIME_SLOT_MULTIPLIERS.get(h, 1.0)


def _get_day_of_week_multiplier() -> float:
    """莫斯科时间的星期系数"""
    msk = now_moscow()
    return DAY_OF_WEEK_MULTIPLIERS.get(msk.weekday(), 1.0)


def _get_cpa_ratio(data_days: int, sku_cpa_ratio: float = None) -> tuple:
    """≥21天时优先使用 SKU 自己的动态 cpa_ratio"""
    if data_days < 7:
        return CPA_RATIO_BY_DAYS["0_6"], f"数据不足{data_days}天，使用店铺均值，保守执行"
    elif data_days < 14:
        return CPA_RATIO_BY_DAYS["7_13"], f"数据有限{data_days}天，混合计算"
    elif data_days < 21:
        return CPA_RATIO_BY_DAYS["14_20"], f"数据较充足{data_days}天，精准计算"
    else:
        ratio = sku_cpa_ratio if sku_cpa_ratio is not None else CPA_RATIO_BY_DAYS["21p"]
        return ratio, ""


def _get_sku_cpa_ratio(db, tenant_id: int, campaign_id: int, sku: str) -> Optional[float]:
    """读取 SKU 级动态 cpa_ratio（≥21天利润试探用）"""
    row = db.execute(text("""
        SELECT cpa_ratio FROM ad_groups
        WHERE campaign_id = :cid AND platform_group_id = :sku
          AND tenant_id = :tid
        LIMIT 1
    """), {"cid": campaign_id, "sku": sku, "tid": tenant_id}).fetchone()
    if row and row.cpa_ratio is not None:
        return float(row.cpa_ratio)
    return None


# ==================== growth_count 冷启动期增长计数 ====================

def _get_growth_count(db, campaign_id: int, sku: str, tenant_id: int,
                      platform: str, data_days: int) -> int:
    """Day 1-6：统计 SKU 级 impressions 环比增长的天数（棘轮）"""
    if data_days < 1:
        return 0

    sku_col = "s.ad_group_id" if platform == "wb" else "COALESCE(s.ad_group_id, 0)"
    lookback = min(data_days, 6) + 1  # 多取一天用于环比

    rows = db.execute(text(f"""
        SELECT s.stat_date, SUM(s.impressions) AS imp
        FROM ad_stats s
        WHERE s.campaign_id = :cid AND {sku_col} = :sku
          AND s.tenant_id = :tid AND s.platform = :platform
          AND s.stat_date >= DATE_SUB(CURDATE(), INTERVAL :days DAY)
        GROUP BY s.stat_date
        ORDER BY s.stat_date ASC
    """), {"cid": campaign_id, "sku": sku, "tid": tenant_id,
           "platform": platform, "days": lookback}).fetchall()

    if len(rows) < 2:
        return 0

    count = 0
    for i in range(1, len(rows)):
        if int(rows[i].imp or 0) > int(rows[i - 1].imp or 0):
            count += 1
    return min(count, 6)


# ==================== A' 偏离保护（14-20天） ====================

def _check_a_prime_protection(sku_stat: dict, shop_avg: dict,
                              breakeven_roas: float) -> bool:
    """14-20天 A' 保护：偏离>50% + ROAS<保本线 → 回退60/40
    返回 True 表示需要触发保护。
    """
    sku_ctr = sku_stat.get("ctr") or 0
    sku_cr  = sku_stat.get("cr") or 0
    avg_ctr = shop_avg.get("ctr", 0)
    avg_cr  = shop_avg.get("cr", 0)

    # 条件①：CTR 或 CR 任一偏离 >50%（开区间）
    deviation_triggered = False
    if avg_ctr > 0 and abs(sku_ctr - avg_ctr) / avg_ctr > 0.50:
        deviation_triggered = True
    if avg_cr > 0 and abs(sku_cr - avg_cr) / avg_cr > 0.50:
        deviation_triggered = True

    if not deviation_triggered:
        return False

    # 条件②：自身 ROAS < 保本线
    sku_roas = sku_stat.get("roas") or 0
    return sku_roas < breakeven_roas


# ==================== ROAS 门控（≥21天） ====================

def _roas_gate(db, campaign_id: int, sku: str, tenant_id: int,
               platform: str, breakeven_roas: float,
               optimal_bid: float, current_bid: float) -> float:
    """≥21天加价前查疗效。返回调整后的 optimal_bid。
    - ROAS < 保本线 → 禁止加价，返回 current_bid（让后续逻辑走降价）
    - ROAS 趋势下跌>10% → 加价幅度砍半
    - 降价 → 直接放行
    """
    if optimal_bid <= current_bid:
        return optimal_bid  # 降价直接放行

    sku_col = "s.ad_group_id" if platform == "wb" else "COALESCE(s.ad_group_id, 0)"
    today = date.today()
    last3_from = today - timedelta(days=3)
    prev3_from = today - timedelta(days=6)

    row = db.execute(text(f"""
        SELECT
            SUM(CASE WHEN s.stat_date >= :l3 THEN s.spend ELSE 0 END) AS l3_spend,
            SUM(CASE WHEN s.stat_date >= :l3 THEN s.revenue ELSE 0 END) AS l3_revenue,
            SUM(CASE WHEN s.stat_date >= :p3 AND s.stat_date < :l3 THEN s.spend ELSE 0 END) AS p3_spend,
            SUM(CASE WHEN s.stat_date >= :p3 AND s.stat_date < :l3 THEN s.revenue ELSE 0 END) AS p3_revenue
        FROM ad_stats s
        WHERE s.campaign_id = :cid AND {sku_col} = :sku
          AND s.tenant_id = :tid AND s.platform = :platform
          AND s.stat_date >= :p3
    """), {"cid": campaign_id, "sku": sku, "tid": tenant_id,
           "platform": platform, "l3": last3_from, "p3": prev3_from}).fetchone()

    if not row:
        return optimal_bid

    l3_spend = float(row.l3_spend or 0)
    l3_revenue = float(row.l3_revenue or 0)
    p3_spend = float(row.p3_spend or 0)
    p3_revenue = float(row.p3_revenue or 0)

    l3_roas = round(l3_revenue / l3_spend, 2) if l3_spend > 0 else 0
    p3_roas = round(p3_revenue / p3_spend, 2) if p3_spend > 0 else 0

    # 检查1：last3 ROAS < 保本线 → 禁止加价
    if l3_roas < breakeven_roas:
        logger.info(f"ROAS门控：sku={sku} last3 ROAS={l3_roas} < 保本线{breakeven_roas}，禁止加价")
        return current_bid  # 不加价，保持当前

    # 检查2：last3 ROAS < prev3 ROAS × 0.9 → 加价幅度砍半
    if p3_roas > 0 and l3_roas < p3_roas * 0.9:
        half_increase = (optimal_bid - current_bid) * 0.5
        adjusted = current_bid + half_increase
        adjusted = int(round(adjusted))
        logger.info(f"ROAS门控：sku={sku} ROAS下跌{l3_roas}/{p3_roas}，加价砍半→{adjusted}")
        return adjusted

    return optimal_bid


# ==================== 利润试探（≥21天） ====================

def _evaluate_profit_trial(db, tenant_id: int, campaign_id: int, sku: str,
                           platform: str, net_margin: float,
                           current_cpa_ratio: float) -> float:
    """每3天评估 last3 vs prev3 利润，调整 cpa_ratio ±0.05。
    返回新的 cpa_ratio。
    """
    CPA_STEP = 0.05
    CPA_MIN  = 0.35
    CPA_MAX  = 0.85

    sku_col = "s.ad_group_id" if platform == "wb" else "COALESCE(s.ad_group_id, 0)"
    today = date.today()
    last3_from = today - timedelta(days=3)
    prev3_from = today - timedelta(days=6)

    row = db.execute(text(f"""
        SELECT
            SUM(CASE WHEN s.stat_date >= :l3 THEN s.spend ELSE 0 END) AS l3_spend,
            SUM(CASE WHEN s.stat_date >= :l3 THEN s.revenue ELSE 0 END) AS l3_revenue,
            SUM(CASE WHEN s.stat_date >= :p3 AND s.stat_date < :l3 THEN s.spend ELSE 0 END) AS p3_spend,
            SUM(CASE WHEN s.stat_date >= :p3 AND s.stat_date < :l3 THEN s.revenue ELSE 0 END) AS p3_revenue
        FROM ad_stats s
        WHERE s.campaign_id = :cid AND {sku_col} = :sku
          AND s.tenant_id = :tid AND s.platform = :platform
          AND s.stat_date >= :p3
    """), {"cid": campaign_id, "sku": sku, "tid": tenant_id,
           "platform": platform, "l3": last3_from, "p3": prev3_from}).fetchone()

    if not row:
        return current_cpa_ratio

    l3_spend = float(row.l3_spend or 0)
    l3_revenue = float(row.l3_revenue or 0)
    p3_spend = float(row.p3_spend or 0)
    p3_revenue = float(row.p3_revenue or 0)

    if l3_spend <= 0 or p3_spend <= 0:
        return current_cpa_ratio

    l3_roas = l3_revenue / l3_spend
    p3_roas = p3_revenue / p3_spend

    l3_profit = l3_spend * (l3_roas * net_margin - 1)
    p3_profit = p3_spend * (p3_roas * net_margin - 1)

    if l3_profit > p3_profit:
        # 利润涨了，继续同方向
        new_ratio = current_cpa_ratio + CPA_STEP
    else:
        # 利润跌了，反向回退
        new_ratio = current_cpa_ratio - CPA_STEP

    new_ratio = max(CPA_MIN, min(CPA_MAX, round(new_ratio, 2)))
    logger.info(
        f"利润试探：sku={sku} l3_profit={l3_profit:.0f} p3_profit={p3_profit:.0f} "
        f"cpa_ratio {current_cpa_ratio}→{new_ratio}"
    )
    return new_ratio


def _save_sku_cpa_ratio(db, tenant_id: int, campaign_id: int,
                        sku: str, new_ratio: float):
    """保存 SKU 级动态 cpa_ratio 到 ad_groups"""
    db.execute(text("""
        UPDATE ad_groups
        SET cpa_ratio = :ratio, cpa_ratio_updated = NOW()
        WHERE campaign_id = :cid AND platform_group_id = :sku
          AND tenant_id = :tid
    """), {"ratio": new_ratio, "cid": campaign_id, "sku": sku, "tid": tenant_id})


# ==================== 净毛利率和客单价读取 ====================

def _get_net_margin(db, tenant_id: int, shop_id: int, platform_sku_id: str) -> float:
    """优先读 products.net_margin，兜底读 ai_pricing_configs 模板里的 gross_margin"""
    row = db.execute(text("""
        SELECT p.net_margin
        FROM platform_listings pl
        JOIN products p ON pl.product_id = p.id
        WHERE pl.platform_product_id = :sku
          AND pl.tenant_id = :tenant_id
          AND p.net_margin IS NOT NULL
          AND p.net_margin > 0
        LIMIT 1
    """), {"sku": platform_sku_id, "tenant_id": tenant_id}).fetchone()

    if row and row.net_margin:
        return float(row.net_margin)

    cfg_row = db.execute(text("""
        SELECT template_name,
               conservative_config, default_config, aggressive_config
        FROM ai_pricing_configs
        WHERE shop_id = :shop_id AND tenant_id = :tenant_id
        LIMIT 1
    """), {"shop_id": shop_id, "tenant_id": tenant_id}).fetchone()

    if cfg_row:
        template = _read_template(cfg_row)
        margin = template.get("gross_margin")
        if margin and float(margin) > 0:
            return float(margin)

    return 0.27


def _get_client_price(db, tenant_id: int, shop_id: int, platform_sku_id: str) -> float:
    """优先 discount_price，其次 price，兜底 default_client_price"""
    row = db.execute(text("""
        SELECT discount_price, price
        FROM platform_listings
        WHERE platform_product_id = :sku
          AND shop_id = :shop_id
          AND tenant_id = :tenant_id
        LIMIT 1
    """), {"sku": platform_sku_id, "shop_id": shop_id, "tenant_id": tenant_id}).fetchone()

    if row:
        if row.discount_price and float(row.discount_price) > 0:
            return float(row.discount_price)
        if row.price and float(row.price) > 0:
            return float(row.price)

    cfg_row = db.execute(text("""
        SELECT default_client_price
        FROM ai_pricing_configs
        WHERE shop_id = :shop_id AND tenant_id = :tenant_id
        LIMIT 1
    """), {"shop_id": shop_id, "tenant_id": tenant_id}).fetchone()

    if cfg_row and cfg_row.default_client_price:
        return float(cfg_row.default_client_price)

    return 600.0


# ==================== 店铺均值 ====================

def _get_shop_avg(db, shop_id: int, tenant_id: int, platform: str) -> dict:
    today = date.today()
    since = today - timedelta(days=21)

    row = db.execute(text("""
        SELECT
            SUM(s.impressions) AS impressions,
            SUM(s.clicks)      AS clicks,
            SUM(s.spend)       AS spend,
            SUM(s.orders)      AS orders,
            SUM(s.revenue)     AS revenue
        FROM ad_stats s
        JOIN ad_campaigns c ON s.campaign_id = c.id
        WHERE c.shop_id   = :shop_id
          AND c.tenant_id = :tenant_id
          AND s.platform  = :platform
          AND s.stat_date >= :since
    """), {"shop_id": shop_id, "tenant_id": tenant_id,
           "platform": platform, "since": since}).fetchone()

    if not row or not row.impressions:
        return {}

    impressions = int(row.impressions or 0)
    clicks      = int(row.clicks or 0)
    spend       = float(row.spend or 0)
    orders      = int(row.orders or 0)
    revenue     = float(row.revenue or 0)

    return {
        "ctr":  round(clicks / impressions * 100, 4) if impressions > 0 else 0,
        "cr":   round(orders / clicks * 100, 4) if clicks > 0 else 0,
        "cpa":  round(spend / orders, 2) if orders > 0 else None,
        "roas": round(revenue / spend, 2) if spend > 0 else 0,
    }


# ==================== 目标出价计算（核心） ====================

def _calc_optimal_bid(platform: str, target_cpa: float, ctr: float,
                      cr: float, time_multiplier: float, day_multiplier: float,
                      max_cpa: float) -> Optional[float]:
    """
    WB:   目标CPM = target_cpa × CTR × CR × 1000 × 小时系数 × 星期系数
    Ozon: 目标CPC = target_cpa × CR × 小时系数 × 星期系数
    安全验证不超过保本线
    """
    if ctr <= 0 or cr <= 0:
        return None

    ctr_dec = ctr / 100.0
    cr_dec  = cr / 100.0
    combined_multiplier = time_multiplier * day_multiplier

    if platform == "wb":
        raw_bid = target_cpa * ctr_dec * cr_dec * 1000 * combined_multiplier
        actual_cpa = raw_bid / (ctr_dec * cr_dec * 1000)
        if actual_cpa > max_cpa:
            raw_bid = max_cpa * ctr_dec * cr_dec * 1000 * combined_multiplier
    else:
        raw_bid = target_cpa * cr_dec * combined_multiplier
        actual_cpa = raw_bid / cr_dec
        if actual_cpa > max_cpa:
            raw_bid = max_cpa * cr_dec * combined_multiplier

    return int(round(raw_bid))


# ==================== Config 更新 ====================

def update_config(db, tenant_id: int, shop_id: int, data: dict) -> dict:
    existing = db.execute(text("""
        SELECT id, tenant_id FROM ai_pricing_configs
        WHERE shop_id = :shop_id LIMIT 1
    """), {"shop_id": shop_id}).fetchone()

    if existing and existing.tenant_id != tenant_id:
        return {"code": ErrorCode.SHOP_NOT_FOUND, "msg": "店铺不存在或无权限"}

    template_name = data.get("template_name", "default")
    if template_name not in ("conservative", "default", "aggressive"):
        return {"code": ErrorCode.PARAM_ERROR,
                "msg": "template_name 必须是 conservative/default/aggressive"}

    auto_execute           = 1 if data.get("auto_execute") else 0
    default_client_price   = float(data.get("default_client_price") or 600.0)
    auto_remove_losing_sku = 1 if data.get("auto_remove_losing_sku") else 0
    losing_days_threshold  = int(data.get("losing_days_threshold") or 21)

    fields = {}
    for key in ("conservative_config", "default_config", "aggressive_config"):
        if key in data and isinstance(data[key], dict):
            err = _validate_template_json(data[key])
            if err:
                return {"code": ErrorCode.PARAM_ERROR, "msg": f"{key}: {err}"}
            fields[key] = json.dumps(data[key])

    if existing:
        sets = [
            "template_name = :template_name",
            "auto_execute = :auto_execute",
            "default_client_price = :default_client_price",
            "auto_remove_losing_sku = :auto_remove_losing_sku",
            "losing_days_threshold = :losing_days_threshold",
            "updated_at = NOW()",
        ]
        params = {
            "id": existing.id, "tenant_id": tenant_id,
            "template_name": template_name, "auto_execute": auto_execute,
            "default_client_price": default_client_price,
            "auto_remove_losing_sku": auto_remove_losing_sku,
            "losing_days_threshold": losing_days_threshold,
        }
        for k, v in fields.items():
            sets.append(f"{k} = :{k}")
            params[k] = v
        db.execute(
            text(f"UPDATE ai_pricing_configs SET {', '.join(sets)} "
                 f"WHERE id = :id AND tenant_id = :tenant_id"),
            params,
        )
    else:
        defaults = {
            "conservative_config": json.dumps(_DEFAULT_CONSERVATIVE),
            "default_config":      json.dumps(_DEFAULT_DEFAULT),
            "aggressive_config":   json.dumps(_DEFAULT_AGGRESSIVE),
        }
        defaults.update(fields)
        db.execute(text("""
            INSERT INTO ai_pricing_configs (
                tenant_id, shop_id, is_active, auto_execute, template_name,
                conservative_config, default_config, aggressive_config,
                default_client_price, auto_remove_losing_sku, losing_days_threshold
            ) VALUES (
                :tenant_id, :shop_id, 0, :auto_execute, :template_name,
                :conservative_config, :default_config, :aggressive_config,
                :default_client_price, :auto_remove_losing_sku, :losing_days_threshold
            )
        """), {
            "tenant_id": tenant_id, "shop_id": shop_id,
            "auto_execute": auto_execute, "template_name": template_name,
            "default_client_price": default_client_price,
            "auto_remove_losing_sku": auto_remove_losing_sku,
            "losing_days_threshold": losing_days_threshold,
            **defaults,
        })

    db.commit()
    return {"code": 0}


# ==================== 启用 / 停用 ====================

def enable(db, tenant_id: int, shop_id: int, auto_execute: bool = False) -> dict:
    init_row = db.execute(text("""
        SELECT is_initialized FROM shop_data_init_status
        WHERE shop_id = :shop_id AND tenant_id = :tenant_id
    """), {"shop_id": shop_id, "tenant_id": tenant_id}).fetchone()
    if not init_row or not init_row.is_initialized:
        return {"code": ErrorCode.BID_DATA_NOT_READY, "msg": "店铺数据未初始化完成"}

    ai_row = db.execute(text("""
        SELECT id FROM ai_pricing_configs
        WHERE shop_id = :shop_id AND tenant_id = :tenant_id FOR UPDATE
    """), {"shop_id": shop_id, "tenant_id": tenant_id}).fetchone()
    if not ai_row:
        return {"code": ErrorCode.BID_AI_CONFIG_NOT_FOUND, "msg": "AI调价配置不存在"}

    time_row = db.execute(text("""
        SELECT id, is_active FROM time_pricing_rules
        WHERE shop_id = :shop_id AND tenant_id = :tenant_id FOR UPDATE
    """), {"shop_id": shop_id, "tenant_id": tenant_id}).fetchone()
    if time_row and time_row.is_active:
        return {"code": ErrorCode.BID_CONFLICT_TIME_AI, "msg": "分时调价已启用，请先停用"}

    db.execute(text("""
        UPDATE ai_pricing_configs
        SET is_active = 1, auto_execute = :auto_execute, updated_at = NOW()
        WHERE shop_id = :shop_id AND tenant_id = :tenant_id
    """), {"shop_id": shop_id, "tenant_id": tenant_id,
           "auto_execute": 1 if auto_execute else 0})
    db.commit()
    return {"code": 0}


def disable(db, tenant_id: int, shop_id: int) -> dict:
    db.execute(text("""
        UPDATE ai_pricing_configs
        SET is_active = 0, auto_execute = 0, updated_at = NOW()
        WHERE shop_id = :shop_id AND tenant_id = :tenant_id
    """), {"shop_id": shop_id, "tenant_id": tenant_id})
    db.commit()
    return {"code": 0}


# ==================== 主分析流程 ====================

async def execute(db, shop_id: int, tenant_id: int = None) -> dict:
    if tenant_id is None:
        cfg_row = db.execute(text("""
            SELECT tenant_id FROM ai_pricing_configs
            WHERE shop_id = :shop_id AND is_active = 1 LIMIT 1
        """), {"shop_id": shop_id}).fetchone()
        if not cfg_row:
            return {"status": "skipped", "message": "AI调价未启用"}
        tenant_id = cfg_row.tenant_id

    cfg = db.execute(text("""
        SELECT id, is_active, auto_execute, template_name,
               conservative_config, default_config, aggressive_config,
               default_client_price, auto_remove_losing_sku, losing_days_threshold,
               retry_at
        FROM ai_pricing_configs
        WHERE shop_id = :shop_id AND tenant_id = :tenant_id AND is_active = 1
        LIMIT 1
    """), {"shop_id": shop_id, "tenant_id": tenant_id}).fetchone()

    if not cfg:
        return {"status": "skipped", "message": "AI调价未启用"}

    if cfg.retry_at and _utc_now().replace(tzinfo=None) < cfg.retry_at:
        return {"status": "skipped", "message": "等待失败重试时间"}

    return await analyze_now(db, tenant_id, shop_id, force=False)


async def analyze_now(db, tenant_id: int, shop_id: int,
                      force: bool = True,
                      campaign_ids: Optional[list] = None) -> dict:
    lock_acquired = _try_acquire_analyze_lock(shop_id)
    if not lock_acquired:
        return {"status": "skipped", "message": "AI分析进行中，请等待60秒",
                "analyzed_count": 0, "suggestion_count": 0, "auto_executed_count": 0}
    try:
        return await _analyze_now_inner(db, tenant_id, shop_id, force, campaign_ids)
    finally:
        _release_analyze_lock(shop_id)


async def analyze_stream(db, tenant_id: int, shop_id: int,
                         campaign_ids: Optional[list] = None):
    """SSE 流式分析包装器：调 analyze_now 拿结果，按 SSE 协议分阶段推送给前端。
    当前不做真流式（DeepSeek token 级别），仅分阶段事件 + 建议逐条推送。
    """
    def _sse(event: str, data) -> str:
        return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    try:
        yield _sse("phase", "正在准备数据...")

        lock_acquired = _try_acquire_analyze_lock(shop_id)
        if not lock_acquired:
            yield _sse("error", "AI 分析进行中，请等待 60 秒后重试")
            yield _sse("done", "已跳过")
            return

        try:
            yield _sse("phase", "DeepSeek 正在生成建议...")
            result = await _analyze_now_inner(db, tenant_id, shop_id,
                                              force=True, campaign_ids=campaign_ids)
        finally:
            _release_analyze_lock(shop_id)

        status = result.get("status")
        if status == "failed":
            msg = result.get("message") or "分析失败"
            yield _sse("error", msg)
            yield _sse("done", f"分析失败：{msg}")
            return

        # 读取本次产生的 suggestions（pending + 今日）
        rows = db.execute(text("""
            SELECT s.id, s.campaign_id, s.platform_sku_id, s.sku_name,
                   s.current_bid, s.suggested_bid, s.current_roas,
                   s.product_stage, s.reason
            FROM ai_pricing_suggestions s
            WHERE s.tenant_id = :tid AND s.shop_id = :sid
              AND DATE(s.generated_at) = CURDATE()
              AND s.status = 'pending'
            ORDER BY s.id DESC
        """), {"tid": tenant_id, "sid": shop_id}).fetchall()

        # 逐条作为 token 事件推送 JSON 片段，前端 extractSuggestions 正则能解析
        for r in rows:
            item = {
                "campaign_id": r.campaign_id,
                "platform_sku_id": r.platform_sku_id,
                "sku_name": r.sku_name,
                "current_bid": float(r.current_bid) if r.current_bid is not None else None,
                "suggested_bid": float(r.suggested_bid) if r.suggested_bid is not None else None,
                "current_roas": float(r.current_roas) if r.current_roas is not None else None,
                "product_stage": r.product_stage,
                "reason": r.reason or "",
            }
            yield _sse("token", json.dumps(item, ensure_ascii=False))
            await _asyncio.sleep(0.05)  # 给前端一点渲染缓冲

        msg = (f"分析完成，生成 {result.get('suggestion_count', 0)} 条调价建议"
               f"（自动执行 {result.get('auto_executed_count', 0)} 条）")
        yield _sse("phase", msg)
        yield _sse("done", msg)

    except Exception as e:
        logger.exception(f"analyze_stream 失败 shop_id={shop_id}: {e}")
        yield _sse("error", f"分析失败: {e}")
        yield _sse("done", f"分析失败: {e}")


async def _analyze_now_inner(db, tenant_id: int, shop_id: int,
                             force: bool, campaign_ids: Optional[list]) -> dict:
    start = _utc_now()

    cfg = db.execute(text("""
        SELECT id, auto_execute, template_name,
               conservative_config, default_config, aggressive_config,
               default_client_price, auto_remove_losing_sku, losing_days_threshold
        FROM ai_pricing_configs
        WHERE shop_id = :shop_id AND tenant_id = :tenant_id LIMIT 1
    """), {"shop_id": shop_id, "tenant_id": tenant_id}).fetchone()

    if not cfg:
        return {"status": "failed", "message": "AI配置不存在",
                "analyzed_count": 0, "suggestion_count": 0, "auto_executed_count": 0}

    from app.models.shop import Shop
    shop = db.query(Shop).filter(
        Shop.id == shop_id, Shop.tenant_id == tenant_id
    ).first()
    if not shop or shop.platform not in ("ozon", "wb"):
        return {"status": "failed", "message": "该平台暂不支持AI调价",
                "analyzed_count": 0, "suggestion_count": 0, "auto_executed_count": 0}

    platform = shop.platform

    # ── 检查店铺数据 ──
    shop_avg = _get_shop_avg(db, shop_id, tenant_id, platform)
    if not shop_avg:
        _update_status(db, tenant_id, shop_id, "failed", "暂无历史数据，请先同步数据源")
        return {"status": "failed", "message": "暂无历史数据，请先同步数据源",
                "analyzed_count": 0, "suggestion_count": 0, "auto_executed_count": 0}

    if shop_avg.get("cr", 0) == 0:
        _update_status(db, tenant_id, shop_id, "failed",
                       "近21天无转化数据，建议优化商品详情页")
        return {"status": "failed", "message": "近21天无转化数据，建议优化商品详情页",
                "analyzed_count": 0, "suggestion_count": 0, "auto_executed_count": 0}

    # ── 获取活跃活动 ──
    from app.models.ad import AdCampaign
    q = db.query(AdCampaign).filter(
        AdCampaign.tenant_id == tenant_id,
        AdCampaign.shop_id == shop_id,
        AdCampaign.platform == platform,
        AdCampaign.status == "active",
    )
    if campaign_ids:
        q = q.filter(AdCampaign.id.in_(campaign_ids))
    campaigns = q.all()

    if not campaigns:
        _update_status(db, tenant_id, shop_id, "success", "无活跃活动")
        return {"status": "success", "message": "无活跃活动",
                "analyzed_count": 0, "suggestion_count": 0, "auto_executed_count": 0}

    # ── 拉取平台商品出价（client 保持开启用于后续 min bid 查询） ──
    client = _create_platform_client(shop)
    products_by_campaign = {}
    try:
        for camp in campaigns:
            try:
                products = await client.fetch_campaign_products(
                    camp.platform_campaign_id)
            except Exception as e:
                logger.warning(f"campaign={camp.id} 拉商品失败: {e}")
                products = []
            products_by_campaign[camp.id] = products
    except Exception:
        await client.close()
        raise

    if not any(products_by_campaign.values()):
        await client.close()
        _update_status(db, tenant_id, shop_id, "success", "活跃活动下无商品")
        return {"status": "success", "message": "无商品数据",
                "analyzed_count": len(campaigns),
                "suggestion_count": 0, "auto_executed_count": 0}

    # ── 查询SKU历史数据 ──
    sku_stats = _query_sku_history(db, shop_id, tenant_id, platform)

    # ── 时段系数 + 星期系数 ──
    time_multiplier = _get_time_slot_multiplier()
    day_multiplier  = _get_day_of_week_multiplier()
    current_hour    = moscow_hour()

    # ── 过期旧建议 ──
    db.execute(text("""
        UPDATE ai_pricing_suggestions
        SET status = 'rejected'
        WHERE shop_id = :shop_id AND tenant_id = :tenant_id AND status = 'pending'
    """), {"shop_id": shop_id, "tenant_id": tenant_id})

    saved        = []
    auto_removed = 0

    for camp in campaigns:
        products = products_by_campaign.get(camp.id) or []

        for p in products:
            sku = str(p.get("sku") or "")
            if not sku:
                continue

            if platform == "ozon":
                bid_raw = p.get("bid", "0")
                try:
                    current_bid = float(int(bid_raw)) / 1_000_000
                except (ValueError, TypeError):
                    current_bid = 0
                sku_name = (p.get("title") or "")[:300]
            else:
                current_bid = float(p.get("bid_search") or 0)
                sku_name    = (p.get("subject_name") or "")[:300]

            if current_bid <= 0:
                continue

            stats_key = f"{camp.id}_{sku}"
            sku_stat  = sku_stats.get(stats_key, {})
            data_days = int(sku_stat.get("days", 0) or 0)

            # ── Step 1: 生命周期管理：亏损检测（永远执行） ──
            net_margin   = _get_net_margin(db, tenant_id, shop_id, sku)
            client_price = _get_client_price(db, tenant_id, shop_id, sku)
            max_cpa          = client_price * net_margin
            breakeven_roas   = 1.0 / net_margin if net_margin > 0 else 0

            if data_days > (cfg.losing_days_threshold or 21):
                is_losing, roas_21_30, be_roas_l, net_margin_l = _is_losing_sku(
                    db, tenant_id, shop_id, camp.id, platform, sku,
                )
                if is_losing:
                    if cfg.auto_remove_losing_sku and cfg.auto_execute:
                        # 全自动删除
                        removed = await _check_and_remove_losing_sku(
                            db, client, shop, camp, sku, sku_name,
                            current_bid, tenant_id, sku_stat,
                        )
                        if removed:
                            auto_removed += 1
                            continue
                    else:
                        # 写建议列表（无论 auto_remove/auto_execute 设置）
                        reason_txt = (
                            f"[亏损删除建议] 21-30天ROAS={roas_21_30:.2f}x "
                            f"低于保本线{be_roas_l:.2f}x (净毛利率={net_margin_l})，"
                            f"数据天数{data_days}天，建议从活动中移除该 SKU"
                        )
                        ins = db.execute(text("""
                            INSERT INTO ai_pricing_suggestions (
                                tenant_id, shop_id, campaign_id,
                                platform_sku_id, sku_name,
                                current_bid, suggested_bid, adjust_pct,
                                product_stage, decision_basis,
                                current_roas, expected_roas,
                                data_days, reason, status, generated_at
                            ) VALUES (
                                :tenant_id, :shop_id, :campaign_id,
                                :sku, :sku_name,
                                :current_bid, 0, -100,
                                'declining', 'history_data',
                                :current_roas, NULL,
                                :data_days, :reason, 'pending', NOW()
                            )
                        """), {
                            "tenant_id": tenant_id, "shop_id": shop_id,
                            "campaign_id": camp.id, "sku": sku,
                            "sku_name": sku_name,
                            "current_bid": current_bid,
                            "current_roas": round(roas_21_30, 2),
                            "data_days": data_days,
                            "reason": reason_txt[:500],
                        })
                        saved.append({
                            "id": ins.lastrowid,
                            "tenant_id": tenant_id, "shop_id": shop_id,
                            "campaign_id": camp.id,
                            "platform_sku_id": sku, "sku_name": sku_name,
                            "current_bid": current_bid, "suggested_bid": 0,
                            "adjust_pct": -100,
                            "product_stage": "declining",
                            "reason": reason_txt,
                        })
                        continue

            # ── Step 2: 选取 CTR/CR 来源（新规则） ──
            if data_days == 0:
                # 冷启动：shop_avg × 40%/20%
                ctr = shop_avg.get("ctr", 0) * 0.40
                cr  = shop_avg.get("cr", 0)  * 0.20
            elif data_days <= 6:
                # Day 1-6：growth_count 棘轮
                growth_count = _get_growth_count(
                    db, camp.id, sku, tenant_id, platform, data_days)
                ctr = shop_avg.get("ctr", 0) * 0.40 * (1.1 ** growth_count)
                cr  = shop_avg.get("cr", 0)  * 0.20 * (1.1 ** growth_count)
            elif data_days < 14:
                # Day 7-13：均值60% + 自身40%
                ctr = shop_avg.get("ctr", 0) * 0.6 + (sku_stat.get("ctr") or 0) * 0.4
                cr  = shop_avg.get("cr", 0)  * 0.6 + (sku_stat.get("cr") or 0)  * 0.4
            elif data_days < 21:
                # Day 14-20：自身70% + 均值30%，A'保护可能回退到60/40
                self_weight = 0.70
                avg_weight  = 0.30
                if _check_a_prime_protection(sku_stat, shop_avg, breakeven_roas):
                    self_weight = 0.40
                    avg_weight  = 0.60
                    logger.info(f"A'保护触发: sku={sku} 回退60/40")
                ctr = (sku_stat.get("ctr") or 0) * self_weight + shop_avg.get("ctr", 0) * avg_weight
                cr  = (sku_stat.get("cr") or 0)  * self_weight + shop_avg.get("cr", 0)  * avg_weight
            else:
                # ≥21天：纯自身
                ctr = sku_stat.get("ctr") or 0
                cr  = sku_stat.get("cr") or 0

            if ctr <= 0:
                logger.info(f"sku={sku} CTR=0，跳过")
                continue

            if cr <= 0:
                cr = shop_avg.get("cr", 0)
                if cr <= 0:
                    logger.info(f"sku={sku} CR=0且均值CR=0，跳过")
                    continue

            # ── Step 3: 确定 cpa_ratio ──
            sku_cpa_ratio = None
            if data_days >= 21:
                sku_cpa_ratio = _get_sku_cpa_ratio(db, tenant_id, camp.id, sku)
            cpa_ratio, data_note = _get_cpa_ratio(data_days, sku_cpa_ratio)
            target_cpa = max_cpa * cpa_ratio

            # ── Step 4: 计算最优出价 ──
            optimal_bid = _calc_optimal_bid(
                platform=platform, target_cpa=target_cpa,
                ctr=ctr, cr=cr,
                time_multiplier=time_multiplier,
                day_multiplier=day_multiplier,
                max_cpa=max_cpa,
            )

            # ── Step 5: 平台最低出价校验 ──
            # WB 最低价是"竞争阈值"不是硬卡，低于它仍能跑但曝光可能差
            # 策略：算法值低于 min 时，标注警告但不强拉（保留利润最大化判断）
            min_bid_warning = ""
            if optimal_bid is not None and platform == "wb":
                try:
                    min_rub = await client.fetch_min_bid(
                        advert_id=str(camp.platform_campaign_id),
                        nm_id=int(sku),
                    )
                    if min_rub and optimal_bid < min_rub:
                        min_bid_warning = f"⚠ 低于WB推荐竞争价₽{int(min_rub)}，曝光可能不足"
                        logger.info(
                            f"WB推荐价提示：sku={sku} optimal={optimal_bid}"
                            f"<推荐竞争价={min_rub}，保留算法值+加警告"
                        )
                except Exception as e:
                    logger.warning(f"WB 最低价查询异常 sku={sku}: {e}")

            # ── Step 6: ROAS 门控（≥21天） ──
            if optimal_bid is not None and data_days >= 21:
                optimal_bid = _roas_gate(
                    db, camp.id, sku, tenant_id, platform,
                    breakeven_roas, optimal_bid, current_bid,
                )
            if optimal_bid is None:
                continue

            optimal_bid = max(optimal_bid, MIN_BID)

            if abs(optimal_bid - current_bid) < MIN_DIFF:
                continue

            adjust_pct = (
                round((optimal_bid - current_bid) / current_bid * 100, 2)
                if current_bid > 0 else 0
            )
            current_roas = sku_stat.get("roas") or 0

            reason = _build_reason(
                platform=platform, net_margin=net_margin,
                client_price=client_price, max_cpa=max_cpa,
                target_cpa=target_cpa, ctr=ctr, cr=cr,
                current_bid=current_bid, optimal_bid=optimal_bid,
                time_multiplier=time_multiplier,
                day_multiplier=day_multiplier,
                current_hour=current_hour,
                data_days=data_days, data_note=data_note,
                breakeven_roas=breakeven_roas, current_roas=current_roas,
            )
            if min_bid_warning:
                reason = f"{reason} | {min_bid_warning}"

            result = db.execute(text("""
                INSERT INTO ai_pricing_suggestions (
                    tenant_id, shop_id, campaign_id,
                    platform_sku_id, sku_name,
                    current_bid, suggested_bid, adjust_pct,
                    product_stage, decision_basis,
                    current_roas, expected_roas,
                    data_days, reason, status, generated_at
                ) VALUES (
                    :tenant_id, :shop_id, :campaign_id,
                    :sku, :sku_name,
                    :current_bid, :suggested_bid, :adjust_pct,
                    :stage, :basis,
                    :current_roas, :expected_roas,
                    :data_days, :reason, 'pending', NOW()
                )
            """), {
                "tenant_id": tenant_id, "shop_id": shop_id,
                "campaign_id": camp.id, "sku": sku, "sku_name": sku_name,
                "current_bid": current_bid, "suggested_bid": optimal_bid,
                "adjust_pct": adjust_pct,
                "stage": _get_product_stage(data_days),
                "basis": ("history_data" if data_days >= 21
                          else "shop_benchmark" if data_days < 7
                          else "history_data"),
                "current_roas": round(current_roas, 2) if current_roas else None,
                "expected_roas": (
                    # WB: ROAS = CTR × CR × client_price × 1000 / CPM
                    # Ozon: ROAS = CR × client_price / CPC
                    round(
                        (ctr / 100) * (cr / 100) * client_price * 1000 / optimal_bid
                        if platform == "wb"
                        else (cr / 100) * client_price / optimal_bid,
                        2,
                    )
                    if optimal_bid > 0 and client_price > 0 and ctr > 0 and cr > 0
                    else None
                ),
                "data_days": data_days,
                "reason": reason[:500],
            })

            saved.append({
                "id": result.lastrowid,
                "tenant_id": tenant_id, "shop_id": shop_id,
                "campaign_id": camp.id,
                "platform_sku_id": sku, "sku_name": sku_name,
                "current_bid": current_bid, "suggested_bid": optimal_bid,
                "adjust_pct": adjust_pct,
                "product_stage": _get_product_stage(data_days),
                "reason": reason,
            })

    db.commit()

    # SKU 处理完成，关闭 client（auto_execute 内部会新建 client）
    await client.close()

    auto_executed = 0
    if cfg.auto_execute and saved:
        auto_executed = await _auto_execute(db, tenant_id, shop, saved)

    # ── Step 9: 利润试探评估（≥21天，每3天） ──
    for camp in campaigns:
        products = products_by_campaign.get(camp.id) or []
        for p in products:
            sku = str(p.get("sku") or "")
            if not sku:
                continue
            stats_key = f"{camp.id}_{sku}"
            sku_stat_t = sku_stats.get(stats_key, {})
            dd = int(sku_stat_t.get("days", 0) or 0)
            if dd < 21:
                continue

            # 检查是否到了3天评估节点
            ag_row = db.execute(text("""
                SELECT cpa_ratio, cpa_ratio_updated FROM ad_groups
                WHERE campaign_id = :cid AND platform_group_id = :sku
                  AND tenant_id = :tid LIMIT 1
            """), {"cid": camp.id, "sku": sku, "tid": tenant_id}).fetchone()

            current_ratio = float(ag_row.cpa_ratio) if ag_row and ag_row.cpa_ratio else 0.60
            last_updated = ag_row.cpa_ratio_updated if ag_row else None

            # 每3天评估一次
            if last_updated:
                try:
                    lu = last_updated if hasattr(last_updated, 'date') else datetime.fromisoformat(str(last_updated))
                    days_since = (datetime.now(timezone.utc).replace(tzinfo=None) - lu.replace(tzinfo=None)).days
                except Exception:
                    days_since = 999
                if days_since < 3:
                    continue

            nm = _get_net_margin(db, tenant_id, shop_id, sku)
            new_ratio = _evaluate_profit_trial(
                db, tenant_id, camp.id, sku, platform, nm, current_ratio)
            if new_ratio != current_ratio:
                _save_sku_cpa_ratio(db, tenant_id, camp.id, sku, new_ratio)
    db.commit()

    elapsed = int((_utc_now() - start).total_seconds() * 1000)
    summary = (f"分析{len(campaigns)}个活动 生成{len(saved)}条建议 "
               f"自动删除{auto_removed}个亏损SKU")
    if auto_executed:
        summary += f" 自动执行{auto_executed}条"
    _update_status(db, tenant_id, shop_id, "success", summary)

    return {
        "status": "success",
        "analyzed_count": len(campaigns),
        "suggestion_count": len(saved),
        "auto_executed_count": auto_executed,
        "auto_removed_count": auto_removed,
        "time_cost_ms": elapsed,
        "suggestions": saved,
    }


# ==================== 生命周期管理 ====================

def _is_losing_sku(db, tenant_id: int, shop_id: int, camp_id: int,
                   platform: str, sku: str):
    """检查 SKU 是否满足"21-30 天持续亏损"条件。
    返回 (is_losing, roas_21_30, breakeven_roas, net_margin)
    任一为 None 表示判定数据不足，is_losing=False。
    """
    roas_21_30 = _get_roas_21_30(db, camp_id, sku, tenant_id, platform)
    if roas_21_30 is None:
        return False, None, None, None
    net_margin = _get_net_margin(db, tenant_id, shop_id, sku)
    breakeven_roas = 1.0 / net_margin if net_margin > 0 else 3.7
    return (roas_21_30 < breakeven_roas, roas_21_30, breakeven_roas, net_margin)


async def _check_and_remove_losing_sku(
    db, client, shop, camp, sku: str, sku_name: str,
    current_bid: float, tenant_id: int, sku_stat: dict,
) -> bool:
    is_losing, roas_21_30, breakeven_roas, _ = _is_losing_sku(
        db, tenant_id, shop.id, camp.id, shop.platform, sku,
    )
    if not is_losing:
        return False

    logger.info(
        f"[auto_remove] sku={sku} camp={camp.id} "
        f"21-30天ROAS={roas_21_30:.2f}x < 保本线{breakeven_roas:.2f}x，自动删除"
    )

    try:
        api_result = await _execute_bid_update(
            client, shop.platform, camp.platform_campaign_id, sku, 0, delete=True,
        )
        success = api_result.get("ok", False)
    except Exception as e:
        logger.error(f"auto_remove API失败 sku={sku}: {e}")
        success = False

    db.execute(text("""
        INSERT INTO bid_adjustment_logs (
            tenant_id, shop_id, campaign_id, campaign_name,
            platform_sku_id, sku_name,
            old_bid, new_bid, adjust_pct,
            execute_type, product_stage, moscow_hour,
            success, error_msg, created_at
        ) VALUES (
            :tenant_id, :shop_id, :campaign_id, :campaign_name,
            :sku, :sku_name,
            :old_bid, 0, -100,
            'auto_remove', 'declining', :hour,
            :success, :error, NOW()
        )
    """), {
        "tenant_id": tenant_id, "shop_id": shop.id,
        "campaign_id": camp.id, "campaign_name": camp.name,
        "sku": sku, "sku_name": sku_name or "",
        "old_bid": current_bid, "hour": moscow_hour(),
        "success": 1 if success else 0,
        "error": None if success else "API删除失败",
    })

    try:
        from app.services.notification.service import send_wechat_work
        status_text = "已成功删除" if success else "删除失败，请手动处理"
        send_wechat_work(
            title="【AI调价】持续亏损商品自动删除",
            content=(
                f"店铺：{shop.name}\n"
                f"商品：{sku_name or sku}\n"
                f"21-30天ROAS：{roas_21_30:.2f}x\n"
                f"保本线：{breakeven_roas:.2f}x\n"
                f"状态：{status_text}"
            ),
        )
    except Exception as e:
        logger.warning(f"企业微信通知失败: {e}")

    return success


def _get_roas_21_30(db, campaign_id: int, sku: str,
                    tenant_id: int, platform: str) -> Optional[float]:
    today     = date.today()
    date_from = today - timedelta(days=30)
    date_to   = today - timedelta(days=21)

    row = db.execute(text("""
        SELECT SUM(spend) AS spend, SUM(revenue) AS revenue
        FROM ad_stats s
        WHERE s.campaign_id = :campaign_id
          AND s.tenant_id   = :tenant_id
          AND s.stat_date  >= :date_from
          AND s.stat_date   < :date_to
    """), {
        "campaign_id": campaign_id, "tenant_id": tenant_id,
        "date_from": date_from, "date_to": date_to,
    }).fetchone()

    if not row or not row.spend or float(row.spend) <= 0:
        return None

    return round(float(row.revenue) / float(row.spend), 2)


# ==================== 自动执行 ====================

async def _auto_execute(db, tenant_id: int, shop, suggestions: list) -> int:
    from app.models.ad import AdCampaign
    client   = _create_platform_client(shop)
    executed = 0
    try:
        for s in suggestions:
            campaign = db.query(AdCampaign).filter(
                AdCampaign.id == s["campaign_id"],
                AdCampaign.tenant_id == tenant_id,
            ).first()
            if not campaign:
                continue

            ag_row = db.execute(text("""
                SELECT user_managed FROM ad_groups
                WHERE campaign_id = :cid AND tenant_id = :tenant_id
                  AND platform_group_id = :sku LIMIT 1
            """), {"cid": campaign.id, "tenant_id": tenant_id,
                   "sku": s["platform_sku_id"]}).fetchone()
            if ag_row and ag_row.user_managed:
                continue

            try:
                api_result = await _execute_bid_update(
                    client, shop.platform, campaign.platform_campaign_id,
                    s["platform_sku_id"], s["suggested_bid"],
                )
                if not api_result.get("ok"):
                    _write_bidlog(db, campaign, s, "ai_auto",
                                  success=False, error=api_result.get("error"))
                    continue
                _upsert_group_last_auto(
                    db, campaign, s["platform_sku_id"],
                    s.get("sku_name") or "", s["suggested_bid"],
                )
                db.execute(text("""
                    UPDATE ai_pricing_suggestions
                    SET status = 'approved', executed_at = :now
                    WHERE id = :id AND tenant_id = :tenant_id
                """), {"id": s["id"], "tenant_id": tenant_id,
                       "now": _utc_now().replace(tzinfo=None)})
                _write_bidlog(db, campaign, s, "ai_auto", success=True)
                executed += 1
            except Exception as e:
                logger.error(f"auto execute 异常 sku={s['platform_sku_id']}: {e}")
                _write_bidlog(db, campaign, s, "ai_auto", success=False, error=str(e))
        db.commit()
    finally:
        await client.close()
    return executed


# ==================== approve / reject ====================

async def approve_suggestion(db, tenant_id: int, suggestion_id: int,
                             override_bid: Optional[float] = None) -> dict:
    row = db.execute(text("""
        SELECT s.id, s.tenant_id, s.shop_id, s.campaign_id,
               s.platform_sku_id, s.sku_name, s.product_stage,
               s.current_bid, s.suggested_bid, s.adjust_pct,
               s.status, s.generated_at,
               c.platform_campaign_id, c.name AS campaign_name
        FROM ai_pricing_suggestions s
        JOIN ad_campaigns c ON s.campaign_id = c.id
        WHERE s.id = :id AND s.tenant_id = :tenant_id
    """), {"id": suggestion_id, "tenant_id": tenant_id}).fetchone()

    if not row:
        return {"code": ErrorCode.BID_SUGGESTION_NOT_FOUND, "msg": "建议不存在"}
    if row.status != "pending":
        return {"code": ErrorCode.BID_INVALID_STATUS,
                "msg": f"当前状态 {row.status} 不允许执行"}
    if row.generated_at and row.generated_at.date() < moscow_today():
        return {"code": ErrorCode.BID_SUGGESTION_EXPIRED, "msg": "建议已过期"}

    from app.models.shop import Shop
    shop = db.query(Shop).filter(
        Shop.id == row.shop_id, Shop.tenant_id == tenant_id
    ).first()
    if not shop:
        return {"code": ErrorCode.SHOP_NOT_FOUND, "msg": "店铺不存在"}

    # 识别"建议删除"：suggested_bid=0 AND adjust_pct=-100
    is_delete = (float(row.suggested_bid) == 0 and float(row.adjust_pct) == -100)
    final_bid = 0 if is_delete else (
        override_bid if override_bid is not None else float(row.suggested_bid)
    )

    client = _create_platform_client(shop)
    try:
        if is_delete:
            api_result = await _execute_bid_update(
                client, shop.platform, row.platform_campaign_id,
                row.platform_sku_id, 0, delete=True,
            )
        else:
            api_result = await _execute_bid_update(
                client, shop.platform, row.platform_campaign_id,
                row.platform_sku_id, final_bid,
            )
    finally:
        await client.close()

    if not api_result.get("ok"):
        return {"code": ErrorCode.BID_EXECUTION_FAILED,
                "msg": api_result.get("error") or "平台API失败"}

    now_utc = _utc_now().replace(tzinfo=None)
    db.execute(text("""
        UPDATE ai_pricing_suggestions
        SET status = 'approved', executed_at = :now
        WHERE id = :id AND tenant_id = :tenant_id
    """), {"id": suggestion_id, "tenant_id": tenant_id, "now": now_utc})

    from app.models.ad import AdCampaign
    campaign = db.query(AdCampaign).filter(
        AdCampaign.id == row.campaign_id, AdCampaign.tenant_id == tenant_id,
    ).first()
    final_adjust_pct = -100 if is_delete else (
        round((final_bid - float(row.current_bid)) / float(row.current_bid) * 100, 2)
        if float(row.current_bid) > 0 else 0
    )
    if not is_delete:
        _upsert_group_last_auto(db, campaign, row.platform_sku_id, row.sku_name or "", final_bid)
    else:
        # 删除操作：给 ad_groups 打 user_managed=1 锁，避免下次分析又对此 SKU 重复出建议
        db.execute(text("""
            UPDATE ad_groups
            SET user_managed = 1, user_managed_at = NOW()
            WHERE campaign_id = :cid AND platform_group_id = :sku
              AND tenant_id = :tid
        """), {
            "cid": row.campaign_id,
            "sku": row.platform_sku_id,
            "tid": tenant_id,
        })
    _write_bidlog(db, campaign, {
        "platform_sku_id": row.platform_sku_id, "sku_name": row.sku_name,
        "current_bid": float(row.current_bid), "suggested_bid": final_bid,
        "adjust_pct": final_adjust_pct, "product_stage": row.product_stage,
    }, "auto_remove" if is_delete else "ai_manual", success=True)
    db.commit()

    return {"code": 0, "data": {
        "id": suggestion_id, "status": "approved",
        "executed_at": now_utc.isoformat() + "Z",
        "old_bid": float(row.current_bid),
        "new_bid": 0 if is_delete else api_result.get("actual_bid_rub", final_bid),
        "suggested_bid": final_bid,
        "action": "remove" if is_delete else "update",
    }}


async def approve_batch(db, tenant_id: int, ids: list) -> dict:
    results = []
    success_cnt = failed_cnt = 0
    for sid in ids:
        try:
            r = await approve_suggestion(db, tenant_id, sid)
            if r.get("code") == 0:
                results.append({"id": sid, "status": "approved"})
                success_cnt += 1
            else:
                results.append({"id": sid, "status": "failed",
                                 "error_code": r.get("code"), "error_msg": r.get("msg")})
                failed_cnt += 1
        except Exception as e:
            results.append({"id": sid, "status": "failed",
                             "error_code": ErrorCode.BID_EXECUTION_FAILED,
                             "error_msg": str(e)})
            failed_cnt += 1
    return {"code": 0, "data": {
        "total": len(ids), "success": success_cnt,
        "failed": failed_cnt, "results": results,
    }}


def reject_suggestion(db, tenant_id: int, suggestion_id: int) -> dict:
    db.execute(text("""
        UPDATE ai_pricing_suggestions SET status = 'rejected'
        WHERE id = :id AND tenant_id = :tenant_id AND status = 'pending'
    """), {"id": suggestion_id, "tenant_id": tenant_id})
    db.commit()
    return {"code": 0, "data": {"id": suggestion_id, "status": "rejected"}}


def reject_batch(db, tenant_id: int, ids: list) -> dict:
    from sqlalchemy import bindparam
    if ids:
        stmt = text("""
            UPDATE ai_pricing_suggestions SET status = 'rejected'
            WHERE id IN :ids AND tenant_id = :tenant_id AND status = 'pending'
        """).bindparams(bindparam("ids", expanding=True))
        db.execute(stmt, {"ids": list(ids), "tenant_id": tenant_id})
        db.commit()
    return {"code": 0, "data": {"total": len(ids)}}


# ==================== SKU历史数据查询 ====================

def _query_sku_history(db, shop_id: int, tenant_id: int, platform: str) -> dict:
    today = date.today()
    boundaries = {
        "last5": (today - timedelta(days=5),  today),
        "prev5": (today - timedelta(days=10), today - timedelta(days=5)),
        "week2": (today - timedelta(days=14), today - timedelta(days=7)),
        "week3": (today - timedelta(days=21), today - timedelta(days=14)),
        "week4": (today - timedelta(days=28), today - timedelta(days=21)),
    }

    if platform == "wb":
        sku_col    = "s.ad_group_id"
        sku_filter = "AND s.ad_group_id IS NOT NULL"
    else:
        sku_col    = "COALESCE(s.ad_group_id, 0)"
        sku_filter = ""

    sql = f"""
        SELECT s.campaign_id,
               {sku_col} AS sku_id,
               CASE
                   WHEN s.stat_date >= :last5_from THEN 'last5'
                   WHEN s.stat_date >= :prev5_from THEN 'prev5'
                   WHEN s.stat_date >= :week2_from THEN 'week2'
                   WHEN s.stat_date >= :week3_from THEN 'week3'
                   WHEN s.stat_date >= :week4_from THEN 'week4'
                   ELSE 'older'
               END AS period,
               SUM(s.impressions) AS impressions,
               SUM(s.clicks)      AS clicks,
               SUM(s.spend)       AS spend,
               SUM(s.orders)      AS orders,
               SUM(s.revenue)     AS revenue,
               COUNT(DISTINCT s.stat_date) AS days
        FROM ad_stats s
        JOIN ad_campaigns c ON s.campaign_id = c.id
        WHERE c.shop_id   = :shop_id
          AND c.tenant_id = :tenant_id
          AND s.platform  = :platform
          AND s.stat_date >= :week4_from
          {sku_filter}
        GROUP BY s.campaign_id, {sku_col}, period
    """
    rows = db.execute(text(sql), {
        "shop_id": shop_id, "tenant_id": tenant_id, "platform": platform,
        "last5_from": boundaries["last5"][0],
        "prev5_from": boundaries["prev5"][0],
        "week2_from": boundaries["week2"][0],
        "week3_from": boundaries["week3"][0],
        "week4_from": boundaries["week4"][0],
    }).fetchall()

    raw = {}
    for r in rows:
        if r.period == "older":
            continue
        key = f"{r.campaign_id}_{r.sku_id}"
        if key not in raw:
            raw[key] = {}
        raw[key][r.period] = _calc_metrics(r)

    result = {}
    for key, periods in raw.items():
        l5    = periods.get("last5") or _empty_metrics()
        p5    = periods.get("prev5") or _empty_metrics()
        w2    = periods.get("week2") or _empty_metrics()
        w3    = periods.get("week3") or _empty_metrics()
        w4    = periods.get("week4") or _empty_metrics()
        total = _merge_metrics(p5, l5)

        if p5["days"] == 0 and l5["days"] == 0:
            trend = "new"
        elif p5["days"] < 3:
            trend = "new"
        elif l5["roas"] > p5["roas"] * 1.05:
            trend = "up"
        elif l5["roas"] < p5["roas"] * 0.95:
            trend = "down"
        else:
            trend = "stable"

        result[key] = {
            **total,
            "last5": l5, "prev5": p5,
            "week2": w2 if w2["days"] > 0 else None,
            "week3": w3 if w3["days"] > 0 else None,
            "week4": w4 if w4["days"] > 0 else None,
            "trend": trend,
        }

    return result


def _calc_metrics(r) -> dict:
    impressions = int(r.impressions or 0)
    clicks      = int(r.clicks or 0)
    spend       = float(r.spend or 0)
    orders      = int(r.orders or 0)
    revenue     = float(r.revenue or 0)
    return {
        "impressions": impressions, "clicks": clicks,
        "spend": round(spend, 2), "orders": orders,
        "revenue": round(revenue, 2),
        "ctr":  round(clicks / impressions * 100, 4) if impressions > 0 else 0,
        "cpc":  round(spend / clicks, 2) if clicks > 0 else 0,
        "cr":   round(orders / clicks * 100, 4) if clicks > 0 else 0,
        "roas": round(revenue / spend, 2) if spend > 0 else 0,
        "days": int(r.days),
    }


def _empty_metrics() -> dict:
    return {"impressions": 0, "clicks": 0, "spend": 0, "orders": 0,
            "revenue": 0, "ctr": 0, "cpc": 0, "cr": 0, "roas": 0, "days": 0}


def _merge_metrics(a: dict, b: dict) -> dict:
    impressions = a["impressions"] + b["impressions"]
    clicks      = a["clicks"] + b["clicks"]
    spend       = round(a["spend"] + b["spend"], 2)
    orders      = a["orders"] + b["orders"]
    revenue     = round(a["revenue"] + b["revenue"], 2)
    return {
        "impressions": impressions, "clicks": clicks,
        "spend": spend, "orders": orders, "revenue": revenue,
        "ctr":  round(clicks / impressions * 100, 4) if impressions > 0 else 0,
        "cpc":  round(spend / clicks, 2) if clicks > 0 else 0,
        "cr":   round(orders / clicks * 100, 4) if clicks > 0 else 0,
        "roas": round(revenue / spend, 2) if spend > 0 else 0,
        "days": a["days"] + b["days"],
    }


# ==================== 辅助函数 ====================

def _get_product_stage(data_days: int) -> str:
    if data_days < 14:
        return "cold_start"
    elif data_days < 35:
        return "testing"
    else:
        return "growing"


def _build_reason(platform, net_margin, client_price, max_cpa,
                  target_cpa, ctr, cr, current_bid, optimal_bid,
                  time_multiplier, day_multiplier, current_hour,
                  data_days, data_note,
                  breakeven_roas, current_roas) -> str:
    direction   = "加价" if optimal_bid > current_bid else "降价"
    weekday_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    msk = now_moscow()
    weekday_name = weekday_names[msk.weekday()]
    time_desc = (f"莫斯科{current_hour}时×{int(time_multiplier*100)}% "
                 f"{weekday_name}×{int(day_multiplier*100)}%")
    output_type = "CPM" if platform == "wb" else "CPC"
    parts = [
        f"净毛利率{int(net_margin*100)}%·客单价₽{client_price:.0f}",
        f"保本ROAS {breakeven_roas:.1f}x·当前ROAS {current_roas:.1f}x",
        f"目标CPA ₽{target_cpa:.0f}·最大CPA ₽{max_cpa:.0f}",
        f"CTR {ctr:.2f}%·CR {cr:.2f}%",
        f"→ {output_type} {direction} ₽{current_bid:.0f}→₽{optimal_bid:.0f}",
        f"时段: {time_desc}",
    ]
    if data_note:
        parts.insert(0, data_note)
    return " | ".join(parts)


# ==================== 平台抽象 ====================

def _create_platform_client(shop):
    if shop.platform == "ozon":
        from app.services.platform.ozon import OzonClient
        return OzonClient(
            shop_id=shop.id, api_key=shop.api_key, client_id=shop.client_id,
            perf_client_id=shop.perf_client_id or "",
            perf_client_secret=shop.perf_client_secret or "",
        )
    elif shop.platform == "wb":
        from app.services.platform.wb import WBClient
        return WBClient(shop_id=shop.id, api_key=shop.api_key)
    else:
        raise ValueError(f"不支持的平台: {shop.platform}")


async def _execute_bid_update(client, platform: str, campaign_id,
                              sku, suggested_bid_rub: float,
                              delete: bool = False) -> dict:
    """
    WB   → update_campaign_cpm（CPM 卢布直接传）
    Ozon → update_campaign_bid（CPC 需转 micro-rubles）
    delete=True → 删除该SKU出价记录
    """
    if delete:
        if platform == "wb":
            return await client.remove_campaign_product(
                advert_id=str(campaign_id), nm_id=int(sku),
            )
        else:
            return await client.remove_campaign_product(
                campaign_id=str(campaign_id), sku=str(sku),
            )

    if platform == "wb":
        return await client.update_campaign_cpm(
            advert_id=str(campaign_id),
            nm_id=int(sku),
            cpm_rub=suggested_bid_rub,
        )
    elif platform == "ozon":
        return await client.update_campaign_bid(
            campaign_id, str(sku),
            str(int(suggested_bid_rub * 1_000_000)),
        )
    else:
        return {"ok": False, "error": f"不支持的平台: {platform}"}


# ==================== 模板默认值 ====================

_DEFAULT_CONSERVATIVE = {"gross_margin": 0.27, "max_bid": 100, "max_adjust_pct": 15}
_DEFAULT_DEFAULT       = {"gross_margin": 0.27, "max_bid": 200, "max_adjust_pct": 30}
_DEFAULT_AGGRESSIVE    = {"gross_margin": 0.27, "max_bid": 400, "max_adjust_pct": 50}


def _read_template(cfg) -> dict:
    name = cfg.template_name or "default"
    raw  = getattr(cfg, f"{name}_config", None)
    if raw is None:
        raw = {}
    elif isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            raw = {}
    if not isinstance(raw, dict):
        raw = {}
    return raw


def _validate_template_json(t: dict) -> Optional[str]:
    try:
        if "gross_margin" in t and t.get("gross_margin") is not None:
            m = float(t["gross_margin"])
            if not (0 < m < 1):
                return "gross_margin 必须在 (0, 1) 开区间"
            return None
    except (KeyError, TypeError, ValueError) as e:
        return f"字段缺失或类型错误: {e}"
    return None


# ==================== Redis锁 ====================

def _try_acquire_analyze_lock(shop_id: int) -> bool:
    try:
        import redis as redis_lib
        pool = redis_lib.ConnectionPool.from_url(settings.REDIS_URL, decode_responses=True)
        r    = redis_lib.Redis(connection_pool=pool)
        return bool(r.set(f"bid:analyze_lock:{shop_id}", "1", nx=True, ex=ANALYZE_LOCK_TTL))
    except Exception as e:
        logger.warning(f"Redis锁不可用，降级直接执行: {e}")
        return True


def _release_analyze_lock(shop_id: int):
    try:
        import redis as redis_lib
        pool = redis_lib.ConnectionPool.from_url(settings.REDIS_URL, decode_responses=True)
        r    = redis_lib.Redis(connection_pool=pool)
        r.delete(f"bid:analyze_lock:{shop_id}")
    except Exception:
        pass


# ==================== 写库小工具 ====================

def _upsert_group_last_auto(db, campaign, sku: str, sku_name: str, last_auto: float):
    db.execute(text("""
        INSERT INTO ad_groups (
            tenant_id, campaign_id, platform_group_id, name,
            last_auto_bid, status
        ) VALUES (
            :tenant_id, :campaign_id, :sku, :name, :last_auto, 'active'
        )
        ON DUPLICATE KEY UPDATE
            name          = VALUES(name),
            last_auto_bid = :last_auto,
            updated_at    = NOW()
    """), {
        "tenant_id": campaign.tenant_id, "campaign_id": campaign.id,
        "sku": sku, "name": sku_name[:200] if sku_name else f"SKU-{sku}",
        "last_auto": last_auto,
    })


def _write_bidlog(db, campaign, suggestion: dict, execute_type: str,
                  success: bool = True, error: str = None):
    db.execute(text("""
        INSERT INTO bid_adjustment_logs (
            tenant_id, shop_id, campaign_id, campaign_name,
            platform_sku_id, sku_name,
            old_bid, new_bid, adjust_pct,
            execute_type, product_stage, moscow_hour,
            success, error_msg, created_at
        ) VALUES (
            :tenant_id, :shop_id, :campaign_id, :campaign_name,
            :sku, :sku_name,
            :old_bid, :new_bid, :pct,
            :execute_type, :stage, :hour,
            :success, :error, NOW()
        )
    """), {
        "tenant_id":    campaign.tenant_id,
        "shop_id":      campaign.shop_id,
        "campaign_id":  campaign.id,
        "campaign_name": campaign.name,
        "sku":     suggestion["platform_sku_id"],
        "sku_name": (suggestion.get("sku_name") or "")[:300] or None,
        "old_bid":  suggestion["current_bid"],
        "new_bid":  suggestion["suggested_bid"],
        "pct":      suggestion.get("adjust_pct") or 0,
        "execute_type": execute_type,
        "stage":   suggestion.get("product_stage") or "unknown",
        "hour":    moscow_hour(),
        "success": 1 if success else 0,
        "error":   (error or "")[:500] if error else None,
    })


def _update_status(db, tenant_id: int, shop_id: int,
                   status: str, msg: str, retry: bool = False):
    db.execute(text("""
        UPDATE ai_pricing_configs
        SET last_executed_at    = NOW(),
            last_execute_status = :status,
            last_error_msg      = :msg,
            retry_at = CASE
                WHEN :retry = 1
                THEN DATE_ADD(NOW(), INTERVAL 30 MINUTE)
                ELSE NULL
            END
        WHERE shop_id = :shop_id AND tenant_id = :tenant_id
    """), {
        "shop_id": shop_id, "tenant_id": tenant_id,
        "status": status,
        "msg":    msg[:500] if msg else None,
        "retry":  1 if retry else 0,
    })
    db.commit()
