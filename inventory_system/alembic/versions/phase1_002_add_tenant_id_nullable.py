"""Phase 1.2: Add nullable tenant_id column to all tenant-scoped tables.

Adds tenant_id (UUID FK → tenants.id) as NULLABLE to 22 tables.
Nullable at this stage so existing data is preserved; backfill
happens in migration 003.

Tables modified:
  products, platform_common, sales, orders, shipments, shipping_profiles,
  activity_log, sync_stats, sync_errors, sync_events,
  reverb_listings, ebay_listings, shopify_listings, vr_listings,
  woocommerce_listings, reverb_orders, ebay_orders, shopify_orders,
  woocommerce_orders, woocommerce_stores, platform_preferences,
  reverb_historical_listings, listing_stats_history

Revision ID: phase1_002
Revises: phase1_001
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "phase1_002"
down_revision: Union[str, Sequence[str], None] = "phase1_001"
branch_labels = None
depends_on = None

# All tables that receive a tenant_id column
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
        op.add_column(
            table,
            sa.Column(
                "tenant_id",
                UUID(as_uuid=True),
                sa.ForeignKey("tenants.id"),
                nullable=True,
            ),
        )
        op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])


def downgrade() -> None:
    for table in reversed(TENANT_SCOPED_TABLES):
        op.drop_index(f"ix_{table}_tenant_id", table_name=table)
        op.drop_column(table, "tenant_id")
