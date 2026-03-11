"""Merge heads

Revision ID: 34ba72961c13
Revises: 92561819fc0a, 92c2007b869e
Create Date: 2025-09-14 18:09:29.517812

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '34ba72961c13'
down_revision: Union[str, None] = ('92561819fc0a', '92c2007b869e')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
