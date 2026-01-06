"""Add historical analytics tables

Revision ID: c1d43d7f2790
Revises: add_listing_stats_history
Create Date: 2026-01-01 15:45:27.433074

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'c1d43d7f2790'
down_revision: Union[str, None] = 'add_listing_stats_history'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create reverb_historical_listings table
    op.create_table('reverb_historical_listings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('reverb_listing_id', sa.String(), nullable=False),
        sa.Column('title', sa.String(), nullable=True),
        sa.Column('sku', sa.String(), nullable=True),
        sa.Column('brand', sa.String(), nullable=True),
        sa.Column('model', sa.String(), nullable=True),
        sa.Column('category_full', sa.String(), nullable=True),
        sa.Column('category_root', sa.String(), nullable=True),
        sa.Column('condition', sa.String(), nullable=True),
        sa.Column('year', sa.String(), nullable=True),
        sa.Column('finish', sa.String(), nullable=True),
        sa.Column('original_price', sa.Float(), nullable=True),
        sa.Column('final_price', sa.Float(), nullable=True),
        sa.Column('currency', sa.String(), nullable=True, default='GBP'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('sold_at', sa.DateTime(), nullable=True),
        sa.Column('ended_at', sa.DateTime(), nullable=True),
        sa.Column('outcome', sa.String(), nullable=True),
        sa.Column('days_listed', sa.Integer(), nullable=True),
        sa.Column('days_to_sell', sa.Integer(), nullable=True),
        sa.Column('view_count', sa.Integer(), nullable=True, default=0),
        sa.Column('watch_count', sa.Integer(), nullable=True, default=0),
        sa.Column('offer_count', sa.Integer(), nullable=True, default=0),
        sa.Column('price_drops', sa.Integer(), nullable=True, default=0),
        sa.Column('total_price_reduction', sa.Float(), nullable=True),
        sa.Column('price_reduction_pct', sa.Float(), nullable=True),
        sa.Column('primary_image', sa.String(), nullable=True),
        sa.Column('image_count', sa.Integer(), nullable=True, default=0),
        sa.Column('shop_id', sa.String(), nullable=True),
        sa.Column('shop_name', sa.String(), nullable=True),
        sa.Column('raw_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('imported_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_reverb_historical_listings_reverb_listing_id', 'reverb_historical_listings', ['reverb_listing_id'], unique=True)
    op.create_index('ix_reverb_historical_listings_sku', 'reverb_historical_listings', ['sku'], unique=False)
    op.create_index('ix_reverb_historical_listings_brand', 'reverb_historical_listings', ['brand'], unique=False)
    op.create_index('ix_reverb_historical_listings_category_full', 'reverb_historical_listings', ['category_full'], unique=False)
    op.create_index('ix_reverb_historical_listings_category_root', 'reverb_historical_listings', ['category_root'], unique=False)
    op.create_index('ix_reverb_historical_listings_outcome', 'reverb_historical_listings', ['outcome'], unique=False)
    op.create_index('ix_reverb_historical_listings_sold_at', 'reverb_historical_listings', ['sold_at'], unique=False)
    op.create_index('ix_reverb_historical_listings_shop_id', 'reverb_historical_listings', ['shop_id'], unique=False)
    op.create_index('ix_reverb_historical_category_outcome', 'reverb_historical_listings', ['category_root', 'outcome'], unique=False)
    op.create_index('ix_reverb_historical_sold_date', 'reverb_historical_listings', ['sold_at', 'category_root'], unique=False)
    op.create_index('ix_reverb_historical_brand_category', 'reverb_historical_listings', ['brand', 'category_root'], unique=False)

    # Create category_velocity_stats table
    op.create_table('category_velocity_stats',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('category_root', sa.String(), nullable=False),
        sa.Column('category_full', sa.String(), nullable=True),
        sa.Column('period_start', sa.Date(), nullable=True),
        sa.Column('period_end', sa.Date(), nullable=True),
        sa.Column('period_type', sa.String(), nullable=True),
        sa.Column('total_listed', sa.Integer(), nullable=True, default=0),
        sa.Column('total_sold', sa.Integer(), nullable=True, default=0),
        sa.Column('total_unsold', sa.Integer(), nullable=True, default=0),
        sa.Column('sell_through_rate', sa.Float(), nullable=True),
        sa.Column('avg_days_to_sell', sa.Float(), nullable=True),
        sa.Column('median_days_to_sell', sa.Float(), nullable=True),
        sa.Column('p25_days_to_sell', sa.Float(), nullable=True),
        sa.Column('p75_days_to_sell', sa.Float(), nullable=True),
        sa.Column('min_days_to_sell', sa.Integer(), nullable=True),
        sa.Column('max_days_to_sell', sa.Integer(), nullable=True),
        sa.Column('avg_list_price', sa.Float(), nullable=True),
        sa.Column('avg_sale_price', sa.Float(), nullable=True),
        sa.Column('median_sale_price', sa.Float(), nullable=True),
        sa.Column('min_sale_price', sa.Float(), nullable=True),
        sa.Column('max_sale_price', sa.Float(), nullable=True),
        sa.Column('avg_price_reduction_pct', sa.Float(), nullable=True),
        sa.Column('pct_items_reduced', sa.Float(), nullable=True),
        sa.Column('avg_reductions_before_sale', sa.Float(), nullable=True),
        sa.Column('avg_views_when_sold', sa.Float(), nullable=True),
        sa.Column('avg_watches_when_sold', sa.Float(), nullable=True),
        sa.Column('avg_offers_when_sold', sa.Float(), nullable=True),
        sa.Column('avg_views_per_day', sa.Float(), nullable=True),
        sa.Column('sample_size', sa.Integer(), nullable=True, default=0),
        sa.Column('computed_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_category_velocity_stats_category_root', 'category_velocity_stats', ['category_root'], unique=False)
    op.create_index('ix_category_velocity_stats_period_type', 'category_velocity_stats', ['period_type'], unique=False)
    op.create_index('ix_category_velocity_period', 'category_velocity_stats', ['category_root', 'period_type'], unique=False)

    # Create inventory_health_snapshots table
    op.create_table('inventory_health_snapshots',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('snapshot_date', sa.Date(), nullable=False),
        sa.Column('total_items', sa.Integer(), nullable=True, default=0),
        sa.Column('total_value', sa.Float(), nullable=True, default=0),
        sa.Column('items_0_30d', sa.Integer(), nullable=True, default=0),
        sa.Column('items_30_90d', sa.Integer(), nullable=True, default=0),
        sa.Column('items_90_180d', sa.Integer(), nullable=True, default=0),
        sa.Column('items_180_365d', sa.Integer(), nullable=True, default=0),
        sa.Column('items_365_plus', sa.Integer(), nullable=True, default=0),
        sa.Column('value_0_30d', sa.Float(), nullable=True, default=0),
        sa.Column('value_30_90d', sa.Float(), nullable=True, default=0),
        sa.Column('value_90_180d', sa.Float(), nullable=True, default=0),
        sa.Column('value_180_365d', sa.Float(), nullable=True, default=0),
        sa.Column('value_365_plus', sa.Float(), nullable=True, default=0),
        sa.Column('avg_age_days', sa.Float(), nullable=True),
        sa.Column('median_age_days', sa.Float(), nullable=True),
        sa.Column('dead_stock_count', sa.Integer(), nullable=True, default=0),
        sa.Column('dead_stock_value', sa.Float(), nullable=True, default=0),
        sa.Column('stale_count', sa.Integer(), nullable=True, default=0),
        sa.Column('stale_value', sa.Float(), nullable=True, default=0),
        sa.Column('single_platform_count', sa.Integer(), nullable=True, default=0),
        sa.Column('two_platform_count', sa.Integer(), nullable=True, default=0),
        sa.Column('three_plus_platform_count', sa.Integer(), nullable=True, default=0),
        sa.Column('total_views', sa.Integer(), nullable=True, default=0),
        sa.Column('total_watches', sa.Integer(), nullable=True, default=0),
        sa.Column('avg_views_per_item', sa.Float(), nullable=True),
        sa.Column('avg_watches_per_item', sa.Float(), nullable=True),
        sa.Column('category_breakdown', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_inventory_health_snapshots_snapshot_date', 'inventory_health_snapshots', ['snapshot_date'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_inventory_health_snapshots_snapshot_date', table_name='inventory_health_snapshots')
    op.drop_table('inventory_health_snapshots')

    op.drop_index('ix_category_velocity_period', table_name='category_velocity_stats')
    op.drop_index('ix_category_velocity_stats_period_type', table_name='category_velocity_stats')
    op.drop_index('ix_category_velocity_stats_category_root', table_name='category_velocity_stats')
    op.drop_table('category_velocity_stats')

    op.drop_index('ix_reverb_historical_brand_category', table_name='reverb_historical_listings')
    op.drop_index('ix_reverb_historical_sold_date', table_name='reverb_historical_listings')
    op.drop_index('ix_reverb_historical_category_outcome', table_name='reverb_historical_listings')
    op.drop_index('ix_reverb_historical_listings_shop_id', table_name='reverb_historical_listings')
    op.drop_index('ix_reverb_historical_listings_sold_at', table_name='reverb_historical_listings')
    op.drop_index('ix_reverb_historical_listings_outcome', table_name='reverb_historical_listings')
    op.drop_index('ix_reverb_historical_listings_category_root', table_name='reverb_historical_listings')
    op.drop_index('ix_reverb_historical_listings_category_full', table_name='reverb_historical_listings')
    op.drop_index('ix_reverb_historical_listings_brand', table_name='reverb_historical_listings')
    op.drop_index('ix_reverb_historical_listings_sku', table_name='reverb_historical_listings')
    op.drop_index('ix_reverb_historical_listings_reverb_listing_id', table_name='reverb_historical_listings')
    op.drop_table('reverb_historical_listings')
