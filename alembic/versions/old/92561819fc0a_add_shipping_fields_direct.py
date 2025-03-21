"""add_shipping_fields_direct

Revision ID: 92561819fc0a
Revises: c27fe9ececbd
Create Date: 2025-03-18 12:22:36.029409

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '92561819fc0a'
down_revision: Union[str, None] = 'c27fe9ececbd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


from alembic import op
import sqlalchemy as sa

def upgrade():
    # Use SQL directly to avoid transaction issues
    op.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS shipping_profile_id INTEGER")
    op.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS package_type VARCHAR")
    op.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS package_length FLOAT")
    op.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS package_width FLOAT")
    op.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS package_height FLOAT")
    op.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS package_weight FLOAT")
    op.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS shipping_rates JSON")
    
    # Add foreign key if not exists (PostgreSQL syntax)
    op.execute("""
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

def downgrade():
    # Drop foreign key first
    op.execute("ALTER TABLE products DROP CONSTRAINT IF EXISTS fk_product_shipping_profile")
    
    # Drop columns
    op.execute("ALTER TABLE products DROP COLUMN IF EXISTS shipping_rates")
    op.execute("ALTER TABLE products DROP COLUMN IF EXISTS package_weight")
    op.execute("ALTER TABLE products DROP COLUMN IF EXISTS package_height")
    op.execute("ALTER TABLE products DROP COLUMN IF EXISTS package_width")
    op.execute("ALTER TABLE products DROP COLUMN IF EXISTS package_length")
    op.execute("ALTER TABLE products DROP COLUMN IF EXISTS package_type")
    op.execute("ALTER TABLE products DROP COLUMN IF EXISTS shipping_profile_id")
