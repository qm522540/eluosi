"""DeepSeek AI客户端

用途：数据分析、ROI计算、广告优化、库存预测
API兼容OpenAI格式
"""

from app.services.ai.base import BaseAIClient


class DeepSeekClient(BaseAIClient):

    def __init__(self, api_key: str, base_url: str = "https://api.deepseek.com"):
        super().__init__(
            api_key=api_key,
            base_url=base_url,
            model_name="deepseek-chat",
            timeout=120,
        )

    def _get_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _get_chat_url(self) -> str:
        return f"{self.base_url}/chat/completions"

    def _parse_response(self, resp_json: dict) -> dict:
        choice = resp_json["choices"][0]
        usage = resp_json.get("usage", {})
        return {
            "content": choice["message"]["content"],
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        }
