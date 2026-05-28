"""tracing — Distributed tracing utilities."""
from __future__ import annotations
import time
import uuid
from typing import Any

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
        return {"trace_id": self.trace_id, "span_id": self.span_id, "name": self.name, "duration_ms": self.duration_ms, "attributes": self.attributes}

class Tracer:
    """Simple in-process tracer.

    Example:
        >>> t = Tracer()
        >>> span = t.start_span("compute")
        >>> span.end()
    """
    def __init__(self) -> None:
        self._spans: list[Span] = []

    def start_span(self, name: str, *, trace_id: str | None = None) -> Span:
        span = Span(name, trace_id)
        self._spans.append(span)
        return span

    @property
    def spans(self) -> list[Span]:
        return self._spans
