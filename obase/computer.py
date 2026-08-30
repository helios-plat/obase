"""Computer value types shared by local and Docker execution adapters.

This module contains infrastructure data only.  It does not create processes,
containers, worktrees, or service state; those responsibilities remain in the
existing adapters and the higher 3O layers.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

ComputerBackend = Literal["local", "docker"]
ComputerState = Literal["created", "running", "stopped", "attached", "failed"]


@dataclass(frozen=True)
class ComputerProfile:
    """Declarative execution profile for one caller-owned workspace."""

    id: str
    backend: ComputerBackend = "local"
    workspace: str | None = None
    image: str | None = None
    block_network: bool = True
    cpu: str = "1"
    memory: str = "512m"
    owner_id: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ComputerHandle:
    """Opaque handle returned by the computer atomics."""

    computer_id: str
    profile_id: str
    backend: ComputerBackend
    workspace: str | None
    sandbox_id: str
    container_id: str = ""
    state: ComputerState = "created"
    attached: bool = False
    owner_id: str = ""
    version: int = 1

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


__all__ = [
    "ComputerBackend",
    "ComputerHandle",
    "ComputerProfile",
    "ComputerState",
]
