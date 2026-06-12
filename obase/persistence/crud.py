"""obase.persistence.crud — Async CRUD primitives for single-row operations."""

from __future__ import annotations

from typing import Any

from obase.persistence.pool import PgPool
from obase.persistence.transaction import transaction
from obase.persistence.upsert import upsert_batch


async def insert_one(
    pool: PgPool,
    *,
    table: str,
    data: dict[str, Any],
    returning: str = "id",
) -> Any:
    """单行 INSERT, 返回 RETURNING 列值. (对齐 oprim.db_insert)"""
    if not data:
        raise ValueError("insert_one: data must not be empty")

    keys = sorted(data.keys())
    cols = ", ".join(f'"{k}"' for k in keys)
    placeholders = ", ".join(f"${i+1}" for i in range(len(keys)))
    sql = f'INSERT INTO "{table}" ({cols}) VALUES ({placeholders}) RETURNING "{returning}"'

    async with transaction(pool) as tx:
        row = await tx.fetchrow(sql, *[data[k] for k in keys])

    return row[returning] if row else None


async def query(
    pool: PgPool,
    *,
    sql: str,
    params: list[Any] | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """参数化 SELECT, 返回 list[dict]. (对齐 oprim.db_query)"""
    # Note: If limit is positive and no LIMIT in SQL, append it.
    final_sql = sql
    if limit > 0 and "LIMIT" not in sql.upper():
        final_sql = f"{sql} LIMIT {limit}"

    async with pool.acquire() as conn:
        rows = await conn.fetch(final_sql, *(params or []))

    return [dict(r) for r in rows]


async def read_one(
    pool: PgPool,
    *,
    table: str,
    id: Any,  # noqa: A002
    id_column: str = "id",
) -> dict[str, Any] | None:
    """按 ID 读单行 (含 deleted_at IS NULL 过滤). (对齐 oprim.db_read)"""
    sql = f'SELECT * FROM "{table}" WHERE "{id_column}" = $1 AND deleted_at IS NULL'
    async with pool.acquire() as conn:
        try:
            row = await conn.fetchrow(sql, id)
        except Exception:  # Fallback if deleted_at column does not exist
            fallback_sql = f'SELECT * FROM "{table}" WHERE "{id_column}" = $1'
            row = await conn.fetchrow(fallback_sql, id)

    return dict(row) if row else None


async def update_one(
    pool: PgPool,
    *,
    table: str,
    id: Any,  # noqa: A002
    data: dict[str, Any],
    id_column: str = "id",
) -> bool:
    """按 ID 更新单行. 返回是否更新成功. (对齐 oprim.db_update)"""
    if not data:
        raise ValueError("update_one: data must not be empty")

    keys = sorted(data.keys())
    sets = ", ".join(f'"{k}" = ${i+2}' for i, k in enumerate(keys))
    sql = f'UPDATE "{table}" SET {sets} WHERE "{id_column}" = $1'

    async with transaction(pool) as tx:
        result = await tx.execute(sql, id, *[data[k] for k in keys])

    return result.split()[-1] != "0"


async def soft_delete_one(
    pool: PgPool,
    *,
    table: str,
    id: Any,  # noqa: A002
    id_column: str = "id",
    deleted_at_column: str = "deleted_at",
) -> bool:
    """软删: 设 deleted_at = NOW(). (对齐 oprim.db_soft_delete)"""
    sql = (
        f'UPDATE "{table}" SET "{deleted_at_column}" = NOW() '
        f'WHERE "{id_column}" = $1 AND "{deleted_at_column}" IS NULL'
    )
    async with transaction(pool) as tx:
        result = await tx.execute(sql, id)

    return result.split()[-1] != "0"


async def write_one(
    pool: PgPool,
    *,
    table: str,
    data: dict[str, Any],
    conflict_on: list[str] | None = None,
) -> int:
    """Thin wrapper around upsert_batch for single row write."""
    return await upsert_batch(
        pool=pool,
        table=table,
        rows=[data],
        conflict_columns=conflict_on or [],
    )
