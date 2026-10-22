"""跨进程守护总线 (3O 范式 Phase 1) — 进程内默认实现.

注意: 本实现尚未在 obase.__init__ 收口导出, 待跨进程方案定稿后接入。
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import AsyncGenerator
from copy import deepcopy
from typing import Any, Protocol, runtime_checkable

from obase.contracts import IDaemon_Bus


@runtime_checkable
class IDaemon_Subscription(Protocol):
    async def receive(self) -> dict[str, Any]: ...
    def close(self) -> None: ...


class DaemonBusProvider(Protocol):
    """跨进程通信总线 (v3.0 纯适配器)"""

    async def publish(self, topic: str, payload: dict[str, Any]) -> None: ...

    async def subscribe(self, topic: str) -> AsyncGenerator[dict[str, Any], None]: ...


_CLOSED = object()


class _Subscription:
    """订阅器句柄"""

    def __init__(self, bus: InProcessDaemonBus, topic: str, queue: asyncio.Queue):
        self._bus = bus
        self._topic = topic
        self._queue = queue

    async def receive(self) -> dict:
        """Read the next payload; a closed handle terminates iteration."""
        payload = await self._queue.get()
        if payload is _CLOSED:
            raise StopAsyncIteration("subscription is closed")
        if not isinstance(payload, dict):
            raise RuntimeError("daemon bus delivered an invalid payload")
        return payload

    def close(self) -> None:
        """Unsubscribe this handle and unblock pending receivers."""
        self._bus._unsubscribe(self._topic, self._queue)
        self._queue.put_nowait(_CLOSED)


class InProcessDaemonBus(IDaemon_Bus):
    """进程内守护总线 (进程内 pub/sub, 跨进程方案后续迭代)"""

    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue]] = defaultdict(set)

    async def publish(self, topic: str, payload: dict) -> None:
        if not isinstance(topic, str) or not topic.strip():
            raise ValueError("topic must be a non-empty string")
        if not isinstance(payload, dict):
            raise TypeError("payload must be a dictionary")
        for queue in list(self._subscribers.get(topic, ())):
            await queue.put(deepcopy(payload))

    async def subscribe(self, topic: str) -> Any:
        if not isinstance(topic, str) or not topic.strip():
            raise ValueError("topic must be a non-empty string")
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers[topic].add(queue)
        return _Subscription(self, topic, queue)

    def _unsubscribe(self, topic: str, queue: asyncio.Queue) -> None:
        subscribers = self._subscribers.get(topic)
        if subscribers is not None:
            subscribers.discard(queue)
            if not subscribers:
                self._subscribers.pop(topic, None)


# Keep the contracts-layer ABC as the canonical public interface.
IDaemon_Bus = __import__('obase.contracts', fromlist=['IDaemon_Bus']).IDaemon_Bus
DaemonBusProvider = IDaemon_Bus
