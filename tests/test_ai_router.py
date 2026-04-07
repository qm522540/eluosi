"""AI路由调度单元测试"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.services.ai.router import TASK_MODEL_MAP, _get_client


class TestTaskModelMapping:
    """测试任务类型→模型映射"""

    def test_ad_optimization_uses_deepseek(self):
        assert TASK_MODEL_MAP["ad_optimization"] == "deepseek"

    def test_roi_analysis_uses_deepseek(self):
        assert TASK_MODEL_MAP["roi_analysis"] == "deepseek"

    def test_inventory_forecast_uses_deepseek(self):
        assert TASK_MODEL_MAP["inventory_forecast"] == "deepseek"

    def test_report_generation_uses_kimi(self):
        assert TASK_MODEL_MAP["report_generation"] == "kimi"

    def test_seo_generation_uses_glm(self):
        assert TASK_MODEL_MAP["seo_generation"] == "glm"


class TestGetClient:
    """测试客户端获取"""

    @patch("app.services.ai.router.settings")
    def test_missing_deepseek_key_raises(self, mock_settings):
        """未配置API Key应该报错"""
        mock_settings.DEEPSEEK_API_KEY = ""
        # 清除缓存
        from app.services.ai.router import _clients
        _clients.pop("deepseek", None)
        with pytest.raises(ValueError, match="DEEPSEEK_API_KEY"):
            _get_client("deepseek")

    def test_unknown_model_raises(self):
        """未知模型应该报错"""
        with pytest.raises(ValueError, match="未知的AI模型"):
            _get_client("gpt-4")


class TestDeepSeekClient:
    """测试DeepSeek客户端"""

    def test_headers(self):
        from app.services.ai.deepseek import DeepSeekClient
        client = DeepSeekClient(api_key="test-key")
        headers = client._get_headers()
        assert headers["Authorization"] == "Bearer test-key"

    def test_chat_url(self):
        from app.services.ai.deepseek import DeepSeekClient
        client = DeepSeekClient(api_key="test-key")
        assert client._get_chat_url() == "https://api.deepseek.com/chat/completions"

    def test_parse_response(self):
        from app.services.ai.deepseek import DeepSeekClient
        client = DeepSeekClient(api_key="test-key")
        resp = {
            "choices": [{"message": {"content": "分析结果"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        }
        result = client._parse_response(resp)
        assert result["content"] == "分析结果"
        assert result["total_tokens"] == 30


class TestKimiClient:
    """测试Kimi客户端"""

    def test_timeout_is_longer(self):
        from app.services.ai.kimi import KimiClient
        client = KimiClient(api_key="test-key")
        assert client.timeout == 180  # 长文档需要更长超时


class TestGLMClient:
    """测试GLM客户端"""

    def test_model_name(self):
        from app.services.ai.glm import GLMClient
        client = GLMClient(api_key="test-key")
        assert client.model_name == "glm-4-flash"

    def test_chat_url(self):
        from app.services.ai.glm import GLMClient
        client = GLMClient(api_key="test-key")
        assert "chat/completions" in client._get_chat_url()
