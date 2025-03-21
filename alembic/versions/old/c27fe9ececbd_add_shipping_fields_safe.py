"""add_shipping_fields_safe

Revision ID: c27fe9ececbd
Revises: 9d8582100767
Create Date: 2025-03-18 12:21:21.542936

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c27fe9ececbd'
down_revision: Union[str, None] = '9d8582100767'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    # Get connection
    connection = op.get_bind()
    
    # Add columns with IF NOT EXISTS for safety
    for column_data in [
        ('shipping_profile_id', 'INTEGER'),
        ('package_type', 'VARCHAR'),
        ('package_length', 'FLOAT'),
        ('package_width', 'FLOAT'),
        ('package_height', 'FLOAT'),
        ('package_weight', 'FLOAT'),
        ('shipping_rates', 'JSON')
    ]:
        try:
            column_name, column_type = column_data
            connection.execute(f"ALTER TABLE products ADD COLUMN IF NOT EXISTS {column_name} {column_type}")
            print(f"Added {column_name} column")
        except Exception as e:
            print(f"Error adding {column_name}: {str(e)}")
    
    # Add foreign key
    try:
        connection.execute("""
            DO $$ 
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname = 'fk_product_shipping_profile'
                ) THEN
                    ALTER TABLE products 
                    ADD CONSTRAINT fk_product_shipping_profile 
                    FOREIGN KEY (shipping_profile_id) 
                    REFERENCES shipping_profiles (id);
                END IF;
            END $$;
        """)
        print("Added foreign key")
    except Exception as e:
        print(f"Error adding foreign key: {str(e)}")

def downgrade():
    # Get connection
    connection = op.get_bind()
    
    # Drop foreign key
    try:
        connection.execute("ALTER TABLE products DROP CONSTRAINT IF EXISTS fk_product_shipping_profile")
    except Exception as e:
        print(f"Error dropping foreign key: {str(e)}")
    
    # Drop columns
    for column_name in [
        'shipping_rates',
        'package_weight',
        'package_height',
        'package_width',
        'package_length',
        'package_type',
        'shipping_profile_id'
    ]:
        try:
            connection.execute(f"ALTER TABLE products DROP COLUMN IF EXISTS {column_name}")
        except Exception as e:
            print(f"Error dropping {column_name}: {str(e)}")