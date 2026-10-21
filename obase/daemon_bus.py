"""跨进程守护总线 (3O 范式 Phase 1) — 进程内默认实现.

注意: 本实现尚未在 obase.__init__ 收口导出, 待跨进程方案定稿后接入。
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import AsyncGenerator
from typing import Any, Protocol

from obase.contracts import IDaemon_Bus


class DaemonBusProvider(Protocol):
    """跨进程通信总线 (v3.0 纯适配器)"""

    async def publish(self, topic: str, payload: dict[str, Any]) -> None: ...

    async def subscribe(self, topic: str) -> AsyncGenerator[dict[str, Any], None]: ...


class _Subscription:
    """订阅器句柄"""

    def __init__(self, bus: InProcessDaemonBus, topic: str, queue: asyncio.Queue):
        self._bus = bus
        self._topic = topic
        self._queue = queue

    async def receive(self) -> dict:
        """阻塞读取下一条消息"""
        return await self._queue.get()

    def close(self) -> None:
        """退订"""
        self._bus._unsubscribe(self._topic, self._queue)


class InProcessDaemonBus(IDaemon_Bus):
    """进程内守护总线 (进程内 pub/sub, 跨进程方案后续迭代)"""

    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue]] = defaultdict(set)

    async def publish(self, topic: str, payload: dict) -> None:
        for queue in list(self._subscribers.get(topic, ())):
            await queue.put(payload)

    async def subscribe(self, topic: str) -> Any:
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers[topic].add(queue)
        return _Subscription(self, topic, queue)

    def _unsubscribe(self, topic: str, queue: asyncio.Queue) -> None:
        subscribers = self._subscribers.get(topic)
        if subscribers is not None:
            subscribers.discard(queue)
            if not subscribers:
                self._subscribers.pop(topic, None)
