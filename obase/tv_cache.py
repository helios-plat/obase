"""Provider-agnostic bounded TTL cache and request pacing primitives."""
from __future__ import annotations
from collections import OrderedDict
from dataclasses import dataclass
import threading
import time
from typing import Any, Callable

@dataclass(frozen=True)
class _CacheEntry:
    value: Any
    fresh_until: float
    stale_until: float

class TTLCache:
    """Thread-safe LRU cache. Stale values are returned only with explicit opt-in."""
    def __init__(self, max_entries: int = 512, clock: Callable[[], float] = time.monotonic) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be >= 1")
        self._max_entries, self._clock = max_entries, clock
        self._entries: OrderedDict[str, _CacheEntry] = OrderedDict()
        self._lock = threading.RLock()

    def lookup(self, key: str, *, allow_stale: bool = False) -> tuple[bool, Any, bool]:
        now = self._clock()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return False, None, False
            if now <= entry.fresh_until:
                self._entries.move_to_end(key)
                return True, entry.value, False
            if now <= entry.stale_until:
                if allow_stale:
                    self._entries.move_to_end(key)
                    return True, entry.value, True
                return False, None, False
            self._entries.pop(key, None)
            return False, None, False

    def store(self, key: str, value: Any, ttl_seconds: float, stale_seconds: float = 0) -> None:
        if ttl_seconds < 0 or stale_seconds < 0:
            raise ValueError("ttl_seconds and stale_seconds must be >= 0")
        now = self._clock()
        with self._lock:
            self._entries[key] = _CacheEntry(value, now + ttl_seconds, now + ttl_seconds + stale_seconds)
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

class SlidingWindowRateGate:
    """Thread-safe minimum inter-request interval gate with injectable clock/sleeper."""
    def __init__(self, interval_seconds: float = 0.15, clock: Callable[[], float] = time.monotonic,
                 sleeper: Callable[[float], None] = time.sleep) -> None:
        if interval_seconds < 0:
            raise ValueError("interval_seconds must be >= 0")
        self._interval, self._clock, self._sleep = interval_seconds, clock, sleeper
        self._last_at: float | None = None
        self._lock = threading.Lock()

    def acquire(self) -> None:
        with self._lock:
            now = self._clock()
            delay = 0 if self._last_at is None else max(0.0, self._last_at + self._interval - now)
            if delay:
                self._sleep(delay)
                now = self._clock()
            self._last_at = now
