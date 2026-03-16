"""Phase 1.1: Create tenant management tables and seed Tenant Zero.

Creates:
- tenants: Core tenant identity (UUID PK)
- users: System user accounts (if not exists)
- tenant_credentials: Per-tenant API keys (encrypted)
- tenant_users: Many-to-many tenant↔user with role
- tenant_usage: Per-tenant resource metering
- tenant_webhooks: Per-tenant event notification endpoints

Seeds Tenant Zero (Hanks Music) with a well-known UUID so existing
data can be backfilled in subsequent migrations.

Revision ID: phase1_001
Revises: merge_pre_phase1
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "phase1_001"
down_revision: Union[str, Sequence[str], None] = "merge_pre_phase1"
branch_labels = None
depends_on = None

TENANT_ZERO_ID = "00000000-0000-0000-0000-000000000001"


def upgrade() -> None:
    # --- Create enum types ---
    tenantstatus = sa.Enum("active", "suspended", "archived", name="tenantstatus")
    tenantstatus.create(op.get_bind(), checkfirst=True)

    credentialtype = sa.Enum(
        "reverb_api_key",
        "ebay_auth",
        "shopify_token",
        "vr_username",
        "woocommerce_key",
        name="credentialtype",
    )
    credentialtype.create(op.get_bind(), checkfirst=True)

    tenantrole = sa.Enum("owner", "admin", "operator", "viewer", name="tenantrole")
    tenantrole.create(op.get_bind(), checkfirst=True)

    # --- tenants ---
    op.create_table(
        "tenants",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(100), unique=True, nullable=False),
        sa.Column("status", tenantstatus, nullable=False, server_default="active"),
        sa.Column("metadata", JSONB, nullable=True, server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=False), server_default=sa.text("timezone('utc', now())"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.TIMESTAMP(timezone=False), server_default=sa.text("timezone('utc', now())"), nullable=False
        ),
    )
    op.create_index("ix_tenants_slug", "tenants", ["slug"])

    # --- users (create if not exists) ---
    # The User model exists but may not have been migrated yet.
    # Use a raw check to avoid errors if it already exists.
    conn = op.get_bind()
    result = conn.execute(sa.text("SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'users')"))
    users_exists = result.scalar()
    if not users_exists:
        op.create_table(
            "users",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("username", sa.String(), unique=True, nullable=False),
            sa.Column("email", sa.String(), unique=True, nullable=False),
            sa.Column("hashed_password", sa.String(), nullable=False),
            sa.Column("is_active", sa.Boolean(), server_default="true"),
            sa.Column("is_superuser", sa.Boolean(), server_default="false"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True)),
        )

    # --- tenant_credentials ---
    op.create_table(
        "tenant_credentials",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("credential_type", credentialtype, nullable=False),
        sa.Column("credential_key", sa.String(500), nullable=False),
        sa.Column("credential_secret", sa.String(500), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=False), server_default=sa.text("timezone('utc', now())"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.TIMESTAMP(timezone=False), server_default=sa.text("timezone('utc', now())"), nullable=False
        ),
    )
    op.create_index("ix_tenant_credentials_tenant_id", "tenant_credentials", ["tenant_id"])

    # --- tenant_users ---
    op.create_table(
        "tenant_users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", tenantrole, nullable=False, server_default="viewer"),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=False), server_default=sa.text("timezone('utc', now())"), nullable=False
        ),
    )
    op.create_index("ix_tenant_users_tenant_id", "tenant_users", ["tenant_id"])
    op.create_index("ix_tenant_users_user_id", "tenant_users", ["user_id"])
    op.create_unique_constraint("uq_tenant_user", "tenant_users", ["tenant_id", "user_id"])

    # --- tenant_usage ---
    op.create_table(
        "tenant_usage",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("sync_events_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("orders_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("api_calls_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("storage_bytes", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=False), server_default=sa.text("timezone('utc', now())"), nullable=False
        ),
    )
    op.create_index("ix_tenant_usage_tenant_id", "tenant_usage", ["tenant_id"])

    # --- tenant_webhooks ---
    op.create_table(
        "tenant_webhooks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("webhook_url", sa.String(500), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=False), server_default=sa.text("timezone('utc', now())"), nullable=False
        ),
    )
    op.create_index("ix_tenant_webhooks_tenant_id", "tenant_webhooks", ["tenant_id"])

    # --- Seed Tenant Zero (Hanks Music) ---
    op.execute(
        sa.text(
            f"INSERT INTO tenants (id, name, slug, status, created_at, updated_at) "
            f"VALUES ('{TENANT_ZERO_ID}', 'Hanks Music', 'hanks', 'active', "
            f"timezone('utc', now()), timezone('utc', now())) "
            f"ON CONFLICT (slug) DO NOTHING"
        )
    )


def downgrade() -> None:
    # Remove Tenant Zero
    op.execute(sa.text(f"DELETE FROM tenants WHERE id = '{TENANT_ZERO_ID}'"))

    # Drop tables in reverse dependency order
    op.drop_table("tenant_webhooks")
    op.drop_table("tenant_usage")
    op.drop_table("tenant_users")
    op.drop_table("tenant_credentials")
    op.drop_table("tenants")

    # Drop enum types
    sa.Enum(name="tenantrole").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="credentialtype").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="tenantstatus").drop(op.get_bind(), checkfirst=True)

    # Do NOT drop the users table — it may have been pre-existing
