"""纯底层大模型网络请求通道 (3O 范式 Phase 1).

收发器语义: 本文件只负责 HTTP 流式传输。
绝对禁止出现 messages / max_tokens 等大模型业务参数与 Prompt 组装。
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import httpx

from obase.contracts import ILLM_Client


class HttpLLMClient(ILLM_Client):
    """纯底层 HTTP 流式客户端"""

    def __init__(self, timeout: float = 60.0):
        self.timeout = timeout

    async def stream_request(
        self, endpoint: str, payload: dict, headers: dict
    ) -> AsyncGenerator[bytes, None]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream(
                "POST", endpoint, json=payload, headers=headers
            ) as response:
                response.raise_for_status()
                async for chunk in response.aiter_bytes():
                    if chunk:
                        yield chunk
