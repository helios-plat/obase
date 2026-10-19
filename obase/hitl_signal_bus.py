"""obase.hitl_signal_bus — 基于 ContextVar / asyncio.Event 的打断信号总线.

设计:
- 全局 ContextVar 持有共享 HitlSignalBus 引用（子 Task 继承同一总线，
  对象内操作，无锁竞争）——与 decision_logger / cost_tracker 同构。
- 每笔审批 = 一个 asyncio.Event + 请求记录（request_id 键控）。
- interrupt 信号独立于审批流：置位后所有 wait 点可轮询 interrupted()。

Example:
    >>> bus = HitlSignalBus()
    >>> rid = bus.request_approval(scope="checkout", summary="订单 #123")
    >>> # 人工侧（另一 Task / 线程事件循环外也可同步调用）:
    >>> bus.approve(rid)
    >>> decision = await bus.wait_for_decision(rid, timeout=10.0)
    >>> decision["outcome"]
    'approved'
"""

from __future__ import annotations

import asyncio
import threading
import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Literal

__all__ = [
    "ApprovalRequest",
    "DecisionOutcome",
    "HitlSignalBus",
    "bind_bus",
    "get_bus",
    "request_approval",
    "wait_for_decision",
    "signal_interrupt",
    "interrupted",
]

DecisionOutcome = Literal["approved", "rejected", "timed_out", "cancelled"]


@dataclass
class ApprovalRequest:
    """单笔人工审批请求（bus 内部注册表条目）。"""

    request_id: str
    scope: str
    summary: str
    created_at: float = field(default_factory=time.time)
    decided_at: float | None = None
    outcome: DecisionOutcome | None = None
    note: str = ""
    event: asyncio.Event = field(default_factory=asyncio.Event)


class HitlSignalBus:
    """打断信号总线：审批请求 + 全局中断信号。

    线程安全说明：asyncio.Event.set() 从其他线程调用是安全的
    （loop.call_soon_threadsafe 语义由 asyncio 保证，Event.set 是原子的）。
    """

    def __init__(self) -> None:
        self._requests: dict[str, ApprovalRequest] = {}
        self._interrupt = asyncio.Event()
        self._interrupt_reason: str = ""
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # 审批流
    # ------------------------------------------------------------------

    def request_approval(
        self, *, scope: str, summary: str, request_id: str | None = None
    ) -> str:
        """创建审批请求，返回 request_id。"""
        rid = request_id or f"hitl-{uuid.uuid4().hex[:12]}"
        req = ApprovalRequest(request_id=rid, scope=scope, summary=summary)
        with self._lock:
            self._requests[rid] = req
        return rid

    def _decide(self, request_id: str, outcome: DecisionOutcome, note: str = "") -> bool:
        with self._lock:
            req = self._requests.get(request_id)
            if req is None:
                return False
            if req.outcome is not None:
                return False  # 已决，幂等
            req.outcome = outcome
            req.decided_at = time.time()
            req.note = note
        req.event.set()
        return True

    def approve(self, request_id: str, *, note: str = "") -> bool:
        """人工批准（幂等；未知/已决请求返回 False）。"""
        return self._decide(request_id, "approved", note)

    def reject(self, request_id: str, *, note: str = "") -> bool:
        """人工拒绝（幂等）。"""
        return self._decide(request_id, "rejected", note)

    def cancel(self, request_id: str, *, note: str = "") -> bool:
        """取消请求（幂等）。"""
        return self._decide(request_id, "cancelled", note)

    async def wait_for_decision(
        self, request_id: str, *, timeout: float = 60.0
    ) -> dict[str, Any]:
        """等待人工决策，返回标准化结果 dict。

        超时返回 outcome="timed_out"（请求保持待决，可继续等）。
        """
        with self._lock:
            req = self._requests.get(request_id)
        if req is None:
            return {"request_id": request_id, "outcome": "unknown", "note": "request not found"}
        if req.outcome is not None:
            return self._decision_dict(req)

        try:
            await asyncio.wait_for(req.event.wait(), timeout=timeout)
        except TimeoutError:
            return {
                "request_id": request_id,
                "outcome": "timed_out",
                "note": req.note,
                "scope": req.scope,
                "summary": req.summary,
            }
        return self._decision_dict(req)

    def get_request(self, request_id: str) -> dict[str, Any] | None:
        with self._lock:
            req = self._requests.get(request_id)
        if req is None:
            return None
        return self._decision_dict(req)

    def list_pending(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                self._decision_dict(r)
                for r in self._requests.values()
                if r.outcome is None
            ]

    @staticmethod
    def _decision_dict(req: ApprovalRequest) -> dict[str, Any]:
        return {
            "request_id": req.request_id,
            "scope": req.scope,
            "summary": req.summary,
            "outcome": req.outcome or "pending",
            "note": req.note,
            "created_at": req.created_at,
            "decided_at": req.decided_at,
        }

    # ------------------------------------------------------------------
    # 中断信号
    # ------------------------------------------------------------------

    def signal_interrupt(self, *, reason: str = "") -> None:
        """发出全局打断信号（置位后一直保持，直到 reset）。"""
        self._interrupt_reason = reason
        self._interrupt.set()

    def reset_interrupt(self) -> None:
        """清除打断信号。"""
        self._interrupt.clear()
        self._interrupt_reason = ""

    @property
    def interrupted(self) -> bool:
        return self._interrupt.is_set()

    @property
    def interrupt_reason(self) -> str:
        return self._interrupt_reason

    def health(self) -> dict[str, Any]:
        return {
            "status": "healthy",
            "pending_approvals": len(self.list_pending()),
            "interrupted": self.interrupted,
        }


# ---------------------------------------------------------------------------
# ContextVar 全局绑定（子 Task 继承同一总线引用）
# ---------------------------------------------------------------------------

_current_bus: ContextVar[HitlSignalBus | None] = ContextVar("hitl_signal_bus", default=None)
_local = threading.local()


def get_bus() -> HitlSignalBus | None:
    """取当前 Context 绑定的总线；无则 None。"""
    bus = _current_bus.get()
    if bus is not None:
        return bus
    return getattr(_local, "bus", None)


def bind_bus(bus: HitlSignalBus | None) -> None:
    """把总线绑定到当前 Context（子 Task 自动继承）。"""
    _current_bus.set(bus)
    _local.bus = bus


def request_approval(*, scope: str, summary: str, bus: HitlSignalBus | None = None) -> str:
    """便捷入口：向当前 Context 总线发起审批请求；无总线抛 RuntimeError。"""
    bus = bus or get_bus()
    if bus is None:
        raise RuntimeError(
            "hitl_signal_bus: no bus bound — pass bus=... or bind_bus() first"
        )
    return bus.request_approval(scope=scope, summary=summary)


async def wait_for_decision(
    request_id: str, *, bus: HitlSignalBus | None = None, timeout: float = 60.0
) -> dict[str, Any]:
    """便捷入口：等待审批决策。"""
    bus = bus or get_bus()
    if bus is None:
        raise RuntimeError(
            "hitl_signal_bus: no bus bound — pass bus=... or bind_bus() first"
        )
    return await bus.wait_for_decision(request_id, timeout=timeout)


def signal_interrupt(*, reason: str = "", bus: HitlSignalBus | None = None) -> None:
    """便捷入口：发出打断信号。"""
    bus = bus or get_bus()
    if bus is not None:
        bus.signal_interrupt(reason=reason)


def interrupted(*, bus: HitlSignalBus | None = None) -> bool:
    """便捷入口：当前是否被打断。"""
    bus = bus or get_bus()
    return bus.interrupted if bus is not None else False
