"""Add activity log table manually

Revision ID: a117699444e2
Revises: 349090d555d4
Create Date: 2025-05-12 19:45:23.693605

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from typing import Union, Sequence

# revision identifiers, used by Alembic.
revision: str = 'a117699444e2'
down_revision: Union[str, None] = '349090d555d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    # Create activity_log table
    op.create_table('activity_log',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('action', sa.String(length=50), nullable=False),
        sa.Column('entity_type', sa.String(length=50), nullable=False),
        sa.Column('entity_id', sa.String(length=100), nullable=False),
        sa.Column('platform', sa.String(length=50), nullable=True),
        sa.Column('details', JSONB(), nullable=True),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create indexes for faster querying
    op.create_index(op.f('ix_activity_log_action'), 'activity_log', ['action'], unique=False)
    op.create_index(op.f('ix_activity_log_created_at'), 'activity_log', ['created_at'], unique=False)
    op.create_index(op.f('ix_activity_log_entity_id'), 'activity_log', ['entity_id'], unique=False)
    op.create_index(op.f('ix_activity_log_entity_type'), 'activity_log', ['entity_type'], unique=False)
    op.create_index(op.f('ix_activity_log_platform'), 'activity_log', ['platform'], unique=False)
    
    # Add a foreign key if the users table exists
    # op.create_foreign_key(None, 'activity_log', 'users', ['user_id'], ['id'])
    # Uncomment the line above if you have a users table


def downgrade():
    # Remove foreign key if it was added
    # op.drop_constraint(None, 'activity_log', type_='foreignkey')
    
    # Drop indexes
    op.drop_index(op.f('ix_activity_log_platform'), table_name='activity_log')
    op.drop_index(op.f('ix_activity_log_entity_type'), table_name='activity_log')
    op.drop_index(op.f('ix_activity_log_entity_id'), table_name='activity_log')
    op.drop_index(op.f('ix_activity_log_created_at'), table_name='activity_log')
    op.drop_index(op.f('ix_activity_log_action'), table_name='activity_log')
    
    # Drop table
    op.drop_table('activity_log')
