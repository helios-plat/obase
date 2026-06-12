"""Tests for obase.persistence.crud — async CRUD primitives.

Integration tests require PostgreSQL; auto-skip when unavailable.
Set TEST_PG_DSN env var or ensure postgresql://postgres:test@localhost:5432/obase_test.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from obase.persistence.crud import (
    insert_one,
    query,
    read_one,
    soft_delete_one,
    update_one,
    write_one,
)
from obase.persistence.pool import PgPool

TEST_DSN = os.environ.get("TEST_PG_DSN", "postgresql://postgres:test@localhost:5432/obase_test")
_SCHEMA = "test_crud"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_pool_registry():
    PgPool.clear()
    yield
    PgPool.clear()


@pytest.fixture
async def pg_pool():
    import asyncpg

    try:
        conn = await asyncpg.connect(TEST_DSN, timeout=3)
        await conn.close()
    except Exception:
        pytest.skip("PostgreSQL not available")

    pool = await PgPool.create(name="crud_integ", dsn=TEST_DSN, min_size=1, max_size=5)
    async with pool.acquire() as conn:
        await conn.execute(f"CREATE SCHEMA IF NOT EXISTS {_SCHEMA}")
    yield pool
    async with pool.acquire() as conn:
        await conn.execute(f"DROP SCHEMA IF EXISTS {_SCHEMA} CASCADE")
    await pool.close()


@pytest.fixture
async def items_table(pg_pool):
    """Create a simple items table with id, name, deleted_at."""
    async with pg_pool.acquire() as conn:
        await conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {_SCHEMA}.items (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                value INT DEFAULT 0,
                deleted_at TIMESTAMPTZ
            )
        """)
    return pg_pool


# ---------------------------------------------------------------------------
# Unit tests — validation (no DB)
# ---------------------------------------------------------------------------


class TestCrudValidation:
    async def test_insert_one_empty_data_raises(self):
        mock_pool = MagicMock()
        with pytest.raises(ValueError, match="must not be empty"):
            await insert_one(mock_pool, table="t", data={})

    async def test_update_one_empty_data_raises(self):
        mock_pool = MagicMock()
        with pytest.raises(ValueError, match="must not be empty"):
            await update_one(mock_pool, table="t", id="x", data={})


# ---------------------------------------------------------------------------
# Integration tests — insert_one
# ---------------------------------------------------------------------------


class TestInsertOne:
    async def test_insert_returns_id(self, items_table):
        result = await insert_one(
            items_table,
            table=f"{_SCHEMA}.items",
            data={"name": "alpha", "value": 10},
        )
        assert isinstance(result, int)
        assert result >= 1

    async def test_insert_multiple_distinct_ids(self, items_table):
        id1 = await insert_one(items_table, table=f"{_SCHEMA}.items", data={"name": "a"})
        id2 = await insert_one(items_table, table=f"{_SCHEMA}.items", data={"name": "b"})
        assert id1 != id2

    async def test_insert_custom_returning(self, items_table):
        await insert_one(items_table, table=f"{_SCHEMA}.items", data={"name": "x", "value": 99})
        result = await insert_one(
            items_table,
            table=f"{_SCHEMA}.items",
            data={"name": "y", "value": 42},
            returning="name",
        )
        assert result == "y"


# ---------------------------------------------------------------------------
# Integration tests — read_one
# ---------------------------------------------------------------------------


class TestReadOne:
    async def test_read_existing_row(self, items_table):
        row_id = await insert_one(items_table, table=f"{_SCHEMA}.items", data={"name": "read_me"})
        row = await read_one(items_table, table=f"{_SCHEMA}.items", id=row_id)
        assert row is not None
        assert row["name"] == "read_me"

    async def test_read_nonexistent_returns_none(self, items_table):
        row = await read_one(items_table, table=f"{_SCHEMA}.items", id=999999)
        assert row is None

    async def test_read_deleted_row_returns_none(self, items_table):
        row_id = await insert_one(items_table, table=f"{_SCHEMA}.items", data={"name": "gone"})
        await soft_delete_one(items_table, table=f"{_SCHEMA}.items", id=row_id)
        row = await read_one(items_table, table=f"{_SCHEMA}.items", id=row_id)
        assert row is None

    async def test_read_filters_deleted_at_null(self, items_table):
        active_id = await insert_one(items_table, table=f"{_SCHEMA}.items", data={"name": "active"})
        deleted_id = await insert_one(
            items_table, table=f"{_SCHEMA}.items", data={"name": "deleted"}
        )
        await soft_delete_one(items_table, table=f"{_SCHEMA}.items", id=deleted_id)

        assert await read_one(items_table, table=f"{_SCHEMA}.items", id=active_id) is not None
        assert await read_one(items_table, table=f"{_SCHEMA}.items", id=deleted_id) is None


