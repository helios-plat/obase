"""obase.commerce_batch_schema — 批次仓储电商核心表 DDL（幂等）。

只负责建表结构，不含任何业务逻辑；CRUD 由 omodul 层完成
(见 omodul.create_inventory_batch 等)。

表（按依赖顺序，后表持有前表的 FK）：
  stock_location → product → product_variant → inventory_batch → cart → cart_line_item
  discount → discount_rule → discount_condition
  gift_card
  cart_discount（依赖 cart + discount）
  cart_gift_card（依赖 cart + gift_card）

cart 表的地址列（billing_address/shipping_address）通过 ensure_column 追加，
不写进 ensure_cart_table 的建表列表——ensure_table 只在表不存在时建表，对已存在
的表是 no-op，新增列必须走 ensure_column 这种加列迁移，否则老环境永远加不上。

customer_order / order_line_item（依赖 cart + inventory_batch）：表名故意不叫
"order"——那是 Postgres/SQL 保留字（ORDER BY），叫 customer_order 是常见的
规避写法，省得后面每一条 SQL 都要小心翼翼转义；omodul 元素名(complete_checkout/
update_order/cancel_order 等)仍按 SPEC 命名，表名只是实现细节。
"""

from __future__ import annotations

from obase.persistence.ddl import ensure_column, ensure_index, ensure_table
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
                "INTEGER NOT NULL DEFAULT 0 "
                "CHECK (reserved_qty >= 0 AND reserved_qty <= stock_qty)",
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


async def ensure_cart_address_columns(pool: PgPool) -> None:
    """给 cart 表追加 billing_address/shipping_address 两个 JSONB 列。

    不做独立 address 表(客户地址簿是 SPEC §4.2 尚未落地的另一个功能),
    这里只存本次下单快照,结构由 omodul 层的 Pydantic 输入模型定义。
    """
    for column_name in ("billing_address", "shipping_address"):
        await ensure_column(
            pool=pool,
            schema=SCHEMA,
            table="cart",
            column_name=column_name,
            column_def="JSONB",
        )


async def ensure_discount_table(pool: PgPool) -> None:
    """折扣壳——只存 code + 状态,数值规则在 discount_rule。"""
    await ensure_table(
        pool=pool,
        schema=SCHEMA,
        table="discount",
        columns=[
            ("id", "UUID PRIMARY KEY"),
            ("code", "TEXT NOT NULL UNIQUE"),
            ("status", "TEXT NOT NULL DEFAULT 'active'"),
            ("created_at", "TIMESTAMPTZ NOT NULL DEFAULT NOW()"),
            ("updated_at", "TIMESTAMPTZ"),
            ("deleted_at", "TIMESTAMPTZ"),
        ],
    )


async def ensure_discount_rule_table(pool: PgPool) -> None:
    """折扣数值规则,1:1 挂在 discount 上(一张券只有一种打法)。"""
    await ensure_table(
        pool=pool,
        schema=SCHEMA,
        table="discount_rule",
        columns=[
            ("id", "UUID PRIMARY KEY"),
            ("discount_id", "UUID NOT NULL UNIQUE REFERENCES discount(id)"),
            (
                "rule_type",
                "TEXT NOT NULL CHECK (rule_type IN ('fixed', 'percentage', 'free_shipping'))",
            ),
            ("amount_cents", "INTEGER CHECK (amount_cents IS NULL OR amount_cents >= 0)"),
            ("percent", "NUMERIC CHECK (percent IS NULL OR (percent >= 0 AND percent <= 100))"),
            ("min_subtotal_cents", "INTEGER"),
            ("region_codes", "TEXT[]"),
            ("valid_from", "TIMESTAMPTZ"),
            ("valid_until", "TIMESTAMPTZ"),
            ("max_uses", "INTEGER"),
            ("uses_count", "INTEGER NOT NULL DEFAULT 0"),
            ("created_at", "TIMESTAMPTZ NOT NULL DEFAULT NOW()"),
            ("updated_at", "TIMESTAMPTZ"),
        ],
    )


async def ensure_discount_condition_table(pool: PgPool) -> None:
    """折扣限制池(SKU/分类白名单),同一 discount 下可有多行。"""
    await ensure_table(
        pool=pool,
        schema=SCHEMA,
        table="discount_condition",
        columns=[
            ("id", "UUID PRIMARY KEY"),
            ("discount_id", "UUID NOT NULL REFERENCES discount(id)"),
            (
                "condition_type",
                "TEXT NOT NULL CHECK (condition_type IN ('product', 'category', 'all'))",
            ),
            ("target_id", "UUID"),
            ("created_at", "TIMESTAMPTZ NOT NULL DEFAULT NOW()"),
        ],
    )
    await ensure_index(
        pool=pool,
        schema=SCHEMA,
        table="discount_condition",
        index_name="idx_discount_condition_discount",
        columns="discount_id",
    )


