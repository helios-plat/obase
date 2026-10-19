"""obase.decision_logger — 基于 ContextVar 的全局决策轨迹记录器 (SPEC §5.6 C2).

设计:
- 全局唯一 ContextVar 持有共享的 DecisionTrail 可变对象引用；
  子 Task 创建时继承父 Context 的引用，各 Task 只 `.get()` + 对象内累加，
  天然并发安全（无跨 Task 泄漏，也无锁竞争）。
- 线程场景回退 threading.local（同一线程共享同一 trail）。
- 记录内容禁止真实 PII —— 服务层必须先经 obase.pseudo_anonymizer 伪名化。

Example:
    >>> begin_trail(run_id="run-1")
    >>> record_decision(event="llm_call", model="claude", cost_usd=0.01)
    >>> trail = end_trail()
    >>> len(trail.steps)
    1
"""

from __future__ import annotations

import threading
import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "DecisionTrail",
    "begin_trail",
    "end_trail",
    "get_trail",
    "record_decision",
]


@dataclass
class DecisionTrail:
    """决策轨迹容器：对象内累加，引用由 ContextVar 共享。"""

    run_id: str
    started_at: float = field(default_factory=time.time)
    steps: list[dict[str, Any]] = field(default_factory=list)

    def record(self, *, event: str, **kwargs: Any) -> None:
        """追加一条决策记录（线程/Task 安全：仅对象内 list.append）。"""
        self.steps.append(
            {
                "step_no": len(self.steps) + 1,
                "ts": time.time(),
                "event": event,
                **kwargs,
            }
        )

    def snapshot(self) -> dict[str, Any]:
        """导出不可变快照（供落盘 / 审计 / 上报）。"""
        return {
            "run_id": self.run_id,
            "started_at": self.started_at,
            "steps": list(self.steps),
        }

    def __len__(self) -> int:
        return len(self.steps)


_current_trail: ContextVar[DecisionTrail | None] = ContextVar(
    "decision_trail", default=None
)
_local = threading.local()


def get_trail() -> DecisionTrail | None:
    """取当前 Context / 线程的 decision_trail；无则 None。"""
    trail = _current_trail.get()
    if trail is not None:
        return trail
    return getattr(_local, "trail", None)


def begin_trail(run_id: str | None = None) -> DecisionTrail:
    """开启（或覆盖）当前 Context 的 decision_trail。

    返回新 trail。调用方应持有返回值以便后续 end_trail 配对。
    """
    trail = DecisionTrail(run_id=run_id or uuid.uuid4().hex[:12])
    _current_trail.set(trail)
    _local.trail = trail
    return trail


def end_trail() -> DecisionTrail | None:
    """结束当前 Context 的 trail：返回其快照前的最终对象，并清空绑定。"""
    trail = _current_trail.get()
    _current_trail.set(None)
    _local.trail = None
    return trail


def record_decision(event: str, **kwargs: Any) -> None:
    """向当前 Context 的 trail 追加记录；无绑定 trail 时静默跳过。"""
    trail = get_trail()
    if trail is not None:
        trail.record(event=event, **kwargs)
