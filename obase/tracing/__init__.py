"""tracing — Distributed tracing utilities with ContextVar-based trace propagation."""
from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from typing import Any, AsyncGenerator, Generator

# ContextVar: isolated per asyncio Task — does NOT leak across concurrent tasks
_current_trace_id: ContextVar[str | None] = ContextVar("trace_id", default=None)


class TracingError(Exception):
    """Base error for tracing."""


class Span:
    """A single trace span."""

    def __init__(self, name: str, trace_id: str | None = None) -> None:
        self.name = name
        self.trace_id = trace_id or uuid.uuid4().hex[:16]
        self.span_id = uuid.uuid4().hex[:16]
        self.start_time = time.time()
        self.end_time: float | None = None
        self.attributes: dict[str, Any] = {}

    def end(self) -> None:
        self.end_time = time.time()

    @property
    def duration_ms(self) -> float:
        end = self.end_time or time.time()
        return round((end - self.start_time) * 1000, 2)

    def to_dict(self) -> dict:
        return {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "name": self.name,
            "duration_ms": self.duration_ms,
            "attributes": self.attributes,
        }


class Tracer:
    """Simple in-process tracer."""

    def __init__(self) -> None:
        self._spans: list[Span] = []

    def start_span(self, name: str, *, trace_id: str | None = None) -> Span:
        s = Span(name, trace_id)
        self._spans.append(s)
        return s

    @property
    def spans(self) -> list[Span]:
        return self._spans


# ---------------------------------------------------------------------------
# ContextVar-based API — trace_id propagates automatically within a Task
# ---------------------------------------------------------------------------

@contextmanager
def start_trace(trace_id: str | None = None) -> Generator[str, None, None]:
    """Set a trace_id for the current scope (sync context manager).

    Example:
        with start_trace() as tid:
            assert current_trace_id() == tid
    """
    tid = trace_id or uuid.uuid4().hex[:16]
    token = _current_trace_id.set(tid)
    try:
        yield tid
    finally:
        _current_trace_id.reset(token)


def current_trace_id() -> str | None:
    """Return the trace_id for the current context (None if not set)."""
    return _current_trace_id.get()


@asynccontextmanager
async def span(name: str, *, trace_id: str | None = None) -> AsyncGenerator[Span, None]:
    """Async context manager: create a Span within the current trace.

    Example:
        async with span("my-op") as s:
            s.attributes["key"] = "value"
    """
    tid = trace_id or current_trace_id() or uuid.uuid4().hex[:16]
    s = Span(name, trace_id=tid)
    try:
        yield s
    finally:
        s.end()
