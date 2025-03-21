"""add_shipping_tables

Revision ID: 9d8582100767
Revises: e3326bf7ef11
Create Date: 2025-03-18 12:15:49.846926

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9d8582100767'
down_revision: Union[str, None] = 'e3326bf7ef11'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    # Try to create shipping_profiles table
    try:
        op.create_table(
            'shipping_profiles',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('name', sa.String(), nullable=False),
            sa.Column('description', sa.String(), nullable=True),
            sa.Column('is_default', sa.Boolean(), default=False),
            sa.Column('dimensions', sa.JSON(), nullable=True),  # Stores length, width, height
            sa.Column('weight', sa.Float(), nullable=True),
            sa.Column('carriers', sa.JSON(), nullable=True),  # Stores array of carrier codes
            sa.Column('options', sa.JSON(), nullable=True),  # Stores insurance, signature, etc.
            sa.Column('rates', sa.JSON(), nullable=True),  # Stores regional rates
            sa.Column('created_at', sa.DateTime(), default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(), default=sa.func.now(), onupdate=sa.func.now())
        )
        print("Created shipping_profiles table")
    except Exception as e:
        print(f"Skipping shipping_profiles creation: {e}")
    
    # Try to add each column separately to avoid issues if some columns already exist
    for column_name, column_def in [
        ('shipping_profile_id', sa.Column('shipping_profile_id', sa.Integer(), nullable=True)),
        ('package_type', sa.Column('package_type', sa.String(), nullable=True)),
        ('package_length', sa.Column('package_length', sa.Float(), nullable=True)),
        ('package_width', sa.Column('package_width', sa.Float(), nullable=True)),
        ('package_height', sa.Column('package_height', sa.Float(), nullable=True)),
        ('package_weight', sa.Column('package_weight', sa.Float(), nullable=True)),
        ('shipping_rates', sa.Column('shipping_rates', sa.JSON(), nullable=True)),
    ]:
        try:
            op.add_column('products', column_def)
            print(f"Added column {column_name} to products table")
        except Exception as e:
            print(f"Skipping column {column_name}: {e}")
    
    # Try to add foreign key
    try:
        op.create_foreign_key(
            'fk_product_shipping_profile',
            'products', 'shipping_profiles',
            ['shipping_profile_id'], ['id']
        )
        print("Added foreign key constraint")
    except Exception as e:
        print(f"Skipping foreign key creation: {e}")
        

def downgrade():
    # Remove foreign key first
    op.drop_constraint('fk_product_shipping_profile', 'products', type_='foreignkey')
    
    # Remove added columns
    op.drop_column('products', 'shipping_rates')
    op.drop_column('products', 'package_weight')
    op.drop_column('products', 'package_height')
    op.drop_column('products', 'package_width')
    op.drop_column('products', 'package_length')
    op.drop_column('products', 'package_type')
    op.drop_column('products', 'shipping_profile_id')
    
    # Drop the shipping_profiles table
    op.drop_table('shipping_profiles')
