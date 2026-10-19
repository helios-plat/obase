"""obase.zeromq_bus — ZeroMQ 消息总线适配器.

基于 pyzmq 的 pub/sub + req/rep 双模式总线；pyzmq 为可选依赖（惰性加载），
未安装时提供明确错误。提供 Protocol 形态供上层注入。

Example:
    >>> bus = ZeroMQBus()
    >>> await bus.start()
    >>> await bus.publish("events", {"k": 1})
    >>> await bus.close()
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

__all__ = ["ZeroMQBus", "ZeroMQBusError", "BusHandle"]

Handler = Callable[[dict[str, Any]], Awaitable[None] | None]


class ZeroMQBusError(RuntimeError):
    """ZeroMQ 总线错误（含 pyzmq 未安装）。"""


@runtime_checkable
class BusHandle(Protocol):
    """消息总线协议（上层注入面）。"""

    async def publish(self, topic: str, payload: dict[str, Any]) -> None: ...
    async def subscribe(self, topic: str, handler: Handler) -> None: ...


@dataclass
class _Subscription:
    topic: str
    handler: Handler


class ZeroMQBus:
    """ZeroMQ 总线：publish/subscribe（PUB/SUB）+ request/reply（REQ/REP）。

    - pyzmq 惰性加载：start() 时才 import，未安装抛 ZeroMQBusError。
    - 无 pyzmq 环境下仍可作内存总线使用（inproc 语义退化）。
    """

    def __init__(
        self,
        *,
        pub_addr: str = "tcp://127.0.0.1:5557",
        rep_addr: str = "tcp://127.0.0.1:5558",
        memory_mode: bool = False,
    ) -> None:
        self.pub_addr = pub_addr
        self.rep_addr = rep_addr
        self.memory_mode = memory_mode
        self._ctx: Any = None
        self._pub: Any = None
        self._sub: Any = None
        self._rep: Any = None
        self._running = False
        self._subs: list[_Subscription] = []
        self._memory: list[tuple[str, dict[str, Any]]] = []

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    async def start(self) -> None:
        if self._running:
            return
        if self.memory_mode:
            self._running = True
            return
        try:
            import zmq  # type: ignore[import-untyped]
            import zmq.asyncio  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ZeroMQBusError(
                "pyzmq is not installed — pip install pyzmq, or use memory_mode=True"
            ) from exc
        self._ctx = zmq.asyncio.Context()
        self._pub = self._ctx.socket(zmq.PUB)
        self._pub.bind(self.pub_addr)
        self._sub = self._ctx.socket(zmq.SUB)
        self._sub.setsockopt(zmq.SUBSCRIBE, b"")
        self._sub.connect(self.pub_addr)
        self._rep = self._ctx.socket(zmq.REP)
        self._rep.bind(self.rep_addr)
        self._running = True

    async def close(self) -> None:
        if not self._running:
            return
        for sock in (self._pub, self._sub, self._rep):
            if sock is not None:
                try:
                    sock.close()
                except Exception:  # pragma: no cover
                    pass
        if self._ctx is not None:
            try:
                self._ctx.term()
            except Exception:  # pragma: no cover
                pass
        self._running = False
        self._ctx = self._pub = self._sub = self._rep = None

    # ------------------------------------------------------------------
    # pub/sub
    # ------------------------------------------------------------------

    async def publish(self, topic: str, payload: dict[str, Any]) -> None:
        if not self._running:
            await self.start()
        msg = json.dumps(payload, ensure_ascii=False, default=str)
        if self._pub is not None:
            await self._pub.send_multipart([topic.encode(), msg.encode()])
        else:
            self._memory.append((topic, payload))
            for sub in list(self._subs):
                if sub.topic in ("*", topic):
                    result = sub.handler(payload)
                    if result is not None:
                        await result

    async def subscribe(self, topic: str, handler: Handler) -> None:
        self._subs.append(_Subscription(topic=topic, handler=handler))
        if self._sub is not None:
            self._sub.setsockopt_string(  # type: ignore[attr-defined]
                __import__("zmq", fromlist=["SUBSCRIBE"]).SUBSCRIBE, topic
            )

    # ------------------------------------------------------------------
    # req/rep
    # ------------------------------------------------------------------

    async def request(self, payload: dict[str, Any], *, timeout: float = 5.0) -> dict[str, Any]:
        """发送请求并等待响应（memory_mode 下返回 echo）。"""
        if not self._running:
            await self.start()
        if self._rep is None:
            return {"ok": True, "echo": payload}
        await self._rep.send_json(payload)
        reply = await asyncio.wait_for(self._rep.recv_json(), timeout=timeout)
        return reply

    async def reply_loop(self, handler: Callable[[dict[str, Any]], dict[str, Any]]) -> None:
        """REP 侧响应循环（异步任务中运行）。"""
        if self._rep is None:
            return
        while self._running:
            request = await self._rep.recv_json()
            response = handler(request)
            if asyncio.iscoroutine(response):
                response = await response
            await self._rep.send_json(response)

    @property
    def is_running(self) -> bool:
        return self._running

    def health(self) -> dict[str, Any]:
        return {
            "status": "healthy" if self._running else "idle",
            "memory_mode": self.memory_mode,
            "subscriptions": len(self._subs),
            "memory_messages": len(self._memory),
        }

    async def __aenter__(self) -> ZeroMQBus:
        await self.start()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()
