"""Tests for obase.commerce_batch_schema — batch-warehouse commerce DDL.

Integration tests only (this module is pure DDL, nothing to unit-test without a
real database). Auto-skips when PostgreSQL is unavailable.
Set TEST_PG_DSN env var or ensure postgresql://postgres:test@localhost:5432/obase_test.
"""

from __future__ import annotations

import os

import pytest

from obase.commerce_batch_schema import (
    ensure_cart_line_item_table,
    ensure_cart_table,
    ensure_commerce_batch_schema,
    ensure_inventory_batch_table,
    ensure_product_table,
    ensure_product_variant_table,
    ensure_stock_location_table,
)
from obase.persistence.pool import PgPool

TEST_DSN = os.environ.get("TEST_PG_DSN", "postgresql://postgres:test@localhost:5432/obase_test")

_TABLES = [
    "stock_location",
    "product",
    "product_variant",
    "inventory_batch",
    "cart",
    "cart_line_item",
]


@pytest.fixture(autouse=True)
def clear_pool_registry():
    PgPool.clear()
    yield
    PgPool.clear()


@pytest.fixture
async def pg_pool():
    """Real PG pool; skip if Postgres unavailable. Drops the commerce tables after."""
    import asyncpg

    try:
        conn = await asyncpg.connect(TEST_DSN, timeout=3)
        await conn.close()
    except Exception:
        pytest.skip("PostgreSQL not available")

    pool = await PgPool.create(name="commerce_schema_integ", dsn=TEST_DSN, min_size=1, max_size=5)
    yield pool
    async with pool.acquire() as conn:
        for table in reversed(_TABLES):
            await conn.execute(f'DROP TABLE IF EXISTS "public"."{table}" CASCADE')
    await pool.close()


async def _table_exists(pool: PgPool, table: str) -> bool:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = $1",
            table,
        )
    return row is not None


async def _index_exists(pool: PgPool, index_name: str) -> bool:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT 1 FROM pg_indexes WHERE schemaname = 'public' AND indexname = $1",
            index_name,
        )
    return row is not None


class TestEnsureCommerceBatchSchema:
    async def test_creates_all_six_tables(self, pg_pool):
        await ensure_commerce_batch_schema(pg_pool)
        for table in _TABLES:
            assert await _table_exists(pg_pool, table), f"{table} was not created"

    async def test_creates_expected_indexes(self, pg_pool):
        await ensure_commerce_batch_schema(pg_pool)
        for idx in (
            "idx_variant_product",
            "idx_batch_variant_location_status",
            "idx_batch_location_status",
            "idx_line_item_cart",
            "uq_line_item_cart_batch",
        ):
            assert await _index_exists(pg_pool, idx), f"{idx} was not created"

    async def test_rerun_is_idempotent(self, pg_pool):
        await ensure_commerce_batch_schema(pg_pool)
        # Second run must not raise (IF NOT EXISTS guards throughout).
        await ensure_commerce_batch_schema(pg_pool)
        for table in _TABLES:
            assert await _table_exists(pg_pool, table)

    async def test_dependency_order_fk_constraints_hold(self, pg_pool):
        """product_variant.product_id → product.id must reject orphan inserts."""
        await ensure_commerce_batch_schema(pg_pool)
        async with pg_pool.acquire() as conn:
            with pytest.raises(Exception, match="(?i)foreign key|violates"):
                await conn.execute(
                    'INSERT INTO "public"."product_variant" '
                    "(id, product_id, sku_code) VALUES (gen_random_uuid(), gen_random_uuid(), $1)",
                    "ORPHAN-SKU",
                )

    async def test_cart_line_item_unique_constraint_per_cart_batch(self, pg_pool):
        """UNIQUE(cart_id, batch_id) WHERE deleted_at IS NULL must reject duplicate active rows."""
        await ensure_commerce_batch_schema(pg_pool)
        async with pg_pool.acquire() as conn:
            loc_id = await conn.fetchval(
                'INSERT INTO "public"."stock_location" (id, name, region_code) '
                "VALUES (gen_random_uuid(), 'loc', 'cn-east') RETURNING id"
            )
            prod_id = await conn.fetchval(
                'INSERT INTO "public"."product" (id, title, slug) '
                "VALUES (gen_random_uuid(), 'p', 'p-slug') RETURNING id"
            )
            variant_id = await conn.fetchval(
                'INSERT INTO "public"."product_variant" (id, product_id, sku_code) '
                "VALUES (gen_random_uuid(), $1, 'SKU-1') RETURNING id",
                prod_id,
            )
            batch_id = await conn.fetchval(
                'INSERT INTO "public"."inventory_batch" '
                "(id, batch_no, variant_id, location_id, video_url, cost_price_cents, "
                "retail_price_cents, stock_qty) "
                "VALUES (gen_random_uuid(), 'B1', $1, $2, 'https://x/v.mp4', 100, 200, 5) "
                "RETURNING id",
                variant_id,
                loc_id,
            )
            cart_id = await conn.fetchval(
                'INSERT INTO "public"."cart" (id) VALUES (gen_random_uuid()) RETURNING id'
            )
            await conn.execute(
                'INSERT INTO "public"."cart_line_item" '
                "(id, cart_id, batch_id, quantity, unit_price_cents, line_total_cents) "
                "VALUES (gen_random_uuid(), $1, $2, 1, 200, 200)",
                cart_id,
                batch_id,
            )
            with pytest.raises(Exception, match="(?i)duplicate|unique"):
                await conn.execute(
                    'INSERT INTO "public"."cart_line_item" '
                    "(id, cart_id, batch_id, quantity, unit_price_cents, line_total_cents) "
                    "VALUES (gen_random_uuid(), $1, $2, 1, 200, 200)",
                    cart_id,
                    batch_id,
                )


class TestIndividualTableCreators:
    """Each ensure_*_table function must be independently callable (used by
    callers that only need a subset, and exercised individually for
    fault-isolation when the combined test above fails)."""

    async def test_ensure_stock_location_table_standalone(self, pg_pool):
        await ensure_stock_location_table(pg_pool)
        assert await _table_exists(pg_pool, "stock_location")

    async def test_ensure_product_and_variant_tables_in_order(self, pg_pool):
        await ensure_product_table(pg_pool)
        await ensure_product_variant_table(pg_pool)
        assert await _table_exists(pg_pool, "product")
        assert await _table_exists(pg_pool, "product_variant")

    async def test_ensure_inventory_batch_requires_dependencies_first(self, pg_pool):
        await ensure_stock_location_table(pg_pool)
        await ensure_product_table(pg_pool)
        await ensure_product_variant_table(pg_pool)
        await ensure_inventory_batch_table(pg_pool)
        assert await _table_exists(pg_pool, "inventory_batch")

    async def test_ensure_cart_and_cart_line_item_tables(self, pg_pool):
        await ensure_stock_location_table(pg_pool)
        await ensure_product_table(pg_pool)
        await ensure_product_variant_table(pg_pool)
        await ensure_inventory_batch_table(pg_pool)
        await ensure_cart_table(pg_pool)
        await ensure_cart_line_item_table(pg_pool)
        assert await _table_exists(pg_pool, "cart")
        assert await _table_exists(pg_pool, "cart_line_item")
