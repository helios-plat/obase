"""D1 — Intraday poll scheduler with exception isolation."""

from __future__ import annotations

import logging
from datetime import datetime, time
from typing import Any, Callable
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)


class IntradayPollScheduler:
    """Schedule handlers at specific intraday time windows with exception isolation."""

    def __init__(self, timezone: str = "Asia/Shanghai") -> None:
        self._tz = ZoneInfo(timezone)
        self._windows: list[dict[str, Any]] = []
        self._running = False
        self._status: dict[str, str] = {}

    def register_window(
        self, *, name: str, trigger_time: time, handler: Callable[[], Any]
    ) -> None:
        """Register a polling window."""
        self._windows.append({"name": name, "trigger_time": trigger_time, "handler": handler})
        self._status[name] = "registered"

    def start(self) -> None:
        """Start the scheduler (idempotent)."""
        self._running = True
        for w in self._windows:
            self._status[w["name"]] = "active"

    def stop(self) -> None:
        """Stop the scheduler (idempotent)."""
        self._running = False
        for w in self._windows:
            self._status[w["name"]] = "stopped"

    def tick(self, now: datetime | None = None) -> list[dict[str, Any]]:
        """Check and execute due windows. Exceptions are isolated per window."""
        if not self._running:
            return []

        current = (now or datetime.now(self._tz)).astimezone(self._tz)
        current_time = current.time()
        results: list[dict[str, Any]] = []

        for w in self._windows:
            trigger = w["trigger_time"]
            # Check if within 1-minute window of trigger
            if abs(
                (current_time.hour * 60 + current_time.minute)
                - (trigger.hour * 60 + trigger.minute)
            ) > 0:
                continue

            try:
                result = w["handler"]()
                self._status[w["name"]] = "success"
                results.append({"name": w["name"], "status": "success", "result": result})
            except Exception as e:
                logger.error(f"Handler {w['name']} failed: {e}")
                self._status[w["name"]] = f"error: {e}"
                results.append({"name": w["name"], "status": "error", "error": str(e)})

        return results

    def status(self) -> dict[str, str]:
        """Return current status of all windows."""
        return dict(self._status)

    @property
    def is_running(self) -> bool:
        return self._running
