"""SEO 模块接口单元测试

覆盖 5 个接口（一期 MVP）：
- POST /seo/shop/{id}/generate-title       AI 融合候选词生成新俄语标题
- GET  /seo/shop/{id}/health               店铺健康分
- GET  /seo/shop/{id}/candidates           候选清单（含 product_id 过滤）
- GET  /seo/shop/{id}/generated-titles     AI 标题历史
- POST /seo/shop/{id}/generated-titles/{gid}/apply  标记已应用

每个接口至少验：
- 未认证 403
- 正常路径 200 + code=0
- service 返非零错误码时透传
- shop 不存在 404（少量抽验，不是每接口都测）

认证统一用 override 绕过；服务层函数全 patch。
"""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi.testclient import TestClient

from app.main import app
from app.dependencies import get_current_user, get_tenant_id, get_owned_shop


class _MockShop:
    """伪 Shop 模型对象，service 层读 shop.id"""

    def __init__(self, shop_id=1, tenant_id=1, platform="wb"):
        self.id = shop_id
        self.tenant_id = tenant_id
        self.platform = platform
        self.name = f"Shop-{shop_id}"


def _mock_current_user():
    user = MagicMock()
    user.id = 1
    user.tenant_id = 1
    return user


@pytest.fixture
def client():
    """带认证 + shop 守卫 override 的客户端"""
    app.dependency_overrides[get_current_user] = _mock_current_user
    app.dependency_overrides[get_tenant_id] = lambda: 1
    app.dependency_overrides[get_owned_shop] = lambda: _MockShop(shop_id=1)
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def no_auth_client():
    """无认证客户端"""
    with TestClient(app) as c:
        yield c


# ================== 1. GET /candidates（含 product_id 过滤）==================

class TestListCandidates:

    def test_no_auth(self, no_auth_client):
        resp = no_auth_client.get("/api/v1/seo/shop/1/candidates")
        assert resp.status_code == 403

    @patch("app.api.v1.seo.list_candidates")
    def test_list_default(self, mock_fn, client):
        mock_fn.return_value = {
            "code": 0,
            "data": {
                "totals": {"total": 100, "with_conversion": 10, "gap": 80, "products": 50},
                "items": [], "page": 1, "size": 20,
            },
        }
        resp = client.get("/api/v1/seo/shop/1/candidates")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"]["totals"]["total"] == 100
        # 断言 source_filter 默认 all / status 默认 pending
        args = mock_fn.call_args.kwargs
        assert args["source_filter"] == "all"
        assert args["status"] == "pending"
        assert args["product_id"] is None

    @patch("app.api.v1.seo.list_candidates")
    def test_filter_by_product_id(self, mock_fn, client):
        """Health → Optimize 闭环用的 product_id 过滤参数"""
        mock_fn.return_value = {"code": 0, "data": {
            "totals": {"total": 5, "with_conversion": 2, "gap": 3, "products": 1},
            "items": [], "page": 1, "size": 20,
        }}
        resp = client.get("/api/v1/seo/shop/1/candidates?product_id=145")
        assert resp.status_code == 200
        assert mock_fn.call_args.kwargs["product_id"] == 145

    @patch("app.api.v1.seo.list_candidates")
    def test_source_organic_self(self, mock_fn, client):
        mock_fn.return_value = {"code": 0, "data": {
            "totals": {"total": 0, "with_conversion": 0, "gap": 0, "products": 0},
            "items": [], "page": 1, "size": 20,
        }}
        resp = client.get("/api/v1/seo/shop/1/candidates?source=organic_self")
        assert resp.status_code == 200
        assert mock_fn.call_args.kwargs["source_filter"] == "organic_self"

    def test_invalid_page_rejected(self, client):
        """page<1 被 pydantic 拒"""
        resp = client.get("/api/v1/seo/shop/1/candidates?page=0")
        assert resp.status_code == 422

    def test_size_over_limit_rejected(self, client):
        """size>100 被拒"""
        resp = client.get("/api/v1/seo/shop/1/candidates?size=500")
        assert resp.status_code == 422


# ================== 2. POST /refresh ==================

class TestRefreshCandidates:

    def test_no_auth(self, no_auth_client):
        resp = no_auth_client.post("/api/v1/seo/shop/1/refresh")
        assert resp.status_code == 403

    @patch("app.api.v1.seo.analyze_paid_to_organic")
    def test_refresh_default(self, mock_fn, client):
        mock_fn.return_value = {
            "code": 0,
            "data": {"analyzed_pairs": 100, "candidates": 80, "written": 80,
                     "roas_threshold": 2.0, "days": 30, "shop_id": 1},
        }
        resp = client.post("/api/v1/seo/shop/1/refresh")
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["written"] == 80
        # 默认参数
        assert mock_fn.call_args.kwargs["days"] == 30
        assert mock_fn.call_args.kwargs["roas_threshold"] == 2.0

    @patch("app.api.v1.seo.analyze_paid_to_organic")
    def test_refresh_custom_params(self, mock_fn, client):
        mock_fn.return_value = {"code": 0, "data": {
            "analyzed_pairs": 0, "candidates": 0, "written": 0,
            "roas_threshold": 1.5, "days": 7, "shop_id": 1,
        }}
        resp = client.post("/api/v1/seo/shop/1/refresh",
                           json={"days": 7, "roas_threshold": 1.5, "min_orders": 0})
        assert resp.status_code == 200
        assert mock_fn.call_args.kwargs["days"] == 7
        assert mock_fn.call_args.kwargs["roas_threshold"] == 1.5

    def test_refresh_invalid_days(self, client):
        """days<7 被拒"""
        resp = client.post("/api/v1/seo/shop/1/refresh", json={"days": 3})
        assert resp.status_code == 422


# ================== 3. POST /candidates/{id}/adopt + batch-ignore ==================

class TestAdoptAndIgnore:

    @patch("app.api.v1.seo.adopt_candidate")
    def test_adopt_success(self, mock_fn, client):
        mock_fn.return_value = {"code": 0, "data": {"id": 5, "status": "adopted"}}
        resp = client.post("/api/v1/seo/shop/1/candidates/5/adopt")
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "adopted"

    @patch("app.api.v1.seo.adopt_candidate")
    def test_adopt_not_found(self, mock_fn, client):
        from app.utils.errors import ErrorCode
        mock_fn.return_value = {"code": ErrorCode.SEO_CANDIDATE_NOT_FOUND,
                                "msg": "候选词不存在"}
        resp = client.post("/api/v1/seo/shop/1/candidates/999/adopt")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == ErrorCode.SEO_CANDIDATE_NOT_FOUND

    @patch("app.api.v1.seo.ignore_candidates")
    def test_batch_ignore(self, mock_fn, client):
        mock_fn.return_value = {"code": 0, "data": {"updated": 3}}
        resp = client.post("/api/v1/seo/shop/1/candidates/batch-ignore",
                           json={"ids": [1, 2, 3]})
        assert resp.status_code == 200
        assert resp.json()["data"]["updated"] == 3

    def test_batch_ignore_empty_rejected(self, client):
        """空列表被 pydantic min_length=1 拒 —— 老林 04-20 修的 Pydantic v2"""
        resp = client.post("/api/v1/seo/shop/1/candidates/batch-ignore",
                           json={"ids": []})
        assert resp.status_code == 422


# ================== 4. POST /generate-title（AI 生成）==================

class TestGenerateTitle:

    def test_no_auth(self, no_auth_client):
        resp = no_auth_client.post("/api/v1/seo/shop/1/generate-title",
                                   json={"product_id": 1, "candidate_ids": [1]})
        assert resp.status_code == 403

    @patch("app.api.v1.seo.generate_title", new_callable=AsyncMock)
    def test_generate_success(self, mock_fn, client):
        mock_fn.return_value = {
            "code": 0,
            "data": {
                "generated_id": 1,
                "product_id": 145,
                "original_title": "Крупные сферические ювелирные серьги",
                "new_title": "женские серьги шары люстры крупные бижутерия",
                "reasoning": "将搜索量高的关键词放在前面",
                "included_keywords": ["серьги", "шары", "крупные"],
                "ai_model": "glm",
                "duration_ms": 4145,
                "tokens": {"prompt": 484, "completion": 107, "total": 591},
            },
        }
        resp = client.post("/api/v1/seo/shop/1/generate-title",
                           json={"product_id": 145,
                                 "candidate_ids": [1, 2, 3, 4, 5]})
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert "new_title" in body["data"]
        assert body["data"]["ai_model"] == "glm"

    def test_empty_candidate_ids_rejected(self, client):
        """空候选列表被 min_length=1 拒"""
        resp = client.post("/api/v1/seo/shop/1/generate-title",
                           json={"product_id": 1, "candidate_ids": []})
        assert resp.status_code == 422

    def test_over_30_candidates_rejected(self, client):
        """超 30 个被 max_length=30 拒"""
        resp = client.post("/api/v1/seo/shop/1/generate-title",
                           json={"product_id": 1, "candidate_ids": list(range(1, 32))})
        assert resp.status_code == 422

    def test_invalid_product_id_rejected(self, client):
        """product_id <= 0 被 gt=0 拒"""
        resp = client.post("/api/v1/seo/shop/1/generate-title",
                           json={"product_id": 0, "candidate_ids": [1]})
        assert resp.status_code == 422

    @patch("app.api.v1.seo.generate_title", new_callable=AsyncMock)
    def test_product_not_found(self, mock_fn, client):
        from app.utils.errors import ErrorCode
        mock_fn.return_value = {"code": ErrorCode.SEO_PRODUCT_NOT_FOUND,
                                "msg": "商品不存在"}
        resp = client.post("/api/v1/seo/shop/1/generate-title",
                           json={"product_id": 999, "candidate_ids": [1]})
        assert resp.status_code == 200
        assert resp.json()["code"] == ErrorCode.SEO_PRODUCT_NOT_FOUND


