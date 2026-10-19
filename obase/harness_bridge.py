"""obase.harness_bridge — Agent 运行架桥接适配器.

把 Agent harness（循环引擎/工具执行器）桥接到外部控制器：事件注册、事件
发射、状态上报、心跳、指令下发。进程内控制面总线，纯 stdlib。

Example:
    >>> bridge = HarnessBridge(name="steer-agent")
    >>> bridge.register_handler("on_task_done", my_callback)
    >>> await bridge.emit("task_done", {"task_id": "t1"})
    >>> bridge.set_status("running")
    >>> await bridge.send_command("pause")
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

__all__ = ["HarnessBridge", "HarnessBridgeError"]

Handler = Callable[[dict[str, Any]], Awaitable[None] | None]


class HarnessBridgeError(RuntimeError):
    """桥接错误。"""


@dataclass
class _EventLog:
    ts: float
    event: str
    payload: dict[str, Any]


class HarnessBridge:
    """Agent harness 桥接器：事件 + 状态 + 心跳 + 指令。"""

    def __init__(self, name: str) -> None:
        if not name:
            raise ValueError("harness_bridge: name must not be empty")
        self.name = name
        self._handlers: dict[str, list[Handler]] = {}
        self._status: str = "idle"
        self._status_detail: dict[str, Any] = {}
        self._commands: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._events: list[_EventLog] = []
        self._max_events = 200
        self._lock = asyncio.Lock()
        self._started_at = time.time()

    # ------------------------------------------------------------------
    # 事件
    # ------------------------------------------------------------------

    def register_handler(self, event: str, handler: Handler) -> None:
        """注册事件处理器（同事件可多 handler，按注册序调用）。"""
        self._handlers.setdefault(event, []).append(handler)

    def unregister_handler(self, event: str, handler: Handler) -> bool:
        handlers = self._handlers.get(event, [])
        if handler in handlers:
            handlers.remove(handler)
            return True
        return False

    async def emit(self, event: str, payload: dict[str, Any] | None = None) -> int:
        """发射事件：记录 + 扇出调用处理器。返回处理器调用数。"""
        payload = payload or {}
        async with self._lock:
            self._events.append(_EventLog(ts=time.time(), event=event, payload=payload))
            if len(self._events) > self._max_events:
                self._events = self._events[-self._max_events :]
            handlers = list(self._handlers.get(event, []))
        for handler in handlers:
            result = handler(payload)
            if result is not None:
                await result
        return len(handlers)

    def event_log(self, *, limit: int = 50) -> list[dict[str, Any]]:
        """最近事件日志（时间倒序）。"""
        entries = [
            {"ts": e.ts, "event": e.event, "payload": e.payload} for e in self._events
        ]
        return entries[-limit:][::-1]

    # ------------------------------------------------------------------
    # 状态
    # ------------------------------------------------------------------

    def set_status(self, status: str, **detail: Any) -> None:
        self._status = status
        self._status_detail = detail

    @property
    def status(self) -> str:
        return self._status

    def status_report(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self._status,
            "detail": dict(self._status_detail),
            "uptime_s": round(time.time() - self._started_at, 2),
            "handlers": {k: len(v) for k, v in self._handlers.items()},
        }

    # ------------------------------------------------------------------
    # 指令（控制器 → harness）
    # ------------------------------------------------------------------

    async def send_command(self, command: str, payload: dict[str, Any] | None = None) -> None:
        """下发指令（由 harness 侧 consume_command 消费）。"""
        await self._commands.put({"command": command, "payload": payload or {}, "ts": time.time()})

    async def consume_command(self, *, timeout: float | None = None) -> dict[str, Any] | None:
        """harness 侧取指令（超时返回 None）。"""
        try:
            if timeout is None:
                return await self._commands.get()
            return await asyncio.wait_for(self._commands.get(), timeout=timeout)
        except TimeoutError:
            return None

    # ------------------------------------------------------------------
    # 心跳
    # ------------------------------------------------------------------

    def heartbeat(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self._status,
            "ts": time.time(),
            "pending_commands": self._commands.qsize(),
        }

    def health(self) -> dict[str, Any]:
        return {
            "status": "healthy",
            "details": self.status_report(),
        }
