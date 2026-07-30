"""obase.commerce_batch_schema — 批次仓储电商核心表 DDL（幂等）。

只负责建表结构，不含任何业务逻辑；CRUD 由 omodul 层完成
(见 omodul.create_inventory_batch 等)。

表：stock_location → product → product_variant → inventory_batch → cart → cart_line_item
（按依赖顺序，后表持有前表的 FK）。
"""

from __future__ import annotations

from obase.persistence.ddl import ensure_index, ensure_table
from obase.persistence.pool import PgPool

SCHEMA = "public"


async def ensure_stock_location_table(pool: PgPool) -> None:
    """微仓/仓储店面。"""
    await ensure_table(
        pool=pool,
        schema=SCHEMA,
        table="stock_location",
        columns=[
            ("id", "UUID PRIMARY KEY"),
            ("name", "TEXT NOT NULL"),
            ("region_code", "TEXT NOT NULL"),
            ("lat", "DOUBLE PRECISION"),
            ("lng", "DOUBLE PRECISION"),
            ("channel_tags", "TEXT[] NOT NULL DEFAULT '{}'"),
            ("status", "TEXT NOT NULL DEFAULT 'active'"),
            ("created_at", "TIMESTAMPTZ NOT NULL DEFAULT NOW()"),
            ("updated_at", "TIMESTAMPTZ"),
            ("deleted_at", "TIMESTAMPTZ"),
        ],
    )


async def ensure_product_table(pool: PgPool) -> None:
    """SPU。"""
    await ensure_table(
        pool=pool,
        schema=SCHEMA,
        table="product",
        columns=[
            ("id", "UUID PRIMARY KEY"),
            ("title", "TEXT NOT NULL"),
            ("slug", "TEXT NOT NULL UNIQUE"),
            ("description", "TEXT"),
            ("category_id", "UUID"),
            ("status", "TEXT NOT NULL DEFAULT 'draft'"),
            ("created_at", "TIMESTAMPTZ NOT NULL DEFAULT NOW()"),
            ("updated_at", "TIMESTAMPTZ"),
            ("deleted_at", "TIMESTAMPTZ"),
        ],
    )


async def ensure_product_variant_table(pool: PgPool) -> None:
    """SKU。reference_price_cents 仅供无在架批次时的展示兜底，不参与算价。"""
    await ensure_table(
        pool=pool,
        schema=SCHEMA,
        table="product_variant",
        columns=[
            ("id", "UUID PRIMARY KEY"),
            ("product_id", "UUID NOT NULL REFERENCES product(id)"),
            ("sku_code", "TEXT NOT NULL UNIQUE"),
            ("option_values", "JSONB NOT NULL DEFAULT '{}'"),
            (
                "reference_price_cents",
                "INTEGER CHECK (reference_price_cents IS NULL OR reference_price_cents >= 0)",
            ),
            ("status", "TEXT NOT NULL DEFAULT 'active'"),
            ("created_at", "TIMESTAMPTZ NOT NULL DEFAULT NOW()"),
            ("updated_at", "TIMESTAMPTZ"),
            ("deleted_at", "TIMESTAMPTZ"),
        ],
    )
    await ensure_index(
        pool=pool,
        schema=SCHEMA,
        table="product_variant",
        index_name="idx_variant_product",
        columns="product_id",
    )


async def ensure_inventory_batch_table(pool: PgPool) -> None:
    """批次 — 核心表。价格/成本/库存/溯源视频均独立挂在批次上，不下沉到 variant。"""
    await ensure_table(
        pool=pool,
        schema=SCHEMA,
        table="inventory_batch",
        columns=[
            ("id", "UUID PRIMARY KEY"),
            ("batch_no", "TEXT NOT NULL UNIQUE"),
            ("variant_id", "UUID NOT NULL REFERENCES product_variant(id)"),
            ("location_id", "UUID NOT NULL REFERENCES stock_location(id)"),
            ("video_url", "TEXT NOT NULL"),
            ("media_assets", "JSONB NOT NULL DEFAULT '[]'"),
            ("cost_price_cents", "INTEGER NOT NULL CHECK (cost_price_cents >= 0)"),
            ("retail_price_cents", "INTEGER NOT NULL CHECK (retail_price_cents >= 0)"),
            ("currency", "TEXT NOT NULL DEFAULT 'CNY'"),
            ("stock_qty", "INTEGER NOT NULL DEFAULT 0 CHECK (stock_qty >= 0)"),
            (
                "reserved_qty",
                "INTEGER NOT NULL DEFAULT 0 CHECK (reserved_qty >= 0 AND reserved_qty <= stock_qty)",
            ),
            ("inspection_status", "TEXT NOT NULL DEFAULT 'pending'"),
            ("inspected_by", "TEXT"),
            ("inspected_at", "TIMESTAMPTZ"),
            ("status", "TEXT NOT NULL DEFAULT 'active'"),
            ("created_at", "TIMESTAMPTZ NOT NULL DEFAULT NOW()"),
            ("updated_at", "TIMESTAMPTZ"),
            ("deleted_at", "TIMESTAMPTZ"),
        ],
    )
    await ensure_index(
        pool=pool,
        schema=SCHEMA,
        table="inventory_batch",
        index_name="idx_batch_variant_location_status",
        columns="variant_id, location_id, status",
    )
    await ensure_index(
        pool=pool,
        schema=SCHEMA,
        table="inventory_batch",
        index_name="idx_batch_location_status",
        columns="location_id, status",
    )


