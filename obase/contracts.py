"""Dependency-injection contracts shared by the atomic operation layer."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class IVFS_Sandbox(Protocol):
    """Minimal byte-oriented VFS contract consumed by oprim primitives."""

    async def read_file(self, path: str) -> bytes: ...

    async def write_file(self, path: str, content: bytes) -> None: ...

    async def execute_isolated(
        self, command: str, *, timeout: int = 30
    ) -> dict[str, Any]: ...


@runtime_checkable
class KVStoreProvider(Protocol):
    """Minimal asynchronous key/value contract used by state primitives."""

    async def put(self, key: str, value: dict[str, Any]) -> None: ...

    async def get(self, key: str) -> dict[str, Any] | None: ...


VFSProvider = IVFS_Sandbox
