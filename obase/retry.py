from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable
from typing import Any


class RetryPolicy:
    """Exponential backoff retry for async and sync functions.

    Example:
        >>> policy = RetryPolicy(max_retries=3, base_delay=1.0)
        >>> result = await policy.execute(my_async_func, arg1, kwarg=val)
    """

    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        backoff_factor: float = 2.0,
        retryable_exceptions: tuple[type[Exception], ...] = (ConnectionError, TimeoutError),
    ) -> None:
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.backoff_factor = backoff_factor
        self.retryable_exceptions = retryable_exceptions

    async def execute(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Execute func with retry policy applied.

        Raises:
            Last exception after max_retries exhausted, or immediately for
            non-retryable exceptions.
        """
        last_exc: Exception | None = None

        for attempt in range(self.max_retries + 1):
            try:
                if inspect.iscoroutinefunction(func):
                    return await func(*args, **kwargs)
                return func(*args, **kwargs)

            except self.retryable_exceptions as e:
                last_exc = e
                if attempt < self.max_retries:
                    delay = min(
                        self.base_delay * (self.backoff_factor**attempt),
                        self.max_delay,
                    )
                    await asyncio.sleep(delay)
            except Exception:
                raise  # Non-retryable

        raise last_exc  # type: ignore[misc]


async def retry_with_backoff(
    fn: Callable[..., Any],
    *args: Any,
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    retryable: tuple[type[Exception], ...] = (ConnectionError, TimeoutError),
    **kwargs: Any,
) -> Any:
    """Retry *fn* with exponential backoff up to *max_attempts* total calls.

    Args:
        fn: Callable to invoke (sync or async).
        *args: Positional arguments forwarded to *fn*.
        max_attempts: Total call attempts including the first (≥1). Raises
            ValueError if ≤0.
        base_delay: Initial retry delay in seconds.
        max_delay: Maximum delay cap in seconds.
        retryable: Exception types that trigger a retry.
        **kwargs: Keyword arguments forwarded to *fn*.

    Returns:
        The return value of *fn* on success.

    Raises:
        ValueError: If *max_attempts* ≤ 0.
        Last retryable exception if all attempts are exhausted.
        Any non-retryable exception immediately on first occurrence.
    """
    if max_attempts <= 0:
        raise ValueError(f"max_attempts must be ≥1, got {max_attempts}")

    last_exc: Exception | None = None

    for attempt in range(max_attempts):
        try:
            if inspect.iscoroutinefunction(fn):
                return await fn(*args, **kwargs)
            return fn(*args, **kwargs)
        except retryable as exc:
            last_exc = exc
            if attempt < max_attempts - 1:
                delay = min(base_delay * (2.0 ** attempt), max_delay)
                await asyncio.sleep(delay)
        except Exception:
            raise  # non-retryable: propagate immediately

    raise last_exc  # type: ignore[misc]
