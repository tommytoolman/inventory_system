# scripts/fix_shopify_table_migration.py
"""
Create migration to rename website_listings to shopify_listings and add category fields.
"""

def create_correct_migration():
    migration_content = '''"""Rename website_listings to shopify_listings and add category fields

Revision ID: rename_website_to_shopify_add_categories
Revises: [your_latest_revision]
Create Date: 2025-01-09

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = 'rename_website_to_shopify_add_categories'
down_revision = None  # Replace with your latest revision
branch_labels = None
depends_on = None

def upgrade():
    # 1. Rename the actual PostgreSQL table: website_listings → shopify_listings
    op.rename_table('website_listings', 'shopify_listings')
    
    # 2. Add new Shopify product identifier fields
    op.add_column('shopify_listings', sa.Column('shopify_product_id', sa.String(50), nullable=True))
    op.add_column('shopify_listings', sa.Column('shopify_legacy_id', sa.String(20), nullable=True))
    op.add_column('shopify_listings', sa.Column('handle', sa.String(255), nullable=True))
    op.add_column('shopify_listings', sa.Column('title', sa.String(255), nullable=True))
    op.add_column('shopify_listings', sa.Column('status', sa.String(20), nullable=True))
    
    # 3. Add category fields
    op.add_column('shopify_listings', sa.Column('category_gid', sa.String(100), nullable=True))
    op.add_column('shopify_listings', sa.Column('category_name', sa.String(255), nullable=True))
    op.add_column('shopify_listings', sa.Column('category_full_name', sa.Text(), nullable=True))
    op.add_column('shopify_listings', sa.Column('category_assigned_at', sa.DateTime(), nullable=True))
    op.add_column('shopify_listings', sa.Column('category_assignment_status', sa.String(20), nullable=True))
    
    # 4. Create indexes for better performance
    op.create_index('idx_shopify_product_id', 'shopify_listings', ['shopify_product_id'])
    op.create_index('idx_shopify_handle', 'shopify_listings', ['handle'])
    op.create_index('idx_shopify_category_gid', 'shopify_listings', ['category_gid'])
    op.create_index('idx_shopify_category_status', 'shopify_listings', ['category_assignment_status'])

def downgrade():
    # Drop indexes
    op.drop_index('idx_shopify_category_status', 'shopify_listings')
    op.drop_index('idx_shopify_category_gid', 'shopify_listings')
    op.drop_index('idx_shopify_handle', 'shopify_listings')
    op.drop_index('idx_shopify_product_id', 'shopify_listings')
    
    # Remove added columns
    op.drop_column('shopify_listings', 'category_assignment_status')
    op.drop_column('shopify_listings', 'category_assigned_at')
    op.drop_column('shopify_listings', 'category_full_name')
    op.drop_column('shopify_listings', 'category_name')
    op.drop_column('shopify_listings', 'category_gid')
    op.drop_column('shopify_listings', 'status')
    op.drop_column('shopify_listings', 'title')
    op.drop_column('shopify_listings', 'handle')
    op.drop_column('shopify_listings', 'shopify_legacy_id')
    op.drop_column('shopify_listings', 'shopify_product_id')
    
    # Rename table back
    op.rename_table('shopify_listings', 'website_listings')
'''

    from datetime import datetime
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    migration_file = f"alembic/versions/{timestamp}_rename_website_to_shopify_add_categories.py"
    
    with open(migration_file, 'w') as f:
        f.write(migration_content)
    
    print(f"✅ Created migration: {migration_file}")
    print(f"📝 This migration will:")
    print(f"   1. Rename: website_listings → shopify_listings")
    print(f"   2. Add Shopify product identifier fields")
    print(f"   3. Add category management fields")
    print(f"   4. Create performance indexes")

if __name__ == "__main__":
    create_correct_migration()