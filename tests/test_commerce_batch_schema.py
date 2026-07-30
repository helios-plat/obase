"""Tests for obase.commerce_batch_schema — batch-warehouse commerce DDL.

Integration tests only (this module is pure DDL, nothing to unit-test without a
real database). Auto-skips when PostgreSQL is unavailable.
Set TEST_PG_DSN env var or ensure postgresql://postgres:test@localhost:5432/obase_test.
"""

from __future__ import annotations

import os

import pytest

from obase.commerce_batch_schema import (
    ensure_app_user_table,
    ensure_cart_address_columns,
    ensure_cart_discount_table,
    ensure_cart_gift_card_table,
    ensure_cart_line_item_table,
    ensure_cart_table,
    ensure_commerce_batch_schema,
    ensure_customer_address_table,
    ensure_customer_group_table,
    ensure_customer_order_table,
    ensure_customer_table,
    ensure_discount_condition_table,
    ensure_discount_rule_table,
    ensure_discount_table,
    ensure_gift_card_table,
    ensure_inventory_batch_table,
    ensure_order_line_item_table,
    ensure_payment_session_table,
    ensure_price_list_item_table,
    ensure_price_list_table,
    ensure_product_category_table,
    ensure_product_collection_item_table,
    ensure_product_collection_table,
    ensure_product_option_table,
    ensure_product_table,
    ensure_product_variant_table,
    ensure_region_table,
    ensure_sales_channel_product_table,
    ensure_sales_channel_table,
    ensure_stock_location_table,
    ensure_tax_rate_table,
)
from obase.persistence.pool import PgPool

TEST_DSN = os.environ.get("TEST_PG_DSN", "postgresql://postgres:test@localhost:5432/obase_test")

