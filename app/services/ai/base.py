"""AI模型客户端基类"""

import asyncio
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

        # 429 限流时指数退避重试: sleep 1s -> 2s -> 4s, 最多 3 次
        # Moonshot 高并发场景常见,Retry-After header 优先用,没有就走指数
        max_retries = 3
        last_err = None
        for attempt in range(max_retries):
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
                    + (f" (重试 {attempt} 次后成功)" if attempt > 0 else "")
                )
                return result

            except httpx.TimeoutException:
                duration_ms = int((time.time() - start_time) * 1000)
                logger.error(f"AI调用超时: model={self.model_name} duration={duration_ms}ms")
                raise
            except httpx.HTTPStatusError as e:
                last_err = e
                # 仅 429 重试; 其他 HTTP 错误立即抛出
                if e.response.status_code == 429 and attempt < max_retries - 1:
                    retry_after = e.response.headers.get("Retry-After")
                    sleep_s = float(retry_after) if retry_after else (2 ** attempt)
                    logger.warning(
                        f"AI 限流 429: model={self.model_name} 第 {attempt+1} 次,"
                        f" sleep {sleep_s}s 后重试"
                    )
                    await asyncio.sleep(sleep_s)
                    continue
                logger.error(f"AI调用HTTP错误: model={self.model_name} status={e.response.status_code}")
                raise
            except Exception as e:
                logger.error(f"AI调用异常: model={self.model_name}: {e}")
                raise

        # 不应到达这里(循环里要么 return 要么 raise)
        raise last_err if last_err else RuntimeError("AI调用未知失败")

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
