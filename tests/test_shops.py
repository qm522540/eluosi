"""Shops模块单元测试"""

import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from app.main import app
from app.dependencies import get_current_user, get_tenant_id


@pytest.fixture
def client():
    """带认证的测试客户端"""
    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": 1, "tenant_id": 1, "role": "owner"
    }
    app.dependency_overrides[get_tenant_id] = lambda: 1
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def no_auth_client():
    """不带认证的测试客户端"""
    with TestClient(app) as c:
        yield c


# =========== 店铺列表 ===========

class TestShopList:
    """GET /api/v1/shops"""

    def test_list_no_auth(self, no_auth_client):
        """未认证不能访问"""
        resp = no_auth_client.get("/api/v1/shops")
        assert resp.status_code == 403

    @patch("app.api.v1.shops.list_shops")
    def test_list_success(self, mock_list, client):
        """获取店铺列表"""
        mock_list.return_value = {
            "code": 0,
            "data": {
                "items": [
                    {"id": 1, "name": "WB店铺1", "platform": "wb", "status": "active"},
                ],
                "total": 1, "page": 1, "page_size": 20, "pages": 1,
            },
        }
        resp = client.get("/api/v1/shops")
        data = resp.json()
        assert data["code"] == 0
        assert len(data["data"]["items"]) == 1

    @patch("app.api.v1.shops.list_shops")
    def test_list_with_platform_filter(self, mock_list, client):
        """按平台筛选"""
        mock_list.return_value = {
            "code": 0,
            "data": {"items": [], "total": 0, "page": 1, "page_size": 20, "pages": 0},
        }
        resp = client.get("/api/v1/shops?platform=ozon")
        assert resp.json()["code"] == 0


# =========== 创建店铺 ===========

class TestShopCreate:
    """POST /api/v1/shops"""

    def test_create_missing_fields(self, client):
        """缺少必填字段"""
        resp = client.post("/api/v1/shops", json={"name": "test"})
        assert resp.status_code == 422

    def test_create_invalid_platform(self, client):
        """无效平台"""
        resp = client.post("/api/v1/shops", json={
            "name": "test", "platform": "amazon"
        })
        assert resp.status_code == 422

    @patch("app.api.v1.shops.create_shop")
    def test_create_success(self, mock_create, client):
        """创建成功"""
        mock_create.return_value = {
            "code": 0,
            "data": {"id": 1, "name": "WB店铺", "platform": "wb", "status": "active"},
        }
        resp = client.post("/api/v1/shops", json={
            "name": "WB店铺",
            "platform": "wb",
            "api_key": "test-key",
        })
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["platform"] == "wb"

    @patch("app.api.v1.shops.create_shop")
    def test_create_limit_exceeded(self, mock_create, client):
        """超出店铺数量限制"""
        mock_create.return_value = {
            "code": 30003, "msg": "店铺数量已达上限(3)"
        }
        resp = client.post("/api/v1/shops", json={
            "name": "新店铺", "platform": "wb",
        })
        data = resp.json()
        assert data["code"] == 30003


# =========== 店铺详情 ===========

class TestShopDetail:
    """GET /api/v1/shops/{shop_id}"""

    @patch("app.api.v1.shops.get_shop")
    def test_detail_success(self, mock_get, client):
        """获取店铺详情"""
        mock_get.return_value = {
            "code": 0,
            "data": {
                "id": 1, "name": "WB店铺", "platform": "wb",
                "has_api_key": True, "has_api_secret": False,
                "has_client_id": False, "has_oauth_token": False,
            },
        }
        resp = client.get("/api/v1/shops/1")
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["has_api_key"] is True

    @patch("app.api.v1.shops.get_shop")
    def test_detail_not_found(self, mock_get, client):
        """店铺不存在"""
        mock_get.return_value = {"code": 30001, "msg": "店铺不存在"}
        resp = client.get("/api/v1/shops/999")
        data = resp.json()
        assert data["code"] == 30001


# =========== 更新店铺 ===========

class TestShopUpdate:
    """PUT /api/v1/shops/{shop_id}"""

    @patch("app.api.v1.shops.update_shop")
    def test_update_success(self, mock_update, client):
        """更新店铺"""
        mock_update.return_value = {
            "code": 0,
            "data": {"id": 1, "name": "新名称", "platform": "wb", "status": "active"},
        }
        resp = client.put("/api/v1/shops/1", json={"name": "新名称"})
        data = resp.json()
        assert data["code"] == 0


# =========== 删除店铺 ===========

class TestShopDelete:
    """DELETE /api/v1/shops/{shop_id}"""

    @patch("app.api.v1.shops.delete_shop")
    def test_delete_success(self, mock_delete, client):
        """删除店铺"""
        mock_delete.return_value = {"code": 0, "data": None}
        resp = client.delete("/api/v1/shops/1")
        data = resp.json()
        assert data["code"] == 0


# =========== 测试连接 ===========

class TestShopTestConnection:
    """POST /api/v1/shops/{shop_id}/test-connection"""

    @patch("app.api.v1.shops.test_connection")
    def test_connection_success(self, mock_test, client):
        """连接测试成功"""
        mock_test.return_value = {
            "code": 0,
            "data": {"connected": True, "detail": "ok"},
        }
        resp = client.post("/api/v1/shops/1/test-connection")
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["connected"] is True
