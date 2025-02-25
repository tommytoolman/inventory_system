"""drop_old_platform_listings_table

Revision ID: 0880cf909e4c
Revises: 4ee276a8ccca
Create Date: 2025-02-20 11:43:04.242688

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0880cf909e4c'
down_revision: Union[str, None] = '4ee276a8ccca'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade():
    op.drop_table('old_platform_listings')

def downgrade():
    # Recreate the table if we need to downgrade
    op.create_table('old_platform_listings',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(), nullable=True),
        sa.Column('updated_at', sa.TIMESTAMP(), nullable=True),
        sa.Column('platform_name', sa.VARCHAR(), nullable=True),
        sa.Column('external_id', sa.VARCHAR(), nullable=True),
        sa.Column('product_id', sa.Integer(), nullable=True),
        sa.Column('listing_url', sa.VARCHAR(), nullable=True),
        sa.Column('sync_status', sa.VARCHAR(), nullable=True),
        sa.Column('last_sync', sa.TIMESTAMP(), nullable=True),
        sa.Column('platform_specific_data', sa.JSONB(), nullable=True),
        sa.ForeignKeyConstraint(['product_id'], ['products.id'], ),
        sa.PrimaryKeyConstraint('id')
    )