from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from obase.cache import Cache, DistributedLock, cache_invalidate, cached
from obase.exceptions import CacheError, LockAcquisitionError, OBaseError

TEST_REDIS_URL = os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/0")


class TestCacheGetPut:
    async def test_put_then_get(self):
        c = Cache("test")
        await c.put("key1", {"val": 42})
        result = await c.get("key1")
        assert result == {"val": 42}

    async def test_get_miss_returns_none(self):
        c = Cache("test2")
        result = await c.get("nonexistent-key-xyz")
        assert result is None

    async def test_put_overwrites(self):
        c = Cache("test3")
        await c.put("k", "v1")
        await c.put("k", "v2")
        assert await c.get("k") == "v2"

    async def test_different_namespaces_isolated(self):
        c1 = Cache("ns1")
        c2 = Cache("ns2")
        await c1.put("k", "ns1_val")
        assert await c2.get("k") is None

    async def test_ttl_expiry(self):
        c = Cache("ttl-test", ttl_seconds=0.05)
        await c.put("k", "fresh")
        assert await c.get("k") == "fresh"
        await asyncio.sleep(0.1)
        assert await c.get("k") is None

    async def test_no_ttl_persists(self):
        c = Cache("no-ttl")
        await c.put("k", "persists")
        await asyncio.sleep(0.05)
        assert await c.get("k") == "persists"

    async def test_invalidate(self):
        c = Cache("inv-test")
        await c.put("k", "val")
        await c.invalidate("k")
        assert await c.get("k") is None

    async def test_clear_expired(self):
        c = Cache("clear-test", ttl_seconds=0.05)
        await c.put("k1", "v1")
        await c.put("k2", "v2")
        await asyncio.sleep(0.1)
        removed = await c.clear_expired()
        assert removed >= 2

    async def test_put_fail_raises_cache_error(self, tmp_path):
        """Cache write failure must raise CacheError (no silent suppression)."""
        c = Cache("fail-test")
        # Force a failure by patching Path.write_bytes
        with patch("pathlib.Path.write_bytes", side_effect=OSError("disk full")):
            with pytest.raises(CacheError, match="disk full"):
                await c.put("k", "v")

    async def test_get_corrupt_file_raises_cache_error(self, tmp_path):
        """Corrupt pickle file raises CacheError."""
        c = Cache("corrupt-test")
        key_path = c._key_path("mykey")
        key_path.parent.mkdir(parents=True, exist_ok=True)
        key_path.write_bytes(b"not-pickle-data!!!")
        with pytest.raises(CacheError):
            await c.get("mykey")


class TestCachedDecorator:
    async def test_cached_calls_fn_once(self):
        c = Cache("deco-test")
        call_count = {"n": 0}

        @cached(c, key_fn=lambda x: f"key:{x}")
        async def compute(x: int) -> int:
            call_count["n"] += 1
            return x * 2

        r1 = await compute(5)
        r2 = await compute(5)
        assert r1 == 10
        assert r2 == 10
        assert call_count["n"] == 1

    async def test_cached_different_args_different_keys(self):
        c = Cache("deco-test2")
        results = []

        @cached(c)
        async def fn(x: int) -> int:
            results.append(x)
            return x

        await fn(1)
        await fn(2)
        await fn(1)
        assert results == [1, 2]

    async def test_cached_put_failure_propagates(self):
        """CacheError from put must propagate — no silent fallback."""
        c = Cache("deco-fail")

        @cached(c)
        async def fn(x: int) -> int:
            return x

        with patch("obase.cache.Cache.put", side_effect=CacheError("write fail")):
            with pytest.raises(CacheError, match="write fail"):
                await fn(42)


class TestCacheInvalidate:
    def _make_redis_mock(self, delete_return: int = 1) -> MagicMock:
        redis_mod = MagicMock()
        client = MagicMock()
        client.delete.return_value = delete_return
        redis_mod.Redis.from_url.return_value = client
        return redis_mod

    def test_invalidate_existing_key_returns_true(self):
        redis_mock = self._make_redis_mock(delete_return=1)
        with patch.dict("sys.modules", {"redis": redis_mock}):
            result = cache_invalidate(key="mykey")
        assert result is True

    def test_invalidate_missing_key_returns_false(self):
        redis_mock = self._make_redis_mock(delete_return=0)
        with patch.dict("sys.modules", {"redis": redis_mock}):
            result = cache_invalidate(key="nokey")
        assert result is False

    def test_invalidate_connection_error_raises_obase_error(self):
        redis_mod = MagicMock()
        redis_mod.Redis.from_url.side_effect = Exception("connection refused")
        with patch.dict("sys.modules", {"redis": redis_mod}):
            with pytest.raises(OBaseError, match="cache_invalidate redis failed"):
                cache_invalidate(key="k")

    def test_invalidate_no_redis_package_raises_obase_error(self):
        # sys.modules["redis"] = None causes ImportError on `import redis`
        with patch.dict("sys.modules", {"redis": None}):
            with pytest.raises((OBaseError, ImportError)):
                cache_invalidate(key="k")


