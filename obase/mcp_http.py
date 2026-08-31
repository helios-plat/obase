"""obase.mcp_http — Streamable HTTP transport MCP 客户端 (JSON-RPC over HTTP + SSE)。

通用机制: 连接任意 HTTP MCP 服务器 (如 Stratum /mcp), 实现 McpClientHandle 协议
(list_tools / call_tool), 供 McpClientRegistry 注册。

协议 (MCP Streamable HTTP):
  - initialize → 响应头 Mcp-Session-Id (会话态);
  - 后续请求带 Mcp-Session-Id 头;
  - 响应可能为 SSE (event: message / data: {...}) 或纯 JSON — 自动解析。
"""

from __future__ import annotations

import json
from typing import Any, cast

import httpx

from .mcp_client import McpClientHandle, McpClientRegistry


class HttpMcpError(RuntimeError):
    """HTTP MCP 客户端错误 (握手失败 / 非 2xx / 协议异常)。"""


def _parse_sse_or_json(body: str) -> dict[str, Any]:
    """解析响应: SSE 流 (event: message + data:) 或纯 JSON。"""
    text = body.strip()
    if text.startswith("{"):
        try:
            return cast(dict[str, Any], json.loads(text))
        except json.JSONDecodeError as exc:
            raise HttpMcpError("MCP JSON 响应无效") from exc
    # SSE: 取所有 data: 行拼接 (多帧时最后一帧是结果)
    payload = None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            payload = line[5:].strip()
    if payload is None:
        raise HttpMcpError("无法解析 MCP 响应")
    try:
        return cast(dict[str, Any], json.loads(payload))
    except json.JSONDecodeError as exc:
        raise HttpMcpError("MCP SSE 响应无效") from exc


class StreamableHttpMcpClient:
    """Streamable HTTP MCP 客户端 (McpClientHandle 协议实现)。

    Usage::

        client = StreamableHttpMcpClient("http://stratum-api:9302/mcp/mcp")
        await client.start()            # initialize → session
        await client.list_tools()
        await client.call_tool("search_knowledge", {"query_text": "..."})
        await client.close()
    """

    def __init__(
        self,
        endpoint: str,
        *,
        timeout: float = 60.0,
        name: str = "http-mcp",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.endpoint = endpoint
        self.timeout = timeout
        self.name = name
        self.headers = headers or {}
        self._client: httpx.AsyncClient | None = None
        self._session_id: str | None = None
        self._next_id = 1
        self._started = False

    # ── 生命周期 ───────────────────────────────────────────────────────

    async def start(self) -> None:
        """initialize 握手 → 保存 session id。幂等。"""
        if self._started:
            return
        self._client = httpx.AsyncClient(timeout=self.timeout)
        resp = await self._client.post(
            self.endpoint,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                **self.headers,
            },
            json={
                "jsonrpc": "2.0",
                "id": 0,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "veya-http-mcp", "version": "0.1"},
                },
            },
        )
        if resp.status_code not in (200, 202):
            raise HttpMcpError(f"{self.name}: initialize 失败 (HTTP {resp.status_code})")
        sid = resp.headers.get("Mcp-Session-Id")
        if sid:
            self._session_id = sid
        self._started = True

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
        self._started = False

    def health(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "started": self._started,
            "session": bool(self._session_id),
            "endpoint": self.endpoint,
        }

    # ── McpClientHandle 协议 ───────────────────────────────────────────

    async def list_tools(self) -> list[dict]:
        res = await self._request("tools/list", {})
        return cast(list[dict], (res or {}).get("tools", []))

    async def call_tool(self, name: str, args: dict) -> Any:
        res = await self._request("tools/call", {"name": name, "arguments": args})
        if isinstance(res, dict) and res.get("isError"):
            raise HttpMcpError(f"{self.name}: tool {name!r} 返回错误")
        return res

    # ── 内部 ───────────────────────────────────────────────────────────

    async def _request(self, method: str, params: dict) -> Any:
        if not self._started:
            await self.start()
        if self._client is None:
            raise HttpMcpError(f"{self.name}: 客户端未初始化")
        rid = self._next_id
        self._next_id += 1
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            **self.headers,
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        resp = await self._client.post(
            self.endpoint,
            headers=headers,
            json={"jsonrpc": "2.0", "id": rid, "method": method, "params": params},
        )
        if resp.status_code not in (200, 202):
            raise HttpMcpError(f"{self.name}: {method} 失败 (HTTP {resp.status_code})")
        payload = _parse_sse_or_json(resp.text)
        if "error" in payload:
            raise HttpMcpError(f"{self.name}: {method} 返回 MCP 错误")
        return payload.get("result")


__all__ = ["HttpMcpError", "StreamableHttpMcpClient", "McpClientRegistry", "McpClientHandle"]
