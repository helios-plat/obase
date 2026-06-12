from __future__ import annotations

import asyncio
import hashlib
import inspect
import pickle
import time
from collections.abc import Callable
from functools import wraps
from pathlib import Path
from typing import Any

import structlog

from obase.exceptions import CacheError, OBaseError
from obase.fs import FS

log = structlog.get_logger()


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
