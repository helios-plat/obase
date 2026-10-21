"""Structural contract for the injected daemon message bus."""

from __future__ import annotations

from typing import Any, Protocol


class IDaemon_Subscription(Protocol):
    """A subscription yielding message payloads until closed."""

    async def receive(self) -> dict[str, Any]: ...

    def close(self) -> None: ...


class IDaemon_Bus(Protocol):
    """Async pub/sub interface consumed by the oservi daemon engine."""

    async def publish(self, topic: str, payload: dict[str, Any]) -> None: ...

    async def subscribe(self, topic: str) -> IDaemon_Subscription: ...
