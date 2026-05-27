"""Tests for obase.mcp_server — MCPServer + SkillDef Facade.

9 tests required (P7-B1 hard requirement):
1. register_skill_normal            — no raise on valid SkillDef
2. stdio_initialize_list_call       — in-process stdio: initialize + tools/list + tools/call
3. streamable_http_transport        — random-port HTTP server: tools/list + tools/call
4. handler_exception_returns_error  — handler raises → isError=True response
5. handler_bad_input_returns_error  — handler raises on unexpected input → error response
6. unknown_skill_call_error         — call nonexistent tool → McpError / error response
7. capability_negotiation           — initialize: protocolVersion + capabilities present
8. multiple_skills_registered       — register 5 skills → tools/list returns all 5
9. snake_camel_serialization        — SkillDef.model_dump(by_alias=True) → inputSchema/outputSchema
"""

from __future__ import annotations

import socket

import anyio
import pytest

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.memory import create_client_server_memory_streams
from mcp.types import TextContent

from obase.mcp_server import MCPServer, MCPServerError, SkillDef


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_server(name: str = "test", version: str = "1.0.0") -> MCPServer:
    return MCPServer(name=name, version=version)


def _echo_skill(name: str = "test.echo") -> SkillDef:
    """SkillDef whose handler echoes its input."""

    async def _handler(args: dict) -> dict:
        return {"echo": args}

    return SkillDef(
        name=name,
        description="Echo the input",
        input_schema={
            "type": "object",
            "properties": {"message": {"type": "string"}},
            "required": ["message"],
        },
        handler=_handler,
    )


async def _run_in_process(server: MCPServer, coro):
    """Run *coro* with an in-process ClientSession connected to *server*."""
    async with create_client_server_memory_streams() as (client_streams, server_streams):
        client_read, client_write = client_streams
        server_read, server_write = server_streams

        async with anyio.create_task_group() as tg:

            async def _run_server() -> None:
                await server._fastmcp._mcp_server.run(  # type: ignore[attr-defined]
                    server_read,
                    server_write,
                    server._fastmcp._mcp_server.create_initialization_options(),  # type: ignore[attr-defined]
                )

            tg.start_soon(_run_server)

            async with ClientSession(client_read, client_write) as session:
                await session.initialize()
                result = await coro(session)

            tg.cancel_scope.cancel()

    return result


# ---------------------------------------------------------------------------
# Test 1: register_skill normal
# ---------------------------------------------------------------------------


def test_register_skill_normal():
    """Creating SkillDef + MCPServer + register_skill does not raise."""
    server = _make_server()
    skill = _echo_skill()
    server.register_skill(skill)  # must not raise


# ---------------------------------------------------------------------------
# Test 2: stdio — initialize + tools/list + tools/call
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stdio_tools_list_and_call():
    """In-process stdio: initialize → tools/list → tools/call all succeed."""
    server = _make_server()
    server.register_skill(_echo_skill("test.echo"))

    async def _interact(session: ClientSession):
        tools_result = await session.list_tools()
        tool_names = [t.name for t in tools_result.tools]
        assert "test.echo" in tool_names

        call_result = await session.call_tool("test.echo", {"message": "hi"})
        assert call_result.isError is False
        return call_result

    result = await _run_in_process(server, _interact)
    # handler returned {"echo": {"message": "hi"}}
    assert result is not None


# ---------------------------------------------------------------------------
# Test 3: Streamable HTTP transport
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_streamable_http_transport():
    """Streamable HTTP transport: tools/list and tools/call succeed over HTTP.

    Starts the server on a random free port (in-process, no separate process).
    The FastMCP streamable-HTTP ASGI app requires a proper Uvicorn lifespan
    to initialise its session manager, so we use serve_streamable_http() in a
    background task rather than the raw ASGI transport.
    """
    server = _make_server()
    server.register_skill(_echo_skill("http.echo"))

    # Find a free port
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

    url = f"http://127.0.0.1:{port}/mcp"

    async with anyio.create_task_group() as tg:
        tg.start_soon(server.serve_streamable_http, "127.0.0.1", port)

        # Brief wait for Uvicorn to be ready
        await anyio.sleep(0.3)

        async with streamable_http_client(url) as (read, write, _get_sid):
            async with ClientSession(read, write) as session:
                await session.initialize()

                tools_result = await session.list_tools()
                tool_names = [t.name for t in tools_result.tools]
                assert "http.echo" in tool_names

                call_result = await session.call_tool("http.echo", {"message": "http!"})
                assert call_result.isError is False

        tg.cancel_scope.cancel()


# ---------------------------------------------------------------------------
# Test 4: handler exception → error response (not propagated)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handler_exception_returns_error_response():
    """When handler raises, the MCP response has isError=True (not propagated)."""

    async def _failing_handler(args: dict) -> dict:
        raise RuntimeError("intentional handler failure")

    server = _make_server()
    server.register_skill(
        SkillDef(
            name="test.failing",
            description="Always fails",
            input_schema={"type": "object"},
            handler=_failing_handler,
        )
    )

    async def _interact(session: ClientSession):
        return await session.call_tool("test.failing", {})

    result = await _run_in_process(server, _interact)
    assert result.isError is True