_TABLES = [
    "region",
    "tax_rate",
    "app_user",
    "customer_group",
    "customer",
    "customer_address",
    "stock_location",
    "product",
    "product_variant",
    "product_option",
    "product_category",
    "product_collection",
    "product_collection_item",
    "price_list",
    "price_list_item",
    "sales_channel",
    "sales_channel_product",
    "inventory_batch",
    "cart",
    "cart_line_item",
    "discount",
    "discount_rule",
    "discount_condition",
    "gift_card",
    "cart_discount",
    "cart_gift_card",
    "payment_session",
    "customer_order",
    "order_line_item",
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
            "idx_discount_condition_discount",
            "idx_cart_discount_cart",
            "uq_cart_discount_active",
            "idx_cart_gift_card_cart",
            "uq_cart_gift_card_active",
            "idx_payment_session_cart",
            "uq_payment_session_cart_provider",
            "idx_order_line_item_order",
            "idx_tax_rate_region",
            "idx_customer_group",
            "idx_customer_address_customer",
            "idx_product_option_product",
            "idx_product_category_parent",
            "uq_collection_item_collection_product",
            "uq_price_list_item_list_variant",
            "uq_sales_channel_product_channel_product",
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


class TestCartAddressColumns:
    async def test_columns_added_and_writable(self, pg_pool):
        # asyncpg has no automatic dict<->jsonb codec registered on this pool,
        # so both write and read go through explicit json.dumps/json.loads —
        # exactly what omodul callers must do too (see create_inventory_batch's
        # media_assets column for the existing precedent).
        import json

        await ensure_cart_table(pg_pool)
        await ensure_cart_address_columns(pg_pool)
        async with pg_pool.acquire() as conn:
            cart_id = await conn.fetchval(
                'INSERT INTO "public"."cart" (id) VALUES (gen_random_uuid()) RETURNING id'
            )
            await conn.execute(
                'UPDATE "public"."cart" SET billing_address = $1, shipping_address = $2 '
                "WHERE id = $3",
                json.dumps({"city": "Shanghai"}),
                json.dumps({"city": "Beijing"}),
                cart_id,
            )
            row = await conn.fetchrow(
                'SELECT billing_address, shipping_address FROM "public"."cart" WHERE id = $1',
                cart_id,
            )
        assert json.loads(row["billing_address"]) == {"city": "Shanghai"}
        assert json.loads(row["shipping_address"]) == {"city": "Beijing"}

    async def test_rerun_is_idempotent(self, pg_pool):
        await ensure_cart_table(pg_pool)
        await ensure_cart_address_columns(pg_pool)
        await ensure_cart_address_columns(pg_pool)  # must not raise


class TestDiscountAndGiftCardTables:
    async def test_discount_rule_type_check_constraint(self, pg_pool):
        await ensure_commerce_batch_schema(pg_pool)
        async with pg_pool.acquire() as conn:
            discount_id = await conn.fetchval(
                'INSERT INTO "public"."discount" (id, code) '
                "VALUES (gen_random_uuid(), 'SAVE10') RETURNING id"
            )
            with pytest.raises(Exception, match="(?i)check constraint|violates"):
                await conn.execute(
                    'INSERT INTO "public"."discount_rule" (id, discount_id, rule_type) '
                    "VALUES (gen_random_uuid(), $1, 'bogus_type')",
                    discount_id,
                )

    async def test_discount_rule_unique_per_discount(self, pg_pool):
        """One discount can only have one rule row (1:1)."""
        await ensure_commerce_batch_schema(pg_pool)
        async with pg_pool.acquire() as conn:
            discount_id = await conn.fetchval(
                'INSERT INTO "public"."discount" (id, code) '
                "VALUES (gen_random_uuid(), 'SAVE20') RETURNING id"
            )
            await conn.execute(
                'INSERT INTO "public"."discount_rule" '
                "(id, discount_id, rule_type, amount_cents) "
                "VALUES (gen_random_uuid(), $1, 'fixed', 500)",
                discount_id,
            )
            with pytest.raises(Exception, match="(?i)duplicate|unique"):
                await conn.execute(
                    'INSERT INTO "public"."discount_rule" '
                    "(id, discount_id, rule_type, percent) "
                    "VALUES (gen_random_uuid(), $1, 'percentage', 10)",
                    discount_id,
                )

    async def test_gift_card_balance_cannot_exceed_initial(self, pg_pool):
        await ensure_commerce_batch_schema(pg_pool)
        async with pg_pool.acquire() as conn:
            with pytest.raises(Exception, match="(?i)check constraint|violates"):
                await conn.execute(
                    'INSERT INTO "public"."gift_card" '
                    "(id, code, initial_balance_cents, balance_cents) "
                    "VALUES (gen_random_uuid(), 'GC1', 1000, 1500)"
                )

    async def test_cart_discount_rejects_duplicate_active_application(self, pg_pool):
        await ensure_commerce_batch_schema(pg_pool)
        async with pg_pool.acquire() as conn:
            cart_id = await conn.fetchval(
                'INSERT INTO "public"."cart" (id) VALUES (gen_random_uuid()) RETURNING id'
            )
            discount_id = await conn.fetchval(
                'INSERT INTO "public"."discount" (id, code) '
                "VALUES (gen_random_uuid(), 'SAVE5') RETURNING id"
            )
            await conn.execute(
                'INSERT INTO "public"."cart_discount" '
                "(id, cart_id, discount_id, applied_amount_cents) "
                "VALUES (gen_random_uuid(), $1, $2, 500)",
                cart_id,
                discount_id,
            )
            with pytest.raises(Exception, match="(?i)duplicate|unique"):
                await conn.execute(
                    'INSERT INTO "public"."cart_discount" '
                    "(id, cart_id, discount_id, applied_amount_cents) "
                    "VALUES (gen_random_uuid(), $1, $2, 500)",
                    cart_id,
                    discount_id,
                )

    async def test_cart_gift_card_rejects_duplicate_active_application(self, pg_pool):
        await ensure_commerce_batch_schema(pg_pool)
        async with pg_pool.acquire() as conn:
            cart_id = await conn.fetchval(
                'INSERT INTO "public"."cart" (id) VALUES (gen_random_uuid()) RETURNING id'
            )
            gift_card_id = await conn.fetchval(
                'INSERT INTO "public"."gift_card" '
                "(id, code, initial_balance_cents, balance_cents) "
                "VALUES (gen_random_uuid(), 'GC2', 1000, 1000) RETURNING id"
            )
            await conn.execute(
                'INSERT INTO "public"."cart_gift_card" '
                "(id, cart_id, gift_card_id, applied_amount_cents) "
                "VALUES (gen_random_uuid(), $1, $2, 300)",
                cart_id,
                gift_card_id,
            )
            with pytest.raises(Exception, match="(?i)duplicate|unique"):
                await conn.execute(
                    'INSERT INTO "public"."cart_gift_card" '
                    "(id, cart_id, gift_card_id, applied_amount_cents) "
                    "VALUES (gen_random_uuid(), $1, $2, 300)",
                    cart_id,
                    gift_card_id,
                )

    async def test_discount_condition_allows_multiple_rows_per_discount(self, pg_pool):
        await ensure_commerce_batch_schema(pg_pool)
        async with pg_pool.acquire() as conn:
            discount_id = await conn.fetchval(
                'INSERT INTO "public"."discount" (id, code) '
                "VALUES (gen_random_uuid(), 'MULTI') RETURNING id"
            )
            for _ in range(2):
                await conn.execute(
                    'INSERT INTO "public"."discount_condition" '
                    "(id, discount_id, condition_type, target_id) "
                    "VALUES (gen_random_uuid(), $1, 'product', gen_random_uuid())",
                    discount_id,
                )
            rows = await conn.fetch(
                'SELECT * FROM "public"."discount_condition" WHERE discount_id = $1', discount_id
            )
        assert len(rows) == 2


class TestPaymentSessionTable:
    async def test_status_check_constraint_rejects_bogus_status(self, pg_pool):
        await ensure_commerce_batch_schema(pg_pool)
        async with pg_pool.acquire() as conn:
            cart_id = await conn.fetchval(
                'INSERT INTO "public"."cart" (id) VALUES (gen_random_uuid()) RETURNING id'
            )
            with pytest.raises(Exception, match="(?i)check constraint|violates"):
                await conn.execute(
                    'INSERT INTO "public"."payment_session" '
                    "(id, cart_id, provider_name, amount_cents, currency, status) "
                    "VALUES (gen_random_uuid(), $1, 'manual', 100, 'CNY', 'bogus')",
                    cart_id,
                )

    async def test_rejects_duplicate_active_session_per_provider(self, pg_pool):
        await ensure_commerce_batch_schema(pg_pool)
        async with pg_pool.acquire() as conn:
            cart_id = await conn.fetchval(
                'INSERT INTO "public"."cart" (id) VALUES (gen_random_uuid()) RETURNING id'
            )
            await conn.execute(
                'INSERT INTO "public"."payment_session" '
                "(id, cart_id, provider_name, amount_cents, currency) "
                "VALUES (gen_random_uuid(), $1, 'manual', 100, 'CNY')",
                cart_id,
            )
            with pytest.raises(Exception, match="(?i)duplicate|unique"):
                await conn.execute(
                    'INSERT INTO "public"."payment_session" '
                    "(id, cart_id, provider_name, amount_cents, currency) "
                    "VALUES (gen_random_uuid(), $1, 'manual', 200, 'CNY')",
                    cart_id,
                )

    async def test_default_status_is_authorized(self, pg_pool):
        await ensure_commerce_batch_schema(pg_pool)
        async with pg_pool.acquire() as conn:
            cart_id = await conn.fetchval(
                'INSERT INTO "public"."cart" (id) VALUES (gen_random_uuid()) RETURNING id'
            )
            status = await conn.fetchval(
                'INSERT INTO "public"."payment_session" '
                "(id, cart_id, provider_name, amount_cents, currency) "
                "VALUES (gen_random_uuid(), $1, 'manual', 100, 'CNY') RETURNING status",
                cart_id,
            )
        assert status == "authorized"


class TestRegionAndTaxRateTables:
    async def test_region_code_is_the_primary_key(self, pg_pool):
        await ensure_commerce_batch_schema(pg_pool)
        async with pg_pool.acquire() as conn:
            await conn.execute(
                'INSERT INTO "public"."region" (code, name, currency) '
                "VALUES ('cn-east', '华东', 'CNY')"
            )
            with pytest.raises(Exception, match="(?i)duplicate|unique"):
                await conn.execute(
                    'INSERT INTO "public"."region" (code, name, currency) '
                    "VALUES ('cn-east', '华东2', 'CNY')"
                )

    async def test_tax_rate_fk_to_region_code(self, pg_pool):
        await ensure_commerce_batch_schema(pg_pool)
        async with pg_pool.acquire() as conn:
            with pytest.raises(Exception, match="(?i)foreign key|violates"):
                await conn.execute(
                    'INSERT INTO "public"."tax_rate" (id, region_code, name, rate_percent) '
                    "VALUES (gen_random_uuid(), 'ghost-region', 'VAT', 10)"
                )

    async def test_tax_rate_percent_bounds(self, pg_pool):
        await ensure_commerce_batch_schema(pg_pool)
        async with pg_pool.acquire() as conn:
            await conn.execute(
                'INSERT INTO "public"."region" (code, name, currency) '
                "VALUES ('cn-south', '华南', 'CNY')"
            )
            with pytest.raises(Exception, match="(?i)check constraint|violates"):
                await conn.execute(
                    'INSERT INTO "public"."tax_rate" (id, region_code, name, rate_percent) '
                    "VALUES (gen_random_uuid(), 'cn-south', 'VAT', 101)"
                )

    async def test_region_defaults(self, pg_pool):
        await ensure_commerce_batch_schema(pg_pool)
        async with pg_pool.acquire() as conn:
            row = await conn.fetchrow(
                'INSERT INTO "public"."region" (code, name, currency) '
                "VALUES ('cn-north', '华北', 'CNY') RETURNING status, payment_provider_names"
            )
        assert row["status"] == "active"
        assert row["payment_provider_names"] == []


class TestPricingAndChannelTables:
    async def test_price_list_item_fk_and_unique(self, pg_pool):
        await ensure_commerce_batch_schema(pg_pool)
        async with pg_pool.acquire() as conn:
            price_list_id = await conn.fetchval(
                'INSERT INTO "public"."price_list" (id, name, currency) '
                "VALUES (gen_random_uuid(), 'Sale', 'CNY') RETURNING id"
            )
            prod_id = await conn.fetchval(
                'INSERT INTO "public"."product" (id, title, slug) '
                "VALUES (gen_random_uuid(), 'p', 'p-slug-price') RETURNING id"
            )
            variant_id = await conn.fetchval(
                'INSERT INTO "public"."product_variant" (id, product_id, sku_code) '
                "VALUES (gen_random_uuid(), $1, 'SKU-PRICE-1') RETURNING id",
                prod_id,
            )
            await conn.execute(
                'INSERT INTO "public"."price_list_item" '
                "(id, price_list_id, variant_id, price_cents) "
                "VALUES (gen_random_uuid(), $1, $2, 1000)",
                price_list_id,
                variant_id,
            )
            with pytest.raises(Exception, match="(?i)duplicate|unique"):
                await conn.execute(
                    'INSERT INTO "public"."price_list_item" '
                    "(id, price_list_id, variant_id, price_cents) "
                    "VALUES (gen_random_uuid(), $1, $2, 1200)",
                    price_list_id,
                    variant_id,
                )

    async def test_sales_channel_product_fk_and_unique(self, pg_pool):
        await ensure_commerce_batch_schema(pg_pool)
        async with pg_pool.acquire() as conn:
            channel_id = await conn.fetchval(
                'INSERT INTO "public"."sales_channel" (id, name) '
                "VALUES (gen_random_uuid(), 'Storefront') RETURNING id"
            )
            prod_id = await conn.fetchval(
                'INSERT INTO "public"."product" (id, title, slug) '
                "VALUES (gen_random_uuid(), 'p', 'p-slug-channel') RETURNING id"
            )
            await conn.execute(
                'INSERT INTO "public"."sales_channel_product" (id, channel_id, product_id) '
                "VALUES (gen_random_uuid(), $1, $2)",
                channel_id,
                prod_id,
            )
            with pytest.raises(Exception, match="(?i)duplicate|unique"):
                await conn.execute(
                    'INSERT INTO "public"."sales_channel_product" (id, channel_id, product_id) '
                    "VALUES (gen_random_uuid(), $1, $2)",
                    channel_id,
                    prod_id,
                )

    async def test_price_list_item_negative_price_rejected(self, pg_pool):
        await ensure_commerce_batch_schema(pg_pool)
        async with pg_pool.acquire() as conn:
            price_list_id = await conn.fetchval(
                'INSERT INTO "public"."price_list" (id, name, currency) '
                "VALUES (gen_random_uuid(), 'Sale2', 'CNY') RETURNING id"
            )
            prod_id = await conn.fetchval(
                'INSERT INTO "public"."product" (id, title, slug) '
                "VALUES (gen_random_uuid(), 'p', 'p-slug-price2') RETURNING id"
            )
            variant_id = await conn.fetchval(
                'INSERT INTO "public"."product_variant" (id, product_id, sku_code) '
                "VALUES (gen_random_uuid(), $1, 'SKU-PRICE-2') RETURNING id",
                prod_id,
            )
            with pytest.raises(Exception, match="(?i)check constraint|violates"):
                await conn.execute(
                    'INSERT INTO "public"."price_list_item" '
                    "(id, price_list_id, variant_id, price_cents) "
                    "VALUES (gen_random_uuid(), $1, $2, -100)",
                    price_list_id,
                    variant_id,
                )


class TestProductTaxonomyTables:
    async def test_product_option_fk_to_product(self, pg_pool):
        await ensure_commerce_batch_schema(pg_pool)
        async with pg_pool.acquire() as conn:
            with pytest.raises(Exception, match="(?i)foreign key|violates"):
                await conn.execute(
                    'INSERT INTO "public"."product_option" (id, product_id, name) '
                    "VALUES (gen_random_uuid(), gen_random_uuid(), 'Size')"
                )

    async def test_product_category_self_referencing_parent(self, pg_pool):
        await ensure_commerce_batch_schema(pg_pool)
        async with pg_pool.acquire() as conn:
            parent_id = await conn.fetchval(
                'INSERT INTO "public"."product_category" (id, name, slug) '
                "VALUES (gen_random_uuid(), 'Clothing', 'clothing') RETURNING id"
            )
            await conn.execute(
                'INSERT INTO "public"."product_category" (id, name, slug, parent_id) '
                "VALUES (gen_random_uuid(), 'Shirts', 'shirts', $1)",
                parent_id,
            )
            with pytest.raises(Exception, match="(?i)foreign key|violates"):
                await conn.execute(
                    'INSERT INTO "public"."product_category" (id, name, slug, parent_id) '
                    "VALUES (gen_random_uuid(), 'Ghost', 'ghost', gen_random_uuid())"
                )

    async def test_product_category_lft_rgt_default_zero(self, pg_pool):
        await ensure_commerce_batch_schema(pg_pool)
        async with pg_pool.acquire() as conn:
            row = await conn.fetchrow(
                'INSERT INTO "public"."product_category" (id, name, slug) '
                "VALUES (gen_random_uuid(), 'Root', 'root') RETURNING lft, rgt"
            )
        assert row["lft"] == 0
        assert row["rgt"] == 0

    async def test_product_collection_item_unique_and_fk(self, pg_pool):
        await ensure_commerce_batch_schema(pg_pool)
        async with pg_pool.acquire() as conn:
            collection_id = await conn.fetchval(
                'INSERT INTO "public"."product_collection" (id, name, slug) '
                "VALUES (gen_random_uuid(), 'Summer', 'summer') RETURNING id"
            )
            product_id = await conn.fetchval(
                'INSERT INTO "public"."product" (id, title, slug) '
                "VALUES (gen_random_uuid(), 'p', 'p-slug-coll') RETURNING id"
            )
            await conn.execute(
                'INSERT INTO "public"."product_collection_item" '
                "(id, collection_id, product_id) VALUES (gen_random_uuid(), $1, $2)",
                collection_id,
                product_id,
            )
            with pytest.raises(Exception, match="(?i)duplicate|unique"):
                await conn.execute(
                    'INSERT INTO "public"."product_collection_item" '
                    "(id, collection_id, product_id) VALUES (gen_random_uuid(), $1, $2)",
                    collection_id,
                    product_id,
                )


class TestCustomerDomainTables:
    async def test_app_user_email_unique(self, pg_pool):
        await ensure_commerce_batch_schema(pg_pool)
        async with pg_pool.acquire() as conn:
            await conn.execute(
                'INSERT INTO "public"."app_user" (id, email, password_hash) '
                "VALUES (gen_random_uuid(), 'admin@x.com', 'hash1')"
            )
            with pytest.raises(Exception, match="(?i)duplicate|unique"):
                await conn.execute(
                    'INSERT INTO "public"."app_user" (id, email, password_hash) '
                    "VALUES (gen_random_uuid(), 'admin@x.com', 'hash2')"
                )

    async def test_customer_email_unique(self, pg_pool):
        await ensure_commerce_batch_schema(pg_pool)
        async with pg_pool.acquire() as conn:
            await conn.execute(
                'INSERT INTO "public"."customer" (id, email) '
                "VALUES (gen_random_uuid(), 'buyer@x.com')"
            )
            with pytest.raises(Exception, match="(?i)duplicate|unique"):
                await conn.execute(
                    'INSERT INTO "public"."customer" (id, email) '
                    "VALUES (gen_random_uuid(), 'buyer@x.com')"
                )

    async def test_customer_group_fk(self, pg_pool):
        await ensure_commerce_batch_schema(pg_pool)
        async with pg_pool.acquire() as conn:
            group_id = await conn.fetchval(
                'INSERT INTO "public"."customer_group" (id, name) '
                "VALUES (gen_random_uuid(), 'VIP') RETURNING id"
            )
            await conn.execute(
                'INSERT INTO "public"."customer" (id, email, customer_group_id) '
                "VALUES (gen_random_uuid(), 'vip@x.com', $1)",
                group_id,
            )
            with pytest.raises(Exception, match="(?i)foreign key|violates"):
                await conn.execute(
                    'INSERT INTO "public"."customer" (id, email, customer_group_id) '
                    "VALUES (gen_random_uuid(), 'ghost@x.com', gen_random_uuid())"
                )

    async def test_customer_address_fk_and_multiple_per_customer(self, pg_pool):
        await ensure_commerce_batch_schema(pg_pool)
        async with pg_pool.acquire() as conn:
            customer_id = await conn.fetchval(
                'INSERT INTO "public"."customer" (id, email) '
                "VALUES (gen_random_uuid(), 'multi@x.com') RETURNING id"
            )
            for _i in range(2):
                await conn.execute(
                    'INSERT INTO "public"."customer_address" '
                    "(id, customer_id, recipient_name, phone, address_line1, city, postal_code) "
                    "VALUES (gen_random_uuid(), $1, 'name', 'phone', 'addr', 'city', '000000')",
                    customer_id,
                )
            rows = await conn.fetch(
                'SELECT * FROM "public"."customer_address" WHERE customer_id = $1', customer_id
            )
        assert len(rows) == 2


class TestOrderTables:
    async def test_cart_id_unique_per_order(self, pg_pool):
        """A cart can only turn into one order — UNIQUE(cart_id)."""
        await ensure_commerce_batch_schema(pg_pool)
        async with pg_pool.acquire() as conn:
            cart_id = await conn.fetchval(
                'INSERT INTO "public"."cart" (id) VALUES (gen_random_uuid()) RETURNING id'
            )
            await conn.execute(
                'INSERT INTO "public"."customer_order" (id, cart_id) '
                "VALUES (gen_random_uuid(), $1)",
                cart_id,
            )
            with pytest.raises(Exception, match="(?i)duplicate|unique"):
                await conn.execute(
                    'INSERT INTO "public"."customer_order" (id, cart_id) '
                    "VALUES (gen_random_uuid(), $1)",
                    cart_id,
                )

    async def test_draft_order_without_cart_allowed(self, pg_pool):
        """cart_id is nullable — multiple NULLs don't violate UNIQUE in Postgres."""
        await ensure_commerce_batch_schema(pg_pool)
        async with pg_pool.acquire() as conn:
            await conn.execute(
                'INSERT INTO "public"."customer_order" (id, cart_id) '
                "VALUES (gen_random_uuid(), NULL)"
            )
            # A second cart-less order must also succeed (NULLs aren't equal to each other).
            await conn.execute(
                'INSERT INTO "public"."customer_order" (id, cart_id) '
                "VALUES (gen_random_uuid(), NULL)"
            )
            count = await conn.fetchval(
                'SELECT COUNT(*) FROM "public"."customer_order" WHERE cart_id IS NULL'
            )
        assert count == 2

    async def test_order_line_item_fk_to_order_and_batch(self, pg_pool):
        await ensure_commerce_batch_schema(pg_pool)
        async with pg_pool.acquire() as conn:
            loc_id = await conn.fetchval(
                'INSERT INTO "public"."stock_location" (id, name, region_code) '
                "VALUES (gen_random_uuid(), 'loc', 'cn-east') RETURNING id"
            )
            prod_id = await conn.fetchval(
                'INSERT INTO "public"."product" (id, title, slug) '
                "VALUES (gen_random_uuid(), 'p', 'p-slug-order') RETURNING id"
            )
            variant_id = await conn.fetchval(
                'INSERT INTO "public"."product_variant" (id, product_id, sku_code) '
                "VALUES (gen_random_uuid(), $1, 'SKU-ORDER-1') RETURNING id",
                prod_id,
            )
            batch_id = await conn.fetchval(
                'INSERT INTO "public"."inventory_batch" '
                "(id, batch_no, variant_id, location_id, video_url, cost_price_cents, "
                "retail_price_cents, stock_qty) "
                "VALUES (gen_random_uuid(), 'B-ORDER-1', $1, $2, 'https://x/v.mp4', 100, 200, 5) "
                "RETURNING id",
                variant_id,
                loc_id,
            )
            order_id = await conn.fetchval(
                'INSERT INTO "public"."customer_order" (id) VALUES (gen_random_uuid()) RETURNING id'
            )
            await conn.execute(
                'INSERT INTO "public"."order_line_item" '
                "(id, order_id, batch_id, quantity, unit_price_cents, line_total_cents) "
                "VALUES (gen_random_uuid(), $1, $2, 1, 200, 200)",
                order_id,
                batch_id,
            )
            rows = await conn.fetch(
                'SELECT * FROM "public"."order_line_item" WHERE order_id = $1', order_id
            )
        assert len(rows) == 1

    async def test_default_status_is_pending(self, pg_pool):
        await ensure_commerce_batch_schema(pg_pool)
        async with pg_pool.acquire() as conn:
            status = await conn.fetchval(
                'INSERT INTO "public"."customer_order" (id) VALUES (gen_random_uuid()) '
                "RETURNING status"
            )
        assert status == "pending"


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

    async def test_ensure_discount_tables_in_order(self, pg_pool):
        await ensure_discount_table(pg_pool)
        await ensure_discount_rule_table(pg_pool)
        await ensure_discount_condition_table(pg_pool)
        assert await _table_exists(pg_pool, "discount")
        assert await _table_exists(pg_pool, "discount_rule")
        assert await _table_exists(pg_pool, "discount_condition")

    async def test_ensure_gift_card_table_standalone(self, pg_pool):
        await ensure_gift_card_table(pg_pool)
        assert await _table_exists(pg_pool, "gift_card")

    async def test_ensure_cart_discount_and_gift_card_junction_tables(self, pg_pool):
        await ensure_stock_location_table(pg_pool)
        await ensure_product_table(pg_pool)
        await ensure_product_variant_table(pg_pool)
        await ensure_inventory_batch_table(pg_pool)
        await ensure_cart_table(pg_pool)
        await ensure_discount_table(pg_pool)
        await ensure_gift_card_table(pg_pool)
        await ensure_cart_discount_table(pg_pool)
        await ensure_cart_gift_card_table(pg_pool)
        assert await _table_exists(pg_pool, "cart_discount")
        assert await _table_exists(pg_pool, "cart_gift_card")

    async def test_ensure_payment_session_table_standalone(self, pg_pool):
        await ensure_stock_location_table(pg_pool)
        await ensure_product_table(pg_pool)
        await ensure_product_variant_table(pg_pool)
        await ensure_inventory_batch_table(pg_pool)
        await ensure_cart_table(pg_pool)
        await ensure_payment_session_table(pg_pool)
        assert await _table_exists(pg_pool, "payment_session")

    async def test_ensure_order_tables_in_order(self, pg_pool):
        await ensure_stock_location_table(pg_pool)
        await ensure_product_table(pg_pool)
        await ensure_product_variant_table(pg_pool)
        await ensure_inventory_batch_table(pg_pool)
        await ensure_cart_table(pg_pool)
        await ensure_customer_order_table(pg_pool)
        await ensure_order_line_item_table(pg_pool)
        assert await _table_exists(pg_pool, "customer_order")
        assert await _table_exists(pg_pool, "order_line_item")

    async def test_ensure_region_and_tax_rate_tables_in_order(self, pg_pool):
        await ensure_region_table(pg_pool)
        await ensure_tax_rate_table(pg_pool)
        assert await _table_exists(pg_pool, "region")
        assert await _table_exists(pg_pool, "tax_rate")

    async def test_ensure_customer_domain_tables_in_order(self, pg_pool):
        await ensure_app_user_table(pg_pool)
        await ensure_customer_group_table(pg_pool)
        await ensure_customer_table(pg_pool)
        await ensure_customer_address_table(pg_pool)
        assert await _table_exists(pg_pool, "app_user")
        assert await _table_exists(pg_pool, "customer_group")
        assert await _table_exists(pg_pool, "customer")
        assert await _table_exists(pg_pool, "customer_address")

    async def test_ensure_product_taxonomy_tables_in_order(self, pg_pool):
        await ensure_product_table(pg_pool)
        await ensure_product_option_table(pg_pool)
        await ensure_product_category_table(pg_pool)
        await ensure_product_collection_table(pg_pool)
        await ensure_product_collection_item_table(pg_pool)
        assert await _table_exists(pg_pool, "product_option")
        assert await _table_exists(pg_pool, "product_category")
        assert await _table_exists(pg_pool, "product_collection")
        assert await _table_exists(pg_pool, "product_collection_item")

    async def test_ensure_price_list_tables_in_order(self, pg_pool):
        await ensure_price_list_table(pg_pool)
        await ensure_product_table(pg_pool)
        await ensure_product_variant_table(pg_pool)
        await ensure_price_list_item_table(pg_pool)
        assert await _table_exists(pg_pool, "price_list")
        assert await _table_exists(pg_pool, "price_list_item")

    async def test_ensure_sales_channel_tables_in_order(self, pg_pool):
        await ensure_sales_channel_table(pg_pool)
        await ensure_product_table(pg_pool)
        await ensure_sales_channel_product_table(pg_pool)
        assert await _table_exists(pg_pool, "sales_channel")
        assert await _table_exists(pg_pool, "sales_channel_product")
