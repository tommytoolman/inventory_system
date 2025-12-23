"""Add shopify_orders table

Revision ID: add_shopify_orders
Revises: merge_f6f1e1d
Create Date: 2025-12-23
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "add_shopify_orders"
down_revision: Union[str, Sequence[str], None] = "merge_f6f1e1d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "shopify_orders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("shopify_order_id", sa.String(), nullable=False),
        sa.Column("order_name", sa.String(), nullable=True),
        sa.Column("financial_status", sa.String(), nullable=True),
        sa.Column("fulfillment_status", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("paid_at", sa.DateTime(), nullable=True),
        sa.Column("fulfilled_at", sa.DateTime(), nullable=True),
        sa.Column("total_amount", sa.Numeric(), nullable=True),
        sa.Column("total_currency", sa.String(), nullable=True),
        sa.Column("subtotal_amount", sa.Numeric(), nullable=True),
        sa.Column("subtotal_currency", sa.String(), nullable=True),
        sa.Column("shipping_amount", sa.Numeric(), nullable=True),
        sa.Column("shipping_currency", sa.String(), nullable=True),
        sa.Column("tax_amount", sa.Numeric(), nullable=True),
        sa.Column("tax_currency", sa.String(), nullable=True),
        sa.Column("customer_id", sa.String(), nullable=True),
        sa.Column("customer_first_name", sa.String(), nullable=True),
        sa.Column("customer_last_name", sa.String(), nullable=True),
        sa.Column("customer_email", sa.String(), nullable=True),
        sa.Column("customer_phone", sa.String(), nullable=True),
        sa.Column("shipping_name", sa.String(), nullable=True),
        sa.Column("shipping_address1", sa.String(), nullable=True),
        sa.Column("shipping_address2", sa.String(), nullable=True),
        sa.Column("shipping_city", sa.String(), nullable=True),
        sa.Column("shipping_province", sa.String(), nullable=True),
        sa.Column("shipping_province_code", sa.String(), nullable=True),
        sa.Column("shipping_country", sa.String(), nullable=True),
        sa.Column("shipping_country_code", sa.String(), nullable=True),
        sa.Column("shipping_zip", sa.String(), nullable=True),
        sa.Column("shipping_phone", sa.String(), nullable=True),
        sa.Column("shipping_company", sa.String(), nullable=True),
        sa.Column("billing_address", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("tracking_number", sa.String(), nullable=True),
        sa.Column("tracking_company", sa.String(), nullable=True),
        sa.Column("tracking_url", sa.String(), nullable=True),
        sa.Column("fulfillments", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("primary_sku", sa.String(), nullable=True),
        sa.Column("primary_title", sa.String(), nullable=True),
        sa.Column("primary_quantity", sa.Integer(), nullable=True),
        sa.Column("primary_price", sa.Numeric(), nullable=True),
        sa.Column("primary_price_currency", sa.String(), nullable=True),
        sa.Column("line_items", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "raw_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("product_id", sa.Integer(), nullable=True),
        sa.Column("platform_listing_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_row_at",
            sa.DateTime(),
            server_default=sa.text("timezone('utc', now())"),
            nullable=False,
        ),
        sa.Column(
            "updated_row_at",
            sa.DateTime(),
            server_default=sa.text("timezone('utc', now())"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("shopify_order_id"),
    )
    op.create_index(op.f("ix_shopify_orders_id"), "shopify_orders", ["id"], unique=False)
    op.create_index("ix_shopify_orders_order_name", "shopify_orders", ["order_name"], unique=False)
    op.create_index("ix_shopify_orders_primary_sku", "shopify_orders", ["primary_sku"], unique=False)
    op.create_index("ix_shopify_orders_created_at", "shopify_orders", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_shopify_orders_created_at", table_name="shopify_orders")
    op.drop_index("ix_shopify_orders_primary_sku", table_name="shopify_orders")
    op.drop_index("ix_shopify_orders_order_name", table_name="shopify_orders")
    op.drop_index(op.f("ix_shopify_orders_id"), table_name="shopify_orders")
    op.drop_table("shopify_orders")
