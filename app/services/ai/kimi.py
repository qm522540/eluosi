"""Kimi (Moonshot) AI客户端

用途：长文档处理、报告生成
API兼容OpenAI格式，支持超长上下文
"""

from app.services.ai.base import BaseAIClient


class KimiClient(BaseAIClient):

    def __init__(self, api_key: str, base_url: str = "https://api.moonshot.cn/v1"):
        super().__init__(
            api_key=api_key,
            base_url=base_url,
            model_name="moonshot-v1-8k",
            timeout=180,  # 长文档需要更长超时
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
