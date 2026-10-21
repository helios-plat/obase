"""Tests for obase.delivery.claim (atomic batch claim / release / ack).

Upstreamed from the Tide consumer line, generalised: the table name and the
RETURNING column set are registered by the application instead of hard-coded,
so obase ships no project-specific schema (SPEC §2.4).

These tests pin the mechanism contract with a fake asyncpg-style connection:
the SQL shape (``FOR UPDATE SKIP LOCKED``, the lease predicate, bind
parameters), the allow-list guard, and the fail-soft behaviour (a dispatcher
tick must never crash the loop).
"""

from __future__ import annotations

import pytest

from obase.delivery import claim as claim_mod
from obase.delivery.claim import (
    DEFAULT_CLAIM_COLUMNS,
    LEASE_COLUMNS,
    ack,
    claim_batch,
    register_claimable_table,
    registered_claim_columns,
    registered_claim_filter,
    release,
)

TABLE = "outbox"


@pytest.fixture(autouse=True)
def _clean_registry():
    """Keep the process-wide registry from leaking between tests."""
    saved_cols = dict(claim_mod._CLAIM_COLUMNS)
    saved_filters = dict(claim_mod._CLAIM_FILTERS)
    saved_allowed = set(claim_mod._UNREGISTERED_ALLOWED)
    yield
    claim_mod._CLAIM_COLUMNS.clear()
    claim_mod._CLAIM_COLUMNS.update(saved_cols)
    claim_mod._CLAIM_FILTERS.clear()
    claim_mod._CLAIM_FILTERS.update(saved_filters)
    claim_mod._UNREGISTERED_ALLOWED.clear()
    claim_mod._UNREGISTERED_ALLOWED.update(saved_allowed)


class _Conn:
    """Fake asyncpg connection recording every statement."""

    def __init__(self, rows=None, *, raise_on_fetch=None, raise_on_execute=None):
        self._rows = rows or []
        self._raise_on_fetch = raise_on_fetch
        self._raise_on_execute = raise_on_execute
        self.fetches: list[tuple[str, tuple]] = []
        self.executes: list[tuple[str, tuple]] = []

    async def fetch(self, query, *args):
        self.fetches.append((query, args))
        if self._raise_on_fetch:
            raise self._raise_on_fetch
        return self._rows

    async def execute(self, query, *args):
        self.executes.append((query, args))
        if self._raise_on_execute:
            raise self._raise_on_execute
        return "OK"


# ---------------------------------------------------------------------------
# registration / allow-list
# ---------------------------------------------------------------------------


def test_unregistered_table_is_rejected():
    with pytest.raises(ValueError, match="table not allowed"):
        claim_mod._validate_table("never_registered")


def test_no_tables_are_allowed_by_default():
    """A library must not ship a project's table names."""
    assert claim_mod.DEFAULT_ALLOWED_TABLES == frozenset()


def test_registration_allows_the_table():
    register_claimable_table(TABLE)
    assert claim_mod._validate_table(TABLE) == TABLE


def test_default_columns_include_id_and_lease_columns():
    assert "id" in DEFAULT_CLAIM_COLUMNS
    for col in LEASE_COLUMNS:
        assert col in DEFAULT_CLAIM_COLUMNS


def test_registration_rejects_missing_required_columns():
    with pytest.raises(ValueError, match="missing required"):
        register_claimable_table("t", columns=("id", "created_at"))


def test_registration_rejects_conflicting_column_sets():
    register_claimable_table("t", columns=("id", "created_at", *LEASE_COLUMNS))
    with pytest.raises(ValueError, match="already registered with different columns"):
        register_claimable_table("t", columns=("id", "created_at", "payload", *LEASE_COLUMNS))


def test_registration_is_idempotent_for_the_same_columns():
    cols = ("id", "created_at", *LEASE_COLUMNS)
    register_claimable_table("t", columns=cols)
    register_claimable_table("t", columns=cols)  # must not raise


def test_registered_claim_columns_roundtrip():
    cols = ("id", "created_at", "payload", *LEASE_COLUMNS)
    register_claimable_table("t", columns=cols)
    assert registered_claim_columns("t") == cols


def test_unregistered_lookup_returns_the_default_columns():
    assert registered_claim_columns("nope") == DEFAULT_CLAIM_COLUMNS


def test_unregistered_lookup_returns_the_permissive_filter():
    assert registered_claim_filter("nope") == "TRUE"


def test_claimable_filter_roundtrip():
    register_claimable_table("t", claimable_filter="acked_at IS NULL")
    assert registered_claim_filter("t") == "acked_at IS NULL"


@pytest.mark.parametrize(
    "bad",
    [
        "acked_at IS NULL; DROP TABLE t",
        "1=1 -- comment",
        "EXISTS (SELECT 1 FROM secrets)",
        "acked_at IS NULL /* x */",
        "",
    ],
)
def test_registration_rejects_non_boolean_claimable_filter(bad):
    with pytest.raises(ValueError, match="claimable_filter"):
        register_claimable_table("t", claimable_filter=bad)


def test_registration_rejects_conflicting_claimable_filters():
    register_claimable_table("t", claimable_filter="acked_at IS NULL")
    with pytest.raises(ValueError, match="different claimable_filter"):
        register_claimable_table("t", claimable_filter="push_status IS NULL")


