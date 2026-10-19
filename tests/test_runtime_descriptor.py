"""D1 gates: ProtocolFamily + runtime descriptor (ProviderSpec authority).

Covers: 5 family values / invalid fail-closed / serialization,
ProviderSpec backward-compat + availability/version/lifecycle/metadata,
ProviderRegistry family+capability+availability filtering with a single
_specs authority, adapter family admission (harness/acp/a2a), AgentRegistry
reference-only runtime bridge (no duplicated descriptor state), and the
legacy ToolKind -> ProtocolFamily alias map.
"""

from __future__ import annotations

import json

import pytest

from obase.a2a_adapter import A2AAgentAdapter
from obase.acp_adapter import ACPAgentAdapter
from obase.agent_registry import AgentRegistry
from obase.exceptions import ProviderNotFoundError
from obase.harness_adapter import (
    HARNESS_CATEGORY,
    BaseCLIHarnessAdapter,
    ClaudeCodeHarnessAdapter,
    CodexHarnessAdapter,
    OpenCodeHarnessAdapter,
)
from obase.provider_registry import OBaseRegistryConflict, ProviderRegistry
from obase.provider_routing import (
    LIFECYCLE_OPS,
    ModelSpec,
    ProtocolFamily,
    ProviderSpec,
    tool_kind_to_protocol_family,
)


@pytest.fixture()
def specs():
    ProviderRegistry.clear()
    yield ProviderRegistry.get()
    ProviderRegistry.clear()


def _spec(name: str, **kwargs) -> ProviderSpec:
    return ProviderSpec(name=name, **kwargs)


# -- ProtocolFamily -----------------------------------------------------------


def test_protocol_family_has_all_five_values():
    assert {m.value for m in ProtocolFamily} == {"native", "harness", "acp", "a2a", "mcp"}


def test_protocol_family_string_serializable():
    assert json.dumps({"family": ProtocolFamily.ACP}) == '{"family": "acp"}'
    assert ProtocolFamily("a2a") is ProtocolFamily.A2A
    assert ProtocolFamily.coerce("harness") is ProtocolFamily.HARNESS
    assert ProtocolFamily.coerce(ProtocolFamily.MCP) is ProtocolFamily.MCP


def test_protocol_family_unknown_fail_closed():
    with pytest.raises(ValueError):
        ProtocolFamily.coerce("grpc")
    with pytest.raises(ValueError):
        ProtocolFamily.coerce("")
    with pytest.raises(ValueError):
        ProtocolFamily.coerce(None)  # type: ignore[arg-type]


def test_tool_kind_alias_map():
    assert tool_kind_to_protocol_family("native") is ProtocolFamily.NATIVE
    assert tool_kind_to_protocol_family("mcp") is ProtocolFamily.MCP
    with pytest.raises(ValueError):
        tool_kind_to_protocol_family("grpc")


# -- ProviderSpec descriptor --------------------------------------------------


def test_provider_spec_backward_compatible_defaults():
    spec = ProviderSpec(name="legacy")
    assert spec.protocol_family is ProtocolFamily.NATIVE
    assert spec.version is None
    assert spec.available is True
    assert spec.unavailable_reason is None
    assert spec.lifecycle == {op: False for op in LIFECYCLE_OPS}
    assert spec.capabilities == frozenset({"chat"})
    assert spec.metadata == {}


def test_provider_spec_full_descriptor():
    spec = ProviderSpec(
        name="rt-1",
        protocol_family="acp",
        version="0.3.1",
        available=False,
        unavailable_reason="oauth-required",
        capabilities={"chat", "tools"},
        lifecycle={"run": True, "stream": True, "cancel": True},
        metadata={"region": "local"},
    )
    assert spec.protocol_family is ProtocolFamily.ACP
    assert spec.version == "0.3.1"
    assert spec.available is False
    assert spec.unavailable_reason == "oauth-required"
    assert spec.can("run") is True
    assert spec.can("resume") is False
    assert spec.metadata == {"region": "local"}
    assert not hasattr(spec, "run_id")
    assert not hasattr(spec, "session_id")
    wire = spec.to_dict()
    assert wire["protocol_family"] == "acp"
    assert wire["version"] == "0.3.1"
    assert wire["available"] is False
    assert wire["unavailable_reason"] == "oauth-required"
    assert wire["lifecycle"] == {
        "run": True,
        "stream": True,
        "status": False,
        "cancel": True,
        "resume": False,
    }


def test_provider_spec_rejects_unknown_family_and_lifecycle():
    with pytest.raises(ValueError):
        ProviderSpec(name="bad", protocol_family="grpc")
    with pytest.raises(ValueError):
        ProviderSpec(name="bad", lifecycle={"teleport": True})
    with pytest.raises(ValueError):
        _spec("bad").can("teleport")


