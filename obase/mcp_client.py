"""obase.mcp_client — MCP client handle 提供者."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from obase.tool_governance import MCPServerSpec


@runtime_checkable
class McpClientHandle(Protocol):
    """MCP client handle Protocol. mcp_* oprim 通过此 handle 调外部 MCP 工具."""

    async def list_tools(self) -> list[dict]: ...
    async def call_tool(self, name: str, args: dict) -> Any: ...


class McpClientRegistry:
    """管理 MCP client 连接."""

    _clients: dict[str, McpClientHandle] = {}
    _specs: dict[str, MCPServerSpec] = {}

    @classmethod
    def register(cls, name: str, handle: McpClientHandle) -> None:
        cls._clients[name] = handle

    @classmethod
    def register_server(cls, spec: MCPServerSpec, handle: McpClientHandle) -> None:
        """Register a client together with its versioned server contract."""
        cls._specs[spec.name] = spec
        cls._clients[spec.name] = handle

    @classmethod
    def register_spec(cls, spec: MCPServerSpec, *, replace: bool = False) -> None:
        if not replace and spec.name in cls._specs:
            raise ValueError(f"MCP server {spec.name!r} already registered")
        cls._specs[spec.name] = spec

    @classmethod
    def get(cls, name: str) -> McpClientHandle:
        if name not in cls._clients:
            raise KeyError(f"MCP client {name!r} not registered.")
        return cls._clients[name]

    @classmethod
    def spec(cls, name: str) -> MCPServerSpec:
        if name not in cls._specs:
            raise KeyError(f"MCP server spec {name!r} not registered")
        return cls._specs[name]

    @classmethod
    def list_specs(cls) -> list[MCPServerSpec]:
        return list(cls._specs.values())

    @classmethod
    def invalidate(cls, name: str) -> bool:
        spec = cls._specs.get(name)
        if spec is None:
            return False
        cls._specs[name] = MCPServerSpec(
            name=spec.name,
            endpoint=spec.endpoint,
            version=spec.version,
            protocol_version=spec.protocol_version,
            tools=spec.tools,
            credential_ref=spec.credential_ref,
            enabled=False,
        )
        return True

    @classmethod
    def clear(cls) -> None:
        cls._clients.clear()
        cls._specs.clear()
