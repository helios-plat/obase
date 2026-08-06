"""obase.debounced_memory_queue — DeerFlow-style async debounced write queue.

Cross-session memory writes are queued with a configurable debounce window.
Multiple rapid updates within the window are coalesced into a single write,
ensuring the main agent reasoning thread is never blocked by I/O.

3O element: ``obase.debounced_memory_queue`` (``DebouncedMemoryQueue`` class).
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any


class DebouncedMemoryQueue:
    """Async debounced write queue for cross-session memory persistence.

    Usage::

        queue = DebouncedMemoryQueue(debounce_s=5.0)
        queue.enqueue("user_prefs", {"theme": "dark", "language": "zh"})
        # after 5s of silence, the consolidated state is flushed to disk
    """

    def __init__(self, base_dir: str | Path | None = None, debounce_s: float = 5.0) -> None:
        self._base = Path(base_dir) if base_dir else Path.home() / ".veya" / "memory_queue"
        self._base.mkdir(parents=True, exist_ok=True)
        self._debounce_s = debounce_s
        self._pending: dict[str, dict[str, Any]] = {}
        self._timers: dict[str, asyncio.Task[Any]] = {}
        self._lock = asyncio.Lock()

    # -- enqueue (non-blocking) ----------------------------------------------
    def enqueue(self, key: str, updates: dict[str, Any], immediate: bool = False) -> None:
        """Queue an update.  ``immediate=True`` flushes after a zero debounce."""
        self._pending[key] = _merge(self._pending.get(key, {}), updates)
        if immediate:
            self._flush_one(key)
            return
        # reset debounce timer
        if key in self._timers:
            self._timers[key].cancel()
        self._timers[key] = asyncio.ensure_future(self._debounced_flush(key))

    async def _debounced_flush(self, key: str) -> None:
        await asyncio.sleep(self._debounce_s)
        await self._flush_one(key)

    async def _flush_one(self, key: str) -> None:
        data = self._pending.pop(key, None)
        if data is None:
            return
        path = self._base / f"{_safe(key)}.json"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    # -- load ----------------------------------------------------------------
    def load(self, key: str) -> dict[str, Any]:
        path = self._base / f"{_safe(key)}.json"
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    # -- lifecycle -----------------------------------------------------------
    async def flush_all(self, timeout: float = 5.0) -> int:
        """Flush all pending keys (called on shutdown)."""
        async with self._lock:
            keys = list(self._pending)
            for k in keys:
                if k in self._timers:
                    self._timers[k].cancel()
                await self._flush_one(k)
        return len(keys)

    def pending_count(self) -> int:
        return len(self._pending)


def _safe(key: str) -> str:
    return key.replace("/", "_").replace(":", "_").replace("\\", "_")


def _merge(base: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    out.update(updates)
    return out
