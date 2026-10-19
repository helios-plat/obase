"""obase.mcp_client — MCP client handle 提供者 + skills 扩展 substrate.

WAVE B owner: obase. 支持 io.modelcontextprotocol/skills:
- negotiate skills extension / list-discover / metadata / content-resource
- normalize skill capability

只做 substrate (协商/发现/取数/归一化),不做 skill registry/runtime,
不复制 oskill 内容。client 通过注入传入,不持有业务持久化。
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from obase.tool_governance import MCPServerSpec

SKILLS_EXTENSION_URI = "io.modelcontextprotocol/skills"

__all__ = [
    "SKILLS_EXTENSION_URI",
    "McpClientHandle",
    "McpClientRegistry",
    "MCPServerSpec",
    "SkillsExtensionError",
    "negotiate_skills_extension",
    "discover_skills",
    "get_skill_metadata",
    "get_skill_content",
    "normalize_skill_capability",
    "supports_resources",
    "list_resources",
    "read_resource",
]


@runtime_checkable
class McpClientHandle(Protocol):
    """MCP client handle Protocol. mcp_* oprim 通过此 handle 调外部 MCP 工具."""

    async def list_tools(self) -> list[dict[str, Any]]: ...
    async def call_tool(self, name: str, args: dict[str, Any]) -> Any: ...


class McpClientRegistry:
    """管理 MCP client 连接 + 版本化 server contract.

    ``_clients`` 是 (name -> handle) 连接表; ``_specs`` 是 (name -> MCPServerSpec)
    contract 表。两者同居一个 registry,不引入第二套注册中心。
    """

    _clients: dict[str, McpClientHandle] = {}
    _specs: dict[str, MCPServerSpec] = {}

    @classmethod
    def register(cls, name: str, handle: McpClientHandle) -> None:
        cls._clients[name] = handle

    @classmethod
    def register_server(cls, spec: MCPServerSpec, handle: McpClientHandle) -> None:
        """Register a client together with its versioned server contract."""
        cls._specs[spec.name] = spec
        cls._clients[spec.name] = handle

    @classmethod
    def register_spec(cls, spec: MCPServerSpec, *, replace: bool = False) -> None:
        if not replace and spec.name in cls._specs:
            raise ValueError(f"MCP server {spec.name!r} already registered")
        cls._specs[spec.name] = spec

    @classmethod
    def get(cls, name: str) -> McpClientHandle:
        if name not in cls._clients:
            raise KeyError(f"MCP client {name!r} not registered.")
        return cls._clients[name]

    @classmethod
    def has(cls, name: str) -> bool:
        """Whether a client handle is currently registered."""
        return name in cls._clients

    @classmethod
    def list_clients(cls) -> list[str]:
        """Registered client names in registration order."""
        return list(cls._clients)

    @classmethod
    def unregister(cls, name: str) -> bool:
        """Drop a client handle (teardown); specs stay for audit.

        Returns True when a handle was actually removed. Never touches
        ``_specs`` — definitions outlive connections.
        """
        return cls._clients.pop(name, None) is not None

    @classmethod
    def spec(cls, name: str) -> MCPServerSpec:
        if name not in cls._specs:
            raise KeyError(f"MCP server spec {name!r} not registered")
        return cls._specs[name]

    @classmethod
    def list_specs(cls) -> list[MCPServerSpec]:
        return list(cls._specs.values())

    @classmethod
    def invalidate(cls, name: str) -> bool:
        spec = cls._specs.get(name)
        if spec is None:
            return False
        cls._specs[name] = MCPServerSpec(
            name=spec.name,
            endpoint=spec.endpoint,
            version=spec.version,
            protocol_version=spec.protocol_version,
            tools=spec.tools,
            credential_ref=spec.credential_ref,
            enabled=False,
        )
        return True

    @classmethod
    def clear(cls) -> None:
        cls._clients.clear()
        cls._specs.clear()


# ---------------------------------------------------------------------------
# skills extension substrate (io.modelcontextprotocol/skills)
# ---------------------------------------------------------------------------


class SkillsExtensionError(RuntimeError):
    """skills 扩展协商/取数错误。"""


async def _maybe_await(value: Any) -> Any:
    import inspect as _inspect

    if _inspect.isawaitable(value):
        return await value
    return value


async def negotiate_skills_extension(client: McpClientHandle) -> dict[str, Any]:
    """协商 skills 扩展:探测 server 是否支持 io.modelcontextprotocol/skills。

    探测顺序: client.extensions 属性/方法 -> list_tools 中的 skill 相关工具。
    返回 {"supported": bool, "via": str, "extension": str}。
    """
    # 1. 显式 extensions 声明 (属性或方法)
    extensions: Any = getattr(client, "extensions", None)
    if callable(extensions):
        try:
            extensions = await _maybe_await(extensions())
        except Exception:
            extensions = None
    if isinstance(extensions, (list, tuple, set)):
        if SKILLS_EXTENSION_URI in set(extensions):
            return {"supported": True, "via": "extensions", "extension": SKILLS_EXTENSION_URI}
    # 2. server info 声明
    server_info = getattr(client, "server_info", None)
    if callable(server_info):
        try:
            server_info = await _maybe_await(server_info())
        except Exception:
            server_info = None
    if isinstance(server_info, dict):
        exts = server_info.get("extensions") or server_info.get("capabilities") or []
        if SKILLS_EXTENSION_URI in set(exts if isinstance(exts, list) else []):
            return {"supported": True, "via": "server_info", "extension": SKILLS_EXTENSION_URI}
    # 3. 工具面探测:存在 skill_* 工具即视为支持
    try:
        tools = await _maybe_await(client.list_tools())
    except Exception as exc:
        raise SkillsExtensionError(f"negotiate: list_tools failed: {exc}") from exc
    names = {str(t.get("name", "")) for t in tools if isinstance(t, dict)}
    skill_tools = {n for n in names if n.startswith("skill")}
    if skill_tools:
        return {"supported": True, "via": "tools", "extension": SKILLS_EXTENSION_URI}
    return {"supported": False, "via": "none", "extension": SKILLS_EXTENSION_URI}


async def discover_skills(client: McpClientHandle) -> list[dict[str, Any]]:
    """发现远端 skills:优先 skill_list 工具,否则从 tools 面过滤 skill_*。"""
    try:
        result = await _maybe_await(client.call_tool("skill_list", {}))
    except Exception:
        result = None
    if isinstance(result, dict) and isinstance(result.get("skills"), list):
        return [normalize_skill_capability(s) for s in result["skills"] if isinstance(s, dict)]
    if isinstance(result, list):
        return [normalize_skill_capability(s) for s in result if isinstance(s, dict)]
    try:
        tools = await _maybe_await(client.list_tools())
    except Exception as exc:
        raise SkillsExtensionError(f"discover: list_tools failed: {exc}") from exc
    return [
        normalize_skill_capability(t)
        for t in tools
        if isinstance(t, dict) and str(t.get("name", "")).startswith("skill")
    ]


async def get_skill_metadata(client: McpClientHandle, skill_id: str) -> dict[str, Any]:
    """取远端 skill metadata (skill_metadata 工具或 tool schema 回退) 。"""
    if not skill_id:
        raise ValueError("get_skill_metadata: skill_id must not be empty")
    try:
        result = await _maybe_await(client.call_tool("skill_metadata", {"skill_id": skill_id}))
        if isinstance(result, dict) and result:
            candidate = normalize_skill_capability(result)
            # 仅接受确为目标 skill 的 metadata (名字命中或具名描述),否则回退查找
            if candidate["name"] == skill_id or (candidate["name"] and candidate["description"]):
                return candidate
    except Exception:
        pass
    try:
        tools = await _maybe_await(client.list_tools())
    except Exception as exc:
        raise SkillsExtensionError(f"metadata: list_tools failed: {exc}") from exc
    for tool in tools:
        if isinstance(tool, dict) and str(tool.get("name", "")) == skill_id:
            return normalize_skill_capability(tool)
    raise SkillsExtensionError(f"metadata: skill {skill_id!r} not found")


async def get_skill_content(
    client: McpClientHandle, skill_id: str, *, resource_uri: str | None = None
) -> dict[str, Any]:
    """取远端 skill content/resource (skill_content 工具;无则返回 metadata 占位)。"""
    if not skill_id:
        raise ValueError("get_skill_content: skill_id must not be empty")
    args: dict[str, Any] = {"skill_id": skill_id}
    if resource_uri:
        args["resource_uri"] = resource_uri
    try:
        result = await _maybe_await(client.call_tool("skill_content", args))
        if isinstance(result, dict):
            return {"skill_id": skill_id, "content": result.get("content"), "raw": result}
        return {"skill_id": skill_id, "content": result, "raw": result}
    except Exception as exc:
        raise SkillsExtensionError(f"content: skill {skill_id!r} fetch failed: {exc}") from exc


def normalize_skill_capability(skill: dict[str, Any]) -> dict[str, Any]:
    """归一化远端 skill capability (只做形状归一,不持久化,不复制 oskill)。"""
    if not isinstance(skill, dict):
        raise ValueError("normalize_skill_capability: skill must be a dict")
    name = str(skill.get("name") or skill.get("skill_id") or skill.get("id") or "")
    schema = skill.get("input_schema") or skill.get("inputSchema") or skill.get("schema") or {}
    return {
        "name": name,
        "version": str(skill.get("version", "")),
        "description": str(skill.get("description", "")),
        "inputs": schema if isinstance(schema, dict) else {},
        "outputs": skill.get("outputs") or {},
        "extension": SKILLS_EXTENSION_URI,
    }


# ---------------------------------------------------------------------------
# resources substrate (resources/list + resources/read, conditional)
# ---------------------------------------------------------------------------


def supports_resources(client: McpClientHandle) -> bool:
    """Whether a handle observably implements resources/list+read.

    The base :class:`McpClientHandle` contract only requires tools; resource
    access is probed (method presence), never assumed. ``False`` means the
    caller must treat resources as unsupported, not empty.
    """
    return callable(getattr(client, "list_resources", None)) and callable(
        getattr(client, "read_resource", None)
    )


async def list_resources(client: McpClientHandle) -> list[dict[str, Any]]:
    """List remote resources; fail closed when the handle lacks support."""
    if not supports_resources(client):
        raise SkillsExtensionError("resources: handle does not implement resources/list")
    try:
        result = await _maybe_await(client.list_resources())  # type: ignore[attr-defined]
    except Exception as exc:
        raise SkillsExtensionError(f"resources: list failed: {exc}") from exc
    if not isinstance(result, list):
        raise SkillsExtensionError("resources: list returned a non-list payload")
    return [item for item in result if isinstance(item, dict)]


async def read_resource(client: McpClientHandle, uri: str) -> dict[str, Any]:
    """Read one remote resource by URI; fail closed when unsupported."""
    if not uri:
        raise ValueError("read_resource: uri must not be empty")
    if not supports_resources(client):
        raise SkillsExtensionError(f"resources: handle does not implement resources/read ({uri!r})")
    try:
        result = await _maybe_await(client.read_resource(uri))  # type: ignore[attr-defined]
    except Exception as exc:
        raise SkillsExtensionError(f"resources: read {uri!r} failed: {exc}") from exc
    if isinstance(result, dict):
        return {"uri": uri, "content": result.get("content"), "raw": result}
    return {"uri": uri, "content": result, "raw": result}
