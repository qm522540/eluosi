"""Auth模块单元测试"""

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


# =========== 登录接口 ===========

class TestLogin:
    """POST /api/v1/auth/login"""

    def test_login_missing_fields(self, client):
        """缺少必填字段"""
        resp = client.post("/api/v1/auth/login", json={})
        assert resp.status_code == 422

    def test_login_password_too_short(self, client):
        """密码长度不足"""
        resp = client.post("/api/v1/auth/login", json={
            "email": "test@test.com",
            "password": "123",
        })
        assert resp.status_code == 422

    @patch("app.api.v1.auth.authenticate_user")
    def test_login_success(self, mock_auth, client):
        """登录成功"""
        mock_auth.return_value = {
            "code": 0,
            "data": {
                "access_token": "fake-jwt-token",
                "token_type": "bearer",
                "expires_in": 86400,
                "user": {
                    "id": 1, "tenant_id": 1, "username": "张三",
                    "email": "test@test.com", "role": "owner", "status": "active",
                },
            },
        }
        resp = client.post("/api/v1/auth/login", json={
            "email": "test@test.com",
            "password": "password123",
        })
        data = resp.json()
        assert data["code"] == 0
        assert "access_token" in data["data"]

    @patch("app.api.v1.auth.authenticate_user")
    def test_login_wrong_password(self, mock_auth, client):
        """密码错误"""
        mock_auth.return_value = {"code": 20001, "msg": "邮箱或密码错误"}
        resp = client.post("/api/v1/auth/login", json={
            "email": "test@test.com",
            "password": "wrongpassword",
        })
        data = resp.json()
        assert data["code"] == 20001


# =========== 注册接口 ===========

class TestRegister:
    """POST /api/v1/auth/register"""

    def test_register_missing_fields(self, client):
        """缺少必填字段"""
        resp = client.post("/api/v1/auth/register", json={"username": "test"})
        assert resp.status_code == 422

    @patch("app.api.v1.auth.register_user")
    def test_register_success(self, mock_register, client):
        """注册成功"""
        mock_register.return_value = {
            "code": 0,
            "data": {
                "user_id": 1, "tenant_id": 1,
                "username": "张三", "email": "test@test.com", "role": "owner",
            },
        }
        resp = client.post("/api/v1/auth/register", json={
            "username": "张三",
            "email": "test@test.com",
            "password": "password123",
            "tenant_name": "测试公司",
        })
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["user_id"] == 1

    @patch("app.api.v1.auth.register_user")
    def test_register_duplicate_email(self, mock_register, client):
        """邮箱已存在"""
        mock_register.return_value = {"code": 10002, "msg": "该邮箱已被注册"}
        resp = client.post("/api/v1/auth/register", json={
            "username": "张三",
            "email": "dup@test.com",
            "password": "password123",
            "tenant_name": "测试公司",
        })
        data = resp.json()
        assert data["code"] == 10002


# =========== 获取当前用户 ===========

class TestMe:
    """GET /api/v1/auth/me"""

    def test_me_no_token(self, client):
        """未提供token"""
        resp = client.get("/api/v1/auth/me")
        assert resp.status_code == 403

    @patch("app.dependencies.get_current_user")
    @patch("app.api.v1.auth.get_user_info")
    def test_me_success(self, mock_info, mock_user, client):
        """获取当前用户信息"""
        mock_user.return_value = {"user_id": 1, "tenant_id": 1, "role": "owner"}
        mock_info.return_value = {
            "code": 0,
            "data": {
                "id": 1, "tenant_id": 1, "username": "张三",
                "email": "test@test.com", "role": "owner", "status": "active",
                "last_login_at": None, "tenant": None,
            },
        }
        # 需要override依赖
        from app.dependencies import get_current_user
        app.dependency_overrides[get_current_user] = lambda: {"user_id": 1, "tenant_id": 1, "role": "owner"}
        try:
            resp = client.get("/api/v1/auth/me")
            data = resp.json()
            assert data["code"] == 0
            assert data["data"]["username"] == "张三"
        finally:
            app.dependency_overrides.clear()
