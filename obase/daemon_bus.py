"""Structural contract and in-process implementation for the daemon message bus."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class IDaemon_Subscription(Protocol):
    """A subscription yielding message payloads until closed."""

    async def receive(self) -> dict[str, Any]: ...

    def close(self) -> None: ...


@runtime_checkable
class IDaemon_Bus(Protocol):
    """Async pub/sub interface consumed by the oservi daemon engine."""

    async def publish(self, topic: str, payload: dict[str, Any]) -> None: ...

    async def subscribe(self, topic: str) -> IDaemon_Subscription: ...


_CLOSED = object()


class _InProcessSubscription:
    def __init__(self, bus: InProcessDaemonBus, topic: str):
        self._bus = bus
        self.topic = topic
        self._queue: asyncio.Queue[object] = asyncio.Queue()
        self._closed = False

    async def receive(self) -> dict[str, Any]:
        """Receive the next payload or stop once the subscription is closed."""
        item = await self._queue.get()
        if item is _CLOSED:
            raise StopAsyncIteration("subscription is closed")
        if not isinstance(item, dict):
            raise RuntimeError("daemon bus delivered an invalid payload")
        return item

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._bus._discard(self.topic, self)
        self._queue.put_nowait(_CLOSED)


class InProcessDaemonBus:
    """Topic-based asynchronous fan-out bus for tests and single-process use."""

    def __init__(self):
        self._subscriptions: dict[str, set[_InProcessSubscription]] = {}
        self._lock = asyncio.Lock()

    async def subscribe(self, topic: str) -> _InProcessSubscription:
        if not isinstance(topic, str) or not topic.strip():
            raise ValueError("topic must be a non-empty string")
        subscription = _InProcessSubscription(self, topic)
        async with self._lock:
            self._subscriptions.setdefault(topic, set()).add(subscription)
        return subscription

    async def publish(self, topic: str, payload: dict[str, Any]) -> None:
        if not isinstance(topic, str) or not topic.strip():
            raise ValueError("topic must be a non-empty string")
        if not isinstance(payload, dict):
            raise TypeError("payload must be a dictionary")
        async with self._lock:
            subscribers = tuple(self._subscriptions.get(topic, ()))
        for subscriber in subscribers:
            if not subscriber._closed:
                subscriber._queue.put_nowait(deepcopy(payload))

    def _discard(self, topic: str, subscription: _InProcessSubscription) -> None:
        subscribers = self._subscriptions.get(topic)
        if subscribers is None:
            return
        subscribers.discard(subscription)
        if not subscribers:
            self._subscriptions.pop(topic, None)


# Backwards-compatible public name used by existing oprim adapters.
DaemonBusProvider = IDaemon_Bus
