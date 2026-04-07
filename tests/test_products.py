"""商品模块单元测试"""

import unittest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

# Mock认证依赖
mock_user = {"user_id": 1, "tenant_id": 1, "role": "owner"}


def override_get_current_user():
    return mock_user


def override_get_tenant_id():
    return 1


app.dependency_overrides = {}


class TestProductAPI(unittest.TestCase):
    """商品接口测试"""

    def setUp(self):
        from app.dependencies import get_current_user, get_tenant_id
        app.dependency_overrides[get_current_user] = override_get_current_user
        app.dependency_overrides[get_tenant_id] = override_get_tenant_id

    def tearDown(self):
        app.dependency_overrides = {}

    def test_product_list_unauthorized(self):
        """未认证访问应返回403"""
        app.dependency_overrides = {}
        resp = client.get("/api/v1/products")
        self.assertEqual(resp.status_code, 403)

    @patch("app.api.v1.products.list_products")
    def test_product_list_success(self, mock_fn):
        """获取商品列表 - 成功"""
        mock_fn.return_value = {
            "code": 0,
            "data": {"items": [], "total": 0, "page": 1, "page_size": 20, "pages": 0},
        }
        resp = client.get("/api/v1/products")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 0)
        self.assertIn("items", data["data"])

    @patch("app.api.v1.products.list_products")
    def test_product_list_with_keyword(self, mock_fn):
        """获取商品列表 - 关键词搜索"""
        mock_fn.return_value = {
            "code": 0,
            "data": {"items": [], "total": 0, "page": 1, "page_size": 20, "pages": 0},
        }
        resp = client.get("/api/v1/products?keyword=test&category=electronics")
        self.assertEqual(resp.status_code, 200)

    def test_product_create_missing_fields(self):
        """创建商品 - 缺少必填字段"""
        resp = client.post("/api/v1/products", json={})
        self.assertEqual(resp.status_code, 422)

    @patch("app.api.v1.products.create_product")
    def test_product_create_success(self, mock_fn):
        """创建商品 - 成功"""
        mock_fn.return_value = {
            "code": 0,
            "data": {"id": 1, "sku": "TEST001", "name_zh": "测试商品"},
        }
        resp = client.post("/api/v1/products", json={
            "sku": "TEST001",
            "name_zh": "测试商品",
            "cost_price": 100.00,
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["code"], 0)

    @patch("app.api.v1.products.create_product")
    def test_product_create_sku_duplicate(self, mock_fn):
        """创建商品 - SKU重复"""
        mock_fn.return_value = {"code": 40002, "msg": "SKU 'TEST001' 已存在"}
        resp = client.post("/api/v1/products", json={
            "sku": "TEST001",
            "name_zh": "测试商品",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["code"], 40002)

    @patch("app.api.v1.products.get_product")
    def test_product_detail_not_found(self, mock_fn):
        """获取商品详情 - 不存在"""
        mock_fn.return_value = {"code": 40001, "msg": "商品不存在"}
        resp = client.get("/api/v1/products/999")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["code"], 40001)

    @patch("app.api.v1.products.get_product")
    def test_product_detail_with_listings(self, mock_fn):
        """获取商品详情 - 含Listing"""
        mock_fn.return_value = {
            "code": 0,
            "data": {
                "id": 1, "sku": "TEST001", "name_zh": "测试",
                "listings": [
                    {"id": 1, "platform": "wb", "price": 1000},
                    {"id": 2, "platform": "ozon", "price": 1200},
                ],
            },
        }
        resp = client.get("/api/v1/products/1")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()["data"]["listings"]), 2)

    @patch("app.api.v1.products.delete_product")
    def test_product_delete_success(self, mock_fn):
        """删除商品 - 成功"""
        mock_fn.return_value = {"code": 0, "data": None}
        resp = client.delete("/api/v1/products/1")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["code"], 0)

    def test_listing_create_invalid_platform(self):
        """创建Listing - 无效平台"""
        resp = client.post("/api/v1/products/listings", json={
            "product_id": 1,
            "shop_id": 1,
            "platform": "amazon",
            "platform_product_id": "123",
        })
        self.assertEqual(resp.status_code, 422)

    @patch("app.api.v1.products.create_listing")
    def test_listing_create_success(self, mock_fn):
        """创建Listing - 成功"""
        mock_fn.return_value = {
            "code": 0,
            "data": {"id": 1, "platform": "wb", "price": 1000},
        }
        resp = client.post("/api/v1/products/listings", json={
            "product_id": 1,
            "shop_id": 1,
            "platform": "wb",
            "platform_product_id": "WB123",
            "price": 1000,
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["code"], 0)


class TestAdAPI(unittest.TestCase):
    """广告接口测试"""

    def setUp(self):
        from app.dependencies import get_current_user, get_tenant_id
        app.dependency_overrides[get_current_user] = override_get_current_user
        app.dependency_overrides[get_tenant_id] = override_get_tenant_id

    def tearDown(self):
        app.dependency_overrides = {}

    def test_campaigns_unauthorized(self):
        """未认证访问广告活动列表"""
        app.dependency_overrides = {}
        resp = client.get("/api/v1/ads/campaigns")
        self.assertEqual(resp.status_code, 403)

    @patch("app.api.v1.ads.list_campaigns")
    def test_campaigns_list_success(self, mock_fn):
        """获取广告活动列表"""
        mock_fn.return_value = {
            "code": 0,
            "data": {"items": [], "total": 0, "page": 1, "page_size": 20, "pages": 0},
        }
        resp = client.get("/api/v1/ads/campaigns")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["code"], 0)

    @patch("app.api.v1.ads.list_campaigns")
    def test_campaigns_filter_by_platform(self, mock_fn):
        """广告活动按平台筛选"""
        mock_fn.return_value = {
            "code": 0,
            "data": {"items": [], "total": 0, "page": 1, "page_size": 20, "pages": 0},
        }
        resp = client.get("/api/v1/ads/campaigns?platform=wb&status=active")
        self.assertEqual(resp.status_code, 200)

    @patch("app.api.v1.ads.get_ad_stats")
    def test_ad_stats_query(self, mock_fn):
        """查询广告统计数据"""
        mock_fn.return_value = {"code": 0, "data": []}
        resp = client.get("/api/v1/ads/stats?start_date=2026-04-01&end_date=2026-04-07")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["code"], 0)

    def test_ad_stats_missing_date(self):
        """查询广告统计 - 缺少日期参数"""
        resp = client.get("/api/v1/ads/stats")
        self.assertEqual(resp.status_code, 422)

    @patch("app.api.v1.ads.get_ad_summary")
    def test_ad_summary(self, mock_fn):
        """获取广告汇总数据"""
        mock_fn.return_value = {
            "code": 0,
            "data": {
                "total_impressions": 10000,
                "total_clicks": 500,
                "total_spend": 5000.00,
                "total_orders": 50,
                "total_revenue": 25000.00,
                "overall_roas": 5.0,
            },
        }
        resp = client.get("/api/v1/ads/summary")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["data"]["overall_roas"], 5.0)


