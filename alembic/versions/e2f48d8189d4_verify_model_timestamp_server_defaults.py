"""Verify model timestamp server defaults

Revision ID: e2f48d8189d4
Revises: c363c35d0a10
Create Date: 2025-04-30 10:22:36.277807

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e2f48d8189d4'
down_revision: Union[str, None] = 'c363c35d0a10'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    pass
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    pass
    # ### end Alembic commands ###
