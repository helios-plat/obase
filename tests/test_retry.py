"""Tests for obase.retry — retry_with_backoff and RetryPolicy."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── helpers ────────────────────────────────────────────────────────────────

def _make_flaky(fail_times: int, exc: Exception | None = None) -> MagicMock:
    """Return a sync callable that fails *fail_times* then succeeds."""
    exc = exc or ConnectionError("transient")
    calls = 0

    def fn(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls <= fail_times:
            raise exc
        return "ok"

    m = MagicMock(side_effect=fn)
    return m


def _make_async_flaky(fail_times: int, exc: Exception | None = None) -> AsyncMock:
    """Return an async callable that fails *fail_times* then succeeds."""
    exc = exc or ConnectionError("transient")
    calls = 0

    async def fn(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls <= fail_times:
            raise exc
        return "ok"

    return fn  # type: ignore[return-value]


# ── retry_with_backoff ──────────────────────────────────────────────────────

class TestRetryWithBackoff:
    """Tests for the retry_with_backoff function."""

    @pytest.mark.asyncio
    async def test_first_call_success_no_retry(self):
        """Succeeds on first call — fn called exactly once."""
        from obase.retry import retry_with_backoff

        fn = MagicMock(return_value="result")
        with patch("asyncio.sleep") as slp:
            result = await retry_with_backoff(fn, max_attempts=3)
        assert result == "result"
        assert fn.call_count == 1
        slp.assert_not_called()

    @pytest.mark.asyncio
    async def test_retry_then_success(self):
        """Fails once, succeeds on second attempt."""
        from obase.retry import retry_with_backoff

        fn = _make_flaky(fail_times=1)
        with patch("asyncio.sleep"):
            result = await retry_with_backoff(fn, max_attempts=3)
        assert result == "ok"
        assert fn.call_count == 2

    @pytest.mark.asyncio
    async def test_exhausted_raises_last_exception(self):
        """All attempts exhausted — raises the last retryable exception."""
        from obase.retry import retry_with_backoff

        fn = _make_flaky(fail_times=99)
        with patch("asyncio.sleep"), pytest.raises(ConnectionError, match="transient"):
            await retry_with_backoff(fn, max_attempts=3)
        assert fn.call_count == 3

    @pytest.mark.asyncio
    async def test_non_retryable_raises_immediately(self):
        """Non-retryable exception propagates immediately without retry."""
        from obase.retry import retry_with_backoff

        fn = MagicMock(side_effect=ValueError("fatal"))
        with patch("asyncio.sleep") as slp, pytest.raises(ValueError, match="fatal"):
            await retry_with_backoff(
                fn, max_attempts=5, retryable=(ConnectionError,)
            )
        assert fn.call_count == 1
        slp.assert_not_called()

    @pytest.mark.asyncio
    async def test_max_delay_cap_applied(self):
        """Delay is capped at max_delay."""
        from obase.retry import retry_with_backoff

        fn = _make_flaky(fail_times=99)
        delays: list[float] = []

        async def fake_sleep(d: float) -> None:
            delays.append(d)

        with patch("obase.retry.asyncio.sleep", side_effect=fake_sleep):
            with pytest.raises(ConnectionError):
                await retry_with_backoff(
                    fn,
                    max_attempts=5,
                    base_delay=10.0,
                    max_delay=15.0,
                )

        # All delays must be ≤ max_delay
        assert all(d <= 15.0 for d in delays), delays
        # At least one delay should be capped (10 * 2^1 = 20 > 15)
        assert any(d == 15.0 for d in delays)

    @pytest.mark.asyncio
    async def test_max_attempts_zero_raises_value_error(self):
        """max_attempts ≤ 0 raises ValueError before any call."""
        from obase.retry import retry_with_backoff

        fn = MagicMock(return_value="x")
        with pytest.raises(ValueError, match="max_attempts"):
            await retry_with_backoff(fn, max_attempts=0)
        fn.assert_not_called()

    @pytest.mark.asyncio
    async def test_max_attempts_negative_raises_value_error(self):
        """Negative max_attempts raises ValueError."""
        from obase.retry import retry_with_backoff

        fn = MagicMock(return_value="x")
        with pytest.raises(ValueError):
            await retry_with_backoff(fn, max_attempts=-1)

    @pytest.mark.asyncio
    async def test_async_fn_supported(self):
        """Works with async callables."""
        from obase.retry import retry_with_backoff

        fn = _make_async_flaky(fail_times=1)
        with patch("obase.retry.asyncio.sleep"):
            result = await retry_with_backoff(fn, max_attempts=3)
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_args_and_kwargs_forwarded(self):
        """Positional and keyword args are forwarded to fn."""
        from obase.retry import retry_with_backoff

        captured: list[tuple] = []

        def fn(a, b, *, c=0):
            captured.append((a, b, c))
            return a + b + c

        result = await retry_with_backoff(fn, 1, 2, c=3, max_attempts=1)
        assert result == 6
        assert captured == [(1, 2, 3)]

    @pytest.mark.asyncio
    async def test_backoff_delay_doubles(self):
        """Retry delays follow base_delay * 2^attempt pattern."""
        from obase.retry import retry_with_backoff

        fn = _make_flaky(fail_times=3)
        delays: list[float] = []

        async def fake_sleep(d: float) -> None:
            delays.append(d)

        with patch("obase.retry.asyncio.sleep", side_effect=fake_sleep):
            result = await retry_with_backoff(
                fn, max_attempts=5, base_delay=1.0, max_delay=100.0
            )

        assert result == "ok"
        # delays[0]=1.0 (2^0), delays[1]=2.0 (2^1), delays[2]=4.0 (2^2)
        assert delays == pytest.approx([1.0, 2.0, 4.0])


# ── RetryPolicy ─────────────────────────────────────────────────────────────

class TestRetryPolicy:
    """Smoke tests for existing RetryPolicy class."""

    @pytest.mark.asyncio
    async def test_policy_success_first_attempt(self):
        from obase.retry import RetryPolicy

        policy = RetryPolicy(max_retries=2, base_delay=0.0)
        fn = AsyncMock(return_value="done")
        result = await policy.execute(fn)
        assert result == "done"
        fn.assert_called_once()

    @pytest.mark.asyncio
    async def test_policy_retries_on_connection_error(self):
        from obase.retry import RetryPolicy

        policy = RetryPolicy(max_retries=2, base_delay=0.0)
        fn = _make_async_flaky(fail_times=1)
        with patch("asyncio.sleep"):
            result = await policy.execute(fn)
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_policy_exhausted_raises(self):
        from obase.retry import RetryPolicy

        policy = RetryPolicy(max_retries=1, base_delay=0.0)
        fn = AsyncMock(side_effect=ConnectionError("x"))
        with patch("asyncio.sleep"), pytest.raises(ConnectionError):
            await policy.execute(fn)
