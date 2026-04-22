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
from app.services.ai.stage_detector import ProductStage, detect_product_stage
from app.utils.errors import ErrorCode
from app.utils.logger import setup_logger
from app.utils.moscow_time import moscow_hour, moscow_today, now_moscow

logger = setup_logger("bid.ai_pricing_executor")
settings = get_settings()

MIN_BID = 3
MIN_DIFF = 1
ANALYZE_LOCK_TTL = 60

# 时段系数表（莫斯科时间，24小时）
# 2026-04-22 用户调整：抬高低谷段，避免凌晨腰斩触发平台最低价兜底
#   0-4:  0.50 → 0.70 (凌晨低谷)
#   5-6:  0.60 → 0.80 (清晨过渡)
#   23:   0.65 → 0.80 (深夜)
# 高峰段（10-13 上午 / 19-22 晚高峰）保持不变
TIME_SLOT_MULTIPLIERS = {
    0: 0.70, 1: 0.70, 2: 0.70, 3: 0.70, 4: 0.70,
    5: 0.80, 6: 0.80,
    7: 1.05, 8: 1.05, 9: 1.05,
    10: 1.10, 11: 1.10, 12: 1.10, 13: 1.10,
    14: 1.00, 15: 1.00, 16: 1.00, 17: 1.00, 18: 1.00,
    19: 1.20, 20: 1.20, 21: 1.20, 22: 1.20,
    23: 0.80,
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


# ==================== 利润最大化决策（主决策器） ====================

def _profit_max_decision(current_roas: float, breakeven_roas: float,
                         data_days: int, trend: str,
                         max_adjust_pct: float = 30.0) -> dict:
    """利润最大化决策：以 current_roas/breakeven 比值为锚，决定是否调价 + 方向 + 幅度。

    核心原则：利润 = Revenue × net_margin - Spend = (ROAS × net_margin - 1) × Spend
    - ROAS > breakeven (=1/net_margin)：spend 越多利润越多（但有边际递减）
    - ROAS < breakeven：spend 越多亏越多
    - 利润最大点不在 ROAS 极大处，而在 ROAS 略高于 breakeven 的"甜点区"

    分档规则（ratio = current_roas / breakeven_roas）：
    - ratio < 0.5  → 严重亏损，big_down -30%（或 max_adjust_pct）
    - ratio < 1.0  → 亏损，small_down -15%
    - 1.0 ≤ ratio ≤ 1.5  → 利润最大化甜点区，no_change（不修没坏的）
    - ratio > 1.5 + 趋势 up/stable → small_up +5% 试探
    - ratio > 1.5 + 趋势 down → no_change（高位但下行不冒险）

    数据不足（<7天）：偏保守 — 已盈利不动，亏损小幅降。

    Returns: {action, multiplier, reason}
      action ∈ {"no_change", "small_up", "small_down", "big_down", "skip"}
    """
    if not breakeven_roas or breakeven_roas <= 0:
        return {"action": "skip", "multiplier": 1.0,
                "reason": "无法算保本ROAS（净毛利率缺失）"}

    if current_roas is None or current_roas < 0:
        return {"action": "skip", "multiplier": 1.0, "reason": "无 ROAS 历史"}

    # Bug 3 修：trend='insufficient' 数据不足判趋势 → skip
    # Bug 1 修后会出现这个新档（last5<3 天 或 全 5 段都找不到 baseline）
    # 数据不足时连"亏不亏"都判不准，干脆不动比"小降"更稳妥
    if trend == "insufficient":
        return {"action": "skip", "multiplier": 1.0,
                "reason": "数据不足判趋势（动态扩窗到 28 天仍无足够 baseline），先观察不动"}

    # Bug 2 修：ROAS 异常高视为样本不足
    # 真健康商品 ROAS 通常 5-25x，极个别爆款 30-40x
    # 超 50x 几乎肯定是"1 次点击 + 1 单大订单"的偶然 → 不基于偶然加价烧钱
    # 正常的健康加价场景（ROAS 5-50x）不受影响
    if current_roas > 50:
        return {"action": "skip", "multiplier": 1.0,
                "reason": f"ROAS {current_roas:.1f}x>50x 视为样本不足（偶然爆单），先观察不动"}

    # 数据不足兜底：偏保守
    if data_days < 7:
        if current_roas == 0:
            return {"action": "skip", "multiplier": 1.0,
                    "reason": f"数据{data_days}天且无订单，先观察不调价"}
        if current_roas >= breakeven_roas:
            return {"action": "no_change", "multiplier": 1.0,
                    "reason": f"数据少{data_days}天 但当前 ROAS {current_roas:.2f}x ≥ 保本 {breakeven_roas:.2f}x，先观察不动"}
        return {"action": "small_down", "multiplier": 0.85,
                "reason": f"数据少{data_days}天 当前 ROAS {current_roas:.2f}x < 保本 {breakeven_roas:.2f}x，谨慎降价 -15%"}

    if current_roas == 0:
        return {"action": "small_down", "multiplier": 0.7,
                "reason": f"{data_days}天0订单，主动降价 -30% 减少烧钱"}

    ratio = current_roas / breakeven_roas

    if ratio < 0.5:
        # 严重亏损 — 大降，受 max_adjust_pct 上限保护
        mult = 1.0 - min(max_adjust_pct, 30.0) / 100.0
        return {"action": "big_down", "multiplier": mult,
                "reason": f"严重亏损 ROAS {current_roas:.2f}x < 保本 {breakeven_roas:.2f}x × 0.5，大降 {(1-mult)*100:.0f}%"}
    if ratio < 1.0:
        return {"action": "small_down", "multiplier": 0.85,
                "reason": f"亏损 ROAS {current_roas:.2f}x < 保本 {breakeven_roas:.2f}x，降价 -15% 减耗等改善"}
    if ratio <= 1.5:
        return {"action": "no_change", "multiplier": 1.0,
                "reason": f"利润最大化甜点区 ROAS {current_roas:.2f}x（保本 {breakeven_roas:.2f}x×1.0~1.5），不动"}

    # ratio > 1.5 — 远超保本
    if trend == "down":
        return {"action": "no_change", "multiplier": 1.0,
                "reason": f"ROAS {current_roas:.2f}x 偏高但下降趋势，不冒险加价等观察"}
    return {"action": "small_up", "multiplier": 1.05,
            "reason": f"ROAS {current_roas:.2f}x 远超保本 {breakeven_roas:.2f}x×1.5，小幅 +5% 试探多赚总额"}


# ==================== 方案 E 爬山法决策器（>=21天 SKU） ====================
# 核心：每天滑动评估"过去3天利润 vs 再前3天利润"，涨保持方向、跌反转+步长减半
# base 每天最多动 1 次（凌晨评估），白天每小时按 base × 时段系数 × 周末系数 出价
# 详细设计见 docs/daily/2026-04-21_工作内容_老林.md §13-§14

HILL_STEP_SEQUENCE = [0.20, 0.10, 0.05, 0.02]  # 步长收敛序列
HILL_PROFIT_TIE_THRESHOLD = 20.0  # 持平阈值 ₽20（用户拍）
HILL_ROAS_ANOMALY = 50.0          # ROAS > 50x 视为样本不足（与 _profit_max_decision Bug2 一致）
HILL_SKIP_REEVAL_HOURS = 23       # 一天 1 次评估护栏：距上次评估 < 23h 跳过 base 重算（防 Celery 24次/天 + 用户多点 analyze_now 击穿设计假设）


def _calc_profit_window(db, tenant_id: int, campaign_id: int, sku: str,
                        date_from, date_to, margin: float) -> tuple:
    """算指定日期窗口的利润。
    返回 (profit_rub, days_with_data)
    """
    rr = db.execute(text("""
        SELECT COUNT(DISTINCT stat_date) AS d,
               COALESCE(SUM(spend), 0)   AS s,
               COALESCE(SUM(revenue), 0) AS rv
        FROM ad_stats
        WHERE tenant_id=:tid AND campaign_id=:cid
          AND ad_group_id=:sku
          AND stat_date BETWEEN :df AND :dt
    """), {"tid": tenant_id, "cid": campaign_id, "sku": sku,
           "df": date_from, "dt": date_to}).fetchone()
    days = int(rr.d or 0)
    spend = float(rr.s or 0)
    revenue = float(rr.rv or 0)
    profit = revenue * margin - spend
    return profit, days


# 噪声日清洗阈值（用户拍 2026-04-22）
HEALTHY_DAY_ROAS_MAX = 50.0   # 当天 ROAS>50 视为大单噪声，剔除
HEALTHY_DAY_SPEND_MIN = 10.0  # 当天 spend<₽10 视为投入太少，剔除


def _calc_healthy_window_metrics(db, tenant_id: int, campaign_id: int, sku: str,
                                  recent_n: int, skip_n: int = 0) -> tuple:
    """剔除噪声日后，取从近到远第 skip_n+1 ~ skip_n+recent_n 个健康天的聚合数据。
    噪声定义：当天 ROAS > 50（大单）或 spend < ₽10（投入太少）。
    用于 cold-start"凑齐健康 5 天"和日评估"凑齐健康 3 天"。
    返回 (spend_sum, revenue_sum, days_count)
    """
    today = date.today()
    rows = db.execute(text("""
        SELECT stat_date,
               COALESCE(SUM(spend), 0)   AS spend,
               COALESCE(SUM(revenue), 0) AS rev
        FROM ad_stats
        WHERE tenant_id=:tid AND campaign_id=:cid AND ad_group_id=:sku
          AND stat_date >= :since
        GROUP BY stat_date ORDER BY stat_date DESC
    """), {"tid": tenant_id, "cid": campaign_id, "sku": sku,
           "since": today - timedelta(days=28)}).fetchall()

    healthy = []
    for r in rows:
        spend = float(r.spend or 0)
        rev   = float(r.rev or 0)
        roas  = rev / spend if spend > 0 else 0
        if roas <= HEALTHY_DAY_ROAS_MAX and spend >= HEALTHY_DAY_SPEND_MIN:
            healthy.append({"spend": spend, "rev": rev})

    target = healthy[skip_n : skip_n + recent_n]
    sp = sum(d["spend"] for d in target)
    rv = sum(d["rev"]   for d in target)
    return sp, rv, len(target)


def _calc_healthy_window_full(db, tenant_id: int, campaign_id: int, sku: str,
                               recent_n: int, skip_n: int = 0) -> dict:
    """同 _calc_healthy_window_metrics 但返回完整指标 (含 impressions/clicks/orders)
    用于商品阶段 Tooltip 展示近 5 健康天的 CTR / CR / 利润。
    返回 dict: {spend, revenue, impressions, clicks, orders, days}
    """
    today = date.today()
    rows = db.execute(text("""
        SELECT stat_date,
               COALESCE(SUM(impressions), 0) AS imp,
               COALESCE(SUM(clicks), 0)      AS clk,
               COALESCE(SUM(spend), 0)       AS spend,
               COALESCE(SUM(orders), 0)      AS ord,
               COALESCE(SUM(revenue), 0)     AS rev
        FROM ad_stats
        WHERE tenant_id=:tid AND campaign_id=:cid AND ad_group_id=:sku
          AND stat_date >= :since
        GROUP BY stat_date ORDER BY stat_date DESC
    """), {"tid": tenant_id, "cid": campaign_id, "sku": sku,
           "since": today - timedelta(days=28)}).fetchall()

    healthy = []
    for r in rows:
        spend = float(r.spend or 0)
        rev   = float(r.rev or 0)
        roas  = rev / spend if spend > 0 else 0
        if roas <= HEALTHY_DAY_ROAS_MAX and spend >= HEALTHY_DAY_SPEND_MIN:
            healthy.append({
                "spend": spend, "rev": rev,
                "imp": int(r.imp or 0), "clk": int(r.clk or 0), "ord": int(r.ord or 0),
            })

    target = healthy[skip_n : skip_n + recent_n]
    return {
        "spend":       sum(d["spend"] for d in target),
        "revenue":     sum(d["rev"]   for d in target),
        "impressions": sum(d["imp"]   for d in target),
        "clicks":      sum(d["clk"]   for d in target),
        "orders":      sum(d["ord"]   for d in target),
        "days":        len(target),
    }


def _save_hill_state(db, tenant_id: int, campaign_id: int, sku: str,
                     base_bid: float, direction: int, step_size: float):
    """写 hill 状态到 ad_groups（INSERT OR UPDATE）。
    UNIQUE KEY = (campaign_id, platform_group_id)
    INSERT 时补 name=sku 字段（NOT NULL 约束），UPDATE 时不动 name。
    """
    db.execute(text("""
        INSERT INTO ad_groups (
            tenant_id, campaign_id, platform_group_id, name,
            hill_base_bid, hill_step_direction, hill_step_size, hill_last_eval_at
        ) VALUES (
            :tid, :cid, :sku, :sku,
            :base, :dir, :step, UTC_TIMESTAMP()
        )
        ON DUPLICATE KEY UPDATE
            tenant_id = :tid,
            hill_base_bid       = :base,
            hill_step_direction = :dir,
            hill_step_size      = :step,
            hill_last_eval_at   = UTC_TIMESTAMP()
    """), {"tid": tenant_id, "cid": campaign_id, "sku": sku,
           "base": round(base_bid, 2), "dir": direction, "step": step_size})


def _cold_start_direction(sku_stat: dict, breakeven_roas: float) -> tuple:
    """冷启动决策树（按 §11.5 §14.3）：近期优先，不被整体均值误导。
    返回 (direction_pct, reason)
      direction_pct: -0.10 / -0.05 / 0 / +0.10 / +0.15 / +0.20
    """
    l5 = sku_stat.get("last5") or _empty_metrics()
    p5 = sku_stat.get("prev5") or _empty_metrics()
    overall_roas = sku_stat.get("roas") or 0

    l5_d = int(l5.get("days", 0))
    p5_d = int(p5.get("days", 0))
    l5_s = float(l5.get("spend", 0) or 0)
    l5_roas = float(l5.get("roas", 0) or 0)
    p5_roas = float(p5.get("roas", 0) or 0)

    # Step 1 数据质量
    if l5_d < 3 and p5_d < 3:
        return 0, f"数据不足(l5d={l5_d},p5d={p5_d})持平观察"
    if l5_d < 3:
        return -0.05, f"l5不足({l5_d}天)谨慎-5%"

    # Step 2 近期优先（修复核心：忽略 last5 恶化是关键 bug）
    if l5_s > 10 and breakeven_roas > 0 and l5_roas < breakeven_roas:
        return -0.10, f"l5亏损(roas={l5_roas:.2f}<be={breakeven_roas:.2f})-10%减耗"
    if p5_roas > 0:
        ratio = l5_roas / p5_roas
        if ratio < 0.5:
            return -0.05, f"l5/p5={ratio:.2f}跌>50%,-5%"
        if ratio < 0.8:
            return 0, f"跌幅20-50%持平观察"

    # Step 3 整体 ROAS 加价
    if overall_roas >= 5.0:
        return 0.20, f"ROAS{overall_roas:.2f}≥5x,+20%"
    if overall_roas >= 3.5:
        return 0.15, f"ROAS{overall_roas:.2f}≥3.5x,+15%"
    if overall_roas >= 2.5:
        return 0.10, f"ROAS{overall_roas:.2f}≥2.5x,+10%"
    return 0, f"ROAS{overall_roas:.2f}<2.5x持平"


def _hill_climbing_decision(db, tenant_id: int, campaign_id: int, sku: str,
                            current_bid: float, sku_stat: dict,
                            breakeven_roas: float, margin: float,
                            time_multiplier: float, day_multiplier: float) -> dict:
    """方案 E 爬山法主决策。

    Returns: {action, optimal_bid, new_base, reason}
      action ∈ {"cold_start", "climb", "hold", "skip"}
      optimal_bid = 应用时段+周末系数后的最终出价（int）
      new_base = 更新后的 base（已存到 ad_groups）
    """
    # ROAS 异常守卫（与 _profit_max_decision Bug2 一致）
    overall_roas = float(sku_stat.get("roas") or 0)
    if overall_roas > HILL_ROAS_ANOMALY:
        return {"action": "skip", "optimal_bid": int(current_bid), "new_base": None,
                "reason": f"ROAS {overall_roas:.1f}x>{HILL_ROAS_ANOMALY}x 偶然爆单视为样本不足，先观察"}

    # 算近 5 健康天指标（用于 reason 末尾展示，前端 Tooltip parse）
    # 0 schema 改动方案：把数据塞进 reason 字符串末尾
    rw = _calc_healthy_window_full(db, tenant_id, campaign_id, sku, 5, 0)
    if rw["impressions"] > 0:
        r_ctr = rw["clicks"]  / rw["impressions"]
        r_cr  = rw["orders"]  / rw["clicks"] if rw["clicks"] > 0 else 0
        r_pft = rw["revenue"] * margin - rw["spend"]
        recent_seg = (f" | [recent5d: ctr={r_ctr*100:.2f}% cr={r_cr*100:.2f}% "
                      f"profit={r_pft:+.0f} days={rw['days']}]")
    else:
        recent_seg = " | [recent5d: 无健康天数据]"

    # 1. 读 hill 状态
    row = db.execute(text("""
        SELECT hill_base_bid, hill_step_direction, hill_step_size, hill_last_eval_at
        FROM ad_groups
        WHERE tenant_id=:tid AND campaign_id=:cid AND platform_group_id=:sku
        LIMIT 1
    """), {"tid": tenant_id, "cid": campaign_id, "sku": sku}).fetchone()

    is_cold_start = (row is None or row.hill_base_bid is None)

    if is_cold_start:
        # 用"剔除噪声后凑齐健康 5 天 vs 再前 5 天"的 ROAS 对比替代固定窗口
        # 修复：原 last5/prev5 用固定日期段，会被"几乎没投放但偶然中单"的噪声日骗（如 prev5 spend=6.77 ROAS=397x）
        sp_l5, rv_l5, d_l5    = _calc_healthy_window_metrics(db, tenant_id, campaign_id, sku, 5, 0)
        sp_p5, rv_p5, d_p5    = _calc_healthy_window_metrics(db, tenant_id, campaign_id, sku, 5, 5)
        sp_all, rv_all, d_all = _calc_healthy_window_metrics(db, tenant_id, campaign_id, sku, 28, 0)
        sku_stat_clean = {
            **sku_stat,
            "last5": {"days": d_l5, "spend": sp_l5,
                      "roas": rv_l5 / sp_l5 if sp_l5 > 0 else 0},
            "prev5": {"days": d_p5, "spend": sp_p5,
                      "roas": rv_p5 / sp_p5 if sp_p5 > 0 else 0},
            "roas":  rv_all / sp_all if sp_all > 0 else 0,
        }
        direction_pct, reason = _cold_start_direction(sku_stat_clean, breakeven_roas)
        new_base = max(current_bid * (1 + direction_pct), MIN_BID)
        new_direction = 1 if direction_pct >= 0 else -1
        _save_hill_state(db, tenant_id, campaign_id, sku, new_base,
                         new_direction, 0.20)  # 起步步长固定 20%
        optimal_bid = int(round(new_base * time_multiplier * day_multiplier))
        return {"action": "cold_start", "optimal_bid": max(optimal_bid, MIN_BID),
                "new_base": new_base,
                "reason": f"冷启动: {reason} → base ₽{current_bid:.0f}→₽{new_base:.0f}（×时段{time_multiplier}×周末{day_multiplier}）" + recent_seg}

    base = float(row.hill_base_bid)
    direction = int(row.hill_step_direction or 1)
    step_size = float(row.hill_step_size or 0.20)

    # 一天 1 次评估护栏（2026-04-22 修：防 Celery 每小时跑 + 用户多点 analyze_now 触发 N 次评估）
    # 设计假设：base 一天最多动 1 次（凌晨爬山），白天每小时只做时段叠加
    # 实证 sku 498605688 在 21h 内被评估 5 次，base 从 ₽33→₽22 + step 从 0.20→0.05
    if row.hill_last_eval_at is not None:
        # _save_hill_state 用 UTC_TIMESTAMP() 写入，这里用 utc naive 比较（MySQL 返回 naive datetime）
        now_utc_naive = datetime.now(timezone.utc).replace(tzinfo=None)
        hours_since = (now_utc_naive - row.hill_last_eval_at).total_seconds() / 3600
        if 0 <= hours_since < HILL_SKIP_REEVAL_HOURS:
            optimal_bid = int(round(base * time_multiplier * day_multiplier))
            return {"action": "hold_today", "optimal_bid": max(optimal_bid, MIN_BID),
                    "new_base": base,
                    "reason": (f"今日已评估({hours_since:.1f}h前) base ₽{base:.0f}不动 "
                               f"方向{'+1' if direction>0 else '-1'} 步长{step_size*100:.0f}% "
                               f"→ ×时段{time_multiplier}×周末{day_multiplier} = ₽{optimal_bid}") + recent_seg}

    # 2. 滑动评估："剔除噪声后凑齐健康 3 天 vs 再前 3 天"的利润对比
    # 修复：原固定"过去3天 vs 再前3天"在投放断续场景下两边都接近 0，会被微小绝对差骗判涨
    sp_recent, rv_recent, recent_d = _calc_healthy_window_metrics(
        db, tenant_id, campaign_id, sku, 3, 0)
    sp_prev,   rv_prev,   prev_d   = _calc_healthy_window_metrics(
        db, tenant_id, campaign_id, sku, 3, 3)
    p_recent = rv_recent * margin - sp_recent
    p_prev   = rv_prev   * margin - sp_prev

    # 数据缺失保护：任一窗口无数据 → hold（base 不动）
    if recent_d == 0 or prev_d == 0:
        optimal_bid = int(round(base * time_multiplier * day_multiplier))
        return {"action": "hold", "optimal_bid": max(optimal_bid, MIN_BID),
                "new_base": base,
                "reason": f"数据不足(recent_d={recent_d},prev_d={prev_d})保持base ₽{base:.0f}" + recent_seg}

    profit_diff = p_recent - p_prev

    # 持平阈值（用户拍 ₽20 绝对值）
    if abs(profit_diff) < HILL_PROFIT_TIE_THRESHOLD:
        # 全保持上次（方向/步长/base 不动），不更新 last_eval_at
        optimal_bid = int(round(base * time_multiplier * day_multiplier))
        return {"action": "hold", "optimal_bid": max(optimal_bid, MIN_BID),
                "new_base": base,
                "reason": f"利润持平(差₽{profit_diff:+.0f}<阈值₽{HILL_PROFIT_TIE_THRESHOLD:.0f}) base ₽{base:.0f}不动" + recent_seg}

    # 涨/跌
    if profit_diff > 0:
        # 利润涨 → 保持方向，步长不变
        new_direction = direction
        new_step_size = step_size
        change_label = "涨"
    else:
        # 利润跌 → 反转方向，步长减半（最低 0.02）
        new_direction = -direction
        new_step_size = max(step_size / 2, 0.02)
        change_label = "跌"

    new_base = max(base * (1 + new_direction * new_step_size), MIN_BID)
    _save_hill_state(db, tenant_id, campaign_id, sku, new_base,
                     new_direction, new_step_size)
    optimal_bid = int(round(new_base * time_multiplier * day_multiplier))
    return {"action": "climb", "optimal_bid": max(optimal_bid, MIN_BID),
            "new_base": new_base,
            "reason": f"利润{change_label}(差₽{profit_diff:+.0f}) 方向{'+1' if new_direction>0 else '-1'} 步长{new_step_size*100:.0f}% base ₽{base:.0f}→₽{new_base:.0f}" + recent_seg}


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
            # 把 _analyze_now_inner 包成 task，期间每 10s 发 SSE comment 行心跳
            # 防止 nginx upstream 60s 闲置 timeout 切断流（27 SKU + WB API 易跑 60-90s）
            # 实证 nginx error.log 13:09/13:25 两次 "upstream timed out (110)"
            inner_task = _asyncio.create_task(
                _analyze_now_inner(db, tenant_id, shop_id,
                                   force=True, campaign_ids=campaign_ids)
            )
            while not inner_task.done():
                try:
                    await _asyncio.wait_for(_asyncio.shield(inner_task), timeout=10.0)
                except _asyncio.TimeoutError:
                    yield ": keepalive\n\n"  # SSE comment 行，前端忽略，仅维持连接
            result = inner_task.result()
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
    all_campaigns = q.all()

    # 按付费类型过滤：AI 调价公式只支持 WB=CPM 和 Ozon=CPC
    # 其他（WB-CPC / Ozon-CPM / Ozon-CPO）公式不匹配，先排除避免误操作
    SUPPORTED_PT = {"wb": "cpm", "ozon": "cpc"}
    supported = SUPPORTED_PT.get(platform)
    campaigns = [
        c for c in all_campaigns
        if (getattr(c, "payment_type", None) or supported) == supported
    ]
    skipped_pt = len(all_campaigns) - len(campaigns)
    if skipped_pt > 0:
        logger.info(
            f"shop_id={shop_id} 跳过{skipped_pt}个付费类型不支持的活动"
            f"（{platform} 只处理 payment_type={supported}）"
        )

    if not campaigns:
        msg = (f"无活跃活动（{platform}仅支持 {supported} 付费类型）"
               if skipped_pt else "无活跃活动")
        _update_status(db, tenant_id, shop_id, "success", msg)
        return {"status": "success", "message": msg,
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

    # ── Ozon 预取全局最低CPC（每次分析拉一次，所有SKU复用） ──
    ozon_min_cpc = None
    if platform == "ozon":
        try:
            import httpx
            from app.services.platform.ozon import (
                _extract_ozon_min_bid, OZON_PERFORMANCE_API,
            )
            await client._ensure_perf_token()
            async with httpx.AsyncClient(
                headers={"Authorization": f"Bearer {client._perf_token}"},
                timeout=30.0,
            ) as _c:
                _r = await _c.get(f"{OZON_PERFORMANCE_API}/api/client/limits/list")
                if _r.status_code == 200:
                    _limits_data = _r.json()
                    ozon_min_cpc = _extract_ozon_min_bid(
                        _limits_data,
                        placement="CAMPAIGN_PLACEMENT_SEARCH_AND_CATEGORY",
                        payment_method="CPC",
                    )
                    logger.info(f"Ozon 最低CPC预取: ₽{ozon_min_cpc}")
        except Exception as e:
            logger.warning(f"Ozon 最低CPC预取失败: {e}")

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

            # ── Step 0: 查询 user_managed（"忽略" 状态） ──
            ag_check = db.execute(text("""
                SELECT user_managed FROM ad_groups
                WHERE campaign_id = :cid AND platform_group_id = :sku
                  AND tenant_id = :tid LIMIT 1
            """), {"cid": camp.id, "sku": sku, "tid": tenant_id}).fetchone()
            is_ignored_sku = bool(ag_check and ag_check.user_managed)

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
                    # 被忽略的 SKU 不参与自动删除，但仍写建议列表提示
                    if (cfg.auto_remove_losing_sku and cfg.auto_execute
                            and not is_ignored_sku):
                        # 全自动删除
                        removed = await _check_and_remove_losing_sku(
                            db, client, shop, camp, sku, sku_name,
                            current_bid, tenant_id, sku_stat,
                        )
                        if removed:
                            auto_removed += 1
                            continue
                    else:
                        # 写建议列表（无论 auto_remove/auto_execute/is_ignored 设置）
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

            # ── Step 1.5: 决策器 dispatch（2026-04-21 方案 E 引入分流） ──
            # data_days >= 21: 走爬山法（_hill_climbing_decision，方案 E）
            # data_days <  21: 走 _profit_max_decision（Step 1 已修 3 bug）
            current_roas = sku_stat.get("roas") or 0
            trend = sku_stat.get("trend", "stable")
            # cfg.default_config 在 DB 是 TEXT 存 JSON，可能是 dict 或 str
            _dc = getattr(cfg, 'default_config', None)
            if isinstance(_dc, str):
                try:
                    _dc = json.loads(_dc)
                except Exception:
                    _dc = {}
            elif not isinstance(_dc, dict):
                _dc = {}
            try:
                max_adjust_pct_cfg = float(_dc.get("max_adjust_pct") or 30)
            except (TypeError, ValueError):
                max_adjust_pct_cfg = 30.0

            if data_days >= 21:
                # 方案 E 爬山法（每天滑动评估，base × 时段系数 × 周末系数）
                hill_decision = _hill_climbing_decision(
                    db, tenant_id, camp.id, sku, current_bid, sku_stat,
                    breakeven_roas, net_margin,
                    time_multiplier, day_multiplier,
                )
                if hill_decision["action"] == "skip":
                    logger.info(f"sku={sku} 爬山法跳过：{hill_decision['reason']}")
                    continue
                optimal_bid = max(hill_decision["optimal_bid"], MIN_BID)
                data_note = hill_decision["reason"]
            else:
                # 老 _profit_max_decision（Step 1 已修 3 bug：trend动态窗口/ROAS>50/insufficient）
                pm_decision = _profit_max_decision(
                    current_roas=current_roas, breakeven_roas=breakeven_roas,
                    data_days=data_days, trend=trend, max_adjust_pct=max_adjust_pct_cfg,
                )
                if pm_decision["action"] == "no_change" or pm_decision["action"] == "skip":
                    logger.info(f"sku={sku} 利润决策跳过：{pm_decision['reason']}")
                    continue
                # 决策直接给出新出价：current_bid × multiplier
                optimal_bid = int(round(current_bid * pm_decision["multiplier"]))
                if optimal_bid < MIN_BID:
                    optimal_bid = MIN_BID
                data_note = pm_decision["reason"]

            # 冷启动 / 利润策略不需要 CPA 公式重算，但保留 CTR/CR 计算供后续 expected_roas 等用
            # ── Step 2 (legacy): 选取 CTR/CR 来源（旧 CPA 公式备用，仅供 expected_roas 兜底） ──
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

            # ── Step 3-4: 已被利润最大化决策器替代（见 Step 1.5）──
            # optimal_bid 已在 Step 1.5 由 _profit_max_decision 给出
            # 仍计算 target_cpa 给 reason 文案用
            sku_cpa_ratio = None
            if data_days >= 21:
                sku_cpa_ratio = _get_sku_cpa_ratio(db, tenant_id, camp.id, sku)
            cpa_ratio, _ = _get_cpa_ratio(data_days, sku_cpa_ratio)
            target_cpa = max_cpa * cpa_ratio

            # ── Step 5: 平台"推荐竞争价"警告 + 降价反拉保护 ──
            # /bids/min API 返回的是"推荐竞争价"（实测常与硬最低一致）
            # 策略：
            #   - 不拉升 suggested_bid（保留算法值）
            #   - 低于推荐价时加警告
            #   - 关键保护：想降价但被硬卡拉更高时 → 跳过此 SKU
            #   - bid_adjustment_logs 写 actual_bid_rub（执行真实值）
            min_bid_warning = ""
            platform_min = None
            if optimal_bid is not None and platform == "wb":
                try:
                    platform_min = await client.fetch_min_bid(
                        advert_id=str(camp.platform_campaign_id),
                        nm_id=int(sku),
                    )
                except Exception as e:
                    logger.warning(f"WB 最低价查询异常 sku={sku}: {e}")
            elif optimal_bid is not None and platform == "ozon":
                platform_min = ozon_min_cpc

            # 降价反拉保护：想降价但平台最低价 > 当前价
            # → 提交会被拉到更高值，放弃调整
            if (platform_min and optimal_bid is not None
                    and optimal_bid < current_bid
                    and platform_min > current_bid):
                logger.info(
                    f"降价反拉保护：sku={sku} 想降 {current_bid}→{optimal_bid} "
                    f"但平台最低={platform_min}，降了会被拉更高，跳过"
                )
                continue

            # 低于平台最低价时加警告（不改 optimal_bid）
            if platform_min and optimal_bid is not None and optimal_bid < platform_min:
                src = "WB" if platform == "wb" else "Ozon"
                min_bid_warning = (
                    f"⚠ 低于{src}平台最低价₽{int(platform_min)}，"
                    f"执行时可能被拉升至 ₽{int(platform_min)}"
                )

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
                "stage": _detect_stage(sku_stat, data_days, breakeven_roas),
                "basis": ("history_data" if data_days >= 21
                          else "shop_benchmark" if data_days < 7
                          else "history_data"),
                "current_roas": round(current_roas, 2) if current_roas else None,
                "expected_roas": (
                    # Bug C 修：纯数学外推（current_roas × current_bid / new_bid）
                    # 假设 CTR/CR 不变，但实际降价大幅 → 曝光排不上 → 订单暴跌，
                    # ROAS 不可能像数学公式那样涨 25 倍。给上限防误导：
                    # 改善幅度封顶 50%（即 expected ≤ current × 1.5）
                    min(
                        round(current_roas * current_bid / optimal_bid, 2),
                        round(current_roas * 1.5, 2),
                    )
                    if optimal_bid > 0 and current_roas and current_bid > 0
                    # 无历史 ROAS 时降级用公式预测
                    else (
                        round(
                            (ctr / 100) * (cr / 100) * client_price * 1000 / optimal_bid
                            if platform == "wb"
                            else (cr / 100) * client_price / optimal_bid,
                            2,
                        )
                        if optimal_bid > 0 and client_price > 0 and ctr > 0 and cr > 0
                        else None
                    )
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
                "product_stage": _detect_stage(sku_stat, data_days, breakeven_roas),
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
    """计算"亏损判定" 的历史 ROAS：剔除噪声日后取 today-21 往前 9 个健康天。

    Bug 修 2026-04-22 第二轮：与 cold-start / 日评估的清洗规则统一。
    原固定窗口 today-30~today-21 在投放断续场景下会被噪声日扭曲：
    - 停投天 spend=0 不贡献，但减少有效样本
    - 偶然 1 单爆款（spend<10 或 ROAS>50）让窗口 ROAS 假高，漏判亏损

    新规则：从 today-21 往前数，跳过噪声日（ROAS>50 或 spend<₽10），
    凑齐 9 个真实投放天，算合并 ROAS。无论投放断续与否，看到的都是
    真实投放期的 9 天数据。
    """
    today     = date.today()
    cutoff    = today - timedelta(days=21)
    sku_col   = "s.ad_group_id" if platform == "wb" else "COALESCE(s.ad_group_id, 0)"

    # 拉 cutoff 之前所有数据（往前不限），按日期倒序找前 9 个健康天
    rows = db.execute(text(f"""
        SELECT s.stat_date,
               COALESCE(SUM(s.spend), 0)   AS spend,
               COALESCE(SUM(s.revenue), 0) AS rev
        FROM ad_stats s
        WHERE s.campaign_id = :campaign_id
          AND s.tenant_id   = :tenant_id
          AND s.platform    = :platform
          AND {sku_col}     = :sku
          AND s.stat_date  <= :cutoff
        GROUP BY s.stat_date ORDER BY s.stat_date DESC
        LIMIT 60
    """), {
        "campaign_id": campaign_id, "tenant_id": tenant_id,
        "platform": platform, "sku": sku, "cutoff": cutoff,
    }).fetchall()

    healthy = []
    for r in rows:
        spend = float(r.spend or 0)
        rev   = float(r.rev or 0)
        roas  = rev / spend if spend > 0 else 0
        if roas <= HEALTHY_DAY_ROAS_MAX and spend >= HEALTHY_DAY_SPEND_MIN:
            healthy.append({"spend": spend, "rev": rev})
            if len(healthy) >= 9:
                break

    if not healthy:
        return None

    sp = sum(d["spend"] for d in healthy)
    rv = sum(d["rev"]   for d in healthy)
    if sp <= 0:
        return None
    return round(rv / sp, 2)


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

                # 关键：用实际执行价（可能被平台硬最低拉升）
                actual_bid = api_result.get("actual_bid_rub") or s["suggested_bid"]
                s_for_log = {
                    **s,
                    "suggested_bid": actual_bid,
                    "adjust_pct": round(
                        (actual_bid - s["current_bid"]) / s["current_bid"] * 100, 2
                    ) if s.get("current_bid") else 0,
                }
                _upsert_group_last_auto(
                    db, campaign, s["platform_sku_id"],
                    s.get("sku_name") or "", actual_bid,
                )
                db.execute(text("""
                    UPDATE ai_pricing_suggestions
                    SET status = 'approved', executed_at = :now
                    WHERE id = :id AND tenant_id = :tenant_id
                """), {"id": s["id"], "tenant_id": tenant_id,
                       "now": _utc_now().replace(tzinfo=None)})
                _write_bidlog(db, campaign, s_for_log, "ai_auto", success=True)
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

    # 关键：用实际执行价（可能被平台硬最低拉升）
    if is_delete:
        actual_bid = 0
    else:
        actual_bid = api_result.get("actual_bid_rub") or final_bid
    final_adjust_pct = -100 if is_delete else (
        round((actual_bid - float(row.current_bid)) / float(row.current_bid) * 100, 2)
        if float(row.current_bid) > 0 else 0
    )
    if not is_delete:
        _upsert_group_last_auto(db, campaign, row.platform_sku_id, row.sku_name or "", actual_bid)
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
        "current_bid": float(row.current_bid), "suggested_bid": actual_bid,
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
        # Bug A 修：data_days 用全 5 段合并（最多 28 天），不只 last5+prev5
        # 之前只合 p5+l5 = 最多 10 天，导致跑了 30 天的成熟 SKU 被判为 6 天
        # 冷启动 → 算法忽略 SKU 自身数据强用店铺均值算出极低出价
        total = _merge_metrics(_merge_metrics(_merge_metrics(_merge_metrics(p5, l5), w2), w3), w4)

        # Bug 1 修：动态窗口找 baseline，跳过停投期
        # 之前 p5.days<3 直接判 new，把"成熟 SKU 暂停几天"也误判为新手
        # shop=6 实测 49/80 SKU 中招（61%）
        # 新逻辑：prev5 不够 3 天 → 往前找 week2/3/4 当替代 baseline
        if l5["days"] == 0 and p5["days"] == 0 and w2["days"] == 0 and w3["days"] == 0 and w4["days"] == 0:
            trend = "new"  # 真无任何数据
        elif l5["days"] < 3:
            trend = "insufficient"  # last5 数据不足，无法判趋势
        else:
            # 找够 3 天数据的 baseline（优先用近的）
            baseline = None
            for candidate in (p5, w2, w3, w4):
                if candidate["days"] >= 3:
                    baseline = candidate
                    break
            if baseline is None:
                trend = "insufficient"  # 扩到 28 天还找不到 baseline
            elif l5["roas"] > baseline["roas"] * 1.05:
                trend = "up"
            elif l5["roas"] < baseline["roas"] * 0.95:
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

def _detect_stage(sku_stat: dict, data_days: int, target_roas: float) -> str:
    """基于 CTR/CR + ROAS 趋势判断商品阶段（2026-04-20 接回 stage_detector）。

    旧实现 _get_product_stage(data_days) 仅按天数切分，与前端"测试期=CTR ok CR 差"
    的语义对不上 —— 28 天成熟 SKU 被标 testing，tip 文案误导用户。

    现在：
    - data_days < 3 → unknown
    - total_orders < 20 → cold_start
    - CTR ≥ 2% 且 CR < 2% → testing（真正的"测试期"）
    - CTR ≥ 2% 且 CR ≥ 2% → growing
    - sku_stat.trend == "down" 且 ROAS < 保本 → declining（段数据 5 段 < 7 天门槛兜底）
    """
    seg_order = ["week4", "week3", "week2", "prev5", "last5"]
    roas_trend = [
        float(seg.get("roas") or 0)
        for name in seg_order
        for seg in [sku_stat.get(name)]
        if seg and (seg.get("days") or 0) > 0
    ]

    result = detect_product_stage(
        data_days=data_days,
        total_orders=int(sku_stat.get("orders") or 0),
        avg_ctr=float(sku_stat.get("ctr") or 0),
        avg_cr=float(sku_stat.get("cr") or 0),
        roas_trend=roas_trend,
        today_roas=float(sku_stat.get("roas") or 0),
        target_roas=target_roas,
    )

    # 段数据最多 5 段 < stage_detector 的 declining_days=7 阈值，
    # 用 _query_sku_history 已算好的 trend 字段做兜底 declining 判断
    if (result.stage != ProductStage.DECLINING
            and data_days >= 7
            and sku_stat.get("trend") == "down"
            and target_roas > 0
            and (sku_stat.get("roas") or 0) < target_roas):
        return ProductStage.DECLINING.value

    return result.stage.value


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
