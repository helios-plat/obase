"""Atomic claim / release / ack for at-least-once async batch delivery.

3O layer: obase (cross-cutting infrastructure: DB access + concurrency control).

Problem this solves
-------------------
A dispatcher polls a table for undelivered rows and pushes them. With a single
shared query and no row-level ownership, two worker instances (or two loops) can
grab the same rows and double-deliver, or a crashed worker can strand rows that
are never re-picked. ``claim_batch`` + ``release`` + ``ack`` give each worker an
exclusive, time-bounded lease on a batch via
``UPDATE ... WHERE id IN (SELECT ... FOR UPDATE SKIP LOCKED) RETURNING`` — the
canonical PostgreSQL pattern for concurrent, race-free batch claiming.

Why this is obase, not oprim
----------------------------
It is external-system communication (PostgreSQL) and pure infrastructure
mechanism — no business semantics. SPEC §7.4 and the oprim→obase IO migration
blueprint both put DB access in obase.

Table allow-list (SQL-injection defence)
----------------------------------------
``table`` is a SQL identifier and therefore cannot be a bind parameter. Every
table must be registered before use:

* :func:`register_claimable_table` — register a table at application start-up
  (the intended path for project-specific tables), or
* :data:`DEFAULT_ALLOWED_TABLES` — the generic, schema-agnostic default.

An unregistered table raises ``ValueError`` *before* interpolation, so no
attacker-controlled identifier can reach the query. All values flow through
``$N`` bind parameters.

Claimability contract
---------------------
The lease predicate ("free, or stale lease") is the mechanism's own. Whether a
row is *finished* is business knowledge, so the caller declares it at
registration time as ``claimable_filter`` (e.g. ``"acked_at IS NULL"``). Without
it, ``ack`` would clear the lease and the row would immediately become
claimable again — a silent double-delivery.

Column contract
---------------
The claim query needs to know which columns to ``RETURNING``. That set is
supplied per table at registration time (see :func:`register_claimable_table`),
because "what a row looks like" is the caller's schema, not this module's.
"""

from __future__ import annotations

import re
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

__all__ = [
    "DEFAULT_ALLOWED_TABLES",
    "DEFAULT_CLAIM_COLUMNS",
    "ack",
    "claim_batch",
    "register_claimable_table",
    "registered_claim_columns",
    "registered_claim_filter",
]

#: Lease bookkeeping columns every claimable table must have. These are the
#: mechanism's own contract — not business columns — so they are fixed here.
LEASE_COLUMNS: tuple[str, ...] = ("claimed_by", "claimed_at", "retry_count")

#: Columns returned by default. Kept deliberately minimal and generic: callers
#: that need more register their own set via :func:`register_claimable_table`.
DEFAULT_CLAIM_COLUMNS: tuple[str, ...] = ("id", "created_at", *LEASE_COLUMNS)

#: Tables claimable without explicit registration. Empty by design: a library
#: must not ship a project's table names (SPEC §2.4 — no project prefixes).
DEFAULT_ALLOWED_TABLES: frozenset[str] = frozenset()

#: table -> columns to RETURNING. Populated by :func:`register_claimable_table`.
_CLAIM_COLUMNS: dict[str, tuple[str, ...]] = {}

#: table -> extra claimability predicate (SQL fragment, ``TRUE`` when unset).
#: Populated by :func:`register_claimable_table`.
_CLAIM_FILTERS: dict[str, str] = {}

#: Tables permitted without per-table column registration.
_UNREGISTERED_ALLOWED: set[str] = set()


#: A claim filter must be a bare boolean SQL expression over the row's own
#: columns: no statement separator, no comment syntax, no sub-select. It is
#: interpolated into the claim query, so a too-permissive pattern here would be
#: an injection hole (the filter comes from the application, not from a request).
_FILTER_RE = re.compile(r"^[A-Za-z0-9_\s().=<>!'+]*$")

#: Words that turn a predicate into a statement or a sub-select.
_FILTER_FORBIDDEN = re.compile(
    r"\b(select|from|insert|update|delete|drop|alter|grant|union|exists|copy|pg_\w+)\b",
    re.IGNORECASE,
)


def _validate_claimable_filter(table: str, claimable_filter: str) -> str:
    """Return ``claimable_filter`` if it is a bare boolean expression."""
    stripped = claimable_filter.strip()
    if not stripped or not _FILTER_RE.match(stripped) or _FILTER_FORBIDDEN.search(stripped):
        raise ValueError(
            f"claimable_filter for {table!r} must be a bare boolean expression "
            f"over the row's own columns, got {claimable_filter!r}"
        )
    return stripped


