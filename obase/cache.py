from __future__ import annotations

import asyncio
import hashlib
import inspect
import pickle
import secrets
import time
from collections.abc import Callable
from functools import wraps
from pathlib import Path
from types import TracebackType
from typing import Any

import structlog

from obase.exceptions import CacheError, LockAcquisitionError, OBaseError
from obase.fs import FS

log = structlog.get_logger()

_RELEASE_IF_OWNER_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""


class Cache:
    """Pickle-backed async cache with TTL support."""

    def __init__(self, namespace: str = "default", ttl_seconds: float | None = None) -> None:
        self._ns = namespace
        self._ttl = ttl_seconds

    def _cache_dir(self) -> Path:
        d = FS.working_dir() / ".cache" / self._ns
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _key_path(self, key: str) -> Path:
        hk = hashlib.sha256(key.encode()).hexdigest()
        return self._cache_dir() / f"{hk}.pkl"

    async def get(self, key: str) -> Any | None:
        """Return cached value or None on miss."""
        path = self._key_path(key)
        if not path.exists():
            return None
        try:
            data: dict[str, Any] = pickle.loads(path.read_bytes())
        except Exception as exc:
            raise CacheError(f"Cache read failed for key {key!r}: {exc}") from exc
        if self._ttl is not None:
            if time.time() - data.get("stored_at", 0) > self._ttl:
                path.unlink(missing_ok=True)
                return None
        return data.get("value")

    async def put(self, key: str, value: Any) -> None:
        """Store a value. Raises CacheError on failure."""
        path = self._key_path(key)
        payload = {"value": value, "stored_at": time.time()}
        try:
            path.write_bytes(pickle.dumps(payload))
        except Exception as exc:
            raise CacheError(f"Cache write failed for key {key!r}: {exc}") from exc

    async def invalidate(self, key: str) -> None:
        """Remove a single cache entry."""
        self._key_path(key).unlink(missing_ok=True)

    async def clear_expired(self) -> int:
        """Remove all entries past their TTL. Returns count removed."""
        if self._ttl is None:
            return 0
        removed = 0
        now = time.time()
        for p in self._cache_dir().glob("*.pkl"):
            try:
                data: dict[str, Any] = pickle.loads(p.read_bytes())
                if now - data.get("stored_at", 0) > self._ttl:
                    p.unlink(missing_ok=True)
                    removed += 1
            except Exception:
                p.unlink(missing_ok=True)
                removed += 1
        return removed


class DistributedLock:
    """Redis SETNX 分布式锁 — 用于 cart_id、inventory 等临界区防超卖。

    Token 化释放：只有持锁方自己的 token 匹配时才 DEL，避免 TTL 过期后
    误删别的持有者刚抢到的锁（用 Lua 脚本保证 compare-and-del 原子性）。

    Usage:
        async with DistributedLock(key=f"cart:{cart_id}"):
            ...  # 临界区
    """

    def __init__(
        self,
        *,
        key: str,
        redis_url: str = "redis://localhost:6379/0",
        ttl_seconds: float = 10.0,
        timeout_seconds: float = 5.0,
        retry_interval: float = 0.05,
    ) -> None:
        self._key = f"lock:{key}"
        self._redis_url = redis_url
        self._ttl_ms = int(ttl_seconds * 1000)
        self._timeout_seconds = timeout_seconds
        self._retry_interval = retry_interval
        self._token = secrets.token_hex(16)
        self._client: Any = None

    async def __aenter__(self) -> DistributedLock:
        try:
            import redis.asyncio as redis_lib
        except ImportError as exc:
            raise OBaseError(
                "redis package not installed; install obase[cache] to use DistributedLock"
            ) from exc

        self._client = redis_lib.Redis.from_url(self._redis_url)
        deadline = time.monotonic() + self._timeout_seconds
        while True:
            acquired = await self._client.set(self._key, self._token, nx=True, px=self._ttl_ms)
            if acquired:
                return self
            if time.monotonic() >= deadline:
                await self._client.aclose()
                self._client = None
                raise LockAcquisitionError(
                    f"Could not acquire lock {self._key!r} within {self._timeout_seconds}s"
                )
            await asyncio.sleep(self._retry_interval)

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._client is None:
            return
        try:
            await self._client.eval(_RELEASE_IF_OWNER_SCRIPT, 1, self._key, self._token)
        finally:
            await self._client.aclose()
            self._client = None


def cache_invalidate(
    *,
    key: str,
    redis_url: str = "redis://localhost:6379/0",
) -> bool:
    """Invalidate (delete) a single Redis cache key.

    Returns True if the key existed and was deleted, False if not found.
    Raises OBaseError on connection failure.
    """
    try:
        import redis as redis_lib
    except ImportError as exc:
        raise OBaseError(
            "redis package not installed; install obase[cache] to use cache_invalidate"
        ) from exc

    try:
        client = redis_lib.Redis.from_url(redis_url)
        deleted = client.delete(key)
        return int(deleted) > 0  # type: ignore[arg-type]
    except Exception as exc:
        raise OBaseError(f"cache_invalidate redis failed: {exc}") from exc


def cached(cache: Cache, key_fn: Callable[..., str] | None = None) -> Callable[..., Any]:
    """Decorator that wraps an async function with cache get/put logic.
    CacheError from put propagates to callers — no silent fallback.
    """

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            if key_fn is not None:
                cache_key = key_fn(*args, **kwargs)
            else:
                cache_key = f"{fn.__module__}.{fn.__qualname__}:{args!r}:{kwargs!r}"

            hit = await cache.get(cache_key)
            if hit is not None:
                log.debug("obase.cache.hit", key=cache_key)
                return hit

            if inspect.iscoroutinefunction(fn):
                result = await fn(*args, **kwargs)
            else:
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(None, lambda: fn(*args, **kwargs))

            await cache.put(cache_key, result)
            return result

        return wrapper

    return decorator
