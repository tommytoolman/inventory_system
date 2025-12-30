"""Add listing_stats_history table for tracking engagement metrics over time

Revision ID: add_listing_stats_history
Revises: add_sale_processed
Create Date: 2025-12-30

This migration creates a table to store daily snapshots of listing engagement
metrics (views, watches) for trend analysis and business intelligence.
Supports multiple platforms (Reverb, eBay, etc.)
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision: str = "add_listing_stats_history"
down_revision: Union[str, Sequence[str], None] = "add_sale_processed"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def table_exists(table_name: str) -> bool:
    """Check if a table exists in the database."""
    conn = op.get_bind()
    result = conn.execute(
        text(
            "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = :table_name)"
        ),
        {"table_name": table_name},
    )
    return result.scalar()


def upgrade() -> None:
    if not table_exists("listing_stats_history"):
        op.create_table(
            "listing_stats_history",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("platform", sa.String(50), nullable=False, index=True),  # 'reverb', 'ebay', etc.
            sa.Column("platform_listing_id", sa.String(100), nullable=False, index=True),  # External ID
            sa.Column("product_id", sa.Integer(), nullable=True, index=True),  # FK to products.id for easy navigation
            sa.Column("view_count", sa.Integer(), nullable=True),
            sa.Column("watch_count", sa.Integer(), nullable=True),
            sa.Column("price", sa.Float(), nullable=True),  # Price at time of snapshot
            sa.Column("state", sa.String(50), nullable=True),  # Listing state (live, ended, etc.)
            sa.Column(
                "recorded_at",
                sa.TIMESTAMP(timezone=False),
                server_default=text("timezone('utc', now())"),
                nullable=False,
                index=True,
            ),
        )

        # Create composite index for efficient queries by platform + listing + date
        op.create_index(
            "ix_listing_stats_history_platform_listing_date",
            "listing_stats_history",
            ["platform", "platform_listing_id", "recorded_at"],
        )

        print("Created listing_stats_history table")
    else:
        print("listing_stats_history table already exists, skipping")


def downgrade() -> None:
    op.drop_index("ix_listing_stats_history_platform_listing_date", table_name="listing_stats_history")
    op.drop_table("listing_stats_history")
