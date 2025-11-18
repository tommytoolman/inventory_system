"""add jobs table

Revision ID: bd5b6f8c0ccc
Revises: f6f4c9bfc1b4
Create Date: 2025-11-17 22:25:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'bd5b6f8c0ccc'
down_revision: Union[str, None] = 'f6f4c9bfc1b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'jobs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('job_type', sa.String(length=64), nullable=False, index=True),
        sa.Column('status', sa.String(length=32), nullable=False, server_default='pending', index=True),
        sa.Column('payload', sa.JSON(), nullable=True),
        sa.Column('message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text("timezone('utc', now())"), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text("timezone('utc', now())"), onupdate=sa.text("timezone('utc', now())"), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('jobs')
