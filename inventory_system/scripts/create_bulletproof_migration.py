#!/usr/bin/env python3
"""
Create a bulletproof migration that handles all edge cases
"""

def generate_bulletproof_migration():
    return '''"""Initial schema - bulletproof version with proper sequence handling

Revision ID: 002_bulletproof_initial
Revises:
Create Date: 2025-09-16

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '002_bulletproof_initial'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create custom types/enums
    op.execute("CREATE TYPE IF NOT EXISTS productcondition AS ENUM ('NEW', 'EXCELLENT', 'VERY_GOOD', 'GOOD', 'FAIR', 'POOR')")
    op.execute("CREATE TYPE IF NOT EXISTS productstatus AS ENUM ('DRAFT', 'ACTIVE', 'SOLD', 'ARCHIVED', 'draft', 'active', 'sold', 'archived')")
    op.execute("CREATE TYPE IF NOT EXISTS productstatus_old AS ENUM ('DRAFT', 'ACTIVE', 'SOLD', 'ARCHIVED', 'draft', 'active', 'sold', 'archived')")
    op.execute("CREATE TYPE IF NOT EXISTS shipmentstatus AS ENUM ('CREATED', 'LABEL_CREATED', 'PICKED_UP', 'IN_TRANSIT', 'DELIVERED', 'EXCEPTION', 'CANCELLED')")
    op.execute("CREATE TYPE IF NOT EXISTS platformname AS ENUM ('reverb', 'ebay', 'shopify', 'vr')")

    # Create all tables with SERIAL instead of manual sequences
    # This way PostgreSQL handles sequence creation automatically

    # Independent tables first
    op.create_table('shipping_profiles',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('reverb_profile_id', sa.String(), nullable=True),
        sa.Column('ebay_profile_id', sa.String(), nullable=True),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('is_default', sa.Boolean(), server_default='false'),
        sa.Column('package_type', sa.String(), nullable=True),
        sa.Column('weight', sa.Float(), nullable=True),
        sa.Column('dimensions', postgresql.JSONB(), nullable=True),
        sa.Column('carriers', postgresql.JSONB(), nullable=True),
        sa.Column('options', postgresql.JSONB(), nullable=True),
        sa.Column('rates', postgresql.JSONB(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text("timezone('utc', now())")),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text("timezone('utc', now())"))
    )

    op.create_table('users',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('username', sa.String(), nullable=False),
        sa.Column('email', sa.String(), nullable=False),
        sa.Column('hashed_password', sa.String(), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default='true'),
        sa.Column('is_superuser', sa.Boolean(), server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint('username'),
        sa.UniqueConstraint('email')
    )

    op.create_table('activity_log',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('action', sa.String(50), nullable=False),
        sa.Column('entity_type', sa.String(50), nullable=False),
        sa.Column('entity_id', sa.String(100), nullable=False),
        sa.Column('platform', sa.String(50), nullable=True),
        sa.Column('details', postgresql.JSONB(), nullable=True),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()'))
    )

    op.create_table('category_mappings',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('source_platform', sa.String(20), nullable=False),
        sa.Column('source_id', sa.String(36), nullable=False),
        sa.Column('source_name', sa.String(255), nullable=False),
        sa.Column('source_parent_id', sa.String(), nullable=True),
        sa.Column('target_platform', sa.String(20), nullable=False),
        sa.Column('target_id', sa.String(36), nullable=False),
        sa.Column('target_name', sa.String(), nullable=False),
        sa.Column('target_parent_id', sa.String(), nullable=True),
        sa.Column('target_subcategory_id', sa.String(36), nullable=True),
        sa.Column('target_subcategory_name', sa.String(), nullable=True),
        sa.Column('target_tertiary_id', sa.String(36), nullable=True),
        sa.Column('target_tertiary_name', sa.String(), nullable=True),
        sa.Column('target_path', sa.String(), nullable=True),
        sa.Column('is_preferred', sa.Boolean(), server_default='false'),
        sa.Column('is_verified', sa.Boolean(), server_default='false'),
        sa.Column('confidence', sa.Float(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text("timezone('utc', now())")),
        sa.Column('updated_at', sa.DateTime(), nullable=True)
    )

    op.create_table('csv_import_logs',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('filename', sa.String(), nullable=False),
        sa.Column('platform', sa.String(), nullable=False),
        sa.Column('total_rows', sa.Integer(), nullable=True),
        sa.Column('successful_rows', sa.Integer(), nullable=True),
        sa.Column('failed_rows', sa.Integer(), nullable=True),
        sa.Column('error_log', sa.Text(), nullable=True)
    )

    op.create_table('platform_category_mappings',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('source_platform', sa.String(), nullable=False),
        sa.Column('source_category_id', sa.String(), nullable=False),
        sa.Column('source_category_name', sa.String(), nullable=False),
        sa.Column('target_platform', sa.String(), nullable=False),
        sa.Column('target_category_id', sa.String(), nullable=True),
        sa.Column('target_category_name', sa.String(), nullable=True),
        sa.Column('shopify_gid', sa.String(), nullable=True),
        sa.Column('merchant_type', sa.String(), nullable=True),
        sa.Column('vr_category_id', sa.String(), nullable=True),
        sa.Column('vr_subcategory_id', sa.String(), nullable=True),
        sa.Column('vr_sub_subcategory_id', sa.String(), nullable=True),
        sa.Column('vr_sub_sub_subcategory_id', sa.String(), nullable=True),
        sa.Column('item_count', sa.Integer(), nullable=True),
        sa.Column('confidence_score', sa.Float(), nullable=True),
        sa.Column('is_verified', sa.Boolean(), server_default='false'),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text("timezone('utc', now())")),
        sa.Column('updated_at', sa.DateTime(), nullable=True)
    )

    op.create_table('platform_policies',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('platform', sa.String(), nullable=False),
        sa.Column('policy_type', sa.String(), nullable=False),
        sa.Column('policy_id', sa.String(), nullable=False),
        sa.Column('policy_name', sa.String(), nullable=False),
        sa.Column('is_default', sa.Boolean(), server_default='false')
    )

    op.create_table('platform_status_mappings',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('platform', sa.String(), nullable=False),
        sa.Column('internal_status', sa.String(), nullable=False),
        sa.Column('platform_status', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"))
    )

    op.create_table('reverb_categories',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('full_name', sa.String(), nullable=False),
        sa.Column('uuid', sa.String(), nullable=False),
        sa.UniqueConstraint('full_name'),
        sa.UniqueConstraint('uuid')
    )

    op.create_table('vr_accepted_brands',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('brand_name', sa.String(), nullable=False),
        sa.Column('brand_id', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint('brand_name')
    )

    op.create_table('webhook_events',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('event_type', sa.String(), nullable=True),
        sa.Column('platform', sa.String(), nullable=True),
        sa.Column('payload', postgresql.JSONB(), nullable=True),
        sa.Column('processed', sa.Boolean(), server_default='false'),
        sa.Column('processed_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text("timezone('utc', now())"))
    )

    # Products and related tables
    op.create_table('products',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('sku', sa.String(), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('brand', sa.String(), nullable=True),
        sa.Column('model', sa.String(), nullable=True),
        sa.Column('category', sa.String(), nullable=True),
        sa.Column('tags', sa.String(), nullable=True),
        sa.Column('condition', sa.Enum('NEW', 'EXCELLENT', 'VERY_GOOD', 'GOOD', 'FAIR', 'POOR', name='productcondition'), nullable=False),
        sa.Column('condition_notes', sa.Text(), nullable=True),
        sa.Column('base_price', sa.Float(), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('location', sa.String(), nullable=True),
        sa.Column('primary_image', sa.String(), nullable=True),
        sa.Column('additional_images', postgresql.JSONB(), nullable=True),
        sa.Column('video_urls', postgresql.JSONB(), nullable=True),
        sa.Column('shipping_profile_id', sa.Integer(), nullable=True),
        sa.Column('processing_time', sa.Integer(), server_default='3'),
        sa.Column('status', sa.Enum('DRAFT', 'ACTIVE', 'SOLD', 'ARCHIVED', 'draft', 'active', 'sold', 'archived', name='productstatus'), nullable=False, server_default='DRAFT'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('package_type', sa.String(50), nullable=True),
        sa.Column('is_stocked_item', sa.Boolean(), server_default='false'),
        sa.ForeignKeyConstraint(['shipping_profile_id'], ['shipping_profiles.id']),
        sa.UniqueConstraint('sku')
    )

    op.create_table('product_mappings',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('master_product_id', sa.Integer(), nullable=False),
        sa.Column('related_product_id', sa.Integer(), nullable=False),
        sa.Column('mapping_type', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(['master_product_id'], ['products.id']),
        sa.ForeignKeyConstraint(['related_product_id'], ['products.id'])
    )

    op.create_table('product_merges',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('kept_product_id', sa.Integer(), nullable=False),
        sa.Column('merged_product_id', sa.Integer(), nullable=False),
        sa.Column('merged_product_data', postgresql.JSONB(), nullable=True),
        sa.Column('merged_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('merged_by', sa.String(), nullable=True),
        sa.Column('reason', sa.String(), nullable=True),
        sa.ForeignKeyConstraint(['kept_product_id'], ['products.id']),
        sa.ForeignKeyConstraint(['merged_product_id'], ['products.id'])
    )

    op.create_table('platform_common',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('product_id', sa.Integer(), nullable=True),
        sa.Column('platform_name', sa.Enum('reverb', 'ebay', 'shopify', 'vr', name='platformname'), nullable=False),
        sa.Column('external_id', sa.String(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('last_synced_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['product_id'], ['products.id']),
        sa.UniqueConstraint('product_id', 'platform_name', name='uq_product_platform')
    )

    # Platform-specific tables
    op.create_table('reverb_listings',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('platform_id', sa.Integer(), nullable=False),
        sa.Column('reverb_listing_id', sa.String(), nullable=True),
        sa.Column('reverb_id', sa.String(), nullable=True),
        sa.Column('make', sa.String(), nullable=True),
        sa.Column('model', sa.String(), nullable=True),
        sa.Column('finish', sa.String(), nullable=True),
        sa.Column('year', sa.String(), nullable=True),
        sa.Column('serial_number', sa.String(), nullable=True),
        sa.Column('price', sa.Float(), nullable=True),
        sa.Column('handmade', sa.Boolean(), server_default='false'),
        sa.Column('category_uuids', postgresql.JSONB(), nullable=True),
        sa.Column('listing_currency', sa.String(), server_default='GBP'),
        sa.Column('accept_offers', sa.Boolean(), server_default='false'),
        sa.Column('offer_type', sa.String(), nullable=True),
        sa.Column('minimum_offer_percentage', sa.Float(), nullable=True),
        sa.Column('shipping_profile_id', sa.String(), nullable=True),
        sa.Column('reverb_sync_status', sa.String(), nullable=True),
        sa.Column('reverb_state', sa.String(), nullable=True),
        sa.Column('extended_attributes', postgresql.JSONB(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['platform_id'], ['platform_common.id'])
    )

    op.create_table('ebay_listings',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('platform_id', sa.Integer(), nullable=False),
        sa.Column('ebay_item_id', sa.String(), nullable=True),
        sa.Column('ebay_category_id', sa.String(), nullable=True),
        sa.Column('ebay_store_category_id', sa.String(), nullable=True),
        sa.Column('listing_format', sa.String(), server_default='FIXED_PRICE'),
        sa.Column('price', sa.Float(), nullable=True),
        sa.Column('currency', sa.String(), server_default='GBP'),
        sa.Column('quantity', sa.Integer(), server_default='1'),
        sa.Column('condition_id', sa.String(), nullable=True),
        sa.Column('condition_description', sa.Text(), nullable=True),
        sa.Column('item_specifics', postgresql.JSONB(), nullable=True),
        sa.Column('payment_policy_id', sa.String(), nullable=True),
        sa.Column('return_policy_id', sa.String(), nullable=True),
        sa.Column('shipping_policy_id', sa.String(), nullable=True),
        sa.Column('best_offer_enabled', sa.Boolean(), server_default='false'),
        sa.Column('best_offer_auto_accept_price', sa.Float(), nullable=True),
        sa.Column('best_offer_minimum_price', sa.Float(), nullable=True),
        sa.Column('listing_duration', sa.String(), server_default='GTC'),
        sa.Column('private_listing', sa.Boolean(), server_default='false'),
        sa.Column('listing_status', sa.String(), nullable=True),
        sa.Column('extended_attributes', postgresql.JSONB(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('last_synced_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['platform_id'], ['platform_common.id']),
        sa.UniqueConstraint('ebay_item_id')
    )

    op.create_table('shopify_listings',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('platform_id', sa.Integer(), nullable=True),
        sa.Column('seo_title', sa.String(), nullable=True),
        sa.Column('seo_description', sa.String(), nullable=True),
        sa.Column('seo_keywords', postgresql.JSONB(), nullable=True),
        sa.Column('featured', sa.Boolean(), nullable=True),
        sa.Column('custom_layout', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text("timezone('utc', now())")),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text("timezone('utc', now())")),
        sa.Column('last_synced_at', sa.DateTime(), nullable=True),
        sa.Column('shopify_product_id', sa.String(50), nullable=True),
        sa.Column('shopify_legacy_id', sa.String(20), nullable=True),
        sa.Column('handle', sa.String(255), nullable=True),
        sa.Column('title', sa.String(255), nullable=True),
        sa.Column('status', sa.String(20), nullable=True),
        sa.Column('category_gid', sa.String(100), nullable=True),
        sa.Column('category_name', sa.String(255), nullable=True),
        sa.Column('category_full_name', sa.String(500), nullable=True),
        sa.Column('category_assigned_at', sa.DateTime(), nullable=True),
        sa.Column('category_assignment_status', sa.String(20), nullable=True),
        sa.Column('extended_attributes', postgresql.JSONB(), nullable=True),
        sa.Column('vendor', sa.String(255), nullable=True),
        sa.Column('price', sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(['platform_id'], ['platform_common.id'])
    )

    op.create_table('vr_listings',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('platform_id', sa.Integer(), nullable=False),
        sa.Column('vr_listing_id', sa.String(), nullable=True),
        sa.Column('vr_url', sa.String(), nullable=True),
        sa.Column('category_path', sa.String(), nullable=True),
        sa.Column('subcategory', sa.String(), nullable=True),
        sa.Column('decade', sa.String(), nullable=True),
        sa.Column('accepts_offers', sa.Boolean(), server_default='false'),
        sa.Column('accepts_part_exchange', sa.Boolean(), server_default='false'),
        sa.Column('on_sale', sa.Boolean(), server_default='false'),
        sa.Column('ships_from', sa.String(), nullable=True),
        sa.Column('available_to_ship_date', sa.DateTime(), nullable=True),
        sa.Column('tax_included', sa.Boolean(), server_default='true'),
        sa.Column('tax_rate_percentage', sa.Float(), nullable=True),
        sa.Column('price_notax', sa.Float(), nullable=True),
        sa.Column('dealers_collective', sa.Boolean(), server_default='false'),
        sa.Column('extended_attributes', postgresql.JSONB(), nullable=True),
        sa.Column('processing_time', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('last_synced_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['platform_id'], ['platform_common.id'])
    )

    # Category mapping tables
    op.create_table('ebay_category_mappings',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('reverb_category_id', sa.Integer(), nullable=False),
        sa.Column('ebay_category_id', sa.String(), nullable=False),
        sa.Column('ebay_category_name', sa.String(), nullable=False),
        sa.Column('confidence_score', sa.Numeric(3, 2), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(['reverb_category_id'], ['reverb_categories.id'])
    )

    op.create_table('shopify_category_mappings',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('reverb_category_id', sa.Integer(), nullable=False),
        sa.Column('shopify_gid', sa.String(), nullable=False),
        sa.Column('shopify_tags', sa.Text(), nullable=True),
        sa.Column('confidence_score', sa.Numeric(3, 2), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(['reverb_category_id'], ['reverb_categories.id'])
    )

    op.create_table('vr_category_mappings',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('reverb_category_id', sa.Integer(), nullable=False),
        sa.Column('vr_category', sa.String(), nullable=False),
        sa.Column('vr_subcategory', sa.String(), nullable=True),
        sa.Column('confidence_score', sa.Numeric(3, 2), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(['reverb_category_id'], ['reverb_categories.id'])
    )

    # Sales and orders
    op.create_table('sales',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('product_id', sa.Integer(), nullable=True),
        sa.Column('platform_listing_id', sa.Integer(), nullable=True),
        sa.Column('platform_name', sa.String(), nullable=False),
        sa.Column('order_id', sa.String(), nullable=False),
        sa.Column('sold_price', sa.Float(), nullable=False),
        sa.Column('currency', sa.String(), server_default='GBP'),
        sa.Column('quantity', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('buyer_name', sa.String(), nullable=True),
        sa.Column('buyer_email', sa.String(), nullable=True),
        sa.Column('shipping_address', postgresql.JSONB(), nullable=True),
        sa.Column('sold_at', sa.DateTime(), nullable=False),
        sa.Column('platform_fees', sa.Float(), nullable=True),
        sa.Column('shipping_cost', sa.Float(), nullable=True),
        sa.Column('net_amount', sa.Float(), nullable=True),
        sa.Column('status', sa.String(), nullable=True),
        sa.Column('tracking_number', sa.String(), nullable=True),
        sa.Column('shipped_at', sa.DateTime(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['platform_listing_id'], ['platform_common.id']),
        sa.ForeignKeyConstraint(['product_id'], ['products.id'])
    )

    op.create_table('orders',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('platform_listing_id', sa.Integer(), nullable=True),
        sa.Column('platform_order_id', sa.String(), nullable=False),
        sa.Column('platform_name', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('buyer_name', sa.String(), nullable=True),
        sa.Column('buyer_email', sa.String(), nullable=True),
        sa.Column('shipping_address', postgresql.JSONB(), nullable=True),
        sa.Column('order_total', sa.Float(), nullable=False),
        sa.Column('currency', sa.String(), server_default='GBP'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['platform_listing_id'], ['platform_common.id']),
        sa.UniqueConstraint('platform_order_id')
    )

    op.create_table('shipments',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('order_id', sa.Integer(), nullable=True),
        sa.Column('sale_id', sa.Integer(), nullable=True),
        sa.Column('platform_listing_id', sa.Integer(), nullable=True),
        sa.Column('tracking_number', sa.String(), nullable=True),
        sa.Column('carrier', sa.String(), nullable=True),
        sa.Column('service', sa.String(), nullable=True),
        sa.Column('weight', sa.Float(), nullable=True),
        sa.Column('dimensions', postgresql.JSONB(), nullable=True),
        sa.Column('shipping_cost', sa.Float(), nullable=True),
        sa.Column('label_url', sa.String(), nullable=True),
        sa.Column('shipped_at', sa.DateTime(), nullable=True),
        sa.Column('delivered_at', sa.DateTime(), nullable=True),
        sa.Column('status', sa.Enum('CREATED', 'LABEL_CREATED', 'PICKED_UP', 'IN_TRANSIT', 'DELIVERED', 'EXCEPTION', 'CANCELLED', name='shipmentstatus'), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['order_id'], ['orders.id']),
        sa.ForeignKeyConstraint(['platform_listing_id'], ['platform_common.id']),
        sa.ForeignKeyConstraint(['sale_id'], ['sales.id'])
    )

    # Sync tracking
    op.create_table('sync_events',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('sync_type', sa.String(), nullable=False),
        sa.Column('platform', sa.String(), nullable=False),
        sa.Column('product_id', sa.Integer(), nullable=True),
        sa.Column('platform_common_id', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('details', postgresql.JSONB(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=False),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['platform_common_id'], ['platform_common.id']),
        sa.ForeignKeyConstraint(['product_id'], ['products.id'])
    )

    op.create_table('sync_stats',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('sync_date', sa.Date(), nullable=False),
        sa.Column('platform', sa.String(), nullable=False),
        sa.Column('total_products', sa.Integer(), server_default='0'),
        sa.Column('synced_products', sa.Integer(), server_default='0'),
        sa.Column('failed_products', sa.Integer(), server_default='0'),
        sa.Column('new_listings', sa.Integer(), server_default='0'),
        sa.Column('updated_listings', sa.Integer(), server_default='0'),
        sa.Column('removed_listings', sa.Integer(), server_default='0'),
        sa.Column('sync_duration_seconds', sa.Float(), nullable=True),
        sa.Column('error_summary', postgresql.JSONB(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column('metadata_json', postgresql.JSONB(), nullable=True)
    )

    # Create indexes
    op.create_index('idx_activity_log_entity_type', 'activity_log', ['entity_type'])
    op.create_index('idx_activity_log_timestamp', 'activity_log', ['created_at'])
    op.create_index('idx_products_sku', 'products', ['sku'])
    op.create_index('idx_products_status', 'products', ['status'])
    op.create_index('idx_platform_common_platform_name', 'platform_common', ['platform_name'])
    op.create_index('idx_platform_common_external_id', 'platform_common', ['external_id'])
    op.create_index('idx_reverb_listings_reverb_id', 'reverb_listings', ['reverb_id'])
    op.create_index('idx_reverb_listings_reverb_listing_id', 'reverb_listings', ['reverb_listing_id'])
    op.create_index('idx_ebay_listings_listing_status', 'ebay_listings', ['listing_status'])
    op.create_index('idx_sales_order_id', 'sales', ['order_id'])
    op.create_index('idx_sales_platform_name', 'sales', ['platform_name'])
    op.create_index('idx_sales_sold_at', 'sales', ['sold_at'])
    op.create_index('idx_shipments_tracking_number', 'shipments', ['tracking_number'])
    op.create_index('idx_sync_events_platform', 'sync_events', ['platform'])
    op.create_index('idx_sync_events_status', 'sync_events', ['status'])
    op.create_index('idx_sync_events_started_at', 'sync_events', ['started_at'])
    op.create_index('idx_sync_stats_sync_date', 'sync_stats', ['sync_date'])
    op.create_index('idx_sync_stats_platform', 'sync_stats', ['platform'])


def downgrade() -> None:
    # Drop all tables in reverse order
    op.drop_table('sync_stats')
    op.drop_table('sync_events')
    op.drop_table('shipments')
    op.drop_table('orders')
    op.drop_table('sales')
    op.drop_table('vr_category_mappings')
    op.drop_table('shopify_category_mappings')
    op.drop_table('ebay_category_mappings')
    op.drop_table('vr_listings')
    op.drop_table('shopify_listings')
    op.drop_table('ebay_listings')
    op.drop_table('reverb_listings')
    op.drop_table('platform_common')
    op.drop_table('product_merges')
    op.drop_table('product_mappings')
    op.drop_table('products')
    op.drop_table('webhook_events')
    op.drop_table('vr_accepted_brands')
    op.drop_table('reverb_categories')
    op.drop_table('platform_status_mappings')
    op.drop_table('platform_policies')
    op.drop_table('platform_category_mappings')
    op.drop_table('csv_import_logs')
    op.drop_table('category_mappings')
    op.drop_table('activity_log')
    op.drop_table('users')
    op.drop_table('shipping_profiles')

    # Drop enums
    op.execute('DROP TYPE IF EXISTS shipmentstatus')
    op.execute('DROP TYPE IF EXISTS platformname')
    op.execute('DROP TYPE IF EXISTS productstatus')
    op.execute('DROP TYPE IF EXISTS productstatus_old')
    op.execute('DROP TYPE IF EXISTS productcondition')
'''

if __name__ == "__main__":
    with open('alembic/versions/002_bulletproof_initial.py', 'w') as f:
        f.write(generate_bulletproof_migration())
    print("Created bulletproof migration at: alembic/versions/002_bulletproof_initial.py")