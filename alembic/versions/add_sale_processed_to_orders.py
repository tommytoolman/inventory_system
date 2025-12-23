"""Add sale_processed columns to order tables

Revision ID: add_sale_processed
Revises: merge_shopify_taiwan
Create Date: 2025-12-23

This migration adds sale_processed and sale_processed_at columns to:
- reverb_orders
- ebay_orders
- shopify_orders

These columns track whether an order has been processed for inventory
quantity management, preventing double-counting on re-syncs.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision: str = "add_sale_processed"
down_revision: Union[str, Sequence[str], None] = "merge_shopify_taiwan"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def column_exists(table_name: str, column_name: str) -> bool:
    """Check if a column exists in a table."""
    bind = op.get_bind()
    result = bind.execute(
        text(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_name = :table_name
              AND column_name = :column_name
            """
        ),
        {"table_name": table_name, "column_name": column_name}
    ).scalar()
    return result is not None


def upgrade() -> None:
    # Add columns to reverb_orders
    if not column_exists("reverb_orders", "sale_processed"):
        op.add_column(
            "reverb_orders",
            sa.Column(
                "sale_processed",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
        )
    if not column_exists("reverb_orders", "sale_processed_at"):
        op.add_column(
            "reverb_orders",
            sa.Column("sale_processed_at", sa.DateTime(), nullable=True),
        )

    # Add columns to ebay_orders
    if not column_exists("ebay_orders", "sale_processed"):
        op.add_column(
            "ebay_orders",
            sa.Column(
                "sale_processed",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
        )
    if not column_exists("ebay_orders", "sale_processed_at"):
        op.add_column(
            "ebay_orders",
            sa.Column("sale_processed_at", sa.DateTime(), nullable=True),
        )

    # Add columns to shopify_orders
    if not column_exists("shopify_orders", "sale_processed"):
        op.add_column(
            "shopify_orders",
            sa.Column(
                "sale_processed",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
        )
    if not column_exists("shopify_orders", "sale_processed_at"):
        op.add_column(
            "shopify_orders",
            sa.Column("sale_processed_at", sa.DateTime(), nullable=True),
        )


def downgrade() -> None:
    # Remove from shopify_orders
    if column_exists("shopify_orders", "sale_processed_at"):
        op.drop_column("shopify_orders", "sale_processed_at")
    if column_exists("shopify_orders", "sale_processed"):
        op.drop_column("shopify_orders", "sale_processed")

    # Remove from ebay_orders
    if column_exists("ebay_orders", "sale_processed_at"):
        op.drop_column("ebay_orders", "sale_processed_at")
    if column_exists("ebay_orders", "sale_processed"):
        op.drop_column("ebay_orders", "sale_processed")

    # Remove from reverb_orders
    if column_exists("reverb_orders", "sale_processed_at"):
        op.drop_column("reverb_orders", "sale_processed_at")
    if column_exists("reverb_orders", "sale_processed"):
        op.drop_column("reverb_orders", "sale_processed")
