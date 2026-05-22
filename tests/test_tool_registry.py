from __future__ import annotations

import pytest

from obase.tool_registry import ToolRegistry, ToolRegistryConflict, register_tool


def _simple_tool(*, x: str) -> str:
    """First line description.

    More detail here.
    """
    return x


class TestToolRegistryBasic:
    def test_register_tool_basic(self):
        """Register a simple function; verify ToolMeta fields are correct."""
        ToolRegistry.register(_simple_tool)
        name = _simple_tool._aegis_tool_meta.name  # type: ignore[attr-defined]
        meta = ToolRegistry.get(name)
        assert meta is not None
        assert meta.fn is _simple_tool
        assert meta.permission == "read"
        assert meta.stability == "stable"
        assert meta.requires_secrets == []

    def test_register_tool_via_decorator(self):
        """@register_tool attaches _aegis_tool_meta to the function."""

        @register_tool(permission="read")
        def my_decorated_tool(*, value: int) -> int:
            """Decorated tool description."""
            return value

        assert hasattr(my_decorated_tool, "_aegis_tool_meta")
        meta = my_decorated_tool._aegis_tool_meta  # type: ignore[attr-defined]
        assert meta.name.endswith("my_decorated_tool")

    def test_register_tool_conflict_raises(self):
        """Registering the same-name tool twice raises ToolRegistryConflict."""
        ToolRegistry.register(_simple_tool)
        with pytest.raises(ToolRegistryConflict, match="already registered"):
            ToolRegistry.register(_simple_tool)

    def test_register_tool_with_write_permission(self):
        """Tools with permission='write' register successfully."""
        ToolRegistry.register(_simple_tool, permission="write")
        name = _simple_tool._aegis_tool_meta.name  # type: ignore[attr-defined]
        meta = ToolRegistry.get(name)
        assert meta is not None
        assert meta.permission == "write"

    def test_register_tool_with_secrets(self):
        """requires_secrets list is stored on ToolMeta."""
        secrets = ["myapp/api_key", "myapp/token"]
        ToolRegistry.register(_simple_tool, requires_secrets=secrets)
        name = _simple_tool._aegis_tool_meta.name  # type: ignore[attr-defined]
        meta = ToolRegistry.get(name)
        assert meta is not None
        assert meta.requires_secrets == secrets

    def test_get_nonexistent_tool_returns_none(self):
        """get() for an unregistered name returns None."""
        result = ToolRegistry.get("nonexistent.tool")
        assert result is None

    def test_has_nonexistent_tool_returns_false(self):
        """has() for an unregistered name returns False."""
        assert ToolRegistry.has("nonexistent.tool") is False


class TestToolRegistryListing:
    def test_list_tools_all(self):
        """Registering 3 tools returns all 3 from list_tools()."""

        def tool_a(*, x: str) -> str:
            """Tool A."""
            return x

        def tool_b(*, y: int) -> int:
            """Tool B."""
            return y

        def tool_c(*, z: float) -> float:
            """Tool C."""
            return z

        for fn in (tool_a, tool_b, tool_c):
            ToolRegistry.register(fn)

        tools = ToolRegistry.list_tools()
        names = {m.name for m in tools}
        assert any("tool_a" in n for n in names)
        assert any("tool_b" in n for n in names)
        assert any("tool_c" in n for n in names)

    def test_list_tools_filter_by_permission(self):
        """list_tools(permission='write') returns only write-permission tools."""

        def read_tool(*, x: str) -> str:
            """Read tool."""
            return x

        def write_tool(*, x: str) -> str:
            """Write tool."""
            return x

        ToolRegistry.register(read_tool, permission="read")
        ToolRegistry.register(write_tool, permission="write")

        read_tools = ToolRegistry.list_tools(permission="read")
        write_tools = ToolRegistry.list_tools(permission="write")

        assert all(m.permission == "read" for m in read_tools)
        assert all(m.permission == "write" for m in write_tools)
        assert len(read_tools) == 1
        assert len(write_tools) == 1

    def test_list_tools_filter_by_stability(self):
        """list_tools(stability='beta') returns only beta tools."""

        def stable_tool(*, x: str) -> str:
            """Stable tool."""
            return x

        def beta_tool(*, x: str) -> str:
            """Beta tool."""
            return x

        ToolRegistry.register(stable_tool, stability="stable")
        ToolRegistry.register(beta_tool, stability="beta")

        beta_results = ToolRegistry.list_tools(stability="beta")
        assert len(beta_results) == 1
        assert beta_results[0].stability == "beta"


class TestToolRegistryClearAndMeta:
    def test_clear_removes_all_tools(self):
        """clear() removes all registered tools."""
        ToolRegistry.register(_simple_tool)
        name = _simple_tool._aegis_tool_meta.name  # type: ignore[attr-defined]
        assert ToolRegistry.has(name)
        ToolRegistry.clear()
        assert not ToolRegistry.has(name)
        assert ToolRegistry.list_tools() == []

    def test_description_extracted_from_docstring(self):
        """description field is the first line of the function's docstring."""
        ToolRegistry.register(_simple_tool)
        name = _simple_tool._aegis_tool_meta.name  # type: ignore[attr-defined]
        meta = ToolRegistry.get(name)
        assert meta is not None
        assert meta.description == "First line description."

    def test_full_name_from_oprim_module(self):
        """Functions in an oprim module get full_name 'oprim.<fn_name>'."""

        def oprim_tool(*, queue: str) -> dict:
            """Check queue."""
            return {}

        oprim_tool.__module__ = "oprim.rabbitmq_queue_status"
        ToolRegistry.register(oprim_tool)
        assert ToolRegistry.has("oprim.oprim_tool")
        meta = ToolRegistry.get("oprim.oprim_tool")
        assert meta is not None
        assert meta.name == "oprim.oprim_tool"

    def test_full_name_from_oskill_module(self):
        """Functions in an oskill module get full_name 'oskill.<fn_name>'."""

        def investigate(*, target: str) -> dict:
            """Investigate target."""
            return {}

        investigate.__module__ = "oskill.investigate_loop"
        ToolRegistry.register(investigate)
        assert ToolRegistry.has("oskill.investigate")

    def test_register_no_docstring_empty_description(self):
        """Functions without docstrings get empty description."""

        def no_doc_tool(*, x: str) -> str:
            return x

        ToolRegistry.register(no_doc_tool)
        meta = no_doc_tool._aegis_tool_meta  # type: ignore[attr-defined]
        assert meta is not None
        assert meta.description == ""
