"""obase.mcp_server demo — complete Skill registration + in-process smoke test.

Demonstrates:
- Creating an MCPServer with name + version
- Registering multiple SkillDefs (input_schema / output_schema / handler)
- Verifying skills appear in tools/list and respond correctly via stdio transport

Run::

    cd /home/soffy/projects/platform/obase
    uv run python examples/mcp_server_demo.py
"""

from __future__ import annotations

import asyncio

import anyio
from mcp import ClientSession
from mcp.shared.memory import create_client_server_memory_streams

from obase.mcp_server import MCPServer, SkillDef


# ---------------------------------------------------------------------------
# Skill 1: Generate video
# ---------------------------------------------------------------------------


async def generate_video_handler(args: dict) -> dict:
    """Stub handler — returns a fake video path."""
    topic = args.get("topic", "unknown")
    duration = args.get("duration_seconds", 180)
    return {
        "video_path": f"/tmp/hevi/{topic.replace(' ', '_')}_{duration}s.mp4",
        "duration_seconds": duration,
        "status": "queued",
    }


generate_video_skill = SkillDef(
    name="hevi.generate_video",
    description="Generate a 3+ min vertical content video from a topic.",
    input_schema={
        "type": "object",
        "properties": {
            "topic": {"type": "string", "description": "Video topic, e.g. 'Python async'"},
            "duration_seconds": {
                "type": "integer",
                "description": "Target duration in seconds (default 180)",
                "default": 180,
            },
        },
        "required": ["topic"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "video_path": {"type": "string"},
            "duration_seconds": {"type": "integer"},
            "status": {"type": "string"},
        },
    },
    handler=generate_video_handler,
)


# ---------------------------------------------------------------------------
# Skill 2: List runs
# ---------------------------------------------------------------------------


async def list_runs_handler(args: dict) -> dict:
    """Stub handler — returns fake run list."""
    limit = args.get("limit", 10)
    return {"runs": [{"id": f"run_{i}", "status": "done"} for i in range(min(limit, 3))]}


list_runs_skill = SkillDef(
    name="hevi.list_runs",
    description="List recent video generation runs.",
    input_schema={
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "description": "Max runs to return", "default": 10}
        },
    },
    handler=list_runs_handler,
)


# ---------------------------------------------------------------------------
# Demo runner — in-process stdio smoke test
# ---------------------------------------------------------------------------


async def _demo() -> None:
    # Build server
    server = MCPServer(name="hevi", version="5.0.0")
    server.register_skill(generate_video_skill)
    server.register_skill(list_runs_skill)

    print("=== obase.mcp_server Demo ===")
    print(f"Server: hevi v5.0.0  |  Skills: 2")
    print()

    # Serialise SkillDef with camelCase alias (MCP wire format)
    wire = generate_video_skill.model_dump(by_alias=True, exclude={"handler"})
    print("SkillDef wire format (by_alias=True):")
    for k, v in wire.items():
        print(f"  {k}: {v}")
    print()

    # In-process stdio smoke test
    print("--- In-process stdio smoke test ---")
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
                print(f"✓ initialize  protocolVersion={init_result.protocolVersion}")
                print(f"  server={init_result.serverInfo.name} v{init_result.serverInfo.version}")

                tools = await session.list_tools()
                print(f"✓ tools/list  count={len(tools.tools)}")
                for t in tools.tools:
                    print(f"  • {t.name}: {t.description}")

                result = await session.call_tool(
                    "hevi.generate_video", {"topic": "Python async", "duration_seconds": 60}
                )
                print(f"✓ tools/call  isError={result.isError}")
                for content in result.content:
                    print(f"  → {content}")

                result2 = await session.call_tool("hevi.list_runs", {"limit": 2})
                print(f"✓ tools/call  isError={result2.isError}")
                for content in result2.content:
                    print(f"  → {content}")

            tg.cancel_scope.cancel()

    print()
    print("Demo complete — all in-process checks passed.")


if __name__ == "__main__":
    asyncio.run(_demo())
