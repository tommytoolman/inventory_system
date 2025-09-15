"""create_normalized_category_mappings

Revision ID: 92c2007b869e
Revises: be5e5352ef34
Create Date: 2025-09-10 08:44:27.476492

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '92c2007b869e'
down_revision: Union[str, None] = 'be5e5352ef34'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create reverb_categories master table
    op.create_table(
        'reverb_categories',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('uuid', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('full_path', sa.String(), nullable=True),
        sa.Column('parent_uuid', sa.String(), nullable=True),
        sa.Column('item_count', sa.Integer(), nullable=True, default=0),
        sa.Column('created_at', sa.DateTime(), nullable=True, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), nullable=True, server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('uuid')
    )
    op.create_index('ix_reverb_categories_uuid', 'reverb_categories', ['uuid'])
    op.create_index('ix_reverb_categories_name', 'reverb_categories', ['name'])

    # Create eBay category mappings
    op.create_table(
        'ebay_category_mappings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('reverb_category_id', sa.Integer(), nullable=False),
        sa.Column('ebay_category_id', sa.String(), nullable=False),
        sa.Column('ebay_category_name', sa.String(), nullable=False),
        sa.Column('confidence_score', sa.Numeric(3, 2), nullable=True, default=1.0),
        sa.Column('is_verified', sa.Boolean(), nullable=True, default=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), nullable=True, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['reverb_category_id'], ['reverb_categories.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_ebay_category_mappings_reverb_id', 'ebay_category_mappings', ['reverb_category_id'])
    op.create_index('ix_ebay_category_mappings_ebay_id', 'ebay_category_mappings', ['ebay_category_id'])

    # Create Shopify category mappings
    op.create_table(
        'shopify_category_mappings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('reverb_category_id', sa.Integer(), nullable=False),
        sa.Column('shopify_gid', sa.String(), nullable=False),
        sa.Column('shopify_category_name', sa.String(), nullable=False),
        sa.Column('merchant_type', sa.String(), nullable=True),
        sa.Column('confidence_score', sa.Numeric(3, 2), nullable=True, default=1.0),
        sa.Column('is_verified', sa.Boolean(), nullable=True, default=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), nullable=True, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['reverb_category_id'], ['reverb_categories.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_shopify_category_mappings_reverb_id', 'shopify_category_mappings', ['reverb_category_id'])
    op.create_index('ix_shopify_category_mappings_gid', 'shopify_category_mappings', ['shopify_gid'])

    # Create VR category mappings
    op.create_table(
        'vr_category_mappings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('reverb_category_id', sa.Integer(), nullable=False),
        sa.Column('vr_category_id', sa.String(), nullable=False),
        sa.Column('vr_category_name', sa.String(), nullable=True),
        sa.Column('vr_subcategory_id', sa.String(), nullable=True),
        sa.Column('vr_subcategory_name', sa.String(), nullable=True),
        sa.Column('vr_sub_subcategory_id', sa.String(), nullable=True),
        sa.Column('vr_sub_subcategory_name', sa.String(), nullable=True),
        sa.Column('vr_sub_sub_subcategory_id', sa.String(), nullable=True),
        sa.Column('vr_sub_sub_subcategory_name', sa.String(), nullable=True),
        sa.Column('confidence_score', sa.Numeric(3, 2), nullable=True, default=1.0),
        sa.Column('is_verified', sa.Boolean(), nullable=True, default=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), nullable=True, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['reverb_category_id'], ['reverb_categories.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_vr_category_mappings_reverb_id', 'vr_category_mappings', ['reverb_category_id'])
    op.create_index('ix_vr_category_mappings_vr_cat_id', 'vr_category_mappings', ['vr_category_id'])


def downgrade() -> None:
    op.drop_table('vr_category_mappings')
    op.drop_table('shopify_category_mappings')
    op.drop_table('ebay_category_mappings')
    op.drop_table('reverb_categories')