# ---------------------------------------------------------------------------
# DistributedLock — mocked unit tests (deterministic, no real Redis needed)
# ---------------------------------------------------------------------------


class TestDistributedLockMocked:
    def _make_client(self, *, set_side_effect) -> AsyncMock:
        client = AsyncMock()
        client.set.side_effect = set_side_effect
        return client

    async def test_acquire_and_release_happy_path(self):
        client = self._make_client(set_side_effect=[True])
        with patch("redis.asyncio.Redis.from_url", return_value=client):
            async with DistributedLock(key="cart:1", ttl_seconds=1.0) as lock:
                assert lock is not None
        client.set.assert_awaited_once()
        client.eval.assert_awaited_once()
        client.aclose.assert_awaited_once()

    async def test_release_uses_compare_and_del_with_own_token(self):
        client = self._make_client(set_side_effect=[True])
        captured_token = None
        with patch("redis.asyncio.Redis.from_url", return_value=client):
            async with DistributedLock(key="cart:1") as lock:
                captured_token = lock._token
        eval_args = client.eval.await_args.args
        # eval(script, numkeys, key, token) — token must be this instance's own token
        assert eval_args[-1] == captured_token
        assert captured_token is not None

    async def test_acquire_timeout_raises_lock_acquisition_error(self):
        client = self._make_client(set_side_effect=lambda *a, **k: False)
        with patch("redis.asyncio.Redis.from_url", return_value=client):
            with pytest.raises(LockAcquisitionError, match="Could not acquire lock"):
                async with DistributedLock(key="busy", timeout_seconds=0.1, retry_interval=0.03):
                    pass  # pragma: no cover
        client.aclose.assert_awaited_once()

    async def test_acquire_retries_then_succeeds(self):
        client = self._make_client(set_side_effect=[False, False, True])
        with patch("redis.asyncio.Redis.from_url", return_value=client):
            async with DistributedLock(key="retry", timeout_seconds=2.0, retry_interval=0.01):
                pass
        assert client.set.await_count == 3

    async def test_missing_redis_package_raises_obase_error(self):
        with patch.dict("sys.modules", {"redis.asyncio": None}):
            with pytest.raises((OBaseError, ImportError)):
                async with DistributedLock(key="x"):
                    pass  # pragma: no cover


# ---------------------------------------------------------------------------
# DistributedLock — real Redis integration (skips automatically if unavailable)
# ---------------------------------------------------------------------------


class TestDistributedLockIntegration:
    @pytest.fixture(autouse=True)
    async def _require_redis(self):
        try:
            import redis.asyncio as redis_lib
        except ImportError:
            pytest.skip("redis package not installed")

        client = redis_lib.Redis.from_url(TEST_REDIS_URL)
        try:
            await client.ping()
        except Exception:
            pytest.skip("Redis not available at TEST_REDIS_URL")
        finally:
            await client.aclose()

    async def test_mutual_exclusion_across_two_holders(self):
        """Two concurrent lock attempts on the same key must never overlap."""
        key = "it:mutex-test"
        critical_section_active = {"n": 0}
        max_concurrent = {"n": 0}

        async def hold_briefly():
            async with DistributedLock(
                key=key, redis_url=TEST_REDIS_URL, ttl_seconds=2.0, timeout_seconds=3.0
            ):
                critical_section_active["n"] += 1
                max_concurrent["n"] = max(max_concurrent["n"], critical_section_active["n"])
                await asyncio.sleep(0.1)
                critical_section_active["n"] -= 1

        await asyncio.gather(hold_briefly(), hold_briefly())
        assert max_concurrent["n"] == 1

    async def test_second_holder_times_out_while_first_holds(self):
        key = "it:timeout-test"

        async def hold_for(seconds: float):
            async with DistributedLock(
                key=key, redis_url=TEST_REDIS_URL, ttl_seconds=5.0, timeout_seconds=3.0
            ):
                await asyncio.sleep(seconds)

        async def try_acquire_briefly():
            async with DistributedLock(
                key=key, redis_url=TEST_REDIS_URL, ttl_seconds=5.0, timeout_seconds=0.2
            ):
                pass  # pragma: no cover

        holder_task = asyncio.create_task(hold_for(0.5))
        await asyncio.sleep(0.05)  # let holder acquire first
        with pytest.raises(LockAcquisitionError):
            await try_acquire_briefly()
        await holder_task

    async def test_lock_released_after_context_allows_reacquire(self):
        key = "it:release-test"
        async with DistributedLock(key=key, redis_url=TEST_REDIS_URL, timeout_seconds=1.0):
            pass
        # Should not raise — the lock must have been released.
        async with DistributedLock(key=key, redis_url=TEST_REDIS_URL, timeout_seconds=1.0):
            pass
