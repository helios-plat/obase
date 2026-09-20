"""D5C gates: MCP registry teardown primitives + conditional resources."""

from __future__ import annotations

import pytest

from obase.mcp_client import (
    McpClientRegistry,
    McpResourcesError,
    list_resources,
    read_resource,
    supports_resources,
)


class _ToolsOnly:
    async def list_tools(self):
        return [{"name": "read", "description": "read", "inputSchema": {}}]

    async def call_tool(self, name, args):
        return {"ok": True}


class _FullClient(_ToolsOnly):
    async def list_resources(self):
        return [{"uri": "res://a", "name": "a"}]

    async def read_resource(self, uri):
        return {"content": f"body:{uri}"}


@pytest.fixture(autouse=True)
def _clean_registry():
    McpClientRegistry.clear()
    yield
    McpClientRegistry.clear()


def test_has_and_list_clients_snapshot():
    assert McpClientRegistry.has("s") is False
    McpClientRegistry.register("s", _ToolsOnly())
    assert McpClientRegistry.has("s") is True
    snapshot = McpClientRegistry.list_clients()
    assert snapshot == ["s"]
    snapshot.clear()
    assert McpClientRegistry.list_clients() == ["s"]


def test_unregister_targeted_and_idempotent():
    McpClientRegistry.register("a", _ToolsOnly())
    McpClientRegistry.register("b", _ToolsOnly())
    assert McpClientRegistry.unregister("a") is True
    assert McpClientRegistry.has("a") is False
    assert McpClientRegistry.has("b") is True
    assert McpClientRegistry.unregister("a") is False
    with pytest.raises(KeyError):
        McpClientRegistry.get("a")


def test_unregister_never_clears_siblings_or_specs():
    from obase.tool_governance import MCPServerSpec

    spec = MCPServerSpec(name="s", endpoint="http://x", tools=())
    McpClientRegistry.register_server(spec, _ToolsOnly())
    McpClientRegistry.register("other", _ToolsOnly())
    assert McpClientRegistry.unregister("s") is True
    assert McpClientRegistry.spec("s").name == "s"
    assert McpClientRegistry.has("other") is True


def test_resources_probe_and_honest_unsupported():
    assert supports_resources(_ToolsOnly()) is False
    assert supports_resources(_FullClient()) is True


@pytest.mark.asyncio()
async def test_list_and_read_resources():
    assert await list_resources(_FullClient()) == [{"uri": "res://a", "name": "a"}]
    assert await read_resource(_FullClient(), "res://a") == {
        "uri": "res://a",
        "content": "body:res://a",
        "raw": {"content": "body:res://a"},
    }
    with pytest.raises(McpResourcesError):
        await list_resources(_ToolsOnly())
    with pytest.raises(McpResourcesError):
        await read_resource(_ToolsOnly(), "res://a")
    with pytest.raises(ValueError):
        await read_resource(_FullClient(), "")


@pytest.mark.asyncio()
async def test_list_resources_error_is_not_empty():
    class _Broken(_FullClient):
        async def list_resources(self):
            raise RuntimeError("transport down")

    with pytest.raises(McpResourcesError, match="transport down"):
        await list_resources(_Broken())
