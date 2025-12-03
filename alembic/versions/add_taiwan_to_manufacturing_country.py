"""Add Taiwan to manufacturing_country enum

Revision ID: add_taiwan_001
Revises: add_ship_prof_001
Create Date: 2025-12-03

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "add_taiwan_001"
down_revision: Union[str, Sequence[str], None] = "add_ship_prof_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add TW (Taiwan) to the manufacturingcountry enum
    op.execute("ALTER TYPE manufacturingcountry ADD VALUE IF NOT EXISTS 'TW'")


def downgrade() -> None:
    # PostgreSQL doesn't support removing enum values easily
    # This would require recreating the entire enum type
    pass
