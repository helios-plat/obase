from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from obase.cache import Cache, cache_invalidate, cached
from obase.exceptions import CacheError, OBaseError


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
