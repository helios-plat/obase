"""vector_search — pgvector HNSW nearest-neighbour retrieval."""

from __future__ import annotations

from typing import Any, Literal

from obase.persistence.pool import PgPool

VectorMetric = Literal["cosine", "l2", "inner_product"]

_METRIC_OP: dict[VectorMetric, str] = {
    "cosine": "<=>",
    "l2": "<->",
    "inner_product": "<#>",
}


def _fmt_vector(v: list[float]) -> str:
    """Format a float list as a pgvector literal string '[x,y,z]'."""
    return "[" + ",".join(str(x) for x in v) + "]"


async def vector_search(
    *,
    pool: PgPool,
    table: str,
    vector_column: str,
    query_vector: list[float],
    metric: VectorMetric = "cosine",
    top_k: int = 20,
    filter_sql: str | None = None,
    filter_params: list[Any] | None = None,
    select_columns: list[str] | None = None,
) -> list[dict[str, Any]]:
    """pgvector HNSW nearest-neighbour search.

    *query_vector* is passed as a formatted string with ``::vector`` cast so
    no codec registration is required for the query parameter.  If the result
    set should include the vector column itself, create the pool with
    ``enable_vector=True`` to register the pgvector type codec.

    Parameter numbering: ``$1`` is always *query_vector*; *filter_params*
    occupy ``$2, $3, …`` matching the ``$N`` placeholders in *filter_sql*.

    Args:
        filter_sql: Optional WHERE fragment without the ``WHERE`` keyword.
                    Use ``$2``, ``$3``, … for bind params.
        filter_params: Bind values for *filter_sql*.
        select_columns: Columns to return. ``None`` → ``*`` (all columns).

    Returns:
        Rows as dicts with an extra ``distance`` key, sorted ascending.
    """
    op = _METRIC_OP[metric]
    select = "*" if select_columns is None else ", ".join(f'"{c}"' for c in select_columns)
    vec_str = _fmt_vector(query_vector)

    params: list[Any] = [vec_str, *(filter_params or [])]

    where = f"WHERE {filter_sql}" if filter_sql else ""
    sql = (
        f'SELECT {select}, "{vector_column}" {op} $1::vector AS distance '
        f"FROM {table} "
        f"{where} "
        f'ORDER BY "{vector_column}" {op} $1::vector '
        f"LIMIT {top_k}"
    )

    async with pool.acquire() as conn:
        records = await conn.fetch(sql, *params)

    return [dict(r) for r in records]