# ---------------------------------------------------------------------------
# Integration tests — update_one
# ---------------------------------------------------------------------------


class TestUpdateOne:
    async def test_update_returns_true(self, items_table):
        row_id = await insert_one(items_table, table=f"{_SCHEMA}.items", data={"name": "before"})
        ok = await update_one(
            items_table, table=f"{_SCHEMA}.items", id=row_id, data={"name": "after"}
        )
        assert ok is True

    async def test_update_changes_value(self, items_table):
        row_id = await insert_one(
            items_table, table=f"{_SCHEMA}.items", data={"name": "orig", "value": 1}
        )
        await update_one(
            items_table, table=f"{_SCHEMA}.items", id=row_id, data={"value": 99}
        )
        row = await read_one(items_table, table=f"{_SCHEMA}.items", id=row_id)
        assert row is not None
        assert row["value"] == 99

    async def test_update_nonexistent_returns_false(self, items_table):
        ok = await update_one(
            items_table, table=f"{_SCHEMA}.items", id=999999, data={"name": "x"}
        )
        assert ok is False


# ---------------------------------------------------------------------------
# Integration tests — soft_delete_one
# ---------------------------------------------------------------------------


class TestSoftDeleteOne:
    async def test_soft_delete_returns_true(self, items_table):
        row_id = await insert_one(items_table, table=f"{_SCHEMA}.items", data={"name": "del"})
        ok = await soft_delete_one(items_table, table=f"{_SCHEMA}.items", id=row_id)
        assert ok is True

    async def test_soft_delete_idempotent(self, items_table):
        """Second soft_delete on already-deleted row returns False (WHERE deleted_at IS NULL)."""
        row_id = await insert_one(items_table, table=f"{_SCHEMA}.items", data={"name": "idm"})
        first = await soft_delete_one(items_table, table=f"{_SCHEMA}.items", id=row_id)
        second = await soft_delete_one(items_table, table=f"{_SCHEMA}.items", id=row_id)
        assert first is True
        assert second is False

    async def test_soft_delete_nonexistent_returns_false(self, items_table):
        ok = await soft_delete_one(items_table, table=f"{_SCHEMA}.items", id=999999)
        assert ok is False


# ---------------------------------------------------------------------------
# Integration tests — query
# ---------------------------------------------------------------------------


class TestQuery:
    async def test_query_returns_list_of_dicts(self, items_table):
        await insert_one(items_table, table=f"{_SCHEMA}.items", data={"name": "q1", "value": 1})
        await insert_one(items_table, table=f"{_SCHEMA}.items", data={"name": "q2", "value": 2})
        rows = await query(
            items_table, sql=f"SELECT name, value FROM {_SCHEMA}.items ORDER BY value"
        )
        assert len(rows) >= 2
        assert all(isinstance(r, dict) for r in rows)
        assert rows[0]["name"] == "q1"

    async def test_query_with_params(self, items_table):
        await insert_one(items_table, table=f"{_SCHEMA}.items", data={"name": "param_tgt"})
        rows = await query(
            items_table,
            sql=f"SELECT name FROM {_SCHEMA}.items WHERE name = $1",
            params=["param_tgt"],
        )
        assert len(rows) == 1
        assert rows[0]["name"] == "param_tgt"

    async def test_query_limit_respected(self, items_table):
        for i in range(10):
            await insert_one(items_table, table=f"{_SCHEMA}.items", data={"name": f"lim{i}"})
        rows = await query(
            items_table, sql=f"SELECT name FROM {_SCHEMA}.items", limit=3
        )
        assert len(rows) <= 3


# ---------------------------------------------------------------------------
# Integration tests — write_one
# ---------------------------------------------------------------------------


class TestWriteOne:
    async def test_write_one_inserts(self, items_table):
        n = await write_one(
            items_table,
            table=f"{_SCHEMA}.items",
            data={"name": "wo1"},
        )
        assert n == 1

    async def test_write_one_upsert_on_conflict(self, items_table):
        row_id = await insert_one(items_table, table=f"{_SCHEMA}.items", data={"name": "upsert"})
        n = await write_one(
            items_table,
            table=f"{_SCHEMA}.items",
            data={"id": row_id, "name": "upserted"},
            conflict_on=["id"],
        )
        assert n == 1
