"""Idempotent DDL helpers — ensure_table / ensure_column / ensure_index / ensure_extension."""

from __future__ import annotations

from typing import Any

from obase.persistence.pool import PgPool


async def ensure_table(
    *,
    pool: PgPool,
    schema: str,
    table: str,
    columns: list[tuple[str, str]],
    if_not_exists: bool = True,
) -> None:
    """CREATE TABLE idempotently. Skips silently if table already exists.

    Args:
        columns: ``[(name, "type_and_constraints"), …]``
                 e.g. ``[("id", "UUID PRIMARY KEY"), ("body", "TEXT NOT NULL")]``
    """
    guard = "IF NOT EXISTS " if if_not_exists else ""
    col_defs = ",\n    ".join(f'"{name}" {defn}' for name, defn in columns)
    sql = f'CREATE TABLE {guard}"{schema}"."{table}" (\n    {col_defs}\n)'
    async with pool.acquire() as conn:
        await conn.execute(sql)


async def ensure_column(
    *,
    pool: PgPool,
    schema: str,
    table: str,
    column_name: str,
    column_def: str,
) -> None:
    """ALTER TABLE … ADD COLUMN IF NOT EXISTS idempotently.

    Args:
        column_def: Type + constraints, e.g. ``"VARCHAR(255) NOT NULL DEFAULT ''"``
    """
    sql = f'ALTER TABLE "{schema}"."{table}" ADD COLUMN IF NOT EXISTS "{column_name}" {column_def}'
    async with pool.acquire() as conn:
        await conn.execute(sql)


async def ensure_index(
    *,
    pool: PgPool,
    schema: str,
    table: str,
    index_name: str,
    columns: str,
    using: str = "btree",
    options: dict[str, Any] | None = None,
    where_clause: str | None = None,
) -> None:
    """CREATE INDEX IF NOT EXISTS idempotently.

    Args:
        columns: Column expression string, e.g. ``"user_id, created_at"``
                 or ``"embedding vector_cosine_ops"`` for HNSW.
        options: ``WITH (…)`` options dict, e.g. ``{"m": 16, "ef_construction": 64}``.
        where_clause: Optional partial-index predicate (without ``WHERE``).
    """
    with_clause = ""
    if options:
        opts = ", ".join(f"{k} = {v}" for k, v in options.items())
        with_clause = f" WITH ({opts})"

    where = f" WHERE {where_clause}" if where_clause else ""
    sql = (
        f'CREATE INDEX IF NOT EXISTS "{index_name}" '
        f'ON "{schema}"."{table}" USING {using} ({columns})'
        f"{with_clause}{where}"
    )
    async with pool.acquire() as conn:
        await conn.execute(sql)


async def ensure_extension(
    *,
    pool: PgPool,
    extension: str,
) -> None:
    """CREATE EXTENSION IF NOT EXISTS idempotently.

    Args:
        extension: Extension name, e.g. ``"vector"``, ``"uuid-ossp"``.
    """
    sql = f'CREATE EXTENSION IF NOT EXISTS "{extension}"'
    async with pool.acquire() as conn:
        await conn.execute(sql)
