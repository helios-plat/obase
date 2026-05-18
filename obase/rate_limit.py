from __future__ import annotations

import asyncio
import time
from collections import deque
from pathlib import Path
from typing import Any

import structlog
import yaml

from obase.exceptions import OBaseError, RateLimitExceeded

log = structlog.get_logger()


class RateLimiter:
    """Async sliding-window rate limiter."""

    def __init__(self, rate: int, period_seconds: float) -> None:
        if rate <= 0:
            raise ValueError("rate must be > 0")
        if period_seconds <= 0:
            raise ValueError("period_seconds must be > 0")
        self._rate = rate
        self._period = period_seconds
        self._timestamps: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self, *, timeout: float | None = None) -> None:
        """Wait until a slot is available. Raises RateLimitExceeded if timeout elapses."""
        deadline = time.monotonic() + timeout if timeout is not None else None
        async with self._lock:
            while True:
                now = time.monotonic()
                cutoff = now - self._period
                while self._timestamps and self._timestamps[0] <= cutoff:
                    self._timestamps.popleft()
                if len(self._timestamps) < self._rate:
                    self._timestamps.append(now)
                    return
                sleep_for = self._timestamps[0] + self._period - now + 1e-4
                if deadline is not None and time.monotonic() + sleep_for > deadline:
                    raise RateLimitExceeded(
                        f"Rate limit {self._rate}/{self._period}s exceeded "
                        f"and timeout {timeout}s would elapse"
                    )
                await asyncio.sleep(sleep_for)

    @property
    def rate(self) -> int:
        return self._rate

    @property
    def period_seconds(self) -> float:
        return self._period


class RateLimitRegistry:
    """Class-level registry of named RateLimiter instances."""

    _limiters: dict[str, RateLimiter] = {}

    @classmethod
    def register(cls, name: str, rate: int, period_seconds: float) -> RateLimiter:
        limiter = RateLimiter(rate=rate, period_seconds=period_seconds)
        cls._limiters[name] = limiter
        log.info("obase.rate_limit.registered", name=name, rate=rate, period=period_seconds)
        return limiter

    @classmethod
    def get(cls, name: str) -> RateLimiter:
        if name not in cls._limiters:
            raise OBaseError(f"Rate limiter not found: {name!r}")
        return cls._limiters[name]

    @classmethod
    def has(cls, name: str) -> bool:
        return name in cls._limiters

    @classmethod
    def load_from_yaml(cls, path: Path) -> None:
        with path.open(encoding="utf-8") as fh:
            raw: Any = yaml.safe_load(fh)
        for entry in raw or []:
            cls.register(
                name=entry["name"],
                rate=int(entry["rate"]),
                period_seconds=float(entry["period_seconds"]),
            )

    @classmethod
    def clear(cls) -> None:
        """Remove all registered limiters (useful in tests)."""
        cls._limiters.clear()
