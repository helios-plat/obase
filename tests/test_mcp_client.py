"""D5 gates: MCP client registry teardown + conditional resources substrate."""

from __future__ import annotations

import pytest

from obase.mcp_client import (
    McpClientRegistry,
    SkillsExtensionError,
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


def test_registry_register_has_list_unregister():
    assert McpClientRegistry.has("s") is False
    McpClientRegistry.register("s", _ToolsOnly())
    assert McpClientRegistry.has("s") is True
    assert McpClientRegistry.list_clients() == ["s"]
    assert McpClientRegistry.unregister("s") is True
    assert McpClientRegistry.has("s") is False
    assert McpClientRegistry.unregister("s") is False
    assert McpClientRegistry.list_clients() == []


def test_unregister_keeps_specs_for_audit():
    from obase.mcp_client import MCPServerSpec

    spec = MCPServerSpec(name="s", endpoint="http://x", tools=())
    McpClientRegistry.register_server(spec, _ToolsOnly())
    assert McpClientRegistry.unregister("s") is True
    assert McpClientRegistry.spec("s").name == "s"


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
    with pytest.raises(SkillsExtensionError):
        await list_resources(_ToolsOnly())
    with pytest.raises(SkillsExtensionError):
        await read_resource(_ToolsOnly(), "res://a")
    with pytest.raises(ValueError):
        await read_resource(_FullClient(), "")
