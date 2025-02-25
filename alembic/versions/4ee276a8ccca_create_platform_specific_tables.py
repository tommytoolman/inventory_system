# alembic/versions/4ee276a8ccca_create_platform_specific_tables.py

"""create platform specific tables

Revision ID: 4ee276a8ccca
Revises: d76101de8296
Create Date: 2025-02-03 22:07:22.896632

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '4ee276a8ccca'
down_revision: Union[str, None] = 'd76101de8296'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # Create enum type first
    op.execute("CREATE TYPE productstatus AS ENUM ('DRAFT', 'ACTIVE', 'SOLD', 'ARCHIVED')")
    
    # Add new columns to products
    op.add_column('products', sa.Column('sku', sa.String(), nullable=True))
    op.add_column('products', sa.Column('brand', sa.String(), nullable=True))
    op.add_column('products', sa.Column('model', sa.String(), nullable=True))
    op.add_column('products', sa.Column('category', sa.String(), nullable=True))
    op.add_column('products', sa.Column('condition', sa.String(), nullable=True))
    op.add_column('products', sa.Column('base_price', sa.Float(), nullable=True))
    op.add_column('products', sa.Column('cost_price', sa.Float(), nullable=True))
    op.add_column('products', sa.Column('status', postgresql.ENUM('DRAFT', 'ACTIVE', 'SOLD', 'ARCHIVED', name='productstatus'), nullable=True))
    op.add_column('products', sa.Column('primary_image', sa.String(), nullable=True))
    op.add_column('products', sa.Column('additional_images', postgresql.JSONB(), nullable=True))
    
    # Create unique constraint on sku
    op.create_unique_constraint('uq_products_sku', 'products', ['sku'])
    
    # Create platform_common table
    op.create_table('platform_common',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('product_id', sa.Integer(), nullable=True),
        sa.Column('platform_name', sa.String(), nullable=True),
        sa.Column('external_id', sa.String(), nullable=True),
        sa.Column('status', sa.String(), nullable=True),
        sa.Column('last_sync', sa.DateTime(), nullable=True),
        sa.Column('sync_status', sa.String(), nullable=True),
        sa.ForeignKeyConstraint(['product_id'], ['products.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create ebay_listings table
    op.create_table('ebay_listings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('platform_id', sa.Integer(), nullable=True),
        sa.Column('ebay_category_id', sa.String(), nullable=True),
        sa.Column('ebay_condition_id', sa.String(), nullable=True),
        sa.Column('item_specifics', postgresql.JSONB(), nullable=True),
        sa.Column('shipping_policy_id', sa.String(), nullable=True),
        sa.Column('return_policy_id', sa.String(), nullable=True),
        sa.Column('payment_policy_id', sa.String(), nullable=True),
        sa.Column('listing_duration', sa.String(), nullable=True),
        sa.ForeignKeyConstraint(['platform_id'], ['platform_common.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create reverb_listings table
    op.create_table('reverb_listings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('platform_id', sa.Integer(), nullable=True),
        sa.Column('reverb_category_uuid', sa.String(), nullable=True),
        sa.Column('condition_rating', sa.Float(), nullable=True),
        sa.Column('shipping_profile_id', sa.String(), nullable=True),
        sa.Column('shop_policies_id', sa.String(), nullable=True),
        sa.Column('handmade', sa.Boolean(), nullable=True),
        sa.Column('offers_enabled', sa.Boolean(), nullable=True),
        sa.ForeignKeyConstraint(['platform_id'], ['platform_common.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create vr_listings table
    op.create_table('vr_listings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('platform_id', sa.Integer(), nullable=True),
        sa.Column('in_collective', sa.Boolean(), nullable=True),
        sa.Column('in_inventory', sa.Boolean(), nullable=True),
        sa.Column('in_reseller', sa.Boolean(), nullable=True),
        sa.Column('collective_discount', sa.Float(), nullable=True),
        sa.Column('price_notax', sa.Float(), nullable=True),
        sa.Column('show_vat', sa.Boolean(), nullable=True),
        sa.Column('processing_time', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['platform_id'], ['platform_common.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create website_listings table
    op.create_table('website_listings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('platform_id', sa.Integer(), nullable=True),
        sa.Column('seo_title', sa.String(), nullable=True),
        sa.Column('seo_description', sa.String(), nullable=True),
        sa.Column('seo_keywords', postgresql.JSONB(), nullable=True),
        sa.Column('featured', sa.Boolean(), nullable=True),
        sa.Column('custom_layout', sa.String(), nullable=True),
        sa.ForeignKeyConstraint(['platform_id'], ['platform_common.id'], ),
        sa.PrimaryKeyConstraint('id')
    )

def downgrade() -> None:
    # Drop the platform-specific tables first
    op.drop_table('website_listings')
    op.drop_table('vr_listings')
    op.drop_table('reverb_listings')
    op.drop_table('ebay_listings')
    op.drop_table('platform_common')
    
    # Drop new columns from products
    op.drop_column('products', 'additional_images')
    op.drop_column('products', 'primary_image')
    op.drop_column('products', 'status')
    op.drop_column('products', 'cost_price')
    op.drop_column('products', 'base_price')
    op.drop_column('products', 'condition')
    op.drop_column('products', 'category')
    op.drop_column('products', 'model')
    op.drop_column('products', 'brand')
    op.drop_column('products', 'sku')
    
    # Drop the enum type last
    op.execute('DROP TYPE productstatus')