async def test_claim_batch_applies_the_registered_filter():
    """Regression: without a filter, an acked row (lease cleared) is re-claimed."""
    register_claimable_table(TABLE, claimable_filter="acked_at IS NULL")
    conn = _Conn([])
    await claim_batch(conn, TABLE, "w1", 10, 60)
    query, _args = conn.fetches[0]
    assert "AND (acked_at IS NULL)" in query
    # the lease predicate is still the mechanism's own, always applied
    assert "claimed_at < NOW()" in query


async def test_claim_batch_without_filter_is_permissive():
    register_claimable_table(TABLE)
    conn = _Conn([])
    await claim_batch(conn, TABLE, "w1", 10, 60)
    query, _args = conn.fetches[0]
    assert "AND (TRUE)" in query


# ---------------------------------------------------------------------------
# claim_batch
# ---------------------------------------------------------------------------


async def test_claim_batch_returns_rows_as_dicts():
    register_claimable_table(TABLE)
    conn = _Conn([{"id": "a"}, {"id": "b"}])
    rows = await claim_batch(conn, TABLE, "w1", 10, 60)
    assert rows == [{"id": "a"}, {"id": "b"}]


async def test_claim_batch_sql_shape():
    register_claimable_table(TABLE)
    conn = _Conn([])
    await claim_batch(conn, TABLE, "w1", 10, 60)
    query, args = conn.fetches[0]
    assert "FOR UPDATE SKIP LOCKED" in query
    assert "UPDATE" in query
    assert "RETURNING" in query
    assert "claimed_at < NOW()" in query  # stale-lease reclaim
    assert args == (10, "w1", 60)


async def test_claim_batch_uses_registered_columns():
    cols = ("id", "created_at", "payload", *LEASE_COLUMNS)
    register_claimable_table(TABLE, columns=cols)
    conn = _Conn([])
    await claim_batch(conn, TABLE, "w1", 5, 30)
    query, _ = conn.fetches[0]
    for col in cols:
        assert col in query


async def test_claim_batch_rejects_unregistered_table():
    with pytest.raises(ValueError, match="table not allowed"):
        await claim_batch(_Conn([]), "rogue", "w1", 1, 1)


async def test_claim_batch_swallows_query_errors():
    """A failed claim must not raise: the dispatcher loop keeps ticking."""
    register_claimable_table(TABLE)
    conn = _Conn(raise_on_fetch=RuntimeError("connection reset"))
    assert await claim_batch(conn, TABLE, "w1", 10, 60) == []


async def test_claim_batch_empty_result():
    register_claimable_table(TABLE)
    assert await claim_batch(_Conn([]), TABLE, "w1", 10, 60) == []


# ---------------------------------------------------------------------------
# release
# ---------------------------------------------------------------------------


async def test_release_noop_for_empty_ids():
    register_claimable_table(TABLE)
    conn = _Conn()
    await release(conn, TABLE, [])
    assert conn.executes == []


async def test_release_bumps_retry_count():
    register_claimable_table(TABLE)
    conn = _Conn()
    await release(conn, TABLE, ["a", "b"])
    query, args = conn.executes[0]
    assert "retry_count" in query
    assert "COALESCE" in query
    assert args == (["a", "b"],)


async def test_release_clears_the_lease():
    register_claimable_table(TABLE)
    conn = _Conn()
    await release(conn, TABLE, ["a"])
    query, _ = conn.executes[0]
    assert "claimed_by = NULL" in query
    assert "claimed_at = NULL" in query


async def test_release_swallows_errors():
    register_claimable_table(TABLE)
    conn = _Conn(raise_on_execute=RuntimeError("gone"))
    await release(conn, TABLE, ["a"])  # must not raise


async def test_release_rejects_unregistered_table():
    with pytest.raises(ValueError, match="table not allowed"):
        await release(_Conn(), "rogue", ["a"])


# ---------------------------------------------------------------------------
# ack
# ---------------------------------------------------------------------------


async def test_ack_noop_for_empty_ids():
    register_claimable_table(TABLE)
    conn = _Conn()
    await ack(conn, TABLE, [])
    assert conn.executes == []


async def test_ack_stamps_acked_at():
    register_claimable_table(TABLE)
    conn = _Conn()
    await ack(conn, TABLE, ["a"])
    query, args = conn.executes[0]
    assert "acked_at = NOW()" in query
    assert "claimed_by = NULL" in query
    assert args == (["a"],)


async def test_ack_swallows_errors():
    register_claimable_table(TABLE)
    conn = _Conn(raise_on_execute=RuntimeError("gone"))
    await ack(conn, TABLE, ["a"])  # must not raise


async def test_ack_rejects_unregistered_table():
    with pytest.raises(ValueError, match="table not allowed"):
        await ack(_Conn(), "rogue", ["a"])


# ---------------------------------------------------------------------------
# SQL-injection guard
# ---------------------------------------------------------------------------


async def test_table_name_never_reaches_sql_unless_registered():
    """An attacker-supplied table must fail the allow-list, not be interpolated."""
    evil = "outbox; DROP TABLE users"
    with pytest.raises(ValueError, match="table not allowed"):
        await claim_batch(_Conn([]), evil, "w1", 1, 1)