async def ensure_gift_card_table(pool: PgPool) -> None:
    """礼品卡。balance_cents 随核销递减,initial_balance_cents 只作发行记录不变。"""
    await ensure_table(
        pool=pool,
        schema=SCHEMA,
        table="gift_card",
        columns=[
            ("id", "UUID PRIMARY KEY"),
            ("code", "TEXT NOT NULL UNIQUE"),
            ("initial_balance_cents", "INTEGER NOT NULL CHECK (initial_balance_cents >= 0)"),
            (
                "balance_cents",
                "INTEGER NOT NULL "
                "CHECK (balance_cents >= 0 AND balance_cents <= initial_balance_cents)",
            ),
            ("currency", "TEXT NOT NULL DEFAULT 'CNY'"),
            ("status", "TEXT NOT NULL DEFAULT 'active'"),
            ("expires_at", "TIMESTAMPTZ"),
            ("created_at", "TIMESTAMPTZ NOT NULL DEFAULT NOW()"),
            ("updated_at", "TIMESTAMPTZ"),
            ("deleted_at", "TIMESTAMPTZ"),
        ],
    )


async def ensure_cart_discount_table(pool: PgPool) -> None:
    """购物车-折扣关联,记录本次生效的分摊额,便于 remove 时精确回滚。"""
    await ensure_table(
        pool=pool,
        schema=SCHEMA,
        table="cart_discount",
        columns=[
            ("id", "UUID PRIMARY KEY"),
            ("cart_id", "UUID NOT NULL REFERENCES cart(id)"),
            ("discount_id", "UUID NOT NULL REFERENCES discount(id)"),
            ("applied_amount_cents", "INTEGER NOT NULL CHECK (applied_amount_cents >= 0)"),
            ("created_at", "TIMESTAMPTZ NOT NULL DEFAULT NOW()"),
            ("deleted_at", "TIMESTAMPTZ"),
        ],
    )
    await ensure_index(
        pool=pool,
        schema=SCHEMA,
        table="cart_discount",
        index_name="idx_cart_discount_cart",
        columns="cart_id",
    )
    async with pool.acquire() as conn:
        await conn.execute(
            'CREATE UNIQUE INDEX IF NOT EXISTS "uq_cart_discount_active" '
            'ON "public"."cart_discount" (cart_id, discount_id) WHERE deleted_at IS NULL'
        )


async def ensure_cart_gift_card_table(pool: PgPool) -> None:
    """购物车-礼品卡关联,记录本次核销额,便于 remove 时把余额补回礼品卡。"""
    await ensure_table(
        pool=pool,
        schema=SCHEMA,
        table="cart_gift_card",
        columns=[
            ("id", "UUID PRIMARY KEY"),
            ("cart_id", "UUID NOT NULL REFERENCES cart(id)"),
            ("gift_card_id", "UUID NOT NULL REFERENCES gift_card(id)"),
            ("applied_amount_cents", "INTEGER NOT NULL CHECK (applied_amount_cents >= 0)"),
            ("created_at", "TIMESTAMPTZ NOT NULL DEFAULT NOW()"),
            ("deleted_at", "TIMESTAMPTZ"),
        ],
    )
    await ensure_index(
        pool=pool,
        schema=SCHEMA,
        table="cart_gift_card",
        index_name="idx_cart_gift_card_cart",
        columns="cart_id",
    )
    async with pool.acquire() as conn:
        await conn.execute(
            'CREATE UNIQUE INDEX IF NOT EXISTS "uq_cart_gift_card_active" '
            'ON "public"."cart_gift_card" (cart_id, gift_card_id) WHERE deleted_at IS NULL'
        )


