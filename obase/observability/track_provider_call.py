"""obase.observability.track_provider_call — Async context manager for provider call tracking.

Records calls_total, latency_ms, and status for any provider/operation pair.
Compatible with existing obase.observability infrastructure.

Example:
    async with track_provider_call("anthropic", "generate") as ctx:
        result = await some_api_call()
        ctx["status"] = "ok"
"""
from __future__ import annotations

import time
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator


# In-memory metrics store (per-process; replace with Prometheus in production)
_metrics: dict[str, dict[str, Any]] = {}


def _key(provider: str, operation: str) -> str:
    return f"{provider}:{operation}"


def get_metrics(provider: str | None = None, operation: str | None = None) -> dict:
    """Return recorded metrics, optionally filtered by provider/operation."""
    if provider and operation:
        return _metrics.get(_key(provider, operation), {})
    if provider:
        return {k: v for k, v in _metrics.items() if k.startswith(f"{provider}:")}
    return dict(_metrics)


def reset_metrics() -> None:
    """Clear all recorded metrics (useful in tests)."""
    _metrics.clear()


@asynccontextmanager
async def track_provider_call(
    provider: str,
    operation: str = "generate",
) -> AsyncGenerator[dict[str, Any], None]:
    """Async context manager: track a provider API call.

    Yields a mutable context dict so callers can set ``ctx["status"]``.
    Automatically records:
    - ``calls_total`` (int): incremented per call
    - ``latency_ms`` (float): wall-clock duration of the ``async with`` block
    - ``status`` (str): ``"ok"`` by default; override via ``ctx["status"]``
    - ``errors_total`` (int): incremented when ``status != "ok"``
    """
    k = _key(provider, operation)
    if k not in _metrics:
        _metrics[k] = {"calls_total": 0, "errors_total": 0, "latency_ms_total": 0.0}

    ctx: dict[str, Any] = {"status": "ok", "provider": provider, "operation": operation}
    start = time.monotonic()
    try:
        yield ctx
    except Exception:
        ctx["status"] = "error"
        raise
    finally:
        elapsed = (time.monotonic() - start) * 1000.0
        _metrics[k]["calls_total"] += 1
        _metrics[k]["latency_ms_total"] += elapsed
        if ctx.get("status") != "ok":
            _metrics[k]["errors_total"] += 1
        _metrics[k]["last_latency_ms"] = round(elapsed, 2)
        _metrics[k]["last_status"] = ctx.get("status", "ok")
