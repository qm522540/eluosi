"""商品生命周期阶段判断器

基于CTR + CR组合判断，不依赖单一指标。
阶段：冷启动 → 测试验证 → 放量增长 → 衰退预警
"""

from dataclasses import dataclass
from enum import Enum

from app.utils.logger import setup_logger

logger = setup_logger("ai.stage_detector")


class ProductStage(str, Enum):
    COLD_START = "cold_start"
    TESTING = "testing"
    GROWING = "growing"
    DECLINING = "declining"
    UNKNOWN = "unknown"


@dataclass
class StageResult:
    stage: ProductStage
    optimize_target: str
    strategy_hint: str
    allow_roas_override: bool
    max_bid_adjust_pct: float
    reason: str


# 阈值配置
STAGE_THRESHOLDS = {
    "cold_start_max_orders": 20,
    "cold_start_min_days": 3,
    "ctr_threshold": 2.0,
    "cr_threshold": 2.0,
    "declining_days": 7,
    "declining_drop_pct": 20,
}


def detect_product_stage(
    data_days: int,
    total_orders: int,
    avg_ctr: float,
    avg_cr: float,
    roas_trend: list,
    today_roas: float,
    target_roas: float,
) -> StageResult:
    """核心阶段判断函数。优先级：冷启动 > 衰退 > 测试 > 放量"""
    t = STAGE_THRESHOLDS

    # 1. 数据不足
    if data_days < t["cold_start_min_days"]:
        return StageResult(
            stage=ProductStage.UNKNOWN,
            optimize_target="impression",
            strategy_hint=f"数据不足{t['cold_start_min_days']}天，保守处理：维持当前出价，调幅不超过10%",
            allow_roas_override=True,
            max_bid_adjust_pct=10.0,
            reason=f"仅有{data_days}天数据",
        )

    # 2. 冷启动期
    if total_orders < t["cold_start_max_orders"]:
        return StageResult(
            stage=ProductStage.COLD_START,
            optimize_target="impression",
            strategy_hint=f"冷启动期：总订单仅{total_orders}单，核心目标是积累曝光和数据。不因ROAS低而降价，维持或小幅提高出价保曝光。即使ROAS低于目标也不暂停，除非ROAS<1.0",
            allow_roas_override=True,
            max_bid_adjust_pct=15.0,
            reason=f"总订单{total_orders}单<{t['cold_start_max_orders']}单",
        )

    # 3. 衰退预警
    if _is_declining(roas_trend, t["declining_days"], t["declining_drop_pct"], target_roas):
        return StageResult(
            stage=ProductStage.DECLINING,
            optimize_target="profit",
            strategy_hint="衰退预警期：ROAS连续下滑，收缩预算为主，降低出价减少亏损。如果降价后ROAS仍<最低ROAS，建议暂停活动",
            allow_roas_override=False,
            max_bid_adjust_pct=25.0,
            reason=f"ROAS近{t['declining_days']}天持续下滑",
        )

    # 4. 测试验证期：有点击但转化差
    if avg_ctr >= t["ctr_threshold"] and avg_cr < t["cr_threshold"]:
        return StageResult(
            stage=ProductStage.TESTING,
            optimize_target="ctr_cr",
            strategy_hint=f"测试验证期：CTR={avg_ctr}%表明主图吸引人，但CR={avg_cr}%转化偏低，说明详情页/价格需优化。降低出价减少无效消耗，等CR改善后再放量",
            allow_roas_override=False,
            max_bid_adjust_pct=20.0,
            reason=f"CTR={avg_ctr}%OK但CR={avg_cr}%偏低",
        )

    # 5. 放量增长期
    if avg_ctr >= t["ctr_threshold"] and avg_cr >= t["cr_threshold"]:
        return StageResult(
            stage=ProductStage.GROWING,
            optimize_target="roas",
            strategy_hint=f"放量增长期：CTR={avg_ctr}%、CR={avg_cr}%均达标，商品已验证。核心目标是ROAS达标下最大化销量，ROAS高于目标时主动加价抢量",
            allow_roas_override=False,
            max_bid_adjust_pct=30.0,
            reason=f"CTR={avg_ctr}%且CR={avg_cr}%均达标",
        )

    # 6. 兜底
    return StageResult(
        stage=ProductStage.GROWING,
        optimize_target="roas",
        strategy_hint="按标准ROAS逻辑优化",
        allow_roas_override=False,
        max_bid_adjust_pct=20.0,
        reason="综合指标正常",
    )


def _is_declining(roas_trend: list, min_days: int, drop_pct: float, target_roas: float) -> bool:
    """判断是否进入衰退期：近N天ROAS持续下滑且跌幅超阈值"""
    if len(roas_trend) < min_days:
        return False
    recent = roas_trend[-min_days:]
    # 单调下降检查
    if not all(recent[i] >= recent[i + 1] for i in range(len(recent) - 1)):
        return False
    if recent[0] == 0:
        return False
    total_drop = (recent[0] - recent[-1]) / recent[0] * 100
    return total_drop >= drop_pct and recent[-1] < target_roas
