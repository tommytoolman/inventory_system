"""Add platform_preferences table

Revision ID: add_platform_preferences
Revises: add_woocommerce_tables
Create Date: 2026-03-03
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "add_platform_preferences"
down_revision: Union[str, Sequence[str], None] = "add_woocommerce_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"
    ts_default = (
        sa.text("CURRENT_TIMESTAMP")
        if is_sqlite
        else sa.text("timezone('utc', now())")
    )

    op.create_table(
        "platform_preferences",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "username",
            sa.String(),
            nullable=False,
            unique=True,
            index=True,
        ),
        sa.Column(
            "show_ebay", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column(
            "show_reverb", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column(
            "show_shopify",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "show_vintage_rare",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "show_woocommerce",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=ts_default,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_table("platform_preferences")