# -- ProviderRegistry wiring --------------------------------------------------


def test_registry_descriptor_roundtrip(specs):
    spec = _spec("p1", protocol_family=ProtocolFamily.HARNESS, version="1.0")
    specs.register_spec(spec)
    assert specs.spec("p1") is spec
    assert specs.list_specs() == [spec]
    with pytest.raises(ProviderNotFoundError):
        specs.spec("missing")


def test_registry_no_duplicate_authority(specs):
    specs.register_spec(_spec("p1"))
    with pytest.raises(OBaseRegistryConflict):
        specs.register_spec(_spec("p1"))
    specs.register_spec(_spec("p1", version="2.0"), replace=True)
    assert specs.spec("p1").version == "2.0"
    assert len(specs.list_specs()) == 1


def test_registry_family_capability_availability_filters(specs):
    specs.register_spec(_spec("h1", protocol_family="harness", capabilities={"chat", "tools"}))
    specs.register_spec(_spec("a1", protocol_family="acp", capabilities={"chat"}))
    specs.register_spec(
        _spec(
            "h2",
            protocol_family="harness",
            capabilities={"chat"},
            available=False,
            unavailable_reason="binary-missing",
        )
    )
    assert [s.name for s in specs.list_specs(protocol_family="harness")] == ["h1", "h2"]
    assert [s.name for s in specs.list_specs(protocol_family=ProtocolFamily.ACP)] == ["a1"]
    assert [s.name for s in specs.list_specs(capability="tools")] == ["h1"]
    assert [s.name for s in specs.list_specs(available_only=True)] == ["h1", "a1"]
    assert [s.name for s in specs.list_specs(protocol_family="harness")] == ["h1", "h2"]
    only = specs.list_specs(protocol_family="harness", available_only=True)
    assert [s.name for s in only] == ["h1"]
    with pytest.raises(ValueError):
        specs.list_specs(protocol_family="grpc")


# -- Adapter admission --------------------------------------------------------


def test_adapter_protocol_families():
    assert BaseCLIHarnessAdapter.protocol_family is ProtocolFamily.HARNESS
    for cls in (CodexHarnessAdapter, ClaudeCodeHarnessAdapter, OpenCodeHarnessAdapter):
        assert cls.protocol_family is ProtocolFamily.HARNESS
    assert ACPAgentAdapter.protocol_family is ProtocolFamily.ACP
    assert A2AAgentAdapter.protocol_family is ProtocolFamily.A2A
    # Legacy string category maps onto the same authority, not a second one.
    assert HARNESS_CATEGORY == ProtocolFamily.HARNESS.value


def test_adapter_descriptor_uses_canonical_spec():
    spec = ProviderSpec(
        name="codex-cli",
        protocol_family=CodexHarnessAdapter.protocol_family,
        version="1.0",
        capabilities={"tools"},
        lifecycle={"run": True, "resume": True, "cancel": True},
    )
    assert type(spec).__module__ == "obase.provider_routing"
    assert spec.to_dict()["protocol_family"] == "harness"

    model_spec = ProviderSpec(
        name="peer-agent",
        protocol_family=A2AAgentAdapter(transport=lambda m: {}).protocol_family,
    )
    assert model_spec.protocol_family is ProtocolFamily.A2A


# -- AgentRegistry reference-only bridge --------------------------------------


def test_agent_registry_runtime_bridge_resolves_same_object(specs):
    agents = AgentRegistry()
    spec = _spec("rt-bridge", protocol_family="a2a", version="0.1")
    specs.register_spec(spec)

    def _factory():
        return "runtime"

    agents.register_runtime("peer", _factory, spec=spec)
    resolved = agents.runtime_descriptor("peer")
    assert resolved is spec

    entry = agents.get("runtime", "peer")
    assert set(entry) == {"name", "func", "func_name", "desc", "spec"}
    assert entry["spec"] == "rt-bridge"
    agents.reset()


def test_agent_registry_runtime_bridge_miss_returns_none(specs):
    agents = AgentRegistry()

    def _factory():
        return "runtime"

    agents.register_runtime("bare", _factory)
    assert agents.runtime_descriptor("bare") is None
    assert agents.runtime_descriptor("ghost") is None
    agents.register_runtime("dangling", _factory, spec="never-registered")
    assert agents.runtime_descriptor("dangling") is None
    agents.reset()


def test_model_spec_untouched():
    model = ModelSpec(name="m", provider="p")
    assert model.capabilities == frozenset({"chat"})
