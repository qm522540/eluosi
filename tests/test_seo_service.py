"""SEO service 层纯函数 + 关键业务逻辑单元测试

04-20 老张写。填 tests/test_seo.py 只测 API 层、service 0 覆盖的欠账。

覆盖：
- health_service._score_coverage / _score_title_length / _score_description_length
- health_service._finalize_score（动态重分权 —— 候选池为空时的核心机制）
- health_service._classify
- health_service.compute_shop_health（mock DB，测 score_range/sort/分页/缺词合并）
- service._new_candidate / _compute_score
- service.list_candidates（hide_covered + source_filter 分支）
- service.list_champion_keywords（跨商品爆款词）
- service.adopt_candidate / ignore_candidates（状态转换）
- service.analyze_paid_to_organic（引擎核心：类目词扩散 + 去重 + 覆盖判断）

全部不依赖真实 DB，用 MagicMock 注入 db.execute.fetchall 结果。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services.seo import health_service as hs
from app.services.seo import service as svc
from app.utils.errors import ErrorCode


# ============================================================
# 工具：伪造 SQLAlchemy Row（属性访问） + 伪造 db.execute 结果
# ============================================================

def _row(**kwargs):
    """伪 Row：支持 r.xxx 属性读取。"""
    return SimpleNamespace(**kwargs)


class _FakeResult:
    """伪 db.execute() 返回值，支持 fetchall / fetchone / first / rowcount"""

    def __init__(self, rows=None, rowcount=0):
        self._rows = rows or []
        self.rowcount = rowcount

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def first(self):
        return self._rows[0] if self._rows else None


def _fake_db(*result_sequence):
    """构造 db mock：execute 按顺序返回 result_sequence 里的 _FakeResult。"""
    db = MagicMock()
    db.execute.side_effect = list(result_sequence)
    return db


def _shop(shop_id=1, tenant_id=1, platform="wb"):
    return SimpleNamespace(id=shop_id, tenant_id=tenant_id,
                           platform=platform, name=f"Shop-{shop_id}")


# ============================================================
# 1. health_service._score_coverage
# ============================================================

class TestScoreCoverage:

    def test_zero_total_means_data_insufficient(self):
        score, detail = hs._score_coverage(0, 0)
        assert score == 0.0
        assert detail["data_insufficient"] is True
        assert detail["weight"] == 60

    def test_full_coverage(self):
        score, detail = hs._score_coverage(10, 10)
        assert score == 60.0
        assert detail["rate_pct"] == 100.0
        assert detail["data_insufficient"] is False

    def test_half_coverage(self):
        score, detail = hs._score_coverage(10, 5)
        assert score == 30.0
        assert detail["rate_pct"] == 50.0

    def test_zero_covered(self):
        score, detail = hs._score_coverage(10, 0)
        assert score == 0.0
        assert detail["rate_pct"] == 0.0
        assert detail["data_insufficient"] is False  # 有候选但 0 覆盖 ≠ 数据不足

    def test_partial_rounded(self):
        score, _ = hs._score_coverage(7, 3)
        # 3/7 * 60 = 25.714... → round 1 位 = 25.7
        assert score == 25.7


# ============================================================
# 2. health_service._score_title_length
# ============================================================

class TestScoreTitleLength:

    def test_none_title(self):
        score, detail = hs._score_title_length(None)
        assert score == 0.0
        assert detail["length"] == 0
        assert "空" in detail["hint"]

    def test_empty_title(self):
        score, _ = hs._score_title_length("")
        assert score == 0.0

    def test_too_short(self):
        score, detail = hs._score_title_length("a" * 20)
        assert score == 0.0
        assert detail["length"] == 20
        assert "过短" in detail["hint"]

    def test_short_linear(self):
        # 30-50 线性：40 字符 → (40-30)/20*20 = 10
        score, _ = hs._score_title_length("a" * 40)
        assert score == 10.0

    def test_edge_30(self):
        # 恰好 30：(30-30)/20*20 = 0
        score, _ = hs._score_title_length("a" * 30)
        assert score == 0.0

    def test_edge_50(self):
        # 50 字符在 30-50 分支：(50-30)/20*20 = 20
        score, _ = hs._score_title_length("a" * 50)
        assert score == 20.0

    def test_ideal_length(self):
        # 50-180 满分
        score, detail = hs._score_title_length("a" * 120)
        assert score == 20.0
        assert "理想" in detail["hint"]

    def test_boundary_180(self):
        score, _ = hs._score_title_length("a" * 180)
        assert score == 20.0

    def test_slightly_over(self):
        # 190: 20 - (190-180)/20*5 = 17.5
        score, detail = hs._score_title_length("a" * 190)
        assert score == 17.5
        assert "偏长" in detail["hint"]

    def test_edge_200(self):
        # 200: 20 - (200-180)/20*5 = 15
        score, _ = hs._score_title_length("a" * 200)
        assert score == 15.0

    def test_over_200_violation(self):
        score, detail = hs._score_title_length("a" * 210)
        assert score == 0.0
        assert "超长" in detail["hint"]


# ============================================================
# 3. health_service._score_description_length
# ============================================================

class TestScoreDescriptionLength:

    def test_none_description(self):
        score, detail = hs._score_description_length(None)
        assert score == 0.0
        assert detail["length"] == 0
        assert "空" in detail["hint"]

    def test_empty_description(self):
        score, _ = hs._score_description_length("")
        assert score == 0.0

    def test_too_short(self):
        score, detail = hs._score_description_length("a" * 50)
        assert score == 0.0
        assert detail["length"] == 50
        assert "过短" in detail["hint"]

    def test_short_increasing(self):
        # 200: (200-100)/200*20 = 10.0
        score, detail = hs._score_description_length("a" * 200)
        assert score == 10.0
        assert "偏短" in detail["hint"]

    def test_ideal_min(self):
        score, detail = hs._score_description_length("a" * 300)
        assert score == 20.0
        assert "理想" in detail["hint"]

    def test_ideal_mid(self):
        score, _ = hs._score_description_length("a" * 1000)
        assert score == 20.0

    def test_ideal_max(self):
        score, _ = hs._score_description_length("a" * 2000)
        assert score == 20.0

    def test_long_decay(self):
        # 2500: 20 - (2500-2000)/1000*10 = 15.0
        score, detail = hs._score_description_length("a" * 2500)
        assert score == 15.0
        assert "偏长" in detail["hint"]

    def test_over_3000_violation(self):
        score, detail = hs._score_description_length("a" * 3100)
        assert score == 0.0
        assert "超长" in detail["hint"]


# ============================================================
# 4. health_service._finalize_score —— Ozon 动态重分权核心
# ============================================================

class TestFinalizeScore:

    def test_all_dimensions_available(self):
        # 30 + 20 + 10 = 60 / (60+20+20=100) * 100 = 60
        dims = [
            {"score": 30, "weight": 60},
            {"score": 20, "weight": 20},
            {"score": 10, "weight": 20},
        ]
        assert hs._finalize_score(dims) == 60.0

    def test_ozon_rating_redistributed(self):
        """Ozon 商品 rating=None 场景：权重只用 60+20=80 放大回 100 分制"""
        dims = [
            {"score": 60, "weight": 60},                             # 覆盖满分
            {"score": 20, "weight": 20},                             # 标题满分
            {"score": 0, "weight": 20, "data_insufficient": True},   # rating 无数据
        ]
        # raw = 60+20 = 80; avail_weight = 80; score = 80/80*100 = 100
        assert hs._finalize_score(dims) == 100.0

    def test_ozon_rating_partial(self):
        """Ozon 覆盖一半、标题满分、rating 无"""
        dims = [
            {"score": 30, "weight": 60},   # 覆盖一半
            {"score": 20, "weight": 20},   # 标题满
            {"score": 0, "weight": 20, "data_insufficient": True},
        ]
        # raw = 50; avail_weight = 80; 50/80*100 = 62.5
        assert hs._finalize_score(dims) == 62.5

    def test_all_insufficient_returns_zero(self):
        dims = [
            {"score": 0, "weight": 60, "data_insufficient": True},
            {"score": 0, "weight": 20, "data_insufficient": True},
            {"score": 0, "weight": 20, "data_insufficient": True},
        ]
        assert hs._finalize_score(dims) == 0.0

    def test_zero_weight_safe(self):
        """所有可用维度 weight=0（理论上不会发生）不能炸除零"""
        dims = [{"score": 10, "weight": 0}]
        assert hs._finalize_score(dims) == 0.0


# ============================================================
# 5. health_service._classify —— 3 档分级
# ============================================================

class TestClassify:

    def test_good_at_70(self):
        assert hs._classify(70) == "good"

    def test_good_high(self):
        assert hs._classify(95) == "good"

    def test_fair_at_40(self):
        assert hs._classify(40) == "fair"

    def test_fair_upper_edge(self):
        assert hs._classify(69.9) == "fair"

    def test_poor_under_40(self):
        assert hs._classify(39.9) == "poor"

    def test_poor_zero(self):
        assert hs._classify(0) == "poor"


# ============================================================
# 6. service._new_candidate —— 模板初始化
# ============================================================

class TestNewCandidate:

    def test_shape(self):
        c = svc._new_candidate(100, "куртка")
        assert c["product_id"] == 100
        assert c["keyword"] == "куртка"
        assert c["sources"] == []
        assert c["paid_roas"] is None
        assert c["paid_orders"] is None
        assert c["organic_impressions"] is None
        assert c["organic_orders"] is None
        assert c["wordstat_volume"] is None
        assert c["in_title"] == 0
        assert c["in_attrs"] == 0
        assert c["score"] == 0

    def test_long_keyword_truncated(self):
        long_kw = "a" * 300
        c = svc._new_candidate(1, long_kw)
        assert len(c["keyword"]) == 200


# ============================================================
# 7. service._compute_score —— 综合得分公式
# ============================================================

class TestComputeScore:

    def test_empty_candidate_zero(self):
        c = svc._new_candidate(1, "x")
        assert svc._compute_score(c) == 0.0

    def test_single_source_no_metrics(self):
        c = svc._new_candidate(1, "x")
        c["sources"] = [{"type": "paid", "scope": "self"}]
        # 1 源 × 2 = 2，其他全 0
        assert svc._compute_score(c) == 2.0

    def test_multi_source_adds_weight(self):
        c = svc._new_candidate(1, "x")
        c["sources"] = [
            {"type": "paid", "scope": "self"},
            {"type": "organic", "scope": "self"},
        ]
        # 2 源 × 2 = 4
        assert svc._compute_score(c) == 4.0

    def test_with_metrics(self):
        """2 源 + ROAS 3.0 + 10 paid orders + 100 organic imp + 5 organic orders"""
        c = svc._new_candidate(1, "x")
        c["sources"] = [
            {"type": "paid", "scope": "self"},
            {"type": "organic", "scope": "self"},
        ]
        c["paid_roas"] = 3.0
        c["paid_orders"] = 10
        c["organic_impressions"] = 100
        c["organic_orders"] = 5
        # 2*2 + 3.0 + log10(11)*2 + log10(101) + log10(6)*2
        # ≈ 4 + 3.0 + 2.083 + 2.004 + 1.556 = 12.643 → round 2 位 ≈ 12.64
        sc = svc._compute_score(c)
        assert 12.5 < sc < 12.8

    def test_capped_at_100(self):
        """极高指标被封顶到 100"""
        c = svc._new_candidate(1, "x")
        c["sources"] = [{"type": "paid", "scope": "self"}] * 100
        c["paid_roas"] = 1000.0
        c["paid_orders"] = 10 ** 9
        c["organic_impressions"] = 10 ** 9
        c["organic_orders"] = 10 ** 9
        assert svc._compute_score(c) == 100.0


# ============================================================
# 8. health_service.compute_shop_health —— mock DB 集成测
# ============================================================

class TestComputeShopHealth:

    @staticmethod
    def _make_main_row(pid, *, title_ru="a" * 100, description_ru="a" * 1000,
                       rating=4.0, total=10, covered=5, platform="wb"):
        return _row(
            pid=pid, sku=f"SKU-{pid}", name_zh=f"商品{pid}", image_url=None,
            listing_id=pid * 10, title_ru=title_ru, description_ru=description_ru,
            rating=rating, review_count=10, platform=platform,
            total_candidates=total, covered=covered,
        )

    def test_basic_happy_path(self):
        """两个商品一个好一个差，totals 正确 + 排序 score_asc 差的在前"""
        db = _fake_db(
            _FakeResult([
                self._make_main_row(1, title_ru="a" * 120,
                                    description_ru="a" * 1000,
                                    total=10, covered=8),   # 高分
                self._make_main_row(2, title_ru="a" * 10,
                                    description_ru="a" * 50,
                                    total=10, covered=1),   # 低分
            ]),
            _FakeResult([]),  # miss_rows（Top 3 缺词），无数据
        )
        result = hs.compute_shop_health(db, tenant_id=1, shop=_shop())
        assert result["code"] == ErrorCode.SUCCESS
        data = result["data"]
        # 默认 sort=score_asc，差的（商品 2）排前
        assert data["items"][0]["product_id"] == 2
        assert data["items"][1]["product_id"] == 1
        assert data["totals"]["all"] == 2

    def test_full_score_all_dimensions(self):
        """所有维度满分 → 总分 100，dimensions 含 description_length"""
        db = _fake_db(
            _FakeResult([
                # 覆盖满 + 标题满 + 描述满 → 100 分
                self._make_main_row(1, title_ru="a" * 120,
                                    description_ru="a" * 1000,
                                    total=10, covered=10, platform="ozon"),
            ]),
            _FakeResult([]),
        )
        result = hs.compute_shop_health(db, tenant_id=1, shop=_shop(platform="ozon"))
        items = result["data"]["items"]
        assert items[0]["score"] == 100.0
        assert items[0]["grade"] == "good"
        assert items[0]["dimensions"]["description_length"]["score"] == 20.0
        assert "rating" not in items[0]["dimensions"]

    def test_score_range_filter_poor(self):
        db = _fake_db(
            _FakeResult([
                self._make_main_row(1, title_ru="a" * 5,
                                    description_ru="",
                                    total=10, covered=0),   # poor
                self._make_main_row(2, title_ru="a" * 120,
                                    description_ru="a" * 1000,
                                    total=10, covered=10),  # good
            ]),
            _FakeResult([]),
        )
        result = hs.compute_shop_health(
            db, tenant_id=1, shop=_shop(), score_range="poor",
        )
        items = result["data"]["items"]
        assert len(items) == 1
        assert items[0]["product_id"] == 1
        assert items[0]["grade"] == "poor"

    def test_sort_gaps_desc(self):
        """gaps_desc: 缺词数（candidate - covered）大的在前"""
        db = _fake_db(
            _FakeResult([
                self._make_main_row(1, total=100, covered=10),  # gap=90
                self._make_main_row(2, total=10, covered=1),    # gap=9
            ]),
            _FakeResult([]),
        )
        result = hs.compute_shop_health(
            db, tenant_id=1, shop=_shop(), sort="gaps_desc",
        )
        items = result["data"]["items"]
        assert items[0]["product_id"] == 1

    def test_missing_top_keywords_merged(self):
        """第二次 SQL（缺词 Top3）回填到对应 item"""
        db = _fake_db(
            _FakeResult([
                self._make_main_row(1, total=10, covered=3),
            ]),
            # miss_rows: 4 条，按 product_id 分组后只取前 3
            _FakeResult([
                _row(product_id=1, keyword="kw1", score=50,
                     paid_orders=10, paid_roas=3.0,
                     organic_impressions=100, organic_orders=5),
                _row(product_id=1, keyword="kw2", score=40,
                     paid_orders=None, paid_roas=None,
                     organic_impressions=None, organic_orders=2),
                _row(product_id=1, keyword="kw3", score=30,
                     paid_orders=None, paid_roas=None,
                     organic_impressions=50, organic_orders=None),
                _row(product_id=1, keyword="kw4", score=20,   # 应被截掉
                     paid_orders=None, paid_roas=2.5,
                     organic_impressions=None, organic_orders=None),
            ]),
        )
        result = hs.compute_shop_health(db, tenant_id=1, shop=_shop())
        item = result["data"]["items"][0]
        assert len(item["missing_top_keywords"]) == 3
        # 第一条应带 "付费订单 10" 指标
        assert "付费订单" in item["missing_top_keywords"][0]["metric"]
        # 第二条应带 "自然订单"
        assert "自然订单" in item["missing_top_keywords"][1]["metric"]
        # 第三条应带 "自然曝光"
        assert "自然曝光" in item["missing_top_keywords"][2]["metric"]

    def test_keyword_filter(self):
        db = _fake_db(
            _FakeResult([
                _row(pid=1, sku="SKU-1", name_zh="银项链", image_url=None,
                     listing_id=10, title_ru="серебряное колье",
                     description_ru="a" * 500,
                     rating=4.0, review_count=5, platform="wb",
                     total_candidates=10, covered=5),
                _row(pid=2, sku="SKU-2", name_zh="耳环套装", image_url=None,
                     listing_id=20, title_ru="серьги комплект",
                     description_ru="a" * 500,
                     rating=4.0, review_count=5, platform="wb",
                     total_candidates=10, covered=5),
            ]),
            _FakeResult([]),
        )
        result = hs.compute_shop_health(
            db, tenant_id=1, shop=_shop(), keyword="项链",
        )
        items = result["data"]["items"]
        assert len(items) == 1
        assert items[0]["product_id"] == 1

    def test_pagination(self):
        rows = [
            self._make_main_row(i, total=10, covered=3)
            for i in range(1, 26)  # 25 个商品
        ]
        db = _fake_db(_FakeResult(rows), _FakeResult([]))
        result = hs.compute_shop_health(
            db, tenant_id=1, shop=_shop(), page=2, size=10,
        )
        items = result["data"]["items"]
        assert len(items) == 10
        assert result["data"]["totals"]["all"] == 25


# ============================================================
# 9. service.list_candidates —— hide_covered / source_filter
# ============================================================

class TestListCandidates:

    @staticmethod
    def _totals_row(total=0, with_conversion=0, gap=0, products=0):
        return _row(total=total, with_conversion=with_conversion,
                    gap=gap, products=products)

    @staticmethod
    def _item_row(cid=1, kw="test", pid=100, **overrides):
        defaults = dict(
            id=cid, keyword=kw, product_id=pid, sources="[]", score=5.0,
            paid_roas=None, paid_orders=None, paid_spend=None, paid_revenue=None,
            organic_impressions=None, organic_add_to_cart=None,
            organic_orders=None, wordstat_volume=None,
            in_title=0, in_attrs=0, status="pending",
            adopted_at=None, adopted_by=None, updated_at=None,
            product_name="商品A", product_code="QQ-B001", cat_id=1,
            current_title="тест", images=None,
        )
        defaults.update(overrides)
        return _row(**defaults)

    def test_empty_result(self):
        db = _fake_db(
            _FakeResult([self._totals_row()]),   # totals
            _FakeResult([]),                      # items
        )
        result = svc.list_candidates(db, tenant_id=1, shop=_shop())
        assert result["code"] == ErrorCode.SUCCESS
        data = result["data"]
        assert data["totals"]["total"] == 0
        assert data["items"] == []

    def test_totals_and_items(self):
        db = _fake_db(
            _FakeResult([self._totals_row(total=10, with_conversion=3,
                                          gap=7, products=5)]),
            _FakeResult([
                self._item_row(cid=1, kw="test1"),
                self._item_row(cid=2, kw="test2"),
            ]),
        )
        result = svc.list_candidates(db, tenant_id=1, shop=_shop())
        data = result["data"]
        assert data["totals"]["total"] == 10
        assert data["totals"]["with_conversion"] == 3
        assert len(data["items"]) == 2

    def test_hide_covered_adds_where_clause(self):
        db = _fake_db(
            _FakeResult([self._totals_row()]),
            _FakeResult([]),
        )
        svc.list_candidates(db, tenant_id=1, shop=_shop(), hide_covered=True)
        # 检查生成的 SQL 包含 in_title=0 过滤
        first_call_args = db.execute.call_args_list[0]
        sql_text_obj = first_call_args[0][0]
        # SQLAlchemy text 对象可 str() 看到原 SQL
        assert "c.in_title = 0" in str(sql_text_obj)

    def test_source_filter_organic_self(self):
        db = _fake_db(_FakeResult([self._totals_row()]), _FakeResult([]))
        svc.list_candidates(db, tenant_id=1, shop=_shop(),
                            source_filter="organic_self")
        sql_str = str(db.execute.call_args_list[0][0][0])
        assert "'type','organic','scope','self'" in sql_str or \
               "'organic'" in sql_str

    def test_source_filter_with_orders(self):
        db = _fake_db(_FakeResult([self._totals_row()]), _FakeResult([]))
        svc.list_candidates(db, tenant_id=1, shop=_shop(),
                            source_filter="with_orders")
        sql_str = str(db.execute.call_args_list[0][0][0])
        assert "paid_orders" in sql_str and "organic_orders" in sql_str

    def test_product_id_filter(self):
        db = _fake_db(_FakeResult([self._totals_row()]), _FakeResult([]))
        svc.list_candidates(db, tenant_id=1, shop=_shop(), product_id=145)
        # params 里应传 pid=145
        params = db.execute.call_args_list[0][0][1]
        assert params["pid"] == 145

    def test_keyword_search_lowercase(self):
        db = _fake_db(_FakeResult([self._totals_row()]), _FakeResult([]))
        svc.list_candidates(db, tenant_id=1, shop=_shop(), keyword="SERRGI")
        params = db.execute.call_args_list[0][0][1]
        assert params["kw_like"] == "%serrgi%"  # 应转小写

    def test_page_size_clamped(self):
        db = _fake_db(_FakeResult([self._totals_row()]), _FakeResult([]))
        # size=500 被截成 100
        svc.list_candidates(db, tenant_id=1, shop=_shop(), size=500)
        params = db.execute.call_args_list[1][0][1]  # items_sql 的 params
        assert params["size"] == 100

    def test_page_negative_clamped(self):
        db = _fake_db(_FakeResult([self._totals_row()]), _FakeResult([]))
        # page=0 被截成 1 → offset=0
        svc.list_candidates(db, tenant_id=1, shop=_shop(), page=0)
        params = db.execute.call_args_list[1][0][1]
        assert params["offset"] == 0

    def test_json_sources_parsed(self):
        """sources 是 JSON 字符串，应被解析回 list"""
        db = _fake_db(
            _FakeResult([self._totals_row(total=1, products=1)]),
            _FakeResult([
                self._item_row(sources='[{"type":"paid","scope":"self"}]'),
            ]),
        )
        result = svc.list_candidates(db, tenant_id=1, shop=_shop())
        item = result["data"]["items"][0]
        assert item["sources"] == [{"type": "paid", "scope": "self"}]

    def test_images_parsed(self):
        db = _fake_db(
            _FakeResult([self._totals_row(total=1, products=1)]),
            _FakeResult([
                self._item_row(images='["http://cdn/1.jpg","http://cdn/2.jpg"]'),
            ]),
        )
        result = svc.list_candidates(db, tenant_id=1, shop=_shop())
        assert result["data"]["items"][0]["image_url"] == "http://cdn/1.jpg"

    def test_broken_json_safe(self):
        """sources 非法 JSON 应 fallback 到空列表"""
        db = _fake_db(
            _FakeResult([self._totals_row(total=1, products=1)]),
            _FakeResult([
                self._item_row(sources="not a json"),
            ]),
        )
        result = svc.list_candidates(db, tenant_id=1, shop=_shop())
        assert result["data"]["items"][0]["sources"] == []


# ============================================================
# 10. service.list_champion_keywords —— 跨商品爆款词
# ============================================================

class TestListChampionKeywords:

    def test_empty(self):
        db = _fake_db(_FakeResult([]))
        result = svc.list_champion_keywords(db, tenant_id=1, shop=_shop())
        assert result["code"] == ErrorCode.SUCCESS
        assert result["data"]["items"] == []

    def test_populated(self):
        db = _fake_db(_FakeResult([
            _row(keyword="серьги треугольные", product_count=39,
                 total_orders=78, total_impr=4007, max_score=25.5,
                 top_product_names="耳环A|耳环B|耳环C"),
            _row(keyword="happy birthday", product_count=22,
                 total_orders=44, total_impr=86, max_score=12.0,
                 top_product_names="气球A|气球B|气球C"),
        ]))
        result = svc.list_champion_keywords(db, tenant_id=1, shop=_shop())
        items = result["data"]["items"]
        assert len(items) == 2
        assert items[0]["keyword"] == "серьги треугольные"
        assert items[0]["product_count"] == 39
        assert items[0]["total_orders"] == 78
        assert items[0]["top_product_names"] == ["耳环A", "耳环B", "耳环C"]

    def test_limit_capped_at_30(self):
        db = _fake_db(_FakeResult([]))
        svc.list_champion_keywords(db, tenant_id=1, shop=_shop(), limit=999)
        params = db.execute.call_args_list[0][0][1]
        assert params["lim"] == 30

    def test_min_products_lower_bound(self):
        db = _fake_db(_FakeResult([]))
        # min_products=1 被截成 2
        svc.list_champion_keywords(db, tenant_id=1, shop=_shop(),
                                   min_products=1)
        params = db.execute.call_args_list[0][0][1]
        assert params["minp"] == 2

    def test_empty_top_names(self):
        """top_product_names 为空字符串不应炸"""
        db = _fake_db(_FakeResult([
            _row(keyword="x", product_count=2, total_orders=2,
                 total_impr=0, max_score=1, top_product_names=""),
        ]))
        result = svc.list_champion_keywords(db, tenant_id=1, shop=_shop())
        assert result["data"]["items"][0]["top_product_names"] == [""]
        # 空字符 split 结果是 [""]，这是已知行为（不影响前端展示）


# ============================================================
# 11. service.adopt_candidate —— 状态转换
# ============================================================

class TestAdoptCandidate:

    def test_not_found(self):
        db = _fake_db(_FakeResult([]))
        result = svc.adopt_candidate(db, tenant_id=1, shop_id=1,
                                     candidate_id=999, user_id=1)
        assert result["code"] == ErrorCode.SEO_CANDIDATE_NOT_FOUND

    def test_pending_to_adopted(self):
        db = _fake_db(
            _FakeResult([_row(id=1, status="pending")]),
            _FakeResult([], rowcount=1),  # UPDATE
        )
        result = svc.adopt_candidate(db, tenant_id=1, shop_id=1,
                                     candidate_id=1, user_id=5)
        assert result["code"] == ErrorCode.SUCCESS
        assert result["data"]["status"] == "adopted"
        # update + commit 都调过
        assert db.execute.call_count == 2
        db.commit.assert_called_once()

    def test_ignored_to_adopted_allowed(self):
        """已 ignored 的可以重新 adopt"""
        db = _fake_db(
            _FakeResult([_row(id=1, status="ignored")]),
            _FakeResult([], rowcount=1),
        )
        result = svc.adopt_candidate(db, tenant_id=1, shop_id=1,
                                     candidate_id=1)
        assert result["code"] == ErrorCode.SUCCESS

    def test_already_adopted_rejected(self):
        """已 adopted 不能再 adopt"""
        db = _fake_db(_FakeResult([_row(id=1, status="adopted")]))
        result = svc.adopt_candidate(db, tenant_id=1, shop_id=1, candidate_id=1)
        assert result["code"] == ErrorCode.SEO_CANDIDATE_INVALID_STATUS


# ============================================================
# 12. service.ignore_candidates
# ============================================================

class TestIgnoreCandidates:

    def test_empty_ids_early_return(self):
        db = MagicMock()
        result = svc.ignore_candidates(db, tenant_id=1, shop_id=1, ids=[])
        assert result["code"] == ErrorCode.SUCCESS
        assert result["data"]["updated"] == 0
        # 不应调 execute
        db.execute.assert_not_called()

    def test_batch_update(self):
        db = _fake_db(_FakeResult([], rowcount=3))
        result = svc.ignore_candidates(db, tenant_id=1, shop_id=1,
                                       ids=[1, 2, 3])
        assert result["code"] == ErrorCode.SUCCESS
        assert result["data"]["updated"] == 3
        db.commit.assert_called_once()


# ============================================================
# 13. service.analyze_paid_to_organic —— 引擎核心最小化集成测
# ============================================================

class TestAnalyzePaidToOrganic:

    def test_all_empty_data_sources(self):
        """所有 6 次查询（self/cat/prod/organic_self/organic_cat/prod_cat）
        全 0 结果 → 候选 0 条 → written 0"""
        db = _fake_db(
            _FakeResult([]),  # self_sql (paid self)
            _FakeResult([]),  # cat_sql (paid category)
            # cat_kw_map 为空 → prod_sql 不触发
            _FakeResult([]),  # organic_self_sql
            _FakeResult([]),  # organic_cat_sql
            # org_cat_kw_map 为空 → prod_cat_sql 不触发
        )
        result = svc.analyze_paid_to_organic(
            db, tenant_id=1, shop=_shop(), days=30,
            roas_threshold=2.0, min_orders=1,
        )
        assert result["code"] == ErrorCode.SUCCESS
        data = result["data"]
        assert data["analyzed_pairs"] == 0
        assert data["candidates"] == 0
        assert data["written"] == 0

    def test_organic_self_builds_candidate(self):
        """只有自然搜索源有数据 → 1 个候选词生成"""
        db = _fake_db(
            _FakeResult([]),                       # paid self
            _FakeResult([]),                       # paid cat
            _FakeResult([                          # organic self
                _row(keyword="серьги треугольные", product_id=100,
                     cat_id=5, title="кольцо круглое", attrs="",
                     frequency=20, impressions=100, add_to_cart=3,
                     orders=2, revenue=500.0),
            ]),
            _FakeResult([]),                       # organic cat
            _FakeResult([], rowcount=1),           # _upsert_candidates INSERT
        )
        result = svc.analyze_paid_to_organic(db, tenant_id=1, shop=_shop())
        data = result["data"]
        assert data["analyzed_pairs"] == 1
        assert data["candidates"] == 1  # keyword 不在 title 里，不是全覆盖
        assert data["written"] == 1

    def test_covered_candidate_skipped(self):
        """关键词完全在标题和属性里 → 从候选池排除（不是反哺机会）"""
        db = _fake_db(
            _FakeResult([]),
            _FakeResult([]),
            _FakeResult([
                _row(keyword="серьги", product_id=100, cat_id=5,
                     title="серьги треугольные медицинский",  # 已含
                     attrs='{"type":"серьги"}',               # 也含
                     frequency=20, impressions=100, add_to_cart=3,
                     orders=2, revenue=500.0),
            ]),
            _FakeResult([]),
        )
        result = svc.analyze_paid_to_organic(db, tenant_id=1, shop=_shop())
        # in_title AND in_attrs 都为 1 → 跳过
        assert result["data"]["analyzed_pairs"] == 1
        assert result["data"]["candidates"] == 0
        # 没候选不会触发 _upsert_candidates，db.execute 只调 4 次（4 个 SELECT）
        assert db.execute.call_count == 4

    def test_category_word_fans_out_to_products(self):
        """类目维词扩散：organic_cat 里某词 → prod_cat_sql 返回 2 个商品
        → 生成 2 个候选"""
        db = _fake_db(
            _FakeResult([]),  # paid self
            _FakeResult([]),  # paid cat
            _FakeResult([]),  # organic self
            _FakeResult([     # organic cat
                _row(keyword="треугольные", cat_id=5, shared_products=3,
                     frequency=50, impressions=200, add_to_cart=10,
                     orders=5, revenue=1000.0),
            ]),
            _FakeResult([     # prod_cat_sql：同 cat_id=5 的两个商品
                _row(product_id=101, cat_id=5, title="кольцо", attrs=""),
                _row(product_id=102, cat_id=5, title="браслет", attrs=""),
            ]),
            _FakeResult([], rowcount=1),  # INSERT for candidate 1
            _FakeResult([], rowcount=1),  # INSERT for candidate 2
        )
        result = svc.analyze_paid_to_organic(db, tenant_id=1, shop=_shop())
        data = result["data"]
        assert data["analyzed_pairs"] == 2
        assert data["candidates"] == 2
        assert data["written"] == 2

    def test_self_and_category_merge(self):
        """同商品同词分别从 organic_self 和 organic_cat 进来 → 合并成 1 个
        candidate，sources 加两次"""
        db = _fake_db(
            _FakeResult([]),  # paid self
            _FakeResult([]),  # paid cat
            _FakeResult([     # organic self: product=100, kw='X'
                _row(keyword="X", product_id=100, cat_id=5,
                     title="other", attrs="",
                     frequency=20, impressions=100, add_to_cart=5,
                     orders=3, revenue=500.0),
            ]),
            _FakeResult([     # organic cat: kw='X' in cat=5
                _row(keyword="X", cat_id=5, shared_products=3,
                     frequency=200, impressions=800, add_to_cart=20,
                     orders=10, revenue=2000.0),
            ]),
            _FakeResult([     # prod_cat_sql: product=100, 105（两个商品）
                _row(product_id=100, cat_id=5, title="other", attrs=""),
                _row(product_id=105, cat_id=5, title="другое", attrs=""),
            ]),
            _FakeResult([], rowcount=1),
            _FakeResult([], rowcount=1),
        )
        result = svc.analyze_paid_to_organic(db, tenant_id=1, shop=_shop())
        # analyzed pairs = 2 个（100,X）和（105,X）
        assert result["data"]["analyzed_pairs"] == 2
        # 100,X 有 organic_self + organic_category 两源
        # 105,X 只有 organic_category
        assert result["data"]["candidates"] == 2
        assert result["data"]["written"] == 2