def register_claimable_table(
    table: str,
    *,
    columns: tuple[str, ...] | list[str] | None = None,
    claimable_filter: str | None = None,
) -> None:
    """Allow ``table`` to be claimed, optionally declaring its shape.

    Call this once at application start-up for every table a dispatcher polls.
    Registration is global to the process, which matches the lifetime of the
    connection pool the workers share.

    Args:
        table: Physical table name. Interpolated into SQL, hence the allow-list.
        columns: Columns to return from ``claim_batch``. Must include ``id`` and
            the lease columns. Defaults to :data:`DEFAULT_CLAIM_COLUMNS`.
        claimable_filter: Extra SQL predicate deciding whether a row is still
            work to do, e.g. ``"acked_at IS NULL AND push_status IS NULL"``.
            The mechanism's own lease predicate (free or stale lease) is always
            applied on top, so this only has to describe the *business* notion
            of "finished". Defaults to ``None`` (every row is claimable once
            free).

    Raises:
        ValueError: if ``columns`` omits a required column, if ``claimable_filter``
            is not a bare boolean expression, or if ``table`` was already
            registered with a *different* shape (catches two subsystems
            disagreeing about one table).

    Examples
    --------
    >>> register_claimable_table(
    ...     "outbox",
    ...     columns=("id", "created_at", "payload", "claimed_by",
    ...              "claimed_at", "retry_count"),
    ...     claimable_filter="acked_at IS NULL",
    ... )
    """
    resolved = tuple(columns) if columns is not None else DEFAULT_CLAIM_COLUMNS
    missing = {"id", *LEASE_COLUMNS} - set(resolved)
    if missing:
        raise ValueError(f"claim columns for {table!r} missing required: {sorted(missing)}")

    if claimable_filter is not None:
        claimable_filter = _validate_claimable_filter(table, claimable_filter)

    existing = _CLAIM_COLUMNS.get(table)
    if existing is not None and existing != resolved:
        raise ValueError(
            f"table {table!r} already registered with different columns "
            f"({existing!r} != {resolved!r})"
        )
    existing_filter = _CLAIM_FILTERS.get(table)
    if existing_filter is not None and existing_filter != claimable_filter:
        raise ValueError(
            f"table {table!r} already registered with a different claimable_filter "
            f"({existing_filter!r} != {claimable_filter!r})"
        )

    _CLAIM_COLUMNS[table] = resolved
    if claimable_filter is not None:
        _CLAIM_FILTERS[table] = claimable_filter
    _UNREGISTERED_ALLOWED.add(table)


def registered_claim_columns(table: str) -> tuple[str, ...]:
    """Return the RETURNING column set registered for ``table``."""
    return _CLAIM_COLUMNS.get(table, DEFAULT_CLAIM_COLUMNS)


def registered_claim_filter(table: str) -> str:
    """Return the extra claimability predicate registered for ``table``."""
    return _CLAIM_FILTERS.get(table, "TRUE")


def _validate_table(table: str) -> str:
    """Return ``table`` if claimable, else raise ``ValueError``."""
    if table not in _UNREGISTERED_ALLOWED and table not in DEFAULT_ALLOWED_TABLES:
        raise ValueError(
            f"claim_batch: table not allowed: {table!r} "
            "(register it with obase.delivery.register_claimable_table)"
        )
    return table


