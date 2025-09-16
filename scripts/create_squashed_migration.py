#!/usr/bin/env python3
"""
Generate a clean squashed migration from current models
This creates a single migration that represents the current state of all models
"""

import os
import sys
from datetime import datetime
from pathlib import Path

# Add the app directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Import all models to ensure they're registered
from app.models import (
    product, platform_common, reverb, ebay, shopify, vr,
    sale, shipping, sync_event, user, webhook,
    category_mapping, category_mappings, activity_log,
    sync_stats, order
)

# Models to exclude from the migration
EXCLUDE_MODELS = set()  # Keep all models for now

def generate_migration_content():
    """Generate the content for the squashed migration"""

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    revision = datetime.now().strftime("%Y%m%d%H%M%S")[:12]

    migration_content = f'''"""Initial squashed migration - creates all tables from scratch

Revision ID: {revision}
Revises:
Create Date: {datetime.now().isoformat()}

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '{revision}'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create custom types/enums first
    productcondition_enum = postgresql.ENUM(
        'NEW', 'EXCELLENT', 'VERY_GOOD', 'GOOD', 'FAIR', 'POOR',
        name='productcondition'
    )
    productcondition_enum.create(op.get_bind(), checkfirst=True)

    productstatus_enum = postgresql.ENUM(
        'ACTIVE', 'INACTIVE', 'PENDING', 'SOLD', 'DRAFT',
        name='productstatus'
    )
    productstatus_enum.create(op.get_bind(), checkfirst=True)

    platformname_enum = postgresql.ENUM(
        'reverb', 'ebay', 'shopify', 'vr',
        name='platformname'
    )
    platformname_enum.create(op.get_bind(), checkfirst=True)

    # Create tables in dependency order

    # 1. Independent tables first
    op.create_table('shipping_profiles',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('handling_time_days', sa.Integer(), nullable=True, server_default='3'),
        sa.Column('domestic_service', sa.String(), nullable=True),
        sa.Column('domestic_cost', sa.Float(), nullable=True),
        sa.Column('international_service', sa.String(), nullable=True),
        sa.Column('international_cost', sa.Float(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )

    op.create_table('users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('email', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email')
    )

    op.create_table('activity_log',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('timestamp', sa.DateTime(), nullable=False),
        sa.Column('action', sa.String(), nullable=False),
        sa.Column('entity_type', sa.String(), nullable=False),
        sa.Column('entity_id', sa.String(), nullable=True),
        sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('user_id', sa.String(), nullable=True),
        sa.Column('platform', sa.String(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_activity_log_entity_type'), 'activity_log', ['entity_type'], unique=False)
    op.create_index(op.f('ix_activity_log_timestamp'), 'activity_log', ['timestamp'], unique=False)

    op.create_table('reverb_categories',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('full_name', sa.String(), nullable=False),
        sa.Column('uuid', sa.String(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('full_name'),
        sa.UniqueConstraint('uuid')
    )

    op.create_table('category_mappings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('source_platform', sa.String(), nullable=False),
        sa.Column('source_id', sa.String(), nullable=False),
        sa.Column('source_name', sa.String(), nullable=False),
        sa.Column('target_platform', sa.String(), nullable=False),
        sa.Column('target_id', sa.String(), nullable=False),
        sa.Column('target_name', sa.String(), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )

    op.create_table('webhook_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('platform', sa.String(), nullable=False),
        sa.Column('event_type', sa.String(), nullable=False),
        sa.Column('event_id', sa.String(), nullable=True),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('status', sa.String(), nullable=True, server_default='pending'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True),
        sa.Column('processed_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_webhook_events_platform'), 'webhook_events', ['platform'], unique=False)
    op.create_index(op.f('ix_webhook_events_event_type'), 'webhook_events', ['event_type'], unique=False)
    op.create_index(op.f('ix_webhook_events_status'), 'webhook_events', ['status'], unique=False)

    op.create_table('vr_accepted_brands',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('brand_name', sa.String(), nullable=False),
        sa.Column('brand_id', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('brand_name')
    )

    op.create_table('platform_status_mappings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('platform', sa.String(), nullable=False),
        sa.Column('internal_status', sa.String(), nullable=False),
        sa.Column('platform_status', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )

    # 2. Products table (depends on shipping_profiles)
    op.create_table('products',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('sku', sa.String(), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('brand', sa.String(), nullable=True),
        sa.Column('model', sa.String(), nullable=True),
        sa.Column('category', sa.String(), nullable=True),
        sa.Column('tags', sa.String(), nullable=True),
        sa.Column('condition', productcondition_enum, nullable=False),
        sa.Column('condition_notes', sa.Text(), nullable=True),
        sa.Column('base_price', sa.Float(), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('location', sa.String(), nullable=True),
        sa.Column('primary_image', sa.String(), nullable=True),
        sa.Column('additional_images', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('video_urls', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('shipping_profile_id', sa.Integer(), nullable=True),
        sa.Column('processing_time', sa.Integer(), nullable=True, server_default='3'),
        sa.Column('status', productstatus_enum, nullable=False, server_default='DRAFT'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['shipping_profile_id'], ['shipping_profiles.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_products_sku'), 'products', ['sku'], unique=True)
    op.create_index(op.f('ix_products_status'), 'products', ['status'], unique=False)

    # 3. Product mappings table (for related products)
    op.create_table('product_mappings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('master_product_id', sa.Integer(), nullable=False),
        sa.Column('related_product_id', sa.Integer(), nullable=False),
        sa.Column('mapping_type', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True),
        sa.ForeignKeyConstraint(['master_product_id'], ['products.id'], ),
        sa.ForeignKeyConstraint(['related_product_id'], ['products.id'], ),
        sa.PrimaryKeyConstraint('id')
    )

    # 4. Platform common table (depends on products)
    op.create_table('platform_common',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('product_id', sa.Integer(), nullable=False),
        sa.Column('platform_name', platformname_enum, nullable=False),
        sa.Column('external_id', sa.String(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('last_synced_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['product_id'], ['products.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('product_id', 'platform_name', name='uq_product_platform')
    )
    op.create_index(op.f('ix_platform_common_platform_name'), 'platform_common', ['platform_name'], unique=False)
    op.create_index(op.f('ix_platform_common_external_id'), 'platform_common', ['external_id'], unique=False)

    # 5. Platform-specific listing tables
    op.create_table('reverb_listings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('platform_id', sa.Integer(), nullable=False),
        sa.Column('reverb_listing_id', sa.String(), nullable=True),
        sa.Column('reverb_id', sa.String(), nullable=True),
        sa.Column('make', sa.String(), nullable=True),
        sa.Column('model', sa.String(), nullable=True),
        sa.Column('finish', sa.String(), nullable=True),
        sa.Column('year', sa.String(), nullable=True),
        sa.Column('serial_number', sa.String(), nullable=True),
        sa.Column('price', sa.Float(), nullable=True),
        sa.Column('handmade', sa.Boolean(), nullable=True, server_default='false'),
        sa.Column('category_uuids', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('listing_currency', sa.String(), nullable=True, server_default='GBP'),
        sa.Column('accept_offers', sa.Boolean(), nullable=True, server_default='false'),
        sa.Column('offer_type', sa.String(), nullable=True),
        sa.Column('minimum_offer_percentage', sa.Float(), nullable=True),
        sa.Column('shipping_profile_id', sa.String(), nullable=True),
        sa.Column('reverb_sync_status', sa.String(), nullable=True),
        sa.Column('reverb_state', sa.String(), nullable=True),
        sa.Column('extended_attributes', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['platform_id'], ['platform_common.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_reverb_listings_reverb_id'), 'reverb_listings', ['reverb_id'], unique=False)
    op.create_index(op.f('ix_reverb_listings_reverb_listing_id'), 'reverb_listings', ['reverb_listing_id'], unique=False)

    op.create_table('ebay_listings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('platform_id', sa.Integer(), nullable=False),
        sa.Column('ebay_item_id', sa.String(), nullable=True),
        sa.Column('ebay_category_id', sa.String(), nullable=True),
        sa.Column('ebay_store_category_id', sa.String(), nullable=True),
        sa.Column('listing_format', sa.String(), nullable=True, server_default='FIXED_PRICE'),
        sa.Column('price', sa.Float(), nullable=True),
        sa.Column('currency', sa.String(), nullable=True, server_default='GBP'),
        sa.Column('quantity', sa.Integer(), nullable=True, server_default='1'),
        sa.Column('condition_id', sa.String(), nullable=True),
        sa.Column('condition_description', sa.Text(), nullable=True),
        sa.Column('item_specifics', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('payment_policy_id', sa.String(), nullable=True),
        sa.Column('return_policy_id', sa.String(), nullable=True),
        sa.Column('shipping_policy_id', sa.String(), nullable=True),
        sa.Column('best_offer_enabled', sa.Boolean(), nullable=True, server_default='false'),
        sa.Column('best_offer_auto_accept_price', sa.Float(), nullable=True),
        sa.Column('best_offer_minimum_price', sa.Float(), nullable=True),
        sa.Column('listing_duration', sa.String(), nullable=True, server_default='GTC'),
        sa.Column('private_listing', sa.Boolean(), nullable=True, server_default='false'),
        sa.Column('listing_status', sa.String(), nullable=True),
        sa.Column('extended_attributes', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('last_synced_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['platform_id'], ['platform_common.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_ebay_listings_ebay_item_id'), 'ebay_listings', ['ebay_item_id'], unique=True)
    op.create_index(op.f('ix_ebay_listings_listing_status'), 'ebay_listings', ['listing_status'], unique=False)

    op.create_table('shopify_listings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('platform_id', sa.Integer(), nullable=False),
        sa.Column('shopify_product_id', sa.String(), nullable=True),
        sa.Column('shopify_variant_id', sa.String(), nullable=True),
        sa.Column('handle', sa.String(), nullable=True),
        sa.Column('product_type', sa.String(), nullable=True),
        sa.Column('vendor', sa.String(), nullable=True),
        sa.Column('tags', sa.Text(), nullable=True),
        sa.Column('published', sa.Boolean(), nullable=True, server_default='false'),
        sa.Column('published_at', sa.DateTime(), nullable=True),
        sa.Column('template_suffix', sa.String(), nullable=True),
        sa.Column('metafields', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('seo_title', sa.String(), nullable=True),
        sa.Column('seo_description', sa.Text(), nullable=True),
        sa.Column('extended_attributes', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('last_synced_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['platform_id'], ['platform_common.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_shopify_listings_shopify_product_id'), 'shopify_listings', ['shopify_product_id'], unique=False)
    op.create_index(op.f('ix_shopify_listings_handle'), 'shopify_listings', ['handle'], unique=False)

    op.create_table('vr_listings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('platform_id', sa.Integer(), nullable=False),
        sa.Column('vr_listing_id', sa.String(), nullable=True),
        sa.Column('vr_url', sa.String(), nullable=True),
        sa.Column('category_path', sa.String(), nullable=True),
        sa.Column('subcategory', sa.String(), nullable=True),
        sa.Column('decade', sa.String(), nullable=True),
        sa.Column('accepts_offers', sa.Boolean(), nullable=True, server_default='false'),
        sa.Column('accepts_part_exchange', sa.Boolean(), nullable=True, server_default='false'),
        sa.Column('on_sale', sa.Boolean(), nullable=True, server_default='false'),
        sa.Column('ships_from', sa.String(), nullable=True),
        sa.Column('available_to_ship_date', sa.DateTime(), nullable=True),
        sa.Column('tax_included', sa.Boolean(), nullable=True, server_default='true'),
        sa.Column('tax_rate_percentage', sa.Float(), nullable=True),
        sa.Column('price_notax', sa.Float(), nullable=True),
        sa.Column('dealers_collective', sa.Boolean(), nullable=True, server_default='false'),
        sa.Column('extended_attributes', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('processing_time', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('last_synced_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['platform_id'], ['platform_common.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_vr_listings_vr_listing_id'), 'vr_listings', ['vr_listing_id'], unique=False)

    # 6. Category mapping tables
    op.create_table('ebay_category_mappings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('reverb_category_id', sa.Integer(), nullable=False),
        sa.Column('ebay_category_id', sa.String(), nullable=False),
        sa.Column('ebay_category_name', sa.String(), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True),
        sa.ForeignKeyConstraint(['reverb_category_id'], ['reverb_categories.id'], ),
        sa.PrimaryKeyConstraint('id')
    )

    op.create_table('shopify_category_mappings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('reverb_category_id', sa.Integer(), nullable=False),
        sa.Column('shopify_product_type', sa.String(), nullable=False),
        sa.Column('shopify_tags', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True),
        sa.ForeignKeyConstraint(['reverb_category_id'], ['reverb_categories.id'], ),
        sa.PrimaryKeyConstraint('id')
    )

    op.create_table('vr_category_mappings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('reverb_category_id', sa.Integer(), nullable=False),
        sa.Column('vr_category', sa.String(), nullable=False),
        sa.Column('vr_subcategory', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True),
        sa.ForeignKeyConstraint(['reverb_category_id'], ['reverb_categories.id'], ),
        sa.PrimaryKeyConstraint('id')
    )

    # 7. Sales and Orders
    op.create_table('sales',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('product_id', sa.Integer(), nullable=True),
        sa.Column('platform_listing_id', sa.Integer(), nullable=True),
        sa.Column('platform_name', sa.String(), nullable=False),
        sa.Column('order_id', sa.String(), nullable=False),
        sa.Column('sold_price', sa.Float(), nullable=False),
        sa.Column('currency', sa.String(), nullable=True, server_default='GBP'),
        sa.Column('quantity', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('buyer_name', sa.String(), nullable=True),
        sa.Column('buyer_email', sa.String(), nullable=True),
        sa.Column('shipping_address', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('sold_at', sa.DateTime(), nullable=False),
        sa.Column('platform_fees', sa.Float(), nullable=True),
        sa.Column('shipping_cost', sa.Float(), nullable=True),
        sa.Column('net_amount', sa.Float(), nullable=True),
        sa.Column('status', sa.String(), nullable=True),
        sa.Column('tracking_number', sa.String(), nullable=True),
        sa.Column('shipped_at', sa.DateTime(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['platform_listing_id'], ['platform_common.id'], ),
        sa.ForeignKeyConstraint(['product_id'], ['products.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_sales_order_id'), 'sales', ['order_id'], unique=False)
    op.create_index(op.f('ix_sales_platform_name'), 'sales', ['platform_name'], unique=False)
    op.create_index(op.f('ix_sales_sold_at'), 'sales', ['sold_at'], unique=False)

    op.create_table('orders',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('platform_listing_id', sa.Integer(), nullable=True),
        sa.Column('platform_order_id', sa.String(), nullable=False),
        sa.Column('platform_name', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('buyer_name', sa.String(), nullable=True),
        sa.Column('buyer_email', sa.String(), nullable=True),
        sa.Column('shipping_address', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('order_total', sa.Float(), nullable=False),
        sa.Column('currency', sa.String(), nullable=True, server_default='GBP'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['platform_listing_id'], ['platform_common.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_orders_platform_order_id'), 'orders', ['platform_order_id'], unique=True)

    # 8. Shipments
    op.create_table('shipments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('order_id', sa.Integer(), nullable=True),
        sa.Column('sale_id', sa.Integer(), nullable=True),
        sa.Column('platform_listing_id', sa.Integer(), nullable=True),
        sa.Column('tracking_number', sa.String(), nullable=True),
        sa.Column('carrier', sa.String(), nullable=True),
        sa.Column('service', sa.String(), nullable=True),
        sa.Column('weight', sa.Float(), nullable=True),
        sa.Column('dimensions', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('shipping_cost', sa.Float(), nullable=True),
        sa.Column('label_url', sa.String(), nullable=True),
        sa.Column('shipped_at', sa.DateTime(), nullable=True),
        sa.Column('delivered_at', sa.DateTime(), nullable=True),
        sa.Column('status', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['order_id'], ['orders.id'], ),
        sa.ForeignKeyConstraint(['platform_listing_id'], ['platform_common.id'], ),
        sa.ForeignKeyConstraint(['sale_id'], ['sales.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_shipments_tracking_number'), 'shipments', ['tracking_number'], unique=False)

    # 9. Sync tracking tables
    op.create_table('sync_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('sync_type', sa.String(), nullable=False),
        sa.Column('platform', sa.String(), nullable=False),
        sa.Column('product_id', sa.Integer(), nullable=True),
        sa.Column('platform_common_id', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=False),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['platform_common_id'], ['platform_common.id'], ),
        sa.ForeignKeyConstraint(['product_id'], ['products.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_sync_events_platform'), 'sync_events', ['platform'], unique=False)
    op.create_index(op.f('ix_sync_events_status'), 'sync_events', ['status'], unique=False)
    op.create_index(op.f('ix_sync_events_started_at'), 'sync_events', ['started_at'], unique=False)

    op.create_table('sync_stats',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('sync_date', sa.Date(), nullable=False),
        sa.Column('platform', sa.String(), nullable=False),
        sa.Column('total_products', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('synced_products', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('failed_products', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('new_listings', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('updated_listings', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('removed_listings', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('sync_duration_seconds', sa.Float(), nullable=True),
        sa.Column('error_summary', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_sync_stats_sync_date'), 'sync_stats', ['sync_date'], unique=False)
    op.create_index(op.f('ix_sync_stats_platform'), 'sync_stats', ['platform'], unique=False)


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
    op.drop_table('product_mappings')
    op.drop_table('products')
    op.drop_table('platform_status_mappings')
    op.drop_table('vr_accepted_brands')
    op.drop_table('webhook_events')
    op.drop_table('category_mappings')
    op.drop_table('reverb_categories')
    op.drop_table('activity_log')
    op.drop_table('users')
    op.drop_table('shipping_profiles')

    # Drop enums
    op.execute('DROP TYPE IF EXISTS platformname')
    op.execute('DROP TYPE IF EXISTS productstatus')
    op.execute('DROP TYPE IF EXISTS productcondition')
'''

    return migration_content

def main():
    print("Generating squashed migration...")

    # Generate migration
    content = generate_migration_content()

    # Write to file
    migration_path = Path(__file__).parent.parent / 'alembic' / 'versions' / 'squashed_initial_migration.py'

    with open(migration_path, 'w') as f:
        f.write(content)

    print(f"✅ Squashed migration created at: {migration_path}")
    print("\nThis migration includes ALL tables (23 total)")
    print("\nNext steps:")
    print("1. Remove old migration files from alembic/versions/")
    print("2. Test the migration locally")
    print("3. Deploy to Railway")

if __name__ == "__main__":
    main()