"""obase.persistence — PostgreSQL + pgvector connection pool and query primitives.

Provides cross-cutting infrastructure only. Business schemas and thin
service-layer wrappers belong in consumer projects (AII, Stratum, …).
"""

from __future__ import annotations

from obase.persistence.ddl import (
    ensure_column,
    ensure_extension,
    ensure_index,
    ensure_table,
)
from obase.persistence.pool import PgPool
from obase.persistence.transaction import transaction
from obase.persistence.upsert import upsert_batch
from obase.persistence.vector import VectorMetric, vector_search

__all__ = [
    "PgPool",
    "transaction",
    "upsert_batch",
    "vector_search",
    "VectorMetric",
    "ensure_table",
    "ensure_column",
    "ensure_index",
    "ensure_extension",
]
