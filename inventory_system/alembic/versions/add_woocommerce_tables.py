"""Add WooCommerce listings and orders tables

Revision ID: add_woocommerce_tables
Revises: c1d43d7f2790
Create Date: 2026-03-03

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "add_woocommerce_tables"
down_revision: Union[str, Sequence[str], None] = "c1d43d7f2790"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == 'sqlite'

    json_type = sa.JSON() if is_sqlite else postgresql.JSONB()
    ts_default = sa.text("CURRENT_TIMESTAMP") if is_sqlite else sa.text("timezone('utc', now())")

    # ----------------------------------------------------------------
    # woocommerce_listings table
    # ----------------------------------------------------------------
    op.create_table(
        "woocommerce_listings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("platform_id", sa.Integer(), sa.ForeignKey("platform_common.id"), nullable=True),
        # Core WooCommerce identifiers
        sa.Column("wc_product_id", sa.String(50), nullable=True),
        sa.Column("slug", sa.String(255), nullable=True),
        sa.Column("permalink", sa.String(500), nullable=True),
        # Product info
        sa.Column("title", sa.String(255), nullable=True),
        sa.Column("status", sa.String(20), nullable=True),
        sa.Column("product_type", sa.String(50), nullable=True),
        sa.Column("sku", sa.String(100), nullable=True),
        # Pricing
        sa.Column("regular_price", sa.Float(), nullable=True),
        sa.Column("sale_price", sa.Float(), nullable=True),
        sa.Column("price", sa.Float(), nullable=True),
        # Inventory
        sa.Column("manage_stock", sa.Boolean(), default=True),
        sa.Column("stock_quantity", sa.Integer(), nullable=True),
        sa.Column("stock_status", sa.String(20), nullable=True),
        # Category
        sa.Column("category_id", sa.String(50), nullable=True),
        sa.Column("category_name", sa.String(255), nullable=True),
        # Shipping
        sa.Column("weight", sa.String(20), nullable=True),
        sa.Column("shipping_class", sa.String(100), nullable=True),
        # Stats
        sa.Column("total_sales", sa.Integer(), default=0),
        # WooCommerce timestamps
        sa.Column("wc_created_at", sa.DateTime(), nullable=True),
        sa.Column("wc_modified_at", sa.DateTime(), nullable=True),
        # Local timestamps
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=False),
            server_default=ts_default,
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=False),
            server_default=ts_default,
            nullable=False,
        ),
        sa.Column("last_synced_at", sa.DateTime(), nullable=True),
        # Extended attributes
        sa.Column("extended_attributes", json_type, nullable=True),
    )

    # Indexes for woocommerce_listings
    op.create_index("ix_woocommerce_listings_platform_id", "woocommerce_listings", ["platform_id"])
    op.create_index("ix_woocommerce_listings_wc_product_id", "woocommerce_listings", ["wc_product_id"])
    op.create_index("ix_woocommerce_listings_slug", "woocommerce_listings", ["slug"])
    op.create_index("ix_woocommerce_listings_sku", "woocommerce_listings", ["sku"])

    # ----------------------------------------------------------------
    # woocommerce_orders table
    # ----------------------------------------------------------------
    op.create_table(
        "woocommerce_orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        # WooCommerce order identifiers
        sa.Column("wc_order_id", sa.String(50), unique=True, nullable=False),
        sa.Column("order_number", sa.String(50), nullable=True),
        sa.Column("order_key", sa.String(100), nullable=True),
        # Order status
        sa.Column("status", sa.String(30), nullable=True),
        sa.Column("payment_method", sa.String(50), nullable=True),
        sa.Column("payment_method_title", sa.String(100), nullable=True),
        # Customer info
        sa.Column("customer_id", sa.String(50), nullable=True),
        sa.Column("customer_name", sa.String(200), nullable=True),
        sa.Column("customer_email", sa.String(255), nullable=True),
        # Shipping address
        sa.Column("shipping_name", sa.String(200), nullable=True),
        sa.Column("shipping_address_1", sa.String(255), nullable=True),
        sa.Column("shipping_address_2", sa.String(255), nullable=True),
        sa.Column("shipping_city", sa.String(100), nullable=True),
        sa.Column("shipping_state", sa.String(50), nullable=True),
        sa.Column("shipping_postcode", sa.String(20), nullable=True),
        sa.Column("shipping_country", sa.String(10), nullable=True),
        # Pricing
        sa.Column("total", sa.Float(), nullable=True),
        sa.Column("subtotal", sa.Float(), nullable=True),
        sa.Column("shipping_total", sa.Float(), nullable=True),
        sa.Column("tax_total", sa.Float(), nullable=True),
        sa.Column("discount_total", sa.Float(), nullable=True),
        sa.Column("currency", sa.String(10), nullable=True),
        # Line items
        sa.Column("line_items", json_type, nullable=True),
        # RIFF linkage
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=True),
        sa.Column("platform_listing_id", sa.Integer(), sa.ForeignKey("platform_common.id"), nullable=True),
        # Processing
        sa.Column("sale_processed", sa.Boolean(), default=False),
        # Raw payload
        sa.Column("raw_payload", json_type, nullable=True),
        # WooCommerce timestamps
        sa.Column("wc_created_at", sa.DateTime(), nullable=True),
        sa.Column("wc_modified_at", sa.DateTime(), nullable=True),
        # Local timestamps
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=False),
            server_default=ts_default,
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=False),
            server_default=ts_default,
            nullable=False,
        ),
    )

    # Index for woocommerce_orders
    op.create_index("ix_woocommerce_orders_wc_order_id", "woocommerce_orders", ["wc_order_id"])


def downgrade() -> None:
    op.drop_table("woocommerce_orders")
    op.drop_table("woocommerce_listings")
