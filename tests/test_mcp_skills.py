"""WAVE B gates (obase substrate): MCP skills extension.

MCP_SKILLS_NEGOTIATION / DISCOVERY / METADATA / CONTENT / RESOURCE_FETCH
MCP_BASE_PROTOCOL_REGRESSION + NEW_MCP_RUNTIME=0 + NEW_SKILL_REGISTRY=0.
"""

from __future__ import annotations

import pytest

from obase.mcp_client import (
    SKILLS_EXTENSION_URI,
    McpClientRegistry,
    SkillsExtensionError,
    discover_skills,
    get_skill_content,
    get_skill_metadata,
    negotiate_skills_extension,
    normalize_skill_capability,
)


class FakeSkillsClient:
    extensions = [SKILLS_EXTENSION_URI]

    async def list_tools(self):
        return [
            {
                "name": "skill_summarize",
                "description": "summarize text",
                "input_schema": {"type": "object"},
            },
            {"name": "plain_tool", "description": "not a skill"},
        ]

    async def call_tool(self, name, args):
        if name == "skill_list":
            return {
                "skills": [
                    {"name": "skill_summarize", "version": "1.0", "description": "summarize"},
                ]
            }
        if name == "skill_metadata":
            return {"name": args["skill_id"], "version": "1.0", "description": "summarize"}
        if name == "skill_content":
            return {"content": f"content-of-{args['skill_id']}"}
        raise RuntimeError(f"unknown tool {name}")


class ToolsOnlyClient:
    async def list_tools(self):
        return [{"name": "skill_search", "description": "search"}]

    async def call_tool(self, name, args):
        raise RuntimeError("no skill_* methods")


class PlainClient:
    async def list_tools(self):
        return [{"name": "read_file", "description": "read"}]

    async def call_tool(self, name, args):
        return {"ok": True}


@pytest.mark.asyncio()
async def test_negotiation_via_extensions():
    out = await negotiate_skills_extension(FakeSkillsClient())
    assert out == {"supported": True, "via": "extensions", "extension": SKILLS_EXTENSION_URI}


@pytest.mark.asyncio()
async def test_negotiation_via_tools():
    out = await negotiate_skills_extension(ToolsOnlyClient())
    assert out["supported"] is True and out["via"] == "tools"


@pytest.mark.asyncio()
async def test_negotiation_unsupported():
    out = await negotiate_skills_extension(PlainClient())
    assert out["supported"] is False


@pytest.mark.asyncio()
async def test_discovery_metadata_content_resource():
    client = FakeSkillsClient()
    skills = await discover_skills(client)
    assert len(skills) == 1 and skills[0]["name"] == "skill_summarize"
    assert skills[0]["extension"] == SKILLS_EXTENSION_URI

    meta = await get_skill_metadata(client, "skill_summarize")
    assert meta["name"] == "skill_summarize"

    content = await get_skill_content(client, "skill_summarize")
    assert content["content"] == "content-of-skill_summarize"

    resource = await get_skill_content(
        client, "skill_summarize", resource_uri="skill://summarize/v1"
    )
    assert resource["skill_id"] == "skill_summarize"


@pytest.mark.asyncio()
async def test_discovery_tools_fallback():
    skills = await discover_skills(ToolsOnlyClient())
    assert [s["name"] for s in skills] == ["skill_search"]


@pytest.mark.asyncio()
async def test_metadata_missing_raises():
    with pytest.raises(SkillsExtensionError):
        await get_skill_metadata(PlainClient(), "skill_nope")


def test_normalize_shape():
    out = normalize_skill_capability({"skill_id": "s1", "inputSchema": {"type": "object"}})
    assert out["name"] == "s1" and out["inputs"] == {"type": "object"}
    assert out["extension"] == SKILLS_EXTENSION_URI


def test_base_protocol_regression():
    assert McpClientRegistry._clients == {} or isinstance(McpClientRegistry._clients, dict)

    class Handle:
        async def list_tools(self):
            return []

        async def call_tool(self, name, args):
            return {}

    McpClientRegistry.register("wave-b-probe", Handle())
    assert McpClientRegistry.get("wave-b-probe") is not None
    del McpClientRegistry._clients["wave-b-probe"]


def test_no_new_runtime_or_registry():
    import inspect as _inspect

    import obase.mcp_client as mod

    classes = [name for name, obj in vars(mod).items() if _inspect.isclass(obj)]
    assert "SkillsEngine" not in classes
    assert not any(n.endswith("SkillRegistry") for n in classes)
    assert not any("Runtime" in n for n in classes)
    assert "SkillsExtensionError" in classes  # 仅错误类型,非 runtime
