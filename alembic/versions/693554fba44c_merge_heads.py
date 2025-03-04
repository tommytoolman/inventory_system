"""merge heads

Revision ID: 693554fba44c
Revises: 2e74a3eb842a, a31e5bb8a24a
Create Date: 2025-03-04 14:43:42.657403

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '693554fba44c'
down_revision: Union[str, None] = ('2e74a3eb842a', 'a31e5bb8a24a')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