# ================== 5. GET /health（SEO 健康分）==================

class TestShopHealth:

    def test_no_auth(self, no_auth_client):
        resp = no_auth_client.get("/api/v1/seo/shop/1/health")
        assert resp.status_code == 403

    @patch("app.api.v1.seo.compute_shop_health")
    def test_health_default(self, mock_fn, client):
        mock_fn.return_value = {
            "code": 0,
            "data": {
                "totals": {"total": 78, "poor": 78, "fair": 0, "good": 0,
                           "data_insufficient": 0, "avg_score": 17.6},
                "items": [], "page": 1, "size": 20,
            },
        }
        resp = client.get("/api/v1/seo/shop/1/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["totals"]["avg_score"] == 17.6
        # 默认参数
        args = mock_fn.call_args.kwargs
        assert args["score_range"] == "all"
        assert args["sort"] == "score_asc"

    @patch("app.api.v1.seo.compute_shop_health")
    def test_health_filter_poor(self, mock_fn, client):
        mock_fn.return_value = {"code": 0, "data": {
            "totals": {"total": 78, "poor": 78, "fair": 0, "good": 0,
                       "data_insufficient": 0, "avg_score": 17.6},
            "items": [], "page": 1, "size": 20,
        }}
        resp = client.get("/api/v1/seo/shop/1/health?score_range=poor&sort=gaps_desc")
        assert resp.status_code == 200
        assert mock_fn.call_args.kwargs["score_range"] == "poor"
        assert mock_fn.call_args.kwargs["sort"] == "gaps_desc"


# ================== 6. GET /generated-titles（AI 历史）==================

class TestListGeneratedTitles:

    def test_no_auth(self, no_auth_client):
        resp = no_auth_client.get("/api/v1/seo/shop/1/generated-titles")
        assert resp.status_code == 403

    @patch("app.api.v1.seo.list_generated_titles")
    def test_list_default(self, mock_fn, client):
        mock_fn.return_value = {
            "code": 0,
            "data": {
                "total": 1, "page": 1, "size": 20,
                "items": [{
                    "id": 1, "product_id": 145, "ai_model": "glm",
                    "approval_status": "pending",
                    "original_text": "Крупные сферические ювелирные серьги",
                    "generated_text": "женские серьги шары крупные",
                    "created_at": "2026-04-20T09:31:32Z",
                }],
            },
        }
        resp = client.get("/api/v1/seo/shop/1/generated-titles")
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["total"] == 1
        assert body["data"]["items"][0]["ai_model"] == "glm"

    @patch("app.api.v1.seo.list_generated_titles")
    def test_filter_approved(self, mock_fn, client):
        mock_fn.return_value = {"code": 0, "data": {
            "total": 0, "page": 1, "size": 20, "items": [],
        }}
        resp = client.get("/api/v1/seo/shop/1/generated-titles?approval_status=applied")
        assert resp.status_code == 200
        assert mock_fn.call_args.kwargs["approval_status"] == "applied"


# ================== 7. POST /generated-titles/{gid}/apply ==================

class TestApplyGeneratedTitle:

    def test_no_auth(self, no_auth_client):
        resp = no_auth_client.post("/api/v1/seo/shop/1/generated-titles/1/apply")
        assert resp.status_code == 403

    @patch("app.api.v1.seo.mark_title_applied")
    def test_apply_success(self, mock_fn, client):
        mock_fn.return_value = {
            "code": 0,
            "data": {
                "id": 1,
                "approval_status": "applied",
                "applied_at": "2026-04-21T00:00:00Z",
                "approved_by": 1,
            },
        }
        resp = client.post("/api/v1/seo/shop/1/generated-titles/1/apply")
        assert resp.status_code == 200
        assert resp.json()["data"]["approval_status"] == "applied"

    @patch("app.api.v1.seo.mark_title_applied")
    def test_apply_not_found(self, mock_fn, client):
        from app.utils.errors import ErrorCode
        mock_fn.return_value = {"code": ErrorCode.NOT_FOUND,
                                "msg": "生成记录不存在"}
        resp = client.post("/api/v1/seo/shop/1/generated-titles/999/apply")
        assert resp.status_code == 200
        assert resp.json()["code"] == ErrorCode.NOT_FOUND
