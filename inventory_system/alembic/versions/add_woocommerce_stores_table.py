"""Add woocommerce_stores table and wc_store_id FK columns.

Multi-tenant WooCommerce support: per-retailer store credentials,
with nullable FK on existing tables for backward compatibility.
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "wc_multitenant_001"
down_revision = None  # Will be set by Alembic when auto-detected
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create woocommerce_stores table
    op.create_table(
        "woocommerce_stores",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("store_url", sa.String(500), nullable=False),
        sa.Column("consumer_key", sa.String(255), nullable=False),
        sa.Column("consumer_secret", sa.String(255), nullable=False),
        sa.Column("webhook_secret", sa.String(255), nullable=True, server_default=""),
        sa.Column("price_markup_percent", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("sync_status", sa.String(20), nullable=False, server_default="healthy"),
        sa.Column("last_sync_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=False),
            server_default=sa.text("timezone('utc', now())"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=False),
            server_default=sa.text("timezone('utc', now())"),
            nullable=False,
        ),
    )

    # Add wc_store_id to woocommerce_listings (nullable for existing data)
    op.add_column(
        "woocommerce_listings",
        sa.Column("wc_store_id", sa.Integer(), sa.ForeignKey("woocommerce_stores.id"), nullable=True),
    )
    op.create_index("ix_woocommerce_listings_wc_store_id", "woocommerce_listings", ["wc_store_id"])

    # Add wc_store_id to woocommerce_orders (nullable for existing data)
    op.add_column(
        "woocommerce_orders",
        sa.Column("wc_store_id", sa.Integer(), sa.ForeignKey("woocommerce_stores.id"), nullable=True),
    )
    op.create_index("ix_woocommerce_orders_wc_store_id", "woocommerce_orders", ["wc_store_id"])


def downgrade() -> None:
    op.drop_index("ix_woocommerce_orders_wc_store_id", table_name="woocommerce_orders")
    op.drop_column("woocommerce_orders", "wc_store_id")
    op.drop_index("ix_woocommerce_listings_wc_store_id", table_name="woocommerce_listings")
    op.drop_column("woocommerce_listings", "wc_store_id")
    op.drop_table("woocommerce_stores")
