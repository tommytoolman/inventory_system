"""Add shipping_profile_id to shopify_listings

Revision ID: add_ship_prof_001
Revises: merge_f6f1e1d
Create Date: 2025-12-03

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "add_ship_prof_001"
down_revision: Union[str, Sequence[str], None] = "merge_f6f1e1d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add shipping_profile_id column to track which Shopify DeliveryProfile is assigned
    op.add_column(
        "shopify_listings",
        sa.Column("shipping_profile_id", sa.String(100), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("shopify_listings", "shipping_profile_id")
