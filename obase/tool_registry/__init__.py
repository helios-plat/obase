"""obase.tool_registry — LLM-discoverable tool registration.

与 obase.ProviderRegistry 同款 class-level singleton 风格, API 对称。

Usage::

    from obase.tool_registry import ToolRegistry, register_tool

    @register_tool(permission="read", requires_secrets=["myapp/api_key"])
    def rabbitmq_queue_status(*, queue_name: str, vhost: str = "/") -> dict:
        '''Return live queue depth and consumer count from RabbitMQ Management API.'''
        ...

    # In LLM agent:
    tools = ToolRegistry.list_tools(permission="read")
    for meta in tools:
        print(meta.name, meta.description)

    # Generate OpenAI / Anthropic tool schema:
    from obase.tool_registry.schema import to_openai_tool
    meta = ToolRegistry.get("oprim.rabbitmq_queue_status")
    if meta is not None:
        schema = to_openai_tool(meta)
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal

import structlog

from obase.exceptions import OBaseError

log = structlog.get_logger()

ToolPermission = Literal["read", "write"]
ToolStability = Literal["stable", "beta", "experimental"]


class ToolRegistryConflict(OBaseError):
    """Raised when a tool name is already registered in ToolRegistry."""

    retryable = False


@dataclass
class ToolMeta:
    """Metadata for an LLM-discoverable tool.

    Analogous to obase.ProviderRegistry's (category, name) → Callable abstraction:
        ProviderRegistry: registers LLM service providers
        ToolRegistry:     registers LLM-callable tool functions

    Attributes:
        name: Full qualified name, e.g. "oprim.rabbitmq_queue_status".
        fn: Reference to the tool function.
        permission: "read" or "write".
        stability: "stable", "beta", or "experimental".
        description: First line of the docstring shown to the LLM.
        requires_secrets: Infisical secret paths required at runtime.
    """

    name: str
    fn: Callable[..., Any]
    permission: ToolPermission = "read"
    stability: ToolStability = "stable"
    description: str = ""
    requires_secrets: list[str] = field(default_factory=list)


class ToolRegistry:
    """Class-level registry of LLM-discoverable tools.

    Uses the same class-level singleton pattern as obase.ProviderRegistry.
    Call clear() in tests to reset state between test cases.

    Usage::

        @register_tool(permission="read")
        def my_tool(*, arg1: str) -> dict:
            '''Single-line summary for LLM.'''
            ...

        # In LLM agent:
        for meta in ToolRegistry.list_tools(permission="read"):
            print(meta.name, meta.description)
    """

    _tools: ClassVar[dict[str, ToolMeta]] = {}

    @classmethod
    def register(
        cls,
        fn: Callable[..., Any],
        *,
        permission: ToolPermission = "read",
        stability: ToolStability = "stable",
        requires_secrets: list[str] | None = None,
    ) -> Callable[..., Any]:
        """Register a tool function and return it unchanged.

        Args:
            fn: The tool function to register.
            permission: "read" (default) or "write".
            stability: "stable" (default), "beta", or "experimental".
            requires_secrets: Infisical paths for secrets required at runtime.

        Returns:
            fn unchanged (allows use as a decorator).

        Raises:
            ToolRegistryConflict: A tool with the same derived name is already registered.
        """
        module = fn.__module__
        parts = module.split(".")
        if parts[0] in ("oprim", "oskill", "omodul"):
            full_name = f"{parts[0]}.{fn.__name__}"
        else:
            full_name = f"{module}.{fn.__name__}"

        if full_name in cls._tools:
            raise ToolRegistryConflict(
                f"Tool already registered: {full_name!r}. "
                "To override, call ToolRegistry.clear() first (testing) "
                "or use a different name."
            )

        description = (fn.__doc__ or "").strip().split("\n")[0]

        meta = ToolMeta(
            name=full_name,
            fn=fn,
            permission=permission,
            stability=stability,
            description=description,
            requires_secrets=requires_secrets or [],
        )
        cls._tools[full_name] = meta
        log.info("obase.tool_registry.registered", name=full_name, permission=permission)
        fn._aegis_tool_meta = meta  # type: ignore[attr-defined]
        return fn

    @classmethod
    def get(cls, name: str) -> ToolMeta | None:
        """Return tool metadata by full name, or None if not registered."""
        return cls._tools.get(name)

    @classmethod
    def has(cls, name: str) -> bool:
        """Return True if a tool with the given full name is registered."""
        return name in cls._tools

    @classmethod
    def list_tools(
        cls,
        *,
        permission: ToolPermission | None = None,
        stability: ToolStability | None = None,
    ) -> list[ToolMeta]:
        """Return registered tools, optionally filtered.

        Args:
            permission: If set, return only tools with this permission level.
            stability: If set, return only tools with this stability level.

        Returns:
            List of ToolMeta matching all provided filters.
        """
        tools = list(cls._tools.values())
        if permission is not None:
            tools = [t for t in tools if t.permission == permission]
        if stability is not None:
            tools = [t for t in tools if t.stability == stability]
        return tools

    @classmethod
    def clear(cls) -> None:
        """Remove all registered tools. Used in tests."""
        cls._tools.clear()


def register_tool(
    *,
    permission: ToolPermission = "read",
    stability: ToolStability = "stable",
    requires_secrets: list[str] | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator factory to register an LLM-discoverable tool.

    Usage::

        @register_tool(permission="read", requires_secrets=["myapp/db_pwd"])
        def my_tool(*, arg: str) -> dict:
            '''Description shown to LLM.'''
            ...

    Args:
        permission: "read" (default) or "write".
        stability: "stable" (default), "beta", or "experimental".
        requires_secrets: Infisical paths for secrets required at runtime.

    Returns:
        Decorator that registers the function and returns it unchanged.
    """

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        return ToolRegistry.register(
            fn,
            permission=permission,
            stability=stability,
            requires_secrets=requires_secrets,
        )

    return decorator
