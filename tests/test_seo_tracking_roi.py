"""SEO 服务层纯函数单元测试 — 覆盖 keyword_tracking + roi_report 的核心分支

只测纯函数：
- keyword_tracking_service._classify_trend
- keyword_tracking_service._compute_alert
- roi_report_service._delta_pct

这些函数不依赖 DB，适合快速边界测试。API 层测试见 tests/test_seo.py
"""

import pytest

from app.services.seo.keyword_tracking_service import _classify_trend, _compute_alert
from app.services.seo.roi_report_service import _delta_pct


# ==================== _classify_trend ====================

class TestClassifyTrend:
    def test_idle_both_zero(self):
        """本期上期都为 0 → idle"""
        trend, pct = _classify_trend(0, 0)
        assert trend == "idle"
        assert pct is None

    def test_new_prev_zero(self):
        """上期 0 本期有 → new（prev=0 无法算环比）"""
        trend, pct = _classify_trend(100, 0)
        assert trend == "new"
        assert pct is None

    def test_vanish_cur_zero(self):
        """本期 0 上期有 → vanish（delta = -100%）"""
        trend, pct = _classify_trend(0, 50)
        assert trend == "vanish"
        assert pct == -100.0

    def test_up_20pct_exact(self):
        """本期环比 +20% 恰好 → up（边界包含）"""
        trend, pct = _classify_trend(120, 100)
        assert trend == "up"
        assert pct == 20.0

    def test_up_significant(self):
        trend, pct = _classify_trend(200, 100)
        assert trend == "up"
        assert pct == 100.0

    def test_down_20pct_exact(self):
        """本期环比 -20% 恰好 → down"""
        trend, pct = _classify_trend(80, 100)
        assert trend == "down"
        assert pct == -20.0

    def test_stable_within_range(self):
        """-20% < delta < +20% → stable"""
        trend, pct = _classify_trend(110, 100)
        assert trend == "stable"
        assert pct == 10.0

    def test_stable_slight_down(self):
        trend, pct = _classify_trend(95, 100)
        assert trend == "stable"
        assert pct == -5.0

    def test_stable_exact_zero_delta(self):
        trend, pct = _classify_trend(100, 100)
        assert trend == "stable"
        assert pct == 0.0

    def test_rounding(self):
        """delta 按 1 位小数圆整"""
        trend, pct = _classify_trend(123, 100)
        assert trend == "up"
        assert pct == 23.0


# ==================== _compute_alert ====================

class TestComputeAlert:
    def test_no_alert_stable(self):
        """平稳时无预警"""
        alert = _compute_alert(imp_cur=100, imp_prev=100, ord_cur=5, ord_prev=5)
        assert alert is None

    def test_vanish(self):
        """上期 ≥ 50 本期 0 → vanish（严重）"""
        alert = _compute_alert(imp_cur=0, imp_prev=60, ord_cur=0, ord_prev=0)
        assert alert == "vanish"

    def test_vanish_boundary_50(self):
        """上期正好 50 → vanish"""
        alert = _compute_alert(imp_cur=0, imp_prev=50, ord_cur=0, ord_prev=0)
        assert alert == "vanish"

    def test_vanish_not_triggered_below_50(self):
        """上期 < 50 即使本期 0 也不触发 vanish"""
        alert = _compute_alert(imp_cur=0, imp_prev=49, ord_cur=0, ord_prev=0)
        # 但 49 >= 20 且 cur/prev = 0 <= 0.7 → 触发 drop
        assert alert == "drop"

    def test_drop_at_30pct(self):
        """跌幅恰好 30%（cur/prev=0.7）→ drop"""
        alert = _compute_alert(imp_cur=70, imp_prev=100, ord_cur=0, ord_prev=0)
        assert alert == "drop"

    def test_drop_not_triggered_below_20(self):
        """上期 < 20 不触发 drop（避免低曝光噪声）"""
        alert = _compute_alert(imp_cur=0, imp_prev=19, ord_cur=0, ord_prev=0)
        assert alert is None

    def test_drop_not_triggered_mild_drop(self):
        """跌幅 < 30% → 不触发 drop"""
        alert = _compute_alert(imp_cur=80, imp_prev=100, ord_cur=0, ord_prev=0)
        assert alert is None

    def test_orders_drop(self):
        """订单归零预警（上期 ≥ 2）"""
        alert = _compute_alert(imp_cur=100, imp_prev=100, ord_cur=0, ord_prev=5)
        assert alert == "orders_drop"

    def test_orders_drop_boundary_2(self):
        alert = _compute_alert(imp_cur=100, imp_prev=100, ord_cur=0, ord_prev=2)
        assert alert == "orders_drop"

    def test_orders_drop_not_triggered_below_2(self):
        """上期订单 < 2 不触发（单个订单波动不足以预警）"""
        alert = _compute_alert(imp_cur=100, imp_prev=100, ord_cur=0, ord_prev=1)
        assert alert is None

    def test_priority_vanish_over_drop(self):
        """vanish 条件优先于 drop（都满足时返 vanish）"""
        alert = _compute_alert(imp_cur=0, imp_prev=100, ord_cur=0, ord_prev=0)
        assert alert == "vanish"  # 100>=50 优先

    def test_priority_drop_over_orders_drop(self):
        """drop 条件满足时 orders_drop 让位（drop 信号更强）"""
        alert = _compute_alert(imp_cur=50, imp_prev=100, ord_cur=0, ord_prev=5)
        assert alert == "drop"


# ==================== _delta_pct ====================

class TestDeltaPct:
    def test_before_zero_returns_none(self):
        """before=0 返 None（零基线）"""
        assert _delta_pct(after=100, before=0) is None

    def test_before_negative_returns_none(self):
        """before 负值当零基线处理（虽业务不该出现）"""
        assert _delta_pct(after=100, before=-1) is None

    def test_positive_delta(self):
        assert _delta_pct(after=150, before=100) == 50.0

    def test_negative_delta(self):
        assert _delta_pct(after=50, before=100) == -50.0

    def test_zero_delta(self):
        assert _delta_pct(after=100, before=100) == 0.0

    def test_rounding(self):
        """按 1 位小数圆整"""
        assert _delta_pct(after=123, before=100) == 23.0

    def test_after_zero(self):
        """after=0 且 before>0 → -100%"""
        assert _delta_pct(after=0, before=100) == -100.0

    def test_float_values(self):
        """float 值正常计算"""
        assert _delta_pct(after=150.5, before=100.0) == 50.5
