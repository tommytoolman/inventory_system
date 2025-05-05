"""add timestamp and reverb_listing_id columns to reverb_listings

Revision ID: 2e74a3eb842a
Revises: [put previous revision ID here or leave empty string if it's the first]
Create Date: [current date and time]

"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from datetime import datetime, timezone

# revision identifiers, used by Alembic.
revision: str = '2e74a3eb842a'
down_revision: Union[str, None] = None  # Replace with previous revision if needed
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # Add missing columns
    op.add_column('reverb_listings', sa.Column('reverb_listing_id', sa.String(), nullable=True))
    op.add_column('reverb_listings', sa.Column('created_at', sa.DateTime(), nullable=True, server_default=sa.func.now()))
    op.add_column('reverb_listings', sa.Column('updated_at', sa.DateTime(), nullable=True, server_default=sa.func.now()))
    op.add_column('reverb_listings', sa.Column('last_synced_at', sa.DateTime(), nullable=True))

def downgrade() -> None:
    # Remove columns if needed
    op.drop_column('reverb_listings', 'last_synced_at')
    op.drop_column('reverb_listings', 'updated_at')
    op.drop_column('reverb_listings', 'created_at')
    op.drop_column('reverb_listings', 'reverb_listing_id')