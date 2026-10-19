"""obase.event_bus — synchronous in-process event bus for 3O engines.

3O layer: obase (cross-cutting infrastructure resource).
Engines (omodul/oskill) publish structured events; the host application
(Veya) subscribes and bridges them to its own notification channels
(e.g. SSE / fire_step). Keeps main-library engines free of host deps.
"""

from __future__ import annotations

import logging
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

_log = logging.getLogger(__name__)


@dataclass
class Event:
    """A single structured event."""

    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


class EventBus:
    """Synchronous pub/sub bus: publish() fans out to all subscribers.

    Handlers are called synchronously in publish order and must not block
    (they typically enqueue to an async queue or forward to a notifier).
    """

    def __init__(self) -> None:
        self._subs: dict[str, list[Callable[[Event], None]]] = {}
        self._wildcards: list[Callable[[Event], None]] = []
        self._lock = threading.RLock()
        self._history: list[Event] = []
        self._max_history = 200

    # ── 订阅 ─────────────────────────────────────────────────────────
    def subscribe(self, event_type: str, handler: Callable[[Event], None]) -> None:
        """Subscribe to a specific event type ('*' matches everything)."""
        with self._lock:
            if event_type == "*":
                self._wildcards.append(handler)
            else:
                self._subs.setdefault(event_type, []).append(handler)

    def unsubscribe(self, event_type: str, handler: Callable[[Event], None]) -> None:
        with self._lock:
            if event_type == "*":
                self._wildcards = [h for h in self._wildcards if h != handler]
            else:
                self._subs[event_type] = [h for h in self._subs.get(event_type, []) if h != handler]

    # ── 发布 ─────────────────────────────────────────────────────────
    def publish(self, event_type: str, payload: dict[str, Any] | None = None) -> Event:
        """Publish an event to all matching subscribers (sync, ordered)."""
        event = Event(type=event_type, payload=dict(payload or {}))
        with self._lock:
            handlers = list(self._subs.get(event_type, [])) + list(self._wildcards)
            self._history.append(event)
            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history :]
        for handler in handlers:
            try:
                handler(event)
            except Exception:  # noqa: BLE001 — one bad subscriber must not break the bus
                _log.exception("event_bus: subscriber failed for %s", event_type)
        return event

    # ── 查询 ─────────────────────────────────────────────────────────
    def history(self, event_type: str | None = None, limit: int = 20) -> list[Event]:
        events = [e for e in self._history if event_type is None or e.type == event_type]
        return events[-limit:]

    def clear_history(self) -> None:
        with self._lock:
            self._history.clear()


# 模块级默认总线(主库引擎共享; 宿主可替换)
default_event_bus = EventBus()
