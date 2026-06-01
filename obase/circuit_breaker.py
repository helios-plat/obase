from __future__ import annotations

import inspect
import threading
import time
from collections.abc import Callable
from typing import Any


class CircuitBreakerOpenError(Exception):
    """Raised when circuit is OPEN and call is rejected."""


class CircuitBreaker:
    """Thread-safe circuit breaker with CLOSED/OPEN/HALF_OPEN states.

    States:
        CLOSED: Normal operation. Failures increment counter.
        OPEN: Calls rejected immediately after failure_threshold exceeded.
        HALF_OPEN: Recovery probe — one call allowed. Success → CLOSED; failure → OPEN.

    Example:
        >>> cb = CircuitBreaker(failure_threshold=3, recovery_timeout=30.0)
        >>> await cb.call(some_async_func, arg1, kwarg=val)
    """

    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 30.0) -> None:
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._failure_count = 0
        self._state = "closed"
        self._opened_at: float | None = None
        self._lock = threading.Lock()

    @property
    def state(self) -> str:
        with self._lock:
            return self._get_state()

    @property
    def failure_count(self) -> int:
        with self._lock:
            return self._failure_count

    def _get_state(self) -> str:
        # Called under lock
        if self._state == "open":
            if (
                self._opened_at is not None
                and (time.monotonic() - self._opened_at) >= self._recovery_timeout
            ):
                self._state = "half_open"
        return self._state

    def reset(self) -> None:
        with self._lock:
            self._state = "closed"
            self._failure_count = 0
            self._opened_at = None

    async def call(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Execute func through the circuit breaker.

        Raises:
            CircuitBreakerOpenError: If state is OPEN
            Exception: Whatever func raises (also increments failure count)
        """
        with self._lock:
            current_state = self._get_state()
            if current_state == "open":
                raise CircuitBreakerOpenError(
                    f"Circuit breaker is OPEN (failure_count={self._failure_count})"
                )

        try:
            if inspect.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                result = func(*args, **kwargs)

            with self._lock:
                # Success
                self._failure_count = 0
                self._state = "closed"
                self._opened_at = None
            return result

        except CircuitBreakerOpenError:
            raise
        except Exception:
            with self._lock:
                self._failure_count += 1
                if self._state == "half_open" or self._failure_count >= self._failure_threshold:
                    self._state = "open"
                    self._opened_at = time.monotonic()
            raise
