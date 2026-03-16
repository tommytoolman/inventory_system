"""Phase 1.3: Backfill all existing data with Tenant Zero.

Sets tenant_id = '00000000-0000-0000-0000-000000000001' (Hanks Music)
on every row where tenant_id IS NULL across all 23 tenant-scoped tables.

This must complete before migration 004 adds the NOT NULL constraint.

Revision ID: phase1_003
Revises: phase1_002
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "phase1_003"
down_revision: Union[str, Sequence[str], None] = "phase1_002"
branch_labels = None
depends_on = None

TENANT_ZERO_ID = "00000000-0000-0000-0000-000000000001"

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
        op.execute(sa.text(f"UPDATE {table} SET tenant_id = '{TENANT_ZERO_ID}' WHERE tenant_id IS NULL"))


def downgrade() -> None:
    # Set tenant_id back to NULL (reversible, allows re-running backfill)
    for table in TENANT_SCOPED_TABLES:
        op.execute(sa.text(f"UPDATE {table} SET tenant_id = NULL WHERE tenant_id = '{TENANT_ZERO_ID}'"))
