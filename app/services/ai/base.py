"""AI模型客户端基类"""

import json
import time
from abc import ABC, abstractmethod
from typing import AsyncGenerator, Optional

import httpx

from app.utils.logger import logger


class BaseAIClient(ABC):
    """AI模型客户端基类，统一接口"""

    def __init__(self, api_key: str, base_url: str, model_name: str, timeout: int = 60):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name
        self.timeout = timeout

    @abstractmethod
    def _get_headers(self) -> dict:
        """获取请求头"""
        ...

    @abstractmethod
    def _get_chat_url(self) -> str:
        """获取聊天接口URL"""
        ...

    @abstractmethod
    def _parse_response(self, resp_json: dict) -> dict:
        """解析响应，返回标准格式"""
        ...

    async def chat(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 2000,
        system_prompt: Optional[str] = None,
    ) -> dict:
        """统一的聊天调用接口

        Args:
            messages: [{"role": "user", "content": "..."}]
            temperature: 温度
            max_tokens: 最大输出token
            system_prompt: 系统提示词

        Returns:
            {
                "content": "AI回复内容",
                "prompt_tokens": int,
                "completion_tokens": int,
                "total_tokens": int,
                "duration_ms": int,
                "model": "模型名",
            }
        """
        if system_prompt:
            messages = [{"role": "system", "content": system_prompt}] + messages

        payload = {
            "model": self.model_name,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        start_time = time.time()
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    self._get_chat_url(),
                    headers=self._get_headers(),
                    json=payload,
                )
                resp.raise_for_status()
                resp_json = resp.json()

            duration_ms = int((time.time() - start_time) * 1000)
            result = self._parse_response(resp_json)
            result["duration_ms"] = duration_ms
            result["model"] = self.model_name

            logger.info(
                f"AI调用成功: model={self.model_name} "
                f"tokens={result.get('total_tokens', 0)} "
                f"duration={duration_ms}ms"
            )
            return result

        except httpx.TimeoutException:
            duration_ms = int((time.time() - start_time) * 1000)
            logger.error(f"AI调用超时: model={self.model_name} duration={duration_ms}ms")
            raise
        except httpx.HTTPStatusError as e:
            logger.error(f"AI调用HTTP错误: model={self.model_name} status={e.response.status_code}")
            raise
        except Exception as e:
            logger.error(f"AI调用异常: model={self.model_name}: {e}")
            raise

    async def chat_stream(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 2000,
        system_prompt: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """流式聊天接口，逐块 yield 文本片段"""
        if system_prompt:
            messages = [{"role": "system", "content": system_prompt}] + messages

        payload = {
            "model": self.model_name,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream(
                "POST",
                self._get_chat_url(),
                headers=self._get_headers(),
                json=payload,
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                        delta = chunk["choices"][0].get("delta", {})
                        text = delta.get("content", "")
                        if text:
                            yield text
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue
