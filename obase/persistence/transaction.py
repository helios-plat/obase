"""transaction() — async context manager for PG transactions."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import asyncpg

from obase.persistence.pool import PgPool


@asynccontextmanager
async def transaction(pool: PgPool) -> AsyncIterator[asyncpg.Connection]:
    """Yield a connection with an open transaction.

    Commits on clean exit; rolls back on any exception.

    Example::

        async with transaction(pool) as tx:
            await tx.execute("INSERT INTO ku ...")
            await tx.execute("UPDATE state ...")
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            yield conn
