"""Add sync_errors table for automatic error capture

Revision ID: add_sync_errors_001
Revises: add_ship_prof_001
Create Date: 2026-03-11

Stores all sync/upload errors with full context for debugging and
support. Referenced by the error log UI at /errors/sync.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "add_sync_errors_001"
down_revision: Union[str, Sequence[str], None] = "add_ship_prof_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def table_exists(table_name: str) -> bool:
    conn = op.get_bind()
    if conn.dialect.name == "sqlite":
        result = conn.execute(
            text("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name = :n"),
            {"n": table_name},
        )
        return result.scalar() > 0
    result = conn.execute(
        text(
            "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = :n)"
        ),
        {"n": table_name},
    )
    return result.scalar()


def upgrade() -> None:
    if table_exists("sync_errors"):
        print("sync_errors table already exists, skipping")
        return

    op.create_table(
        "sync_errors",
        sa.Column("id", sa.String(12), primary_key=True),
        sa.Column(
            "product_id",
            sa.Integer(),
            sa.ForeignKey("products.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("platform", sa.String(50), nullable=False, index=True),
        sa.Column("operation", sa.String(20), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("error_type", sa.String(100), nullable=False),
        sa.Column("stack_trace", sa.Text(), nullable=False),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("extra_context", JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=text("timezone('utc', now())"),
            index=True,
        ),
        sa.Column("resolved", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("resolution_notes", sa.Text(), nullable=True),
    )

    print("Created sync_errors table")


def downgrade() -> None:
    op.drop_table("sync_errors")