async def ensure_cart_table(pool: PgPool) -> None:
    """购物车容器。discount/tax/shipping 本轮均为透传字段，无对应计算引擎。"""
    await ensure_table(
        pool=pool,
        schema=SCHEMA,
        table="cart",
        columns=[
            ("id", "UUID PRIMARY KEY"),
            ("customer_id", "UUID"),
            ("region_code", "TEXT"),
            ("currency", "TEXT NOT NULL DEFAULT 'CNY'"),
            ("status", "TEXT NOT NULL DEFAULT 'active'"),
            ("subtotal_cents", "INTEGER NOT NULL DEFAULT 0 CHECK (subtotal_cents >= 0)"),
            ("discount_cents", "INTEGER NOT NULL DEFAULT 0 CHECK (discount_cents >= 0)"),
            ("tax_cents", "INTEGER NOT NULL DEFAULT 0 CHECK (tax_cents >= 0)"),
            ("shipping_cents", "INTEGER NOT NULL DEFAULT 0 CHECK (shipping_cents >= 0)"),
            ("grand_total_cents", "INTEGER NOT NULL DEFAULT 0 CHECK (grand_total_cents >= 0)"),
            ("created_at", "TIMESTAMPTZ NOT NULL DEFAULT NOW()"),
            ("updated_at", "TIMESTAMPTZ"),
            ("deleted_at", "TIMESTAMPTZ"),
        ],
    )


async def ensure_cart_line_item_table(pool: PgPool) -> None:
    """购物车行 — 强绑定 batch_id（不是 variant_id），价格快照自 batch.retail_price_cents。

    UNIQUE(cart_id, batch_id)：同一批次重复加购在同一行累加数量，不产生重复行。
    """
    await ensure_table(
        pool=pool,
        schema=SCHEMA,
        table="cart_line_item",
        columns=[
            ("id", "UUID PRIMARY KEY"),
            ("cart_id", "UUID NOT NULL REFERENCES cart(id)"),
            ("batch_id", "UUID NOT NULL REFERENCES inventory_batch(id)"),
            ("quantity", "INTEGER NOT NULL CHECK (quantity > 0)"),
            ("unit_price_cents", "INTEGER NOT NULL CHECK (unit_price_cents >= 0)"),
            ("line_total_cents", "INTEGER NOT NULL CHECK (line_total_cents >= 0)"),
            ("created_at", "TIMESTAMPTZ NOT NULL DEFAULT NOW()"),
            ("updated_at", "TIMESTAMPTZ"),
            ("deleted_at", "TIMESTAMPTZ"),
        ],
    )
    await ensure_index(
        pool=pool,
        schema=SCHEMA,
        table="cart_line_item",
        index_name="idx_line_item_cart",
        columns="cart_id",
    )
    # ensure_index() (obase.persistence.ddl) has no UNIQUE option — raw DDL for the constraint.
    async with pool.acquire() as conn:
        await conn.execute(
            'CREATE UNIQUE INDEX IF NOT EXISTS "uq_line_item_cart_batch" '
            'ON "public"."cart_line_item" (cart_id, batch_id) WHERE deleted_at IS NULL'
        )


async def ensure_commerce_batch_schema(pool: PgPool) -> None:
    """一次性按依赖顺序建齐本垂直所需的全部表。"""
    await ensure_stock_location_table(pool)
    await ensure_product_table(pool)
    await ensure_product_variant_table(pool)
    await ensure_inventory_batch_table(pool)
    await ensure_cart_table(pool)
    await ensure_cart_line_item_table(pool)
