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
