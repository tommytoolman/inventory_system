"""Add Panama to manufacturing_country enum

Revision ID: add_panama_001
Revises: c1d43d7f2790
Create Date: 2026-03-18

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "add_panama_001"
down_revision: Union[str, Sequence[str], None] = "c1d43d7f2790"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE manufacturingcountry ADD VALUE IF NOT EXISTS 'PA'")


def downgrade() -> None:
    # PostgreSQL doesn't support removing enum values easily
    pass
