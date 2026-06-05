"""Tests for obase.persistence — pool, transaction, upsert, vector, DDL.

Unit tests (no DB):  TestPgPoolRegistry, TestUpsertValidation
Integration tests:   TestTransaction, TestUpsertBatch, TestVectorSearch, TestDDL
  → require PostgreSQL with pgvector; skip automatically when unavailable.
  → set TEST_PG_DSN env var or ensure postgresql://postgres:test@localhost:5432/obase_test.
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from obase.persistence.ddl import (
    ensure_column,
    ensure_extension,
    ensure_index,
    ensure_table,
)
from obase.persistence.pool import PgPool
from obase.persistence.transaction import transaction
from obase.persistence.upsert import upsert_batch
from obase.persistence.vector import vector_search

TEST_DSN = os.environ.get("TEST_PG_DSN", "postgresql://postgres:test@localhost:5432/obase_test")
_SCHEMA = "test_persistence"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_pool_registry():
    """Reset PgPool class registry before and after every test."""
    PgPool.clear()
    yield
    PgPool.clear()


@pytest.fixture
def mock_asyncpg_pool() -> MagicMock:
    """Asyncpg pool mock with async .close()."""
    p = MagicMock()
    p.close = AsyncMock()
    return p


@pytest.fixture
async def pg_pool():
    """Real PG pool for integration tests; skip if Postgres unavailable."""
    import asyncpg

    try:
        conn = await asyncpg.connect(TEST_DSN, timeout=3)
        await conn.close()
    except Exception:
        pytest.skip("PostgreSQL not available")

    pool = await PgPool.create(name="integ", dsn=TEST_DSN, min_size=1, max_size=5)
    async with pool.acquire() as conn:
        await conn.execute(f"CREATE SCHEMA IF NOT EXISTS {_SCHEMA}")
    yield pool
    async with pool.acquire() as conn:
        await conn.execute(f"DROP SCHEMA IF EXISTS {_SCHEMA} CASCADE")
    await pool.close()


@pytest.fixture
async def pg_pool_vector():
    """Real PG pool with pgvector codec; skip if Postgres or pgvector unavailable."""
    import asyncpg

    try:
        conn = await asyncpg.connect(TEST_DSN, timeout=3)
        await conn.close()
    except Exception:
        pytest.skip("PostgreSQL not available")

    try:
        pool = await PgPool.create(
            name="vec_integ", dsn=TEST_DSN, min_size=1, max_size=5, enable_vector=True
        )
    except Exception:
        pytest.skip("pgvector extension or codec not available")

    async with pool.acquire() as conn:
        await conn.execute(f"CREATE SCHEMA IF NOT EXISTS {_SCHEMA}")
        await conn.execute('CREATE EXTENSION IF NOT EXISTS "vector"')
    yield pool
    async with pool.acquire() as conn:
        await conn.execute(f"DROP SCHEMA IF EXISTS {_SCHEMA} CASCADE")
    await pool.close()


# ---------------------------------------------------------------------------
# TestPgPoolRegistry — unit tests (mocked asyncpg)
# ---------------------------------------------------------------------------


class TestPgPoolRegistry:
    async def test_create_registers_pool(self, mock_asyncpg_pool):
        with patch("asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_asyncpg_pool):
            pool = await PgPool.create(name="mypool", dsn="postgresql://x")
        assert pool.name == "mypool"
        assert PgPool.get("mypool") is pool

    async def test_create_duplicate_name_raises(self, mock_asyncpg_pool):
        with patch("asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_asyncpg_pool):
            await PgPool.create(name="dup", dsn="postgresql://x")
            with pytest.raises(ValueError, match="already registered"):
                await PgPool.create(name="dup", dsn="postgresql://x")

    async def test_get_registered_returns_instance(self, mock_asyncpg_pool):
        with patch("asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_asyncpg_pool):
            pool = await PgPool.create(name="getme", dsn="postgresql://x")
        assert PgPool.get("getme") is pool

    async def test_get_unknown_raises_key_error(self):
        with pytest.raises(KeyError, match="not registered"):
            PgPool.get("ghost")

    async def test_list_pools_returns_all_names(self, mock_asyncpg_pool):
        with patch("asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_asyncpg_pool):
            await PgPool.create(name="a", dsn="postgresql://x")
            await PgPool.create(name="b", dsn="postgresql://x")
        assert set(PgPool.list_pools()) == {"a", "b"}

    async def test_close_removes_from_registry(self, mock_asyncpg_pool):
        with patch("asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_asyncpg_pool):
            pool = await PgPool.create(name="goodbye", dsn="postgresql://x")
        await pool.close()
        assert "goodbye" not in PgPool.list_pools()
        mock_asyncpg_pool.close.assert_awaited_once()


# ---------------------------------------------------------------------------
# TestUpsertValidation — unit tests, no DB needed
# ---------------------------------------------------------------------------


class TestUpsertValidation:
    async def test_empty_rows_raises(self, mock_asyncpg_pool):
        with patch("asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_asyncpg_pool):
            pool = await PgPool.create(name="v", dsn="postgresql://x")
        with pytest.raises(ValueError, match="non-empty"):
            await upsert_batch(pool=pool, table="t", rows=[], conflict_columns=["id"])

    async def test_inconsistent_columns_raises(self, mock_asyncpg_pool):
        with patch("asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_asyncpg_pool):
            pool = await PgPool.create(name="v2", dsn="postgresql://x")
        rows: list[dict[str, Any]] = [{"id": 1, "val": "a"}, {"id": 2, "other": "b"}]
        with pytest.raises(ValueError, match="columns differ"):
            await upsert_batch(pool=pool, table="t", rows=rows, conflict_columns=["id"])


# ---------------------------------------------------------------------------
# TestTransaction — integration
# ---------------------------------------------------------------------------


class TestTransaction:
    async def test_commit_on_exit(self, pg_pool):
        async with pg_pool.acquire() as conn:
            await conn.execute(f"CREATE TABLE IF NOT EXISTS {_SCHEMA}.tx_test (id INT PRIMARY KEY)")
        async with transaction(pg_pool) as tx:
            await tx.execute(f"INSERT INTO {_SCHEMA}.tx_test VALUES (1)")
        async with pg_pool.acquire() as conn:
            row = await conn.fetchrow(f"SELECT id FROM {_SCHEMA}.tx_test WHERE id = 1")
        assert row is not None and row["id"] == 1

    async def test_rollback_on_exception(self, pg_pool):
        async with pg_pool.acquire() as conn:
            await conn.execute(
                f"CREATE TABLE IF NOT EXISTS {_SCHEMA}.tx_rollback (id INT PRIMARY KEY)"
            )
        with pytest.raises(RuntimeError):
            async with transaction(pg_pool) as tx:
                await tx.execute(f"INSERT INTO {_SCHEMA}.tx_rollback VALUES (99)")
                raise RuntimeError("abort")
        async with pg_pool.acquire() as conn:
            count = await conn.fetchval(f"SELECT COUNT(*) FROM {_SCHEMA}.tx_rollback")
        assert count == 0

    async def test_nested_savepoint(self, pg_pool):
        async with pg_pool.acquire() as conn:
            await conn.execute(
                f"CREATE TABLE IF NOT EXISTS {_SCHEMA}.tx_nested (id INT PRIMARY KEY)"
            )
        async with transaction(pg_pool) as outer:
            await outer.execute(f"INSERT INTO {_SCHEMA}.tx_nested VALUES (1)")
            async with outer.transaction():
                await outer.execute(f"INSERT INTO {_SCHEMA}.tx_nested VALUES (2)")
        async with pg_pool.acquire() as conn:
            count = await conn.fetchval(f"SELECT COUNT(*) FROM {_SCHEMA}.tx_nested")
        assert count == 2

    async def test_multi_statement_in_transaction(self, pg_pool):
        async with pg_pool.acquire() as conn:
            await conn.execute(
                f"CREATE TABLE IF NOT EXISTS {_SCHEMA}.tx_multi (id INT PRIMARY KEY, v TEXT)"
            )
        async with transaction(pg_pool) as tx:
            await tx.execute(f"INSERT INTO {_SCHEMA}.tx_multi VALUES (1, 'a')")
            await tx.execute(f"INSERT INTO {_SCHEMA}.tx_multi VALUES (2, 'b')")
            await tx.execute(f"UPDATE {_SCHEMA}.tx_multi SET v = 'A' WHERE id = 1")
        async with pg_pool.acquire() as conn:
            row = await conn.fetchrow(f"SELECT v FROM {_SCHEMA}.tx_multi WHERE id = 1")
        assert row["v"] == "A"


# ---------------------------------------------------------------------------
# TestUpsertBatch — integration
# ---------------------------------------------------------------------------


class TestUpsertBatch:
    async def _setup_table(self, pool, name="upsert_t"):
        async with pool.acquire() as conn:
            await conn.execute(
                f"CREATE TABLE IF NOT EXISTS {_SCHEMA}.{name} (id INT PRIMARY KEY, val TEXT)"
            )

    async def test_insert_new_rows(self, pg_pool):
        await self._setup_table(pg_pool)
        n = await upsert_batch(
            pool=pg_pool,
            table=f"{_SCHEMA}.upsert_t",
            rows=[{"id": 1, "val": "x"}, {"id": 2, "val": "y"}],
            conflict_columns=["id"],
            update_columns=["val"],
        )
        assert n == 2

    async def test_conflict_updates_row(self, pg_pool):
        await self._setup_table(pg_pool, "upsert_upd")
        await upsert_batch(
            pool=pg_pool,
            table=f"{_SCHEMA}.upsert_upd",
            rows=[{"id": 1, "val": "old"}],
            conflict_columns=["id"],
            update_columns=["val"],
        )
        await upsert_batch(
            pool=pg_pool,
            table=f"{_SCHEMA}.upsert_upd",
            rows=[{"id": 1, "val": "new"}],
            conflict_columns=["id"],
            update_columns=["val"],
        )
        async with pg_pool.acquire() as conn:
            row = await conn.fetchrow(f"SELECT val FROM {_SCHEMA}.upsert_upd WHERE id = 1")
        assert row["val"] == "new"

    async def test_conflict_do_nothing(self, pg_pool):
        await self._setup_table(pg_pool, "upsert_nothing")
        await upsert_batch(
            pool=pg_pool,
            table=f"{_SCHEMA}.upsert_nothing",
            rows=[{"id": 1, "val": "original"}],
            conflict_columns=["id"],
        )
        await upsert_batch(
            pool=pg_pool,
            table=f"{_SCHEMA}.upsert_nothing",
            rows=[{"id": 1, "val": "ignored"}],
            conflict_columns=["id"],
            update_columns=None,
        )
        async with pg_pool.acquire() as conn:
            row = await conn.fetchrow(f"SELECT val FROM {_SCHEMA}.upsert_nothing WHERE id = 1")
        assert row["val"] == "original"

    async def test_batch_100_rows(self, pg_pool):
        async with pg_pool.acquire() as conn:
            await conn.execute(
                f"CREATE TABLE IF NOT EXISTS {_SCHEMA}.upsert_bulk (id INT PRIMARY KEY, val TEXT)"
            )
        rows = [{"id": i, "val": f"v{i}"} for i in range(100)]
        n = await upsert_batch(
            pool=pg_pool,
            table=f"{_SCHEMA}.upsert_bulk",
            rows=rows,
            conflict_columns=["id"],
            update_columns=["val"],
        )
        assert n == 100


# ---------------------------------------------------------------------------
# TestVectorSearch — integration (requires pgvector)
# ---------------------------------------------------------------------------


class TestVectorSearch:
    async def _setup_vec_table(self, pool, name="vec_t", dim=3):
        async with pool.acquire() as conn:
            await conn.execute(
                f"CREATE TABLE IF NOT EXISTS {_SCHEMA}.{name} "
                f"(id INT PRIMARY KEY, label TEXT, embedding vector({dim}))"
            )

    async def _insert_vecs(self, pool, name, rows):
        for row in rows:
            vec = "[" + ",".join(str(x) for x in row["embedding"]) + "]"
            async with pool.acquire() as conn:
                await conn.execute(
                    f"INSERT INTO {_SCHEMA}.{name} (id, label, embedding) "
                    f"VALUES ($1, $2, $3::vector)",
                    row["id"],
                    row["label"],
                    vec,
                )

    async def test_cosine_results_ascending(self, pg_pool_vector):
        await self._setup_vec_table(pg_pool_vector)
        await self._insert_vecs(
            pg_pool_vector,
            "vec_t",
            [
                {"id": 1, "label": "identical", "embedding": [1.0, 0.0, 0.0]},
                {"id": 2, "label": "close", "embedding": [0.9, 0.1, 0.0]},
                {"id": 3, "label": "far", "embedding": [0.0, 0.0, 1.0]},
            ],
        )
        results = await vector_search(
            pool=pg_pool_vector,
            table=f"{_SCHEMA}.vec_t",
            vector_column="embedding",
            query_vector=[1.0, 0.0, 0.0],
            metric="cosine",
            top_k=3,
            select_columns=["id", "label"],
        )
        assert len(results) == 3
        distances = [r["distance"] for r in results]
        assert distances == sorted(distances)
        assert results[0]["id"] == 1

    async def test_l2_metric(self, pg_pool_vector):
        await self._setup_vec_table(pg_pool_vector, "vec_l2")
        await self._insert_vecs(
            pg_pool_vector,
            "vec_l2",
            [
                {"id": 1, "label": "near", "embedding": [1.0, 0.0, 0.0]},
                {"id": 2, "label": "far", "embedding": [10.0, 10.0, 10.0]},
            ],
        )
        results = await vector_search(
            pool=pg_pool_vector,
            table=f"{_SCHEMA}.vec_l2",
            vector_column="embedding",
            query_vector=[1.0, 0.0, 0.0],
            metric="l2",
            top_k=2,
            select_columns=["id"],
        )
        assert results[0]["id"] == 1

    async def test_inner_product_metric(self, pg_pool_vector):
        await self._setup_vec_table(pg_pool_vector, "vec_ip")
        await self._insert_vecs(
            pg_pool_vector,
            "vec_ip",
            [
                {"id": 1, "label": "high", "embedding": [5.0, 0.0, 0.0]},
                {"id": 2, "label": "low", "embedding": [1.0, 0.0, 0.0]},
            ],
        )
        results = await vector_search(
            pool=pg_pool_vector,
            table=f"{_SCHEMA}.vec_ip",
            vector_column="embedding",
            query_vector=[1.0, 0.0, 0.0],
            metric="inner_product",
            top_k=2,
            select_columns=["id"],
        )
        # <#> returns negative inner product; smaller = higher similarity
        assert results[0]["id"] == 1

    async def test_filter_sql_restricts_results(self, pg_pool_vector):
        await self._setup_vec_table(pg_pool_vector, "vec_filter")
        await self._insert_vecs(
            pg_pool_vector,
            "vec_filter",
            [
                {"id": 1, "label": "keep", "embedding": [1.0, 0.0, 0.0]},
                {"id": 2, "label": "drop", "embedding": [1.0, 0.0, 0.0]},
            ],
        )
        results = await vector_search(
            pool=pg_pool_vector,
            table=f"{_SCHEMA}.vec_filter",
            vector_column="embedding",
            query_vector=[1.0, 0.0, 0.0],
            metric="cosine",
            top_k=10,
            filter_sql="label = $2",
            filter_params=["keep"],
            select_columns=["id", "label"],
        )
        assert len(results) == 1
        assert results[0]["label"] == "keep"

    async def test_select_columns_limits_fields(self, pg_pool_vector):
        await self._setup_vec_table(pg_pool_vector, "vec_sel")
        await self._insert_vecs(
            pg_pool_vector,
            "vec_sel",
            [{"id": 1, "label": "a", "embedding": [1.0, 0.0, 0.0]}],
        )
        results = await vector_search(
            pool=pg_pool_vector,
            table=f"{_SCHEMA}.vec_sel",
            vector_column="embedding",
            query_vector=[1.0, 0.0, 0.0],
            top_k=1,
            select_columns=["id"],
        )
        assert "label" not in results[0]
        assert "distance" in results[0]

    async def test_empty_table_returns_empty_list(self, pg_pool_vector):
        await self._setup_vec_table(pg_pool_vector, "vec_empty")
        results = await vector_search(
            pool=pg_pool_vector,
            table=f"{_SCHEMA}.vec_empty",
            vector_column="embedding",
            query_vector=[1.0, 0.0, 0.0],
            top_k=5,
            select_columns=["id"],
        )
        assert results == []


# ---------------------------------------------------------------------------
# TestDDL — integration
# ---------------------------------------------------------------------------


class TestDDL:
    async def test_ensure_table_creates(self, pg_pool):
        await ensure_table(
            pool=pg_pool,
            schema=_SCHEMA,
            table="ddl_new",
            columns=[("id", "UUID PRIMARY KEY"), ("body", "TEXT NOT NULL")],
        )
        async with pg_pool.acquire() as conn:
            exists = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM information_schema.tables "
                "WHERE table_schema=$1 AND table_name=$2)",
                _SCHEMA,
                "ddl_new",
            )
        assert exists is True

    async def test_ensure_table_idempotent(self, pg_pool):
        for _ in range(2):
            await ensure_table(
                pool=pg_pool,
                schema=_SCHEMA,
                table="ddl_idem",
                columns=[("id", "INT PRIMARY KEY")],
            )
        # No exception raised = idempotent

    async def test_ensure_column_adds(self, pg_pool):
        await ensure_table(
            pool=pg_pool,
            schema=_SCHEMA,
            table="ddl_col",
            columns=[("id", "INT PRIMARY KEY")],
        )
        await ensure_column(
            pool=pg_pool,
            schema=_SCHEMA,
            table="ddl_col",
            column_name="new_col",
            column_def="TEXT",
        )
        async with pg_pool.acquire() as conn:
            exists = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM information_schema.columns "
                "WHERE table_schema=$1 AND table_name=$2 AND column_name=$3)",
                _SCHEMA,
                "ddl_col",
                "new_col",
            )
        assert exists is True

    async def test_ensure_column_idempotent(self, pg_pool):
        await ensure_table(
            pool=pg_pool,
            schema=_SCHEMA,
            table="ddl_col_idem",
            columns=[("id", "INT PRIMARY KEY")],
        )
        for _ in range(2):
            await ensure_column(
                pool=pg_pool,
                schema=_SCHEMA,
                table="ddl_col_idem",
                column_name="extra",
                column_def="TEXT",
            )
        # No exception = idempotent

    async def test_ensure_index_btree(self, pg_pool):
        await ensure_table(
            pool=pg_pool,
            schema=_SCHEMA,
            table="ddl_idx_bt",
            columns=[("id", "INT PRIMARY KEY"), ("created_at", "TIMESTAMPTZ")],
        )
        await ensure_index(
            pool=pg_pool,
            schema=_SCHEMA,
            table="ddl_idx_bt",
            index_name="idx_ddl_created",
            columns="created_at",
            using="btree",
        )
        async with pg_pool.acquire() as conn:
            exists = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM pg_indexes "
                "WHERE schemaname=$1 AND tablename=$2 AND indexname=$3)",
                _SCHEMA,
                "ddl_idx_bt",
                "idx_ddl_created",
            )
        assert exists is True

    async def test_ensure_index_hnsw(self, pg_pool_vector):
        await ensure_extension(pool=pg_pool_vector, extension="vector")
        await ensure_table(
            pool=pg_pool_vector,
            schema=_SCHEMA,
            table="ddl_idx_hnsw",
            columns=[("id", "INT PRIMARY KEY"), ("emb", "vector(4)")],
        )
        await ensure_index(
            pool=pg_pool_vector,
            schema=_SCHEMA,
            table="ddl_idx_hnsw",
            index_name="idx_ddl_emb_hnsw",
            columns="emb vector_cosine_ops",
            using="hnsw",
            options={"m": 16, "ef_construction": 64},
        )
        async with pg_pool_vector.acquire() as conn:
            exists = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM pg_indexes "
                "WHERE schemaname=$1 AND tablename=$2 AND indexname=$3)",
                _SCHEMA,
                "ddl_idx_hnsw",
                "idx_ddl_emb_hnsw",
            )
        assert exists is True

    async def test_ensure_index_idempotent(self, pg_pool):
        await ensure_table(
            pool=pg_pool,
            schema=_SCHEMA,
            table="ddl_idx_idem",
            columns=[("id", "INT PRIMARY KEY")],
        )
        for _ in range(2):
            await ensure_index(
                pool=pg_pool,
                schema=_SCHEMA,
                table="ddl_idx_idem",
                index_name="idx_ddl_idem",
                columns="id",
                using="btree",
            )
        # No exception = idempotent

    async def test_ensure_extension_vector(self, pg_pool_vector):
        # Should not raise even when already installed
        await ensure_extension(pool=pg_pool_vector, extension="vector")
