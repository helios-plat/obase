"""全局事件同步屏障 (3O 范式 Phase 1) — 进程内默认实现.

注意: 本实现尚未在 obase.__init__ 收口导出, 待跨进程方案定稿后接入。
"""

from __future__ import annotations

import asyncio

from obase.contracts import IEvent_Barrier


class InProcessEventBarrier(IEvent_Barrier):
    """进程内事件屏障 (asyncio.Event 集合, 一次性全局信号)"""

    def __init__(self) -> None:
        self._events: dict[str, asyncio.Event] = {}

    async def wait_for_event(self, event_name: str, timeout: float) -> bool:
        event = self._events.get(event_name)
        if event is None:
            event = asyncio.Event()
            self._events[event_name] = event
        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
            return event.is_set()
        except TimeoutError:
            return False

    async def set_event(self, event_name: str) -> None:
        event = self._events.get(event_name)
        if event is None:
            event = asyncio.Event()
            self._events[event_name] = event
        event.set()


class LocalEventBarrier:
    """单机版同步屏障 (复刻 Pi-Agent 神经中枢, 3O 全栈元素 2)"""

    def __init__(self) -> None:
        self._events: dict[str, asyncio.Event] = {}

    def _get_event(self, name: str) -> asyncio.Event:
        if name not in self._events:
            self._events[name] = asyncio.Event()
        return self._events[name]

    async def wait_for(self, event_name: str, timeout: float = 10.0) -> bool:
        try:
            await asyncio.wait_for(self._get_event(event_name).wait(), timeout)
            return True
        except TimeoutError:
            return False

    def set_event(self, event_name: str) -> None:
        self._get_event(event_name).set()
