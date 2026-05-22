"""Schema generation: convert ToolMeta into OpenAI / Anthropic tool call schemas."""
from __future__ import annotations

import inspect
from typing import Any, get_type_hints

from pydantic import BaseModel, Field, create_model

from obase.tool_registry import ToolMeta

# Types that LLMs struggle to handle reliably — forbidden in tool parameters.
_FORBIDDEN_TYPE_HINTS: dict[str, str] = {
    "Path": "use str instead",
    "datetime": "use ISO 8601 string instead",
    "date": "use ISO 8601 string instead",
    "bytes": "use base64-encoded str instead",
    "tuple": "use list or separate parameters",
}


def build_args_model(fn: Any) -> type[BaseModel]:
    """Build a Pydantic model from a tool function's keyword-only signature.

    All parameters must be keyword-only (after a bare ``*``).
    All parameters must have type annotations (no forbidden types).
    Google-style ``Args:`` docstring sections populate Field descriptions.

    Args:
        fn: The tool function to introspect.

    Returns:
        A dynamically created Pydantic BaseModel subclass.

    Raises:
        RuntimeError: If any parameter is positional, missing annotation,
            or uses a forbidden type.
    """
    sig = inspect.signature(fn)
    type_hints = get_type_hints(fn)
    docstring_args = _parse_docstring_args(fn.__doc__ or "")

    fields: dict[str, Any] = {}
    for pname, param in sig.parameters.items():
        if param.kind != inspect.Parameter.KEYWORD_ONLY:
            raise RuntimeError(
                f"{fn.__name__}: parameter {pname!r} must be keyword-only "
                "(use * separator). This is required for stable LLM tool calls."
            )
        if pname not in type_hints:
            raise RuntimeError(
                f"{fn.__name__}: parameter {pname!r} missing type annotation"
            )
        annot = type_hints[pname]
        _validate_param_type(pname, annot, fn_name=fn.__name__)

        description = docstring_args.get(pname, "")
        default = ... if param.default is inspect.Parameter.empty else param.default
        fields[pname] = (annot, Field(default=default, description=description))

    return create_model(f"{fn.__name__}_args", **fields)


def to_openai_tool(meta: ToolMeta) -> dict[str, Any]:
    """Generate an OpenAI function-calling schema dict from ToolMeta.

    The tool name uses ``__`` in place of ``.`` (OpenAI rejects dots in names).

    Args:
        meta: Registered tool metadata.

    Returns:
        OpenAI tool schema dict with ``type``, ``function`` keys.

    Raises:
        RuntimeError: If the transformed name exceeds 64 characters.
    """
    args_model = build_args_model(meta.fn)
    name_safe = meta.name.replace(".", "__")
    if len(name_safe) > 64:
        raise RuntimeError(
            f"Tool name too long for OpenAI (>64 chars): {name_safe!r}. "
            "Shorten the function or module name."
        )
    return {
        "type": "function",
        "function": {
            "name": name_safe,
            "description": meta.description,
            "parameters": args_model.model_json_schema(),
        },
    }


def to_anthropic_tool(meta: ToolMeta) -> dict[str, Any]:
    """Generate an Anthropic tool-use schema dict from ToolMeta.

    Args:
        meta: Registered tool metadata.

    Returns:
        Anthropic tool schema dict with ``name``, ``description``, ``input_schema``.

    Raises:
        RuntimeError: If the transformed name exceeds 64 characters.
    """
    args_model = build_args_model(meta.fn)
    name_safe = meta.name.replace(".", "__")
    if len(name_safe) > 64:
        raise RuntimeError(
            f"Tool name too long for Anthropic (>64 chars): {name_safe!r}."
        )
    return {
        "name": name_safe,
        "description": meta.description,
        "input_schema": args_model.model_json_schema(),
    }


def _validate_param_type(name: str, annot: Any, fn_name: str) -> None:
    """Raise RuntimeError if the parameter type is not LLM-friendly."""
    type_name = getattr(annot, "__name__", str(annot))
    if type_name in _FORBIDDEN_TYPE_HINTS:
        raise RuntimeError(
            f"{fn_name}: parameter {name!r} has forbidden type {type_name!r} "
            f"({_FORBIDDEN_TYPE_HINTS[type_name]})"
        )
    if hasattr(annot, "__origin__") and annot.__origin__ is tuple:
        raise RuntimeError(
            f"{fn_name}: parameter {name!r} type tuple not allowed "
            "(LLM struggles with tuples). Use list or split into multiple params."
        )


def _parse_docstring_args(docstring: str) -> dict[str, str]:
    """Extract parameter descriptions from a Google-style docstring Args: section.

    Example input::

        Args:
            arg1: Description for arg1.
            arg2: Description for arg2 spanning
                multiple lines.

    Returns:
        Mapping from parameter name to description string.
    """
    lines = docstring.split("\n")
    in_args = False
    result: dict[str, str] = {}
    current_arg: str | None = None
    current_desc: list[str] = []
    arg_indent: int | None = None

    _SECTION_HEADERS = frozenset(
        {"Returns:", "Raises:", "Yields:", "Examples:", "Note:", "Notes:"}
    )

    for line in lines:
        stripped = line.strip()

        if stripped == "Args:":
            in_args = True
            continue

        if not in_args:
            continue

        if not stripped:
            continue

        indent = len(line) - len(line.lstrip())

        if stripped in _SECTION_HEADERS:
            break

        if arg_indent is None:
            arg_indent = indent

        if indent == arg_indent and ":" in stripped:
            if current_arg:
                result[current_arg] = " ".join(current_desc).strip()
            arg_name, _, desc_start = stripped.partition(":")
            current_arg = arg_name.strip()
            current_desc = [desc_start.strip()] if desc_start.strip() else []
        elif indent > arg_indent and current_arg is not None:
            current_desc.append(stripped)

    if current_arg:
        result[current_arg] = " ".join(current_desc).strip()

    return result
