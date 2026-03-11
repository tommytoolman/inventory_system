"""Merge VR jobs and reverb orders constraint heads

Revision ID: merge_f6f1e1d
Revises: f696435af2ee, 1e5b6a0f1e1d
Create Date: 2025-11-23 14:05:00
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "merge_f6f1e1d"
down_revision: Union[str, Sequence[str], None] = ("f696435af2ee", "1e5b6a0f1e1d")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