async def ensure_payment_session_table(pool: PgPool) -> None:
    """购物车的候选支付会话——一个 cart 可以对多个 provider 各建一条(SPEC
    "多态调 ext_pay_authorize 生成多 Session"),set_payment_session 从中选一条
    标记 status='selected'。UNIQUE(cart_id, provider_name):同一 provider 不
    重复建会话(重试应该更新既有行,不是插新行——由 omodul 层用
    ON CONFLICT/先查再写实现,这里只保证约束)。
    """
    await ensure_table(
        pool=pool,
        schema=SCHEMA,
        table="payment_session",
        columns=[
            ("id", "UUID PRIMARY KEY"),
            ("cart_id", "UUID NOT NULL REFERENCES cart(id)"),
            ("provider_name", "TEXT NOT NULL"),
            ("amount_cents", "INTEGER NOT NULL CHECK (amount_cents >= 0)"),
            ("currency", "TEXT NOT NULL"),
            (
                "status",
                "TEXT NOT NULL DEFAULT 'authorized' "
                "CHECK (status IN ('authorized', 'selected', 'canceled', 'failed'))",
            ),
            ("provider_intent_id", "TEXT"),
            ("error_message", "TEXT"),
            ("created_at", "TIMESTAMPTZ NOT NULL DEFAULT NOW()"),
            ("updated_at", "TIMESTAMPTZ"),
            ("deleted_at", "TIMESTAMPTZ"),
        ],
    )
    await ensure_index(
        pool=pool,
        schema=SCHEMA,
        table="payment_session",
        index_name="idx_payment_session_cart",
        columns="cart_id",
    )
    async with pool.acquire() as conn:
        await conn.execute(
            'CREATE UNIQUE INDEX IF NOT EXISTS "uq_payment_session_cart_provider" '
            'ON "public"."payment_session" (cart_id, provider_name) WHERE deleted_at IS NULL'
        )


async def ensure_customer_order_table(pool: PgPool) -> None:
    """结账完成后的订单——totals/地址都是从 cart 复制过来的快照，不是引用
    (cart 后续可能被清理/变化，订单必须保留下单当时的真相)。
    """
    await ensure_table(
        pool=pool,
        schema=SCHEMA,
        table="customer_order",
        columns=[
            ("id", "UUID PRIMARY KEY"),
            ("cart_id", "UUID UNIQUE REFERENCES cart(id)"),
            ("customer_id", "UUID"),
            ("region_code", "TEXT"),
            ("currency", "TEXT NOT NULL DEFAULT 'CNY'"),
            ("status", "TEXT NOT NULL DEFAULT 'pending'"),
            ("subtotal_cents", "INTEGER NOT NULL DEFAULT 0 CHECK (subtotal_cents >= 0)"),
            ("discount_cents", "INTEGER NOT NULL DEFAULT 0 CHECK (discount_cents >= 0)"),
            ("tax_cents", "INTEGER NOT NULL DEFAULT 0 CHECK (tax_cents >= 0)"),
            ("shipping_cents", "INTEGER NOT NULL DEFAULT 0 CHECK (shipping_cents >= 0)"),
            ("grand_total_cents", "INTEGER NOT NULL DEFAULT 0 CHECK (grand_total_cents >= 0)"),
            ("payment_provider_name", "TEXT"),
            ("payment_intent_id", "TEXT"),
            ("billing_address", "JSONB"),
            ("shipping_address", "JSONB"),
            ("created_at", "TIMESTAMPTZ NOT NULL DEFAULT NOW()"),
            ("updated_at", "TIMESTAMPTZ"),
        ],
    )


async def ensure_order_line_item_table(pool: PgPool) -> None:
    """订单行——同样是从 cart_line_item 复制的快照，不引用 cart_line_item。"""
    await ensure_table(
        pool=pool,
        schema=SCHEMA,
        table="order_line_item",
        columns=[
            ("id", "UUID PRIMARY KEY"),
            ("order_id", "UUID NOT NULL REFERENCES customer_order(id)"),
            ("batch_id", "UUID NOT NULL REFERENCES inventory_batch(id)"),
            ("quantity", "INTEGER NOT NULL CHECK (quantity > 0)"),
            ("unit_price_cents", "INTEGER NOT NULL CHECK (unit_price_cents >= 0)"),
            ("line_total_cents", "INTEGER NOT NULL CHECK (line_total_cents >= 0)"),
            ("created_at", "TIMESTAMPTZ NOT NULL DEFAULT NOW()"),
        ],
    )
    await ensure_index(
        pool=pool,
        schema=SCHEMA,
        table="order_line_item",
        index_name="idx_order_line_item_order",
        columns="order_id",
    )


async def ensure_commerce_batch_schema(pool: PgPool) -> None:
    """一次性按依赖顺序建齐本垂直所需的全部表。"""
    await ensure_stock_location_table(pool)
    await ensure_product_table(pool)
    await ensure_product_variant_table(pool)
    await ensure_inventory_batch_table(pool)
    await ensure_cart_table(pool)
    await ensure_cart_line_item_table(pool)
    await ensure_cart_address_columns(pool)
    await ensure_discount_table(pool)
    await ensure_discount_rule_table(pool)
    await ensure_discount_condition_table(pool)
    await ensure_gift_card_table(pool)
    await ensure_cart_discount_table(pool)
    await ensure_cart_gift_card_table(pool)
    await ensure_payment_session_table(pool)
    await ensure_customer_order_table(pool)
    await ensure_order_line_item_table(pool)