# ---------------------------------------------------------------------------
# Test 5: handler raises on bad input → error response
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handler_bad_input_returns_error_response():
    """Handler that validates input and raises returns an error response."""

    async def _strict_handler(args: dict) -> dict:
        if "required_field" not in args:
            raise ValueError("Missing required_field")
        return {"ok": True}

    server = _make_server()
    server.register_skill(
        SkillDef(
            name="test.strict",
            description="Requires required_field",
            input_schema={
                "type": "object",
                "properties": {"required_field": {"type": "string"}},
                "required": ["required_field"],
            },
            handler=_strict_handler,
        )
    )

    async def _interact(session: ClientSession):
        # Call without required_field → handler raises → error response
        return await session.call_tool("test.strict", {})

    result = await _run_in_process(server, _interact)
    assert result.isError is True


# ---------------------------------------------------------------------------
# Test 6: unknown skill → error response
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_skill_call_error():
    """Calling a nonexistent tool name returns isError=True (MCP protocol behaviour).

    Per MCP 1.27 spec: the server does not raise at the JSON-RPC level for an
    unknown tool name — it returns a CallToolResult with isError=True and an
    error message in content.
    """
    server = _make_server()
    server.register_skill(_echo_skill())

    async def _interact(session: ClientSession):
        result = await session.call_tool("nonexistent.skill", {})
        assert result.isError is True
        # Error message content must mention the unknown tool
        assert any("nonexistent.skill" in str(c) for c in result.content)
        return result

    await _run_in_process(server, _interact)


# ---------------------------------------------------------------------------
# Test 7: capability negotiation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_capability_negotiation():
    """initialize response contains protocolVersion and tools capability."""
    server = _make_server(name="hevi", version="5.0.0")
    server.register_skill(_echo_skill())

    async with create_client_server_memory_streams() as (client_streams, server_streams):
        client_read, client_write = client_streams
        server_read, server_write = server_streams

        async with anyio.create_task_group() as tg:

            async def _run_server() -> None:
                await server._fastmcp._mcp_server.run(  # type: ignore[attr-defined]
                    server_read,
                    server_write,
                    server._fastmcp._mcp_server.create_initialization_options(),  # type: ignore[attr-defined]
                )

            tg.start_soon(_run_server)

            async with ClientSession(client_read, client_write) as session:
                init_result = await session.initialize()

                # protocolVersion must be present and non-empty
                assert init_result.protocolVersion
                # tools capability must be declared
                assert init_result.capabilities.tools is not None
                # server info must reflect our name + version
                assert init_result.serverInfo.name == "hevi"
                assert init_result.serverInfo.version == "5.0.0"

            tg.cancel_scope.cancel()


# ---------------------------------------------------------------------------
# Test 8: multiple skills registered
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multiple_skills_registered():
    """Registering 5 skills — tools/list returns all 5."""
    server = _make_server()
    skill_names = [f"test.skill_{i}" for i in range(5)]
    for name in skill_names:
        server.register_skill(_echo_skill(name))

    async def _interact(session: ClientSession):
        result = await session.list_tools()
        return {t.name for t in result.tools}

    registered = await _run_in_process(server, _interact)
    for name in skill_names:
        assert name in registered


# ---------------------------------------------------------------------------
# Test 9: snake_case → camelCase serialization
# ---------------------------------------------------------------------------


def test_snake_camel_serialization():
    """SkillDef.model_dump(by_alias=True) produces inputSchema / outputSchema."""

    async def _handler(args: dict) -> dict:
        return {}

    skill = SkillDef(
        name="test.skill",
        description="A skill",
        input_schema={"type": "object", "properties": {"x": {"type": "string"}}},
        output_schema={"type": "object", "properties": {"y": {"type": "string"}}},
        handler=_handler,
    )

    dumped = skill.model_dump(by_alias=True, exclude={"handler"})

    # camelCase keys must be present
    assert "inputSchema" in dumped
    assert "outputSchema" in dumped
    # snake_case keys must NOT be at top level
    assert "input_schema" not in dumped
    assert "output_schema" not in dumped
    # values must be preserved
    assert dumped["inputSchema"] == {"type": "object", "properties": {"x": {"type": "string"}}}
    assert dumped["outputSchema"] == {"type": "object", "properties": {"y": {"type": "string"}}}


# ---------------------------------------------------------------------------
# Coverage completers (lines 192-193, 208)
# ---------------------------------------------------------------------------


def test_register_skill_wraps_add_tool_error(monkeypatch):
    """register_skill wraps add_tool failures in MCPServerError."""
    from obase.mcp_server import MCPServerError

    server = _make_server()

    def _raise(*args, **kwargs):
        raise ValueError("simulated add_tool failure")

    monkeypatch.setattr(server._fastmcp, "add_tool", _raise)

    async def _h(args: dict) -> dict:
        return {}

    skill = SkillDef(
        name="test.boom",
        description="Boom",
        input_schema={"type": "object"},
        handler=_h,
    )
    with pytest.raises(MCPServerError, match="simulated add_tool failure"):
        server.register_skill(skill)


@pytest.mark.asyncio
async def test_serve_stdio_delegates(monkeypatch):
    """serve_stdio() calls _fastmcp.run_stdio_async() exactly once."""
    server = _make_server()
    calls: list[bool] = []

    async def _mock_run() -> None:
        calls.append(True)

    monkeypatch.setattr(server._fastmcp, "run_stdio_async", _mock_run)
    await server.serve_stdio()
    assert calls == [True]