class TestFinanceAPI(unittest.TestCase):
    """财务接口测试"""

    def setUp(self):
        from app.dependencies import get_current_user, get_tenant_id
        app.dependency_overrides[get_current_user] = override_get_current_user
        app.dependency_overrides[get_tenant_id] = override_get_tenant_id

    def tearDown(self):
        app.dependency_overrides = {}

    @patch("app.api.v1.finance.get_dashboard_overview")
    def test_dashboard_overview(self, mock_fn):
        """首页大盘数据"""
        mock_fn.return_value = {
            "code": 0,
            "data": {
                "shop_count": 3,
                "product_count": 50,
                "active_campaigns": 10,
                "today_revenue": 15000.00,
                "today_spend": 3000.00,
                "today_roi": 5.0,
            },
        }
        resp = client.get("/api/v1/finance/dashboard")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertEqual(data["shop_count"], 3)
        self.assertEqual(data["today_roi"], 5.0)

    @patch("app.api.v1.finance.get_revenue_list")
    def test_revenue_list(self, mock_fn):
        """获取收入明细"""
        mock_fn.return_value = {
            "code": 0,
            "data": {"items": [], "total": 0, "page": 1, "page_size": 20, "pages": 0},
        }
        resp = client.get("/api/v1/finance/revenue?start_date=2026-04-01&end_date=2026-04-07")
        self.assertEqual(resp.status_code, 200)

    @patch("app.api.v1.finance.create_cost")
    def test_cost_create(self, mock_fn):
        """手动录入费用"""
        mock_fn.return_value = {
            "code": 0,
            "data": {"id": 1, "cost_type": "logistics", "amount": 500.00},
        }
        resp = client.post("/api/v1/finance/costs", json={
            "shop_id": 1,
            "cost_date": "2026-04-07",
            "cost_type": "logistics",
            "amount": 500.00,
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["code"], 0)

    def test_cost_create_invalid_type(self):
        """录入费用 - 无效费用类型"""
        resp = client.post("/api/v1/finance/costs", json={
            "shop_id": 1,
            "cost_date": "2026-04-07",
            "cost_type": "invalid_type",
            "amount": 500.00,
        })
        self.assertEqual(resp.status_code, 422)

    @patch("app.api.v1.finance.get_roi_snapshots")
    def test_roi_trend(self, mock_fn):
        """获取ROI趋势数据"""
        mock_fn.return_value = {
            "code": 0,
            "data": [
                {"snapshot_date": "2026-04-01", "roi": 3.5, "roas": 4.2},
                {"snapshot_date": "2026-04-02", "roi": 4.0, "roas": 5.0},
            ],
        }
        resp = client.get("/api/v1/finance/roi?start_date=2026-04-01&end_date=2026-04-07")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()["data"]), 2)

    @patch("app.api.v1.finance.get_finance_summary")
    def test_finance_summary(self, mock_fn):
        """获取财务汇总"""
        mock_fn.return_value = {
            "code": 0,
            "data": {
                "total_revenue": 100000,
                "total_cost": 30000,
                "gross_profit": 70000,
                "roi": 233.33,
            },
        }
        resp = client.get("/api/v1/finance/summary")
        self.assertEqual(resp.status_code, 200)
        self.assertGreater(resp.json()["data"]["gross_profit"], 0)


