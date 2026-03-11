"""Add sync_stats table for tracking sync statistics

Revision ID: 07657d86e3be
Revises: 34ba72961c13
Create Date: 2025-09-14 18:25:00.642057

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '07657d86e3be'
down_revision: Union[str, None] = '34ba72961c13'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create sync_stats table
    op.create_table('sync_stats',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('sync_run_id', sa.String(), nullable=True),
        sa.Column('platform', sa.String(), nullable=True),
        sa.Column('total_events_processed', sa.BigInteger(), default=0),
        sa.Column('total_sales', sa.BigInteger(), default=0),
        sa.Column('total_listings_created', sa.BigInteger(), default=0),
        sa.Column('total_listings_updated', sa.BigInteger(), default=0),
        sa.Column('total_listings_removed', sa.BigInteger(), default=0),
        sa.Column('total_price_changes', sa.BigInteger(), default=0),
        sa.Column('total_errors', sa.BigInteger(), default=0),
        sa.Column('total_partial_syncs', sa.BigInteger(), default=0),
        sa.Column('total_successful_syncs', sa.BigInteger(), default=0),
        sa.Column('run_events_processed', sa.Integer(), default=0),
        sa.Column('run_sales', sa.Integer(), default=0),
        sa.Column('run_listings_created', sa.Integer(), default=0),
        sa.Column('run_listings_updated', sa.Integer(), default=0),
        sa.Column('run_listings_removed', sa.Integer(), default=0),
        sa.Column('run_price_changes', sa.Integer(), default=0),
        sa.Column('run_errors', sa.Integer(), default=0),
        sa.Column('run_duration_seconds', sa.Integer(), nullable=True),
        sa.Column('metadata_json', sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_sync_stats_sync_run_id'), 'sync_stats', ['sync_run_id'], unique=False)
    op.create_index(op.f('ix_sync_stats_platform'), 'sync_stats', ['platform'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_sync_stats_platform'), table_name='sync_stats')
    op.drop_index(op.f('ix_sync_stats_sync_run_id'), table_name='sync_stats')
    op.drop_table('sync_stats')
