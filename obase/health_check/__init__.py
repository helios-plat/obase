"""health_check — Service health check utilities."""
from __future__ import annotations
import time
from typing import Any, Callable

class HealthCheckError(Exception):
    """Base error for health_check."""

class HealthChecker:
    """Run health checks against registered probes.

    Example:
        >>> hc = HealthChecker()
        >>> hc.register("db", lambda: True)
        >>> hc.run_all()
        {'db': {'healthy': True, ...}}
    """
    def __init__(self) -> None:
        self._probes: dict[str, Callable[[], bool]] = {}

    def register(self, name: str, probe: Callable[[], bool]) -> None:
        self._probes[name] = probe

    def run_all(self) -> dict[str, dict]:
        results = {}
        for name, probe in self._probes.items():
            start = time.time()
            try:
                ok = probe()
                results[name] = {"healthy": ok, "latency_ms": round((time.time() - start) * 1000, 2)}
            except Exception as e:
                results[name] = {"healthy": False, "error": str(e), "latency_ms": round((time.time() - start) * 1000, 2)}
        return results
