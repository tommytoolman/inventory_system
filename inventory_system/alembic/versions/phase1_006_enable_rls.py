"""Phase 1.6: Enable Row-Level Security on all tenant-scoped tables.

Creates four RLS policies per table (SELECT, INSERT, UPDATE, DELETE)
that restrict access to rows matching the current session's tenant_id,
set via: SET app.current_tenant_id = '<uuid>';

FORCE ROW LEVEL SECURITY ensures policies apply even to table owners
(prevents accidental cross-tenant access during development).

Revision ID: phase1_006
Revises: phase1_005
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "phase1_006"
down_revision: Union[str, Sequence[str], None] = "phase1_005"
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
        # Enable RLS on the table
        op.execute(sa.text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))

        # Force RLS even for table owners (safety net)
        op.execute(sa.text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))

        # SELECT policy
        op.execute(
            sa.text(
                f"CREATE POLICY tenant_isolation_select_{table} ON {table} "
                f"FOR SELECT "
                f"USING (tenant_id = CURRENT_SETTING('app.current_tenant_id')::uuid)"
            )
        )

        # INSERT policy
        op.execute(
            sa.text(
                f"CREATE POLICY tenant_isolation_insert_{table} ON {table} "
                f"FOR INSERT "
                f"WITH CHECK (tenant_id = CURRENT_SETTING('app.current_tenant_id')::uuid)"
            )
        )

        # UPDATE policy
        op.execute(
            sa.text(
                f"CREATE POLICY tenant_isolation_update_{table} ON {table} "
                f"FOR UPDATE "
                f"USING (tenant_id = CURRENT_SETTING('app.current_tenant_id')::uuid) "
                f"WITH CHECK (tenant_id = CURRENT_SETTING('app.current_tenant_id')::uuid)"
            )
        )

        # DELETE policy
        op.execute(
            sa.text(
                f"CREATE POLICY tenant_isolation_delete_{table} ON {table} "
                f"FOR DELETE "
                f"USING (tenant_id = CURRENT_SETTING('app.current_tenant_id')::uuid)"
            )
        )


def downgrade() -> None:
    for table in reversed(TENANT_SCOPED_TABLES):
        # Drop all four policies
        op.execute(sa.text(f"DROP POLICY IF EXISTS tenant_isolation_delete_{table} ON {table}"))
        op.execute(sa.text(f"DROP POLICY IF EXISTS tenant_isolation_update_{table} ON {table}"))
        op.execute(sa.text(f"DROP POLICY IF EXISTS tenant_isolation_insert_{table} ON {table}"))
        op.execute(sa.text(f"DROP POLICY IF EXISTS tenant_isolation_select_{table} ON {table}"))

        # Disable RLS
        op.execute(sa.text(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY"))
        op.execute(sa.text(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY"))
