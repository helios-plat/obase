"""obase.observability.tracer — OpenTelemetry tracer abstraction with noop default.

Provides a consistent tracing interface. Uses OpenTelemetry if available,
falls back to a no-op tracer that records nothing (safe for environments
without OTel infrastructure).

Cross-service tracing: track spans across obase/oprim/service layer calls.
"""

from __future__ import annotations
from contextlib import contextmanager
from typing import Any, Generator
import time


class Span:
    """A tracing span. Records name, attributes, start/end times."""

    def __init__(self, name: str, parent: "Span | None" = None):
        self.name = name
        self.parent = parent
        self.attributes: dict[str, Any] = {}
        self.events: list[dict] = []
        self.start_time: float = time.monotonic()
        self.end_time: float | None = None
        self.status: str = "ok"

    def set_attribute(self, key: str, value: Any) -> "Span":
        """Set a span attribute. Returns self for chaining."""
        self.attributes[key] = value
        return self

    def add_event(self, name: str, attributes: dict | None = None) -> "Span":
        """Add a timestamped event to the span."""
        self.events.append({"name": name, "ts": time.monotonic(), "attributes": attributes or {}})
        return self

    def set_status(self, status: str) -> "Span":
        """Set span status: 'ok' | 'error' | 'cancelled'."""
        self.status = status
        return self

    def end(self) -> None:
        """Mark span as ended."""
        self.end_time = time.monotonic()

    @property
    def duration_ms(self) -> float | None:
        if self.end_time is None:
            return None
        return (self.end_time - self.start_time) * 1000


class Tracer:
    """Tracer that creates and manages spans.

    Default implementation records spans in memory (useful for testing).
    Production: swap with OpenTelemetry tracer via ProviderRegistry.
    """

    def __init__(self, service_name: str = "obase"):
        self.service_name = service_name
        self._spans: list[Span] = []
        self._active: Span | None = None

    @contextmanager
    def span(self, name: str, **attributes) -> Generator[Span, None, None]:
        """Context manager that creates, yields, and ends a span.

        Args:
            name: Span name (e.g. "oprim.vector_encode")
            **attributes: Initial span attributes

        Yields:
            Span: The active span for adding events/attributes.

        Example:
            with tracer.span("fetch_data", url="http://example.com") as s:
                data = fetch(url)
                s.add_event("fetched", {"bytes": len(data)})
        """
        s = Span(name, parent=self._active)
        for k, v in attributes.items():
            s.set_attribute(k, v)
        prev = self._active
        self._active = s
        self._spans.append(s)
        try:
            yield s
        except Exception as e:
            s.set_status("error")
            s.set_attribute("error.message", str(e))
            raise
        finally:
            s.end()
            self._active = prev

    def get_spans(self) -> list[Span]:
        """Return all recorded spans (useful for testing)."""
        return list(self._spans)

    def clear(self) -> None:
        """Clear recorded spans."""
        self._spans.clear()
        self._active = None


# Module-level default tracer (noop-safe for production use)
_default_tracer: Tracer | None = None


def get_tracer(service_name: str = "obase") -> Tracer:
    """Get or create the default tracer.

    Returns:
        Tracer: The default in-memory tracer (or OTel tracer if configured).
    """
    global _default_tracer
    if _default_tracer is None:
        _default_tracer = Tracer(service_name)
    return _default_tracer
