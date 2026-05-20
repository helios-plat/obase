from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from obase.tool_registry import ToolMeta, ToolRegistry
from obase.tool_registry.schema import (
    _parse_docstring_args,
    build_args_model,
    to_anthropic_tool,
    to_openai_tool,
)


def _make_meta(fn, **kwargs) -> ToolMeta:
    """Helper: register fn and return its ToolMeta."""
    ToolRegistry.register(fn, **kwargs)
    name = fn._aegis_tool_meta.name  # type: ignore[attr-defined]
    meta = ToolRegistry.get(name)
    assert meta is not None
    return meta


class TestBuildArgsModel:
    def test_build_args_model_basic(self):
        """Keyword-only str + int parameters produce correct Pydantic model fields."""

        def fn(*, x: str, y: int = 5) -> dict:
            """Tool."""
            return {}

        model = build_args_model(fn)
        fields = model.model_fields
        assert "x" in fields
        assert "y" in fields
        assert fields["y"].default == 5

    def test_build_args_model_missing_annotation_raises(self):
        """Parameters without type annotations raise RuntimeError."""

        def fn(*, x) -> dict:  # type: ignore[misc]
            """Tool."""
            return {}

        with pytest.raises(RuntimeError, match="missing type annotation"):
            build_args_model(fn)

    def test_build_args_model_positional_param_raises(self):
        """Positional parameters raise RuntimeError requiring keyword-only."""

        def fn(x: str) -> str:
            """Tool."""
            return x

        with pytest.raises(RuntimeError, match="keyword-only"):
            build_args_model(fn)

    def test_build_args_model_forbidden_path_raises(self):
        """Path parameter type is forbidden and raises RuntimeError."""

        def fn(*, p: Path) -> str:
            """Tool."""
            return str(p)

        with pytest.raises(RuntimeError, match="forbidden type.*Path"):
            build_args_model(fn)

    def test_build_args_model_forbidden_datetime_raises(self):
        """datetime parameter type is forbidden and raises RuntimeError."""

        def fn(*, dt: datetime) -> str:
            """Tool."""
            return str(dt)

        with pytest.raises(RuntimeError, match="forbidden type.*datetime"):
            build_args_model(fn)

    def test_build_args_model_forbidden_tuple_raises(self):
        """Parameterized tuple parameter type is forbidden and raises RuntimeError."""

        def fn(*, t: tuple[str, int]) -> str:  # type: ignore[type-arg]
            """Tool."""
            return str(t)

        with pytest.raises(RuntimeError, match="tuple"):
            build_args_model(fn)

    def test_build_args_model_forbidden_bytes_raises(self):
        """bytes parameter type is forbidden and raises RuntimeError."""

        def fn(*, data: bytes) -> str:
            """Tool."""
            return data.decode()

        with pytest.raises(RuntimeError, match="forbidden type.*bytes"):
            build_args_model(fn)


class TestDocstringParsing:
    def test_parse_docstring_args(self):
        """Google-style Args: section is parsed into {param: description} dict."""
        docstring = """
        Do something.

        Args:
            queue_name: The name of the RabbitMQ queue.
            vhost: Virtual host, defaults to /.

        Returns:
            dict with status.
        """
        result = _parse_docstring_args(docstring)
        assert result["queue_name"] == "The name of the RabbitMQ queue."
        assert result["vhost"] == "Virtual host, defaults to /."

    def test_parse_docstring_no_args_section(self):
        """Docstrings without Args: section return empty dict."""
        result = _parse_docstring_args("Just a summary line.")
        assert result == {}

    def test_parse_docstring_multiline_arg(self):
        """Multi-line arg descriptions are joined into a single string."""
        docstring = """
        Tool.

        Args:
            x: First line of description
                continued on second line.
        """
        result = _parse_docstring_args(docstring)
        assert "First line" in result["x"]
        assert "continued" in result["x"]


class TestSchemaGeneration:
    def test_to_openai_tool_format(self):
        """to_openai_tool returns dict with type/function/name/description/parameters."""

        def fn(*, queue_name: str, vhost: str = "/") -> dict:
            """Return queue depth."""
            return {}

        meta = _make_meta(fn)
        schema = to_openai_tool(meta)

        assert schema["type"] == "function"
        assert "function" in schema
        fn_schema = schema["function"]
        assert "name" in fn_schema
        assert "description" in fn_schema
        assert fn_schema["description"] == "Return queue depth."
        assert "parameters" in fn_schema

    def test_to_anthropic_tool_format(self):
        """to_anthropic_tool returns dict with name/description/input_schema."""

        def fn(*, container_id: str) -> dict:
            """Fetch Docker container logs."""
            return {}

        meta = _make_meta(fn)
        schema = to_anthropic_tool(meta)

        assert "name" in schema
        assert "description" in schema
        assert schema["description"] == "Fetch Docker container logs."
        assert "input_schema" in schema

    def test_to_openai_tool_name_too_long_raises(self):
        """Tool names longer than 64 chars after . → __ raise RuntimeError."""

        def a_very_long_function_name_that_exceeds_the_limit(*, x: str) -> str:
            """Long named tool."""
            return x

        fn = a_very_long_function_name_that_exceeds_the_limit
        fn.__module__ = "oprim.some_submodule"
        ToolRegistry.register(fn)
        name = fn._aegis_tool_meta.name  # type: ignore[attr-defined]
        meta = ToolRegistry.get(name)
        assert meta is not None

        meta_override = ToolMeta(
            name="oprim.toolname" + "x" * 60,
            fn=fn,
            description="Long name.",
        )
        with pytest.raises(RuntimeError, match="too long"):
            to_openai_tool(meta_override)

    def test_to_anthropic_tool_name_too_long_raises(self):
        """Anthropic schema also raises RuntimeError for names >64 chars."""

        def fn(*, x: str) -> str:
            """Tool."""
            return x

        meta_long = ToolMeta(
            name="oprim.toolname" + "y" * 60,
            fn=fn,
            description="Long.",
        )
        with pytest.raises(RuntimeError, match="too long"):
            to_anthropic_tool(meta_long)

    def test_tool_name_dot_to_underscore(self):
        """OpenAI schema name transforms '.' to '__'."""

        def fn(*, x: str) -> str:
            """Tool."""
            return x

        fn.__module__ = "oprim.some_mod"
        meta = _make_meta(fn)
        schema = to_openai_tool(meta)
        assert "." not in schema["function"]["name"]
        assert "__" in schema["function"]["name"]

    def test_anthropic_name_dot_to_underscore(self):
        """Anthropic schema name also transforms '.' to '__'."""

        def fn(*, x: str) -> str:
            """Tool."""
            return x

        fn.__module__ = "oskill.some_mod"
        meta = _make_meta(fn)
        schema = to_anthropic_tool(meta)
        assert "." not in schema["name"]
        assert "__" in schema["name"]
