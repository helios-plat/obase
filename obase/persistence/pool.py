"""PgPool — named asyncpg connection pool with class-level registry."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Coroutine
from typing import Any

import asyncpg


class PgPool:
    """Named PG connection pool. Supports multiple independent instances.

    Args:
        name: Unique instance label (e.g. "aii_kg", "helios_market").
        dsn:  PostgreSQL DSN (postgresql://user:pass@host:port/db).
        min_size: Minimum connections (default 2).
        max_size: Maximum connections (default 20).
        command_timeout: Per-query timeout in seconds (default 60).
        enable_vector: When True registers pgvector codec on each connection.
    """

    _registry: dict[str, PgPool] = {}

    def __init__(self, *, name: str, _pool: asyncpg.Pool) -> None:
        self.name = name
        self._pool = _pool

    # ------------------------------------------------------------------
    # Class-level registry
    # ------------------------------------------------------------------

    @classmethod
    async def create(
        cls,
        *,
        name: str,
        dsn: str,
        min_size: int = 2,
        max_size: int = 20,
        command_timeout: float = 60.0,
        enable_vector: bool = False,
    ) -> PgPool:
        """Create and register a named pool. Raises ValueError if name exists."""
        if name in cls._registry:
            raise ValueError(f"PgPool '{name}' already registered")

        init: Callable[[asyncpg.Connection], Coroutine[Any, Any, None]] | None = None
        if enable_vector:
            from pgvector.asyncpg import register_vector  # type: ignore[import]

            async def init(conn: asyncpg.Connection) -> None:  # noqa: E306
                await register_vector(conn)

        pool = await asyncpg.create_pool(
            dsn=dsn,
            min_size=min_size,
            max_size=max_size,
            command_timeout=command_timeout,
            init=init,
        )
        instance = cls(name=name, _pool=pool)
        cls._registry[name] = instance
        return instance

    @classmethod
    def get(cls, name: str) -> PgPool:
        """Return registered instance. Raises KeyError if unknown."""
        if name not in cls._registry:
            raise KeyError(f"PgPool '{name}' not registered")
        return cls._registry[name]

    @classmethod
    def list_pools(cls) -> list[str]:
        """Return names of all registered pools."""
        return list(cls._registry.keys())

    @classmethod
    def clear(cls) -> None:
        """Clear registry without closing pools. For testing only."""
        cls._registry.clear()

    @classmethod
    async def get_or_create(cls, *, dsn: str, **kw: Any) -> PgPool:
        """Return existing pool keyed by DSN or create a new one.

        Safe for stable few-DSN scenarios (not per-user).
        """
        name = f"_auto_{hashlib.sha1(dsn.encode()).hexdigest()[:12]}"
        try:
            return cls.get(name)
        except KeyError:
            return await cls.create(name=name, dsn=dsn, **kw)

    # ------------------------------------------------------------------
    # Instance API
    # ------------------------------------------------------------------

    def acquire(self) -> asyncpg.pool.PoolAcquireContext:
        """Return acquire context: ``async with pool.acquire() as conn: ...``"""
        return self._pool.acquire()

    async def close(self) -> None:
        """Close pool and remove from registry."""
        await self._pool.close()
        cls = type(self)
        cls._registry.pop(self.name, None)
