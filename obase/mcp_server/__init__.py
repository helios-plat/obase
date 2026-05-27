"""obase.mcp_server — MCP (Model Context Protocol) FastMCP Facade.

Provides :class:`SkillDef` + :class:`MCPServer` for ergonomic MCP server
creation. Wraps ``mcp.server.fastmcp.FastMCP`` internally; does not expose
the underlying instance (no escape hatch).

Usage::

    from obase.mcp_server import MCPServer, SkillDef

    async def greet_handler(args: dict) -> dict:
        return {"greeting": f"Hello, {args['name']}!"}

    server = MCPServer(name="hevi", version="5.0.0")
    server.register_skill(
        SkillDef(
            name="hevi.greet",
            description="Greet someone by name",
            input_schema={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
            handler=greet_handler,
        )
    )
    # stdio transport (e.g. Claude Desktop):
    await server.serve_stdio()
    # OR Streamable HTTP transport:
    await server.serve_streamable_http(host="0.0.0.0", port=8080)
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.utilities.func_metadata import ArgModelBase, FuncMetadata
from mcp.types import ImageContent, TextContent
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

__all__ = [
    "MCPServer",
    "MCPServerError",
    "MCPProtocolError",
    "SkillDef",
]


class MCPServerError(Exception):
    """obase.mcp_server general error."""


class MCPProtocolError(MCPServerError):
    """MCP protocol-layer error (JSON-RPC / capability negotiation failure)."""


class _DynamicArgModel(ArgModelBase):
    """Internal Pydantic model that accepts any extra fields.

    Replaces FastMCP's auto-generated arg model for SkillDef handlers.
    FastMCP calls ``model_validate(arguments_dict)`` then
    ``model_dump_one_level()`` to get the kwargs dict passed to the tool
    function.  By using ``extra='allow'`` and returning the extras from
    ``model_dump_one_level`` we forward the raw MCP arguments dict
    unchanged to the ``**kwargs`` wrapper, which in turn assembles them
    back into a single ``dict`` for the user-supplied ``handler``.
    """

    model_config = ConfigDict(extra="allow")

    def model_dump_one_level(self) -> dict[str, Any]:
        """Return all extra fields as a flat dict (the raw MCP arguments)."""
        return dict(self.model_extra or {})


# Singleton FuncMetadata instance shared by all registered skills.
# It is stateless (only the arg_model class is referenced), so sharing
# is safe and avoids per-registration allocations.
_DYNAMIC_FUNC_META = FuncMetadata(arg_model=_DynamicArgModel, wrap_output=False)


class SkillDef(BaseModel):
    """Business-layer ergonomic abstraction aligned with MCP protocol Tool definition.

    Field names use snake_case (Python convention) internally and are
    serialized to camelCase (MCP wire protocol) via ``by_alias=True``.

    Attributes:
        name: Fully-qualified tool name, e.g. ``"hevi.generate_video"``.
        description: Human-readable description shown to the LLM.
        input_schema: JSON Schema object describing accepted arguments.
        output_schema: Optional JSON Schema for the return value
            (MCP 2025-06-18+ official field).
        handler: Async callable ``(args: dict) → dict | list[Content]``.

    Example::

        skill = SkillDef(
            name="hevi.generate_video",
            description="Generate a 3+ min vertical content video",
            input_schema={
                "type": "object",
                "properties": {"topic": {"type": "string"}},
                "required": ["topic"],
            },
            output_schema={
                "type": "object",
                "properties": {"video_path": {"type": "string"}},
            },
            handler=async_handler_fn,
        )
    """

    name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] | None = None  # MCP 2025-06-18+ official field
    handler: Callable[
        [dict[str, Any]], Awaitable[dict[str, Any] | list[TextContent | ImageContent]]
    ]

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        arbitrary_types_allowed=True,  # handler is Callable, not a Pydantic type
    )


class MCPServer:
    """FastMCP Facade.

    Wraps ``mcp.server.fastmcp.FastMCP`` and provides an ergonomic
    :class:`SkillDef` registration interface.  The underlying FastMCP
    instance is fully encapsulated — no escape-hatch property is exposed.

    Attributes are name-mangled (``_fastmcp``) to signal private intent
    without making them inaccessible to tests that need the ASGI app.

    Example::

        server = MCPServer(name="hevi", version="5.0.0")
        server.register_skill(SkillDef(...))
        await server.serve_stdio()
    """

    def __init__(self, *, name: str, version: str) -> None:
        """Create an MCPServer.

        Args:
            name: Server name reported in MCP capability negotiation.
            version: Server version string reported in MCP capability negotiation.
        """
        self._fastmcp = FastMCP(name=name)
        # FastMCP.__init__ does not accept a version kwarg; inject it into
        # the underlying low-level Server which does expose the field.
        self._fastmcp._mcp_server.version = version

    def register_skill(self, skill_def: SkillDef) -> None:
        """Register a Skill (single signature — only accepts :class:`SkillDef`).

        Internally:

        * Converts ``SkillDef`` into a FastMCP tool via ``add_tool``.
        * Overrides the auto-inferred ``parameters`` with
          ``skill_def.input_schema`` (MCP wire: ``inputSchema``).
        * Replaces FastMCP's per-parameter arg model with
          :class:`_DynamicArgModel` so the handler receives the full
          arguments dict without per-field validation.

        Args:
            skill_def: The skill definition to register.

        Raises:
            MCPServerError: If ``add_tool`` fails (e.g. duplicate name).
        """
        handler = skill_def.handler

        async def _wrapper(**kwargs: Any) -> Any:
            return await handler(kwargs)

        # FastMCP uses __name__ for deduplication and logging.
        _wrapper.__name__ = skill_def.name.replace(".", "_")

        try:
            self._fastmcp.add_tool(
                _wrapper,
                name=skill_def.name,
                description=skill_def.description,
            )
        except Exception as exc:
            raise MCPServerError(f"Failed to register skill {skill_def.name!r}: {exc}") from exc

        # Patch the registered Tool object:
        # 1. Replace auto-inferred schema with the explicit input_schema.
        # 2. Replace fn_metadata so FastMCP passes raw kwargs to _wrapper.
        tool = self._fastmcp._tool_manager._tools[skill_def.name]
        tool.parameters = skill_def.input_schema
        tool.fn_metadata = _DYNAMIC_FUNC_META

    async def serve_stdio(self) -> None:
        """Run the server using stdio transport.

        Used by desktop MCP clients such as Claude Desktop that communicate
        via stdin/stdout.
        """
        await self._fastmcp.run_stdio_async()

    async def serve_streamable_http(self, host: str, port: int) -> None:
        """Run the server using Streamable HTTP transport (MCP 2025-03+).

        Replaces the deprecated HTTP+SSE transport.  Call this when the
        server is accessed over a network by web-based MCP clients.

        Args:
            host: Bind host (e.g. ``"0.0.0.0"`` for all interfaces).
            port: Bind port (e.g. ``8080``).

        Note:
            The old HTTP+SSE transport is deprecated; only Streamable HTTP
            is supported by this Facade.
        """
        self._fastmcp.settings.host = host
        self._fastmcp.settings.port = port
        await self._fastmcp.run_streamable_http_async()
