"""Add deleted product status

Revision ID: 50a15e4ef9f2
Revises: 8c573c6cff44
Create Date: 2025-11-14 08:02:29.530240

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '50a15e4ef9f2'
down_revision: Union[str, None] = 'ebcf9c544f56'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE productstatus ADD VALUE IF NOT EXISTS 'DELETED'")


def downgrade() -> None:
    "Postgres can’t remove enum values without hacks, so instead we simply ..."
    pass
