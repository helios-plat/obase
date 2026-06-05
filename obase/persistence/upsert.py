"""upsert_batch — ON CONFLICT batch upsert for asyncpg."""

from __future__ import annotations

from typing import Any

from obase.persistence.pool import PgPool


async def upsert_batch(
    *,
    pool: PgPool,
    table: str,
    rows: list[dict[str, Any]],
    conflict_columns: list[str],
    update_columns: list[str] | None = None,
) -> int:
    """Batch upsert rows into *table*, return affected row count.

    Generates::

        INSERT INTO {table} (cols...) VALUES ($1,$2,...),($N,...)
        ON CONFLICT (conflict_cols) DO UPDATE SET col = EXCLUDED.col ...
        -- or DO NOTHING when update_columns is None

    Args:
        rows: Non-empty list of dicts; every dict must have identical keys.
        conflict_columns: Columns forming the ON CONFLICT target.
        update_columns: Columns to update on conflict. None → DO NOTHING.

    Returns:
        Number of rows inserted + updated (parsed from command tag).

    Raises:
        ValueError: *rows* is empty or rows have inconsistent column sets.
    """
    if not rows:
        raise ValueError("rows must be non-empty")

    columns = list(rows[0].keys())
    expected = set(columns)
    for i, row in enumerate(rows[1:], 1):
        if set(row.keys()) != expected:
            raise ValueError(f"Row {i} columns differ from row 0")

    num_cols = len(columns)
    placeholders: list[str] = []
    flat_values: list[Any] = []
    for i, row in enumerate(rows):
        base = i * num_cols
        ph = ", ".join(f"${base + j + 1}" for j in range(num_cols))
        placeholders.append(f"({ph})")
        flat_values.extend(row[col] for col in columns)

    cols_sql = ", ".join(f'"{c}"' for c in columns)
    conflict_sql = ", ".join(f'"{c}"' for c in conflict_columns)
    values_sql = ", ".join(placeholders)

    if update_columns:
        set_sql = ", ".join(f'"{c}" = EXCLUDED."{c}"' for c in update_columns)
        conflict_action = f"DO UPDATE SET {set_sql}"
    else:
        conflict_action = "DO NOTHING"

    sql = (
        f"INSERT INTO {table} ({cols_sql}) VALUES {values_sql} "
        f"ON CONFLICT ({conflict_sql}) {conflict_action}"
    )

    async with pool.acquire() as conn:
        tag: str = await conn.execute(sql, *flat_values)

    # tag format: "INSERT 0 N"
    parts = tag.split()
    return int(parts[-1]) if parts else 0
