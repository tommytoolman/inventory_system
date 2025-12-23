"""Merge shopify_orders and taiwan heads

Revision ID: merge_shopify_taiwan
Revises: add_shopify_orders, add_taiwan_001
Create Date: 2025-12-23
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "merge_shopify_taiwan"
down_revision: Union[str, Sequence[str], None] = ("add_shopify_orders", "add_taiwan_001")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
