"""enhance_reverb_listing

Revision ID: e3326bf7ef11
Revises: 693554fba44c
Create Date: 2025-03-04 14:56:30.993859

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB  # Add this import


# revision identifiers, used by Alembic.
revision: str = 'e3326bf7ef11'
down_revision: Union[str, None] = '693554fba44c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop existing table
    op.drop_table('reverb_listings')
    
    # Create the new table with the enhanced schema
    op.create_table(
        'reverb_listings',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('platform_id', sa.Integer(), nullable=True),
        
        # Core Reverb identifiers
        sa.Column('reverb_listing_id', sa.String(), nullable=True),
        sa.Column('reverb_slug', sa.String(), nullable=True),
        
        # Category and condition
        sa.Column('reverb_category_uuid', sa.String(), nullable=True),
        sa.Column('condition_rating', sa.Float(), nullable=True),
        
        # Business-critical fields
        sa.Column('inventory_quantity', sa.Integer(), server_default='1', nullable=True),
        sa.Column('has_inventory', sa.Boolean(), server_default='true', nullable=True),
        sa.Column('offers_enabled', sa.Boolean(), server_default='true', nullable=True),
        sa.Column('is_auction', sa.Boolean(), server_default='false', nullable=True),
        
        # Pricing
        sa.Column('list_price', sa.Float(), nullable=True),
        sa.Column('listing_currency', sa.String(), nullable=True),
        
        # Shipping
        sa.Column('shipping_profile_id', sa.String(), nullable=True),
        sa.Column('shop_policies_id', sa.String(), nullable=True),
        
        # Status
        sa.Column('reverb_state', sa.String(), nullable=True),
        
        # Statistics
        sa.Column('view_count', sa.Integer(), server_default='0', nullable=True),
        sa.Column('watch_count', sa.Integer(), server_default='0', nullable=True),
        
        # Tracking fields
        sa.Column('reverb_created_at', sa.DateTime(), nullable=True),
        sa.Column('reverb_published_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.Column('last_synced_at', sa.DateTime(), nullable=True),
        
        # Flexible storage
        sa.Column('extended_attributes', JSONB(), server_default='{}', nullable=True),
        
        # Other attributes
        sa.Column('handmade', sa.Boolean(), server_default='false', nullable=True),
        
        # Foreign key
        sa.ForeignKeyConstraint(['platform_id'], ['platform_common.id']),
    )


def downgrade() -> None:
    # Drop the new table
    op.drop_table('reverb_listings')
    
    # Recreate original table
    op.create_table(
        'reverb_listings',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('platform_id', sa.Integer(), nullable=True),
        sa.Column('reverb_listing_id', sa.String(), nullable=True),
        sa.Column('reverb_category_uuid', sa.String(), nullable=True),
        sa.Column('condition_rating', sa.Float(), nullable=True),
        sa.Column('shipping_profile_id', sa.String(), nullable=True),
        sa.Column('shop_policies_id', sa.String(), nullable=True),
        sa.Column('handmade', sa.Boolean(), server_default='false', nullable=True),
        sa.Column('offers_enabled', sa.Boolean(), server_default='true', nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.Column('last_synced_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['platform_id'], ['platform_common.id']),
    )
