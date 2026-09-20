"""Canonical MCP registry substrate contract (D5B).

Locks the KEEP_REQUIRED surface of ``obase.mcp_client.McpClientRegistry``
that production (Veya MCP gateway) and oservi ``MCPRegistryEngine`` call:
register_server / register_spec / list_specs / invalidate / clear, plus
duplicate/conflict behavior and the engine-facing call sequence.
"""

from __future__ import annotations

import pytest

from obase.mcp_client import McpClientRegistry
from obase.tool_governance import MCPServerSpec, ToolSpec


class _Handle:
    def __init__(self, tools: list[dict] | None = None):
        self._tools = tools or []

    async def list_tools(self):
        return list(self._tools)

    async def call_tool(self, name, args):
        return {"ok": True, "tool": name}


def _spec(name: str = "srv", version: str = "1") -> MCPServerSpec:
    return MCPServerSpec(
        name=name,
        endpoint="http://127.0.0.1:9000",
        version=version,
        tools=(ToolSpec(name="read", kind="mcp", server=name, effect="read"),),
    )


@pytest.fixture(autouse=True)
def _clean_registry():
    McpClientRegistry.clear()
    yield
    McpClientRegistry.clear()


def test_register_server_binds_client_and_contract():
    McpClientRegistry.register_server(_spec(), _Handle())
    assert McpClientRegistry.get("srv") is not None
    assert McpClientRegistry.spec("srv").identity == "mcp-server/srv@1"


def test_register_spec_fail_closed_on_conflict():
    McpClientRegistry.register_spec(_spec())
    with pytest.raises(ValueError, match="already registered"):
        McpClientRegistry.register_spec(_spec(version="2"))
    McpClientRegistry.register_spec(_spec(version="2"), replace=True)
    assert McpClientRegistry.spec("srv").version == "2"


def test_register_server_reconnect_is_idempotent_upsert():
    McpClientRegistry.register_server(_spec(), _Handle())
    McpClientRegistry.register_server(_spec(), _Handle())
    assert len(McpClientRegistry.list_specs()) == 1
    assert McpClientRegistry.get("srv") is not None


def test_list_specs_snapshot_semantics():
    McpClientRegistry.register_spec(_spec())
    snapshot = McpClientRegistry.list_specs()
    assert [item.name for item in snapshot] == ["srv"]
    snapshot.clear()
    assert len(McpClientRegistry.list_specs()) == 1


def test_invalidate_targeted_and_missing_harmless():
    assert McpClientRegistry.invalidate("ghost") is False
    McpClientRegistry.register_server(_spec(), _Handle())
    assert McpClientRegistry.invalidate("srv") is True
    stored = McpClientRegistry.spec("srv")
    assert stored.enabled is False
    # Invalidation touches only the targeted spec: client handle survives.
    assert McpClientRegistry.get("srv") is not None
    assert McpClientRegistry.list_specs()[0].enabled is False


def test_clear_resets_both_tables():
    McpClientRegistry.register_server(_spec(), _Handle())
    McpClientRegistry.clear()
    assert McpClientRegistry.list_specs() == []
    with pytest.raises(KeyError):
        McpClientRegistry.get("srv")


def test_engine_facing_call_sequence():
    """Mirror of oservi MCPRegistryEngine.register/invalidate/list flow."""
    spec = _spec()
    McpClientRegistry.register_spec(spec)
    McpClientRegistry.register_server(spec, _Handle())
    assert [item.identity for item in McpClientRegistry.list_specs()] == [spec.identity]
    assert McpClientRegistry.invalidate("srv") is True
    assert McpClientRegistry.list_specs()[0].enabled is False
    assert McpClientRegistry.invalidate("srv") is True
