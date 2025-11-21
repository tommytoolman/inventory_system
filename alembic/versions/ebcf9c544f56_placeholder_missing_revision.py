"""Placeholder for missing revision ebcf9c544f56

This file recreates the revision that already exists in the live database so that
Alembic has a continuous history locally.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ebcf9c544f56'
down_revision: Union[str, None] = '8c573c6cff44'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """No-op placeholder."""
    pass


def downgrade() -> None:
    """No-op placeholder."""
    pass