class TestNotificationAPI(unittest.TestCase):
    """通知接口测试"""

    def setUp(self):
        from app.dependencies import get_current_user, get_tenant_id
        app.dependency_overrides[get_current_user] = override_get_current_user
        app.dependency_overrides[get_tenant_id] = override_get_tenant_id

    def tearDown(self):
        app.dependency_overrides = {}

    @patch("app.api.v1.notifications.get_notifications")
    def test_notification_list(self, mock_fn):
        """获取通知列表"""
        mock_fn.return_value = {
            "code": 0,
            "data": {"items": [], "total": 0, "page": 1, "page_size": 20, "pages": 0},
        }
        resp = client.get("/api/v1/notifications")
        self.assertEqual(resp.status_code, 200)

    @patch("app.api.v1.notifications.get_notifications")
    def test_notification_filter_unread(self, mock_fn):
        """获取未读通知"""
        mock_fn.return_value = {
            "code": 0,
            "data": {"items": [], "total": 0, "page": 1, "page_size": 20, "pages": 0},
        }
        resp = client.get("/api/v1/notifications?is_read=0")
        self.assertEqual(resp.status_code, 200)

    @patch("app.api.v1.notifications.mark_notification_read")
    def test_mark_read(self, mock_fn):
        """标记通知已读"""
        mock_fn.return_value = {"code": 0, "data": None}
        resp = client.put("/api/v1/notifications/1/read")
        self.assertEqual(resp.status_code, 200)


if __name__ == "__main__":
    unittest.main()