async def claim_batch(
    conn: Any,
    table: str,
    worker_id: str,
    limit: int,
    lease_seconds: int,
) -> list[dict[str, Any]]:
    """Atomically claim up to ``limit`` unclaimed rows for ``worker_id``.

    Uses the PostgreSQL idiom::

        UPDATE <table>
        SET claimed_by = $2, claimed_at = NOW()
        WHERE id IN (
            SELECT id FROM <table>
            WHERE (claimed_by IS NULL
                   OR claimed_at < NOW() - ($3::int * INTERVAL '1 second'))
            ORDER BY created_at ASC
            LIMIT $1
            FOR UPDATE SKIP LOCKED
        )
        RETURNING <registered columns>

    ``FOR UPDATE SKIP LOCKED`` lets N concurrent workers each take a disjoint
    batch without blocking or double-claiming. Rows already locked by another
    transaction are skipped, so the lease is genuinely exclusive. A stale lease
    (``claimed_at`` older than ``lease_seconds``) is reclaimable, so a crashed
    worker's rows are picked up again.

    Expected schema on ``table``:
        id              UUID (or compatible)
        created_at      TIMESTAMPTZ        — claim ordering
        claimed_by      VARCHAR            — NULL when free
        claimed_at      TIMESTAMPTZ        — lease start
        retry_count     INT   (default 0)  — incremented on release

    Args:
        conn: asyncpg-style connection exposing ``fetch``/``execute``.
        table: registered table name (see :func:`register_claimable_table`).
        worker_id: stable identifier for this worker/loop instance.
        limit: max rows to claim this call.
        lease_seconds: how long the lease is valid before it is reclaimable.

    Returns:
        The claimed rows as dicts. Empty list when nothing is claimable or the
        query failed (failures are logged, never raised — a dispatcher tick must
        not crash the loop).

    Raises:
        ValueError: if ``table`` is not registered.

    Examples
    --------
    >>> rows = await claim_batch(conn, "outbox", "worker-1", 50, 60)
    """
    table = _validate_table(table)
    columns = ", ".join(registered_claim_columns(table))
    claimable = registered_claim_filter(table)

    claim_sql = f"""
        UPDATE {table}
        SET claimed_by = $2,
            claimed_at = NOW()
        WHERE id IN (
            SELECT id FROM {table}
            WHERE (claimed_by IS NULL
                   OR claimed_at < NOW() - ($3::int * INTERVAL '1 second'))
              AND ({claimable})
            ORDER BY created_at ASC
            LIMIT $1
            FOR UPDATE SKIP LOCKED
        )
        RETURNING {columns}
    """
    try:
        rows = await conn.fetch(claim_sql, limit, worker_id, int(lease_seconds))
        claimed = [dict(r) for r in rows]
    except Exception as exc:  # connection error, lock contention, schema drift
        logger.warning("claim_batch.failed", table=table, worker=worker_id, error=str(exc))
        return []

    if claimed:
        logger.info("claim_batch.claimed", table=table, worker=worker_id, n=len(claimed))
    return claimed


async def release(
    conn: Any,
    table: str,
    ids: list[str],
    error: Exception | str | None = None,
) -> None:
    """Release claimed rows back to the pool, incrementing ``retry_count``.

    Called when processing a claimed batch failed (transient dispatch error,
    worker crash mid-batch, ...). Releasing — rather than acking — makes the rows
    claimable again after the lease expires, and bumps ``retry_count`` so a
    poison row can be bounded/observed downstream.

    Args:
        conn: asyncpg-style connection.
        table: registered table name.
        ids: row ids to release (frees ``claimed_by`` / ``claimed_at``).
        error: optional failure reason, logged only.

    Raises:
        ValueError: if ``table`` is not registered.
    """
    if not ids:
        return
    table = _validate_table(table)
    if error is not None:
        logger.warning("release.failed_batch", table=table, n=len(ids), error=str(error))

    release_sql = f"""
        UPDATE {table}
        SET claimed_by = NULL,
            claimed_at = NULL,
            retry_count = COALESCE(retry_count, 0) + 1
        WHERE id = ANY($1::uuid[])
          AND claimed_by IS NOT NULL
    """
    try:
        await conn.execute(release_sql, ids)
    except Exception as exc:
        logger.warning("release.failed", table=table, n=len(ids), error=str(exc))


async def ack(
    conn: Any,
    table: str,
    ids: list[str],
) -> None:
    """Mark a successfully processed batch as done.

    Clears the lease and stamps ``acked_at`` so the rows leave the claim query's
    result set. Writing the per-channel delivery status remains the caller's job
    — ``ack`` only records that *this worker* finished the row.

    Args:
        conn: asyncpg-style connection.
        table: registered table name.
        ids: row ids that were successfully processed.

    Raises:
        ValueError: if ``table`` is not registered.
    """
    if not ids:
        return
    table = _validate_table(table)

    ack_sql = f"""
        UPDATE {table}
        SET claimed_by = NULL,
            claimed_at = NULL,
            acked_at = NOW()
        WHERE id = ANY($1::uuid[])
    """
    try:
        await conn.execute(ack_sql, ids)
    except Exception as exc:
        logger.warning("ack.failed", table=table, n=len(ids), error=str(exc))
