"""obase.observability — Observability utilities subpackage."""

from __future__ import annotations

from obase.observability.tracer import Span, Tracer, get_tracer

__all__ = [
    "Span",
    "Tracer",
    "get_tracer",
]
