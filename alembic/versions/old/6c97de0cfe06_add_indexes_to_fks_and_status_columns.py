"""Add indexes to FKs and status columns

Revision ID: 6c97de0cfe06
Revises: 7c525b74fe68
Create Date: 2025-04-30 09:54:17.440004

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
# No need for postgresql dialect import if only doing indexes

# revision identifiers, used by Alembic.
revision: str = '6c97de0cfe06'
down_revision: Union[str, None] = '7c525b74fe68'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ### Manually adjusted: Only create indexes ###
    print("Creating specified indexes...")
    op.create_index(op.f('ix_ebay_listings_platform_id'), 'ebay_listings', ['platform_id'], unique=False)
    op.create_index(op.f('ix_orders_platform_listing_id'), 'orders', ['platform_listing_id'], unique=False)
    op.create_index(op.f('ix_platform_common_product_id'), 'platform_common', ['product_id'], unique=False)
    op.create_index(op.f('ix_platform_common_status'), 'platform_common', ['status'], unique=False)
    op.create_index(op.f('ix_platform_common_sync_status'), 'platform_common', ['sync_status'], unique=False)
    op.create_index(op.f('ix_products_status'), 'products', ['status'], unique=False)
    op.create_index(op.f('ix_reverb_listings_platform_id'), 'reverb_listings', ['platform_id'], unique=False)
    op.create_index(op.f('ix_reverb_listings_reverb_state'), 'reverb_listings', ['reverb_state'], unique=False)
    op.create_index(op.f('ix_sales_platform_listing_id'), 'sales', ['platform_listing_id'], unique=False)
    op.create_index(op.f('ix_sales_product_id'), 'sales', ['product_id'], unique=False)
    op.create_index(op.f('ix_shipments_sale_id'), 'shipments', ['sale_id'], unique=False)
    op.create_index(op.f('ix_shipments_status'), 'shipments', ['status'], unique=False)
    print("Finished creating indexes.")
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### Manually adjusted: Only drop indexes ###
    print("Dropping specified indexes...")
    op.drop_index(op.f('ix_shipments_status'), table_name='shipments')
    op.drop_index(op.f('ix_shipments_sale_id'), table_name='shipments')
    op.drop_index(op.f('ix_sales_product_id'), table_name='sales')
    op.drop_index(op.f('ix_sales_platform_listing_id'), table_name='sales')
    op.drop_index(op.f('ix_reverb_listings_reverb_state'), table_name='reverb_listings')
    op.drop_index(op.f('ix_reverb_listings_platform_id'), table_name='reverb_listings')
    op.drop_index(op.f('ix_products_status'), table_name='products')
    op.drop_index(op.f('ix_platform_common_sync_status'), table_name='platform_common')
    op.drop_index(op.f('ix_platform_common_status'), table_name='platform_common')
    op.drop_index(op.f('ix_platform_common_product_id'), table_name='platform_common')
    op.drop_index(op.f('ix_orders_platform_listing_id'), table_name='orders')
    op.drop_index(op.f('ix_ebay_listings_platform_id'), table_name='ebay_listings')
    print("Finished dropping indexes.")
    # ### end Alembic commands ###