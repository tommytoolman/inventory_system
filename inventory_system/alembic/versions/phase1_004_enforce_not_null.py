"""Phase 1.4: Enforce NOT NULL on tenant_id columns.

After backfill (migration 003) has set tenant_id on all existing rows,
this migration adds the NOT NULL constraint to prevent any future inserts
without a tenant.

Revision ID: phase1_004
Revises: phase1_003
"""

from typing import Sequence, Union

from alembic import op

revision: str = "phase1_004"
down_revision: Union[str, Sequence[str], None] = "phase1_003"
branch_labels = None
depends_on = None

TENANT_SCOPED_TABLES = [
    "products",
    "platform_common",
    "sales",
    "orders",
    "shipments",
    "shipping_profiles",
    "activity_log",
    "sync_stats",
    "sync_errors",
    "sync_events",
    "reverb_listings",
    "ebay_listings",
    "shopify_listings",
    "vr_listings",
    "woocommerce_listings",
    "reverb_orders",
    "ebay_orders",
    "shopify_orders",
    "woocommerce_orders",
    "woocommerce_stores",
    "platform_preferences",
    "reverb_historical_listings",
    "listing_stats_history",
]


def upgrade() -> None:
    for table in TENANT_SCOPED_TABLES:
        op.alter_column(table, "tenant_id", nullable=False)


def downgrade() -> None:
    for table in TENANT_SCOPED_TABLES:
        op.alter_column(table, "tenant_id", nullable=True)
