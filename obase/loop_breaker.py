"""obase.loop_breaker — per-task agent-loop counters via ContextVar.

Distinct from obase.circuit_breaker (service CLOSED/OPEN/HALF_OPEN).
This tracker is request-scoped so concurrent loops do not share hashes.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass, field


@dataclass
class BreakerState:
    consecutive_errors: int = 0
    trajectory_hashes: list[str] = field(default_factory=list)
    total_steps: int = 0


_current_breaker: ContextVar[BreakerState | None] = ContextVar("loop_breaker", default=None)


def get_breaker() -> BreakerState | None:
    return _current_breaker.get()


def init_breaker(state: BreakerState | None = None) -> Token[BreakerState | None]:
    return _current_breaker.set(state if state is not None else BreakerState())


def reset_breaker(token: Token[BreakerState | None]) -> None:
    _current_breaker.reset(token)
