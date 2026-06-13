"""obase.lsp — LSP client manager (server handle 提供者)."""
from __future__ import annotations
from typing import Any, Protocol, runtime_checkable

@runtime_checkable
class LspServerHandle(Protocol):
    """LSP server handle Protocol. lsp_* oprim 通过此 handle 发 JSON-RPC 请求."""
    async def request(self, method: str, params: dict) -> Any: ...
    async def notify(self, method: str, params: dict) -> None: ...

class LspClientManager:
    """管理语言服务器生命周期 (spawn/connect/close)."""
    _servers: dict[str, LspServerHandle] = {}

    @classmethod
    async def get_or_spawn(cls, lang: str, root: str) -> LspServerHandle:
        """取或建语言服务器 handle."""
        key = f"{lang}:{root}"
        if key not in cls._servers:
            raise RuntimeError(
                f"LSP server for {lang!r} not started. "
                "Call LspClientManager.start(lang, root) first."
            )
        return cls._servers[key]

    @classmethod
    def register(cls, lang: str, root: str, handle: LspServerHandle) -> None:
        """注册已建好的 server handle (服务层调用)."""
        cls._servers[f"{lang}:{root}"] = handle
