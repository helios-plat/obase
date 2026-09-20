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
    def has(cls, name: str) -> bool:
        """Whether a client handle is currently registered (side-effect free)."""
        return name in cls._clients

    @classmethod
    def list_clients(cls) -> list[str]:
        """Registered client names; a snapshot copy, never the live mapping."""
        return list(cls._clients)

    @classmethod
    def unregister(cls, name: str) -> bool:
        """Drop one client handle (targeted teardown).

        Returns True when a handle was removed, False for unknown ids
        (idempotent). Never touches ``_specs`` and never clears siblings.
        """
        return cls._clients.pop(name, None) is not None

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


class McpResourcesError(RuntimeError):
    """MCP resources/list+read negotiation or fetch error (fail-closed)."""


async def _maybe_await(value: Any) -> Any:
    import inspect as _inspect

    if _inspect.isawaitable(value):
        return await value
    return value


def supports_resources(client: McpClientHandle) -> bool:
    """Whether a handle observably implements resources/list+read.

    The base :class:`McpClientHandle` contract only requires tools; resource
    access is probed (method presence), never assumed. ``False`` means the
    caller must treat resources as unsupported, not empty.
    """
    return callable(getattr(client, "list_resources", None)) and callable(
        getattr(client, "read_resource", None)
    )


async def list_resources(client: McpClientHandle) -> list[dict[str, Any]]:
    """List remote resources; fail closed when the handle lacks support.

    A discovery failure raises — it is never reported as an empty result.
    """
    if not supports_resources(client):
        raise McpResourcesError("resources: handle does not implement resources/list")
    try:
        result = await _maybe_await(client.list_resources())  # type: ignore[attr-defined]
    except Exception as exc:
        raise McpResourcesError(f"resources: list failed: {exc}") from exc
    if not isinstance(result, list):
        raise McpResourcesError("resources: list returned a non-list payload")
    return [item for item in result if isinstance(item, dict)]


async def read_resource(client: McpClientHandle, uri: str) -> dict[str, Any]:
    """Read one remote resource by URI (passed through verbatim)."""
    if not uri:
        raise ValueError("read_resource: uri must not be empty")
    if not supports_resources(client):
        raise McpResourcesError(f"resources: handle does not implement resources/read ({uri!r})")
    try:
        result = await _maybe_await(client.read_resource(uri))  # type: ignore[attr-defined]
    except Exception as exc:
        raise McpResourcesError(f"resources: read {uri!r} failed: {exc}") from exc
    if isinstance(result, dict):
        return {"uri": uri, "content": result.get("content"), "raw": result}
    return {"uri": uri, "content": result, "raw": result}
