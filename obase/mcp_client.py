"""obase.mcp_client — MCP client handle 提供者."""
from __future__ import annotations
from typing import Any, Protocol, runtime_checkable

@runtime_checkable
class McpClientHandle(Protocol):
    """MCP client handle Protocol. mcp_* oprim 通过此 handle 调外部 MCP 工具."""
    async def list_tools(self) -> list[dict]: ...
    async def call_tool(self, name: str, args: dict) -> Any: ...

class McpClientRegistry:
    """管理 MCP client 连接."""
    _clients: dict[str, McpClientHandle] = {}

    @classmethod
    def register(cls, name: str, handle: McpClientHandle) -> None:
        cls._clients[name] = handle

    @classmethod
    def get(cls, name: str) -> McpClientHandle:
        if name not in cls._clients:
            raise KeyError(f"MCP client {name!r} not registered.")
        return cls._clients[name]
