"""Initial schema - creates all tables for inventory system

Revision ID: 001_initial_schema
Revises:
Create Date: 2025-09-16

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '001_initial_schema'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create custom types/enums

    productcondition_enum = postgresql.ENUM(
        'NEW', 'EXCELLENT', 'VERYGOOD', 'GOOD', 'FAIR', 'POOR',
        name='productcondition'
    )
    productcondition_enum.create(op.get_bind(), checkfirst=True)

    productstatus_enum = postgresql.ENUM(
        'DRAFT', 'ACTIVE', 'SOLD', 'ARCHIVED',
        name='productstatus'
    )
    productstatus_enum.create(op.get_bind(), checkfirst=True)

    productstatus_old_enum = postgresql.ENUM(
        'DRAFT', 'ACTIVE', 'SOLD', 'ARCHIVED', 'draft', 'active', 'sold', 'archived',
        name='productstatus_old'
    )
    productstatus_old_enum.create(op.get_bind(), checkfirst=True)

    shipmentstatus_enum = postgresql.ENUM(
        'CREATED', 'LABEL_CREATED', 'PICKED_UP', 'IN_TRANSIT', 'DELIVERED', 'EXCEPTION', 'CANCELLED',
        name='shipmentstatus'
    )
    shipmentstatus_enum.create(op.get_bind(), checkfirst=True)

    # Create all sequences first
    sequences = [
        'activity_log_id_seq',
        'category_mappings_id_seq',
        'csv_import_logs_id_seq',
        'ebay_category_mappings_id_seq',
        'ebay_listings_id_seq',
        'orders_id_seq',
        'platform_category_mappings_id_seq',
        'platform_common_id_seq',
        'platform_policies_id_seq',
        'platform_status_mappings_id_seq',
        'product_mappings_id_seq',
        'product_merges_id_seq',
        'products_id_seq',
        'reverb_categories_id_seq',
        'reverb_listings_id_seq',
        'sales_id_seq',
        'shipments_id_seq',
        'shipping_profiles_id_seq',
        'shopify_category_mappings_id_seq',
        'shopify_listings_id_seq',
        'sync_events_id_seq',
        'sync_stats_id_seq',
        'vr_accepted_brands_id_seq',
        'vr_category_mappings_id_seq',
        'vr_listings_id_seq',
        'users_id_seq',
        'webhook_events_id_seq'
    ]

    for seq in sequences:
        op.execute(f"CREATE SEQUENCE IF NOT EXISTS {seq}")

    # Create tables

    # Table: activity_log
    op.execute('''CREATE TABLE activity_log (
    id integer NOT NULL DEFAULT nextval('activity_log_id_seq'::regclass),
    action character varying(50) NOT NULL,
    entity_type character varying(50) NOT NULL,
    entity_id character varying(100) NOT NULL,
    platform character varying(50),
    details jsonb,
    user_id integer,
    created_at timestamp with time zone NOT NULL DEFAULT now()
);''')

    # Table: category_mappings
    op.execute('''CREATE TABLE category_mappings (
    id integer NOT NULL DEFAULT nextval('category_mappings_id_seq'::regclass),
    source_platform character varying(20) NOT NULL,
    source_id character varying(36) NOT NULL,
    source_name character varying(255) NOT NULL,
    target_platform character varying(20) NOT NULL,
    target_id character varying(36) NOT NULL,
    target_subcategory_id character varying(36),
    target_tertiary_id character varying(36),
    created_at timestamp without time zone NOT NULL DEFAULT (now() AT TIME ZONE 'utc'::text),
    updated_at timestamp without time zone NOT NULL DEFAULT (now() AT TIME ZONE 'utc'::text)
);''')

    # Table: csv_import_logs
    op.execute('''CREATE TABLE csv_import_logs (
    id integer NOT NULL DEFAULT nextval('csv_import_logs_id_seq'::regclass),
    "timestamp" timestamp without time zone,
    filename character varying,
    platform character varying,
    total_rows integer,
    successful_rows integer,
    failed_rows integer,
    error_log jsonb
);''')

    # Table: ebay_category_mappings
    op.execute('''CREATE TABLE ebay_category_mappings (
    id integer NOT NULL DEFAULT nextval('ebay_category_mappings_id_seq'::regclass),
    reverb_category_id integer NOT NULL,
    ebay_category_id character varying NOT NULL,
    ebay_category_name character varying NOT NULL,
    confidence_score numeric(3,2),
    is_verified boolean,
    notes text,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);''')

    # Table: ebay_listings
    op.execute('''CREATE TABLE ebay_listings (
    id integer NOT NULL DEFAULT nextval('ebay_listings_id_seq'::regclass),
    platform_id integer,
    ebay_item_id character varying,
    listing_status character varying,
    title character varying,
    format character varying,
    price double precision,
    quantity integer,
    quantity_available integer,
    quantity_sold integer,
    ebay_category_id character varying,
    ebay_category_name character varying,
    ebay_second_category_id character varying,
    start_time timestamp without time zone,
    end_time timestamp without time zone,
    listing_url character varying,
    ebay_condition_id character varying,
    condition_display_name character varying,
    gallery_url character varying,
    picture_urls jsonb,
    item_specifics jsonb,
    payment_policy_id character varying,
    return_policy_id character varying,
    shipping_policy_id character varying,
    transaction_id character varying,
    order_line_item_id character varying,
    buyer_user_id character varying,
    paid_time timestamp without time zone,
    payment_status character varying,
    shipping_status character varying,
    created_at timestamp without time zone NOT NULL DEFAULT (now() AT TIME ZONE 'utc'::text),
    updated_at timestamp without time zone NOT NULL DEFAULT (now() AT TIME ZONE 'utc'::text),
    last_synced_at timestamp without time zone NOT NULL DEFAULT (now() AT TIME ZONE 'utc'::text),
    listing_data jsonb
);''')

    # Table: orders
    op.execute('''CREATE TABLE orders (
    id integer NOT NULL DEFAULT nextval('orders_id_seq'::regclass),
    order_reference character varying,
    created_at timestamp without time zone NOT NULL DEFAULT (now() AT TIME ZONE 'utc'::text),
    platform_listing_id integer
);''')

    # Table: platform_category_mappings
    op.execute('''CREATE TABLE platform_category_mappings (
    id integer NOT NULL DEFAULT nextval('platform_category_mappings_id_seq'::regclass),
    source_platform character varying(50) NOT NULL,
    source_category_id character varying(100) NOT NULL,
    source_category_name text,
    target_platform character varying(50) NOT NULL,
    target_category_id character varying(100),
    target_category_name text,
    shopify_gid character varying(255),
    merchant_type character varying(255),
    vr_category_id character varying(50),
    vr_subcategory_id character varying(50),
    vr_sub_subcategory_id character varying(50),
    vr_sub_sub_subcategory_id character varying(50),
    item_count integer DEFAULT 0,
    confidence_score numeric(3,2),
    is_verified boolean DEFAULT false,
    notes text,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);''')

    # Table: platform_common
    op.execute('''CREATE TABLE platform_common (
    id integer NOT NULL DEFAULT nextval('platform_common_id_seq'::regclass),
    created_at timestamp without time zone NOT NULL DEFAULT (now() AT TIME ZONE 'utc'::text),
    updated_at timestamp without time zone NOT NULL DEFAULT (now() AT TIME ZONE 'utc'::text),
    product_id integer,
    platform_name character varying,
    external_id character varying,
    status character varying,
    last_sync timestamp without time zone,
    sync_status character varying,
    listing_url character varying,
    platform_specific_data jsonb
);''')

    # Table: platform_policies
    op.execute('''CREATE TABLE platform_policies (
    id integer NOT NULL DEFAULT nextval('platform_policies_id_seq'::regclass),
    platform character varying(50),
    policy_type character varying(50),
    policy_id character varying(100),
    policy_name character varying(200),
    is_default boolean DEFAULT false
);''')

    # Table: platform_status_mappings
    op.execute('''CREATE TABLE platform_status_mappings (
    id integer NOT NULL DEFAULT nextval('platform_status_mappings_id_seq'::regclass),
    platform_name character varying(50) NOT NULL,
    platform_status character varying(100) NOT NULL,
    central_status character varying(20) NOT NULL,
    description text,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);''')

    # Table: product_mappings
    op.execute('''CREATE TABLE product_mappings (
    id integer NOT NULL DEFAULT nextval('product_mappings_id_seq'::regclass),
    master_product_id integer NOT NULL,
    related_product_id integer NOT NULL,
    match_confidence double precision,
    match_method character varying,
    created_at timestamp without time zone NOT NULL DEFAULT timezone('utc'::text, now())
);''')

    # Table: product_merges
    op.execute('''CREATE TABLE product_merges (
    id integer NOT NULL DEFAULT nextval('product_merges_id_seq'::regclass),
    kept_product_id integer NOT NULL,
    merged_product_id integer NOT NULL,
    merged_product_data jsonb,
    merged_at timestamp without time zone NOT NULL DEFAULT now(),
    merged_by character varying(255),
    reason character varying(255) DEFAULT 'Product matching'::character varying
);''')

    # Table: products
    op.execute('''CREATE TABLE products (
    id integer NOT NULL DEFAULT nextval('products_id_seq'::regclass),
    created_at timestamp without time zone NOT NULL DEFAULT timezone('utc'::text, now()),
    updated_at timestamp without time zone NOT NULL DEFAULT timezone('utc'::text, now()),
    sku character varying,
    brand character varying,
    model character varying,
    year integer,
    decade integer,
    finish character varying,
    category character varying,
    condition productcondition NOT NULL,
    base_price double precision,
    cost_price double precision,
    price double precision,
    price_notax double precision,
    collective_discount double precision,
    offer_discount double precision,
    status productstatus,
    is_sold boolean,
    in_collective boolean,
    in_inventory boolean,
    in_reseller boolean,
    free_shipping boolean,
    buy_now boolean,
    show_vat boolean,
    local_pickup boolean,
    available_for_shipment boolean,
    primary_image character varying,
    additional_images jsonb,
    video_url character varying,
    external_link character varying,
    processing_time integer,
    shipping_profile_id integer,
    package_type character varying(50),
    package_weight double precision,
    package_dimensions jsonb,
    description character varying,
    title character varying,
    is_stocked_item boolean NOT NULL DEFAULT false,
    quantity integer
);''')

    # Table: reverb_categories
    op.execute('''CREATE TABLE reverb_categories (
    id integer NOT NULL DEFAULT nextval('reverb_categories_id_seq'::regclass),
    uuid character varying NOT NULL,
    name character varying NOT NULL,
    full_path character varying,
    parent_uuid character varying,
    item_count integer,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);''')

    # Table: reverb_listings
    op.execute('''CREATE TABLE reverb_listings (
    id integer NOT NULL DEFAULT nextval('reverb_listings_id_seq'::regclass),
    platform_id integer,
    reverb_listing_id character varying,
    reverb_slug character varying,
    reverb_category_uuid character varying,
    condition_rating double precision,
    inventory_quantity integer,
    has_inventory boolean,
    offers_enabled boolean,
    is_auction boolean,
    list_price double precision,
    listing_currency character varying,
    shipping_profile_id character varying,
    shop_policies_id character varying,
    reverb_state character varying,
    view_count integer,
    watch_count integer,
    reverb_created_at timestamp without time zone,
    reverb_published_at timestamp without time zone,
    created_at timestamp without time zone NOT NULL DEFAULT (now() AT TIME ZONE 'utc'::text),
    updated_at timestamp without time zone NOT NULL DEFAULT (now() AT TIME ZONE 'utc'::text),
    last_synced_at timestamp without time zone,
    extended_attributes jsonb,
    handmade boolean
);''')

    # Table: sales
    op.execute('''CREATE TABLE sales (
    id integer NOT NULL DEFAULT nextval('sales_id_seq'::regclass),
    created_at timestamp without time zone NOT NULL DEFAULT (now() AT TIME ZONE 'utc'::text),
    product_id integer NOT NULL,
    platform_listing_id integer NOT NULL,
    platform_name character varying,
    sale_date timestamp without time zone NOT NULL DEFAULT (now() AT TIME ZONE 'utc'::text),
    sale_price double precision,
    original_list_price double precision,
    platform_fees double precision,
    shipping_cost double precision,
    net_amount double precision,
    days_to_sell integer,
    payment_method character varying,
    shipping_method character varying,
    buyer_location character varying,
    platform_data jsonb
);''')

    # Table: shipments
    op.execute('''CREATE TABLE shipments (
    id integer NOT NULL DEFAULT nextval('shipments_id_seq'::regclass),
    carrier character varying,
    carrier_account character varying,
    shipment_tracking_number character varying,
    status shipmentstatus,
    created_at timestamp without time zone NOT NULL DEFAULT (now() AT TIME ZONE 'utc'::text),
    updated_at timestamp without time zone NOT NULL DEFAULT (now() AT TIME ZONE 'utc'::text),
    origin_address json,
    destination_address json,
    package_weight double precision,
    package_length double precision,
    package_width double precision,
    package_height double precision,
    package_description character varying,
    is_international boolean,
    reference_number character varying,
    customs_value double precision,
    customs_currency character varying,
    carrier_response json,
    label_data text,
    label_format character varying,
    order_id integer,
    sale_id integer,
    platform_listing_id integer
);''')

    # Table: shipping_profiles
    op.execute('''CREATE TABLE shipping_profiles (
    id integer NOT NULL DEFAULT nextval('shipping_profiles_id_seq'::regclass),
    reverb_profile_id character varying,
    ebay_profile_id character varying,
    name character varying NOT NULL,
    description character varying,
    is_default boolean DEFAULT false,
    package_type character varying,
    weight double precision,
    dimensions jsonb,
    carriers jsonb,
    options jsonb,
    rates jsonb,
    created_at timestamp without time zone DEFAULT timezone('utc'::text, now()),
    updated_at timestamp without time zone DEFAULT timezone('utc'::text, now())
);''')

    # Table: users
    op.execute('''CREATE TABLE users (
    id integer NOT NULL DEFAULT nextval('users_id_seq'::regclass),
    username character varying NOT NULL,
    email character varying NOT NULL,
    hashed_password character varying NOT NULL,
    is_active boolean DEFAULT true,
    is_superuser boolean DEFAULT false,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone,
    PRIMARY KEY (id),
    CONSTRAINT users_username_key UNIQUE (username),
    CONSTRAINT users_email_key UNIQUE (email)
);''')

    # Table: webhook_events
    op.execute('''CREATE TABLE webhook_events (
    id integer NOT NULL DEFAULT nextval('webhook_events_id_seq'::regclass),
    event_type character varying,
    platform character varying,
    payload jsonb,
    processed boolean DEFAULT false,
    processed_at timestamp without time zone,
    created_at timestamp without time zone DEFAULT timezone('utc'::text, now()) NOT NULL,
    PRIMARY KEY (id)
);''')

    # Table: shopify_category_mappings
    op.execute('''CREATE TABLE shopify_category_mappings (
    id integer NOT NULL DEFAULT nextval('shopify_category_mappings_id_seq'::regclass),
    reverb_category_id integer NOT NULL,
    shopify_gid character varying NOT NULL,
    shopify_category_name character varying NOT NULL,
    merchant_type character varying,
    confidence_score numeric(3,2),
    is_verified boolean,
    notes text,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);''')

    # Table: shopify_listings
    op.execute('''CREATE TABLE shopify_listings (
    id integer NOT NULL DEFAULT nextval('website_listings_id_seq'::regclass),
    platform_id integer,
    seo_title character varying,
    seo_description character varying,
    seo_keywords jsonb,
    featured boolean,
    custom_layout character varying,
    created_at timestamp without time zone NOT NULL DEFAULT (now() AT TIME ZONE 'utc'::text),
    updated_at timestamp without time zone NOT NULL DEFAULT (now() AT TIME ZONE 'utc'::text),
    last_synced_at timestamp without time zone,
    shopify_product_id character varying(50),
    shopify_legacy_id character varying(20),
    handle character varying(255),
    title character varying(255),
    status character varying(20),
    category_gid character varying(100),
    category_name character varying(255),
    category_full_name character varying(500),
    category_assigned_at timestamp without time zone,
    category_assignment_status character varying(20),
    extended_attributes jsonb,
    vendor character varying(255),
    price double precision
);''')

    # Table: sync_events
    op.execute('''CREATE TABLE sync_events (
    id integer NOT NULL DEFAULT nextval('sync_events_id_seq'::regclass),
    sync_run_id uuid NOT NULL,
    platform_name character varying NOT NULL,
    product_id integer,
    platform_common_id integer,
    external_id character varying NOT NULL,
    change_type character varying NOT NULL,
    change_data json NOT NULL,
    status character varying NOT NULL,
    detected_at timestamp with time zone DEFAULT now(),
    processed_at timestamp with time zone,
    notes text
);''')

    # Table: sync_stats
    op.execute('''CREATE TABLE sync_stats (
    id integer NOT NULL DEFAULT nextval('sync_stats_id_seq'::regclass),
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    sync_run_id character varying,
    platform character varying,
    total_events_processed bigint DEFAULT 0,
    total_sales bigint DEFAULT 0,
    total_listings_created bigint DEFAULT 0,
    total_listings_updated bigint DEFAULT 0,
    total_listings_removed bigint DEFAULT 0,
    total_price_changes bigint DEFAULT 0,
    total_errors bigint DEFAULT 0,
    total_partial_syncs bigint DEFAULT 0,
    total_successful_syncs bigint DEFAULT 0,
    run_events_processed integer DEFAULT 0,
    run_sales integer DEFAULT 0,
    run_listings_created integer DEFAULT 0,
    run_listings_updated integer DEFAULT 0,
    run_listings_removed integer DEFAULT 0,
    run_price_changes integer DEFAULT 0,
    run_errors integer DEFAULT 0,
    run_duration_seconds integer,
    metadata_json jsonb
);''')

    # Table: vr_accepted_brands
    op.execute('''CREATE TABLE vr_accepted_brands (
    id integer NOT NULL DEFAULT nextval('vr_accepted_brands_id_seq'::regclass),
    vr_brand_id integer,
    name character varying NOT NULL,
    name_normalized character varying NOT NULL
);''')

    # Table: vr_category_mappings
    op.execute('''CREATE TABLE vr_category_mappings (
    id integer NOT NULL DEFAULT nextval('vr_category_mappings_id_seq'::regclass),
    reverb_category_id integer NOT NULL,
    vr_category_id character varying NOT NULL,
    vr_category_name character varying,
    vr_subcategory_id character varying,
    vr_subcategory_name character varying,
    vr_sub_subcategory_id character varying,
    vr_sub_subcategory_name character varying,
    vr_sub_sub_subcategory_id character varying,
    vr_sub_sub_subcategory_name character varying,
    confidence_score numeric(3,2),
    is_verified boolean,
    notes text,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);''')

    # Table: vr_listings
    op.execute('''CREATE TABLE vr_listings (
    id integer NOT NULL DEFAULT nextval('vr_listings_id_seq'::regclass),
    platform_id integer,
    in_collective boolean,
    in_inventory boolean,
    in_reseller boolean,
    collective_discount double precision,
    price_notax double precision,
    show_vat boolean,
    processing_time integer,
    vr_listing_id character varying,
    inventory_quantity integer,
    vr_state character varying,
    created_at timestamp without time zone NOT NULL DEFAULT (now() AT TIME ZONE 'utc'::text),
    updated_at timestamp without time zone NOT NULL DEFAULT (now() AT TIME ZONE 'utc'::text),
    last_synced_at timestamp without time zone,
    extended_attributes jsonb
);''')

    # Create indexes
    op.execute('''CREATE INDEX ix_activity_log_action ON public.activity_log USING btree (action)''')
    op.execute('''CREATE INDEX ix_activity_log_created_at ON public.activity_log USING btree (created_at)''')
    op.execute('''CREATE INDEX ix_activity_log_entity_id ON public.activity_log USING btree (entity_id)''')
    op.execute('''CREATE INDEX ix_activity_log_entity_type ON public.activity_log USING btree (entity_type)''')
    op.execute('''CREATE INDEX ix_activity_log_platform ON public.activity_log USING btree (platform)''')
    op.execute('''CREATE INDEX ix_ebay_category_mappings_ebay_id ON public.ebay_category_mappings USING btree (ebay_category_id)''')
    op.execute('''CREATE INDEX ix_ebay_category_mappings_reverb_id ON public.ebay_category_mappings USING btree (reverb_category_id)''')
    op.execute('''CREATE UNIQUE INDEX ebay_listings_item_unique ON public.ebay_listings USING btree (ebay_item_id)''')
    op.execute('''CREATE INDEX ix_ebay_listings_ebay_category_id ON public.ebay_listings USING btree (ebay_category_id)''')
    op.execute('''CREATE UNIQUE INDEX ix_ebay_listings_ebay_item_id ON public.ebay_listings USING btree (ebay_item_id)''')
    op.execute('''CREATE INDEX ix_ebay_listings_id ON public.ebay_listings USING btree (id)''')
    op.execute('''CREATE INDEX ix_ebay_listings_listing_status ON public.ebay_listings USING btree (listing_status)''')
    op.execute('''CREATE INDEX ix_ebay_listings_platform_id ON public.ebay_listings USING btree (platform_id)''')
    op.execute('''CREATE INDEX ix_orders_id ON public.orders USING btree (id)''')
    op.execute('''CREATE INDEX ix_orders_platform_listing_id ON public.orders USING btree (platform_listing_id)''')
    op.execute('''CREATE INDEX idx_category_mappings_source ON public.platform_category_mappings USING btree (source_platform, source_category_id)''')
    op.execute('''CREATE INDEX idx_category_mappings_target ON public.platform_category_mappings USING btree (target_platform)''')
    op.execute('''CREATE INDEX idx_category_mappings_verified ON public.platform_category_mappings USING btree (is_verified)''')
    op.execute('''CREATE INDEX ix_platform_common_product_id ON public.platform_common USING btree (product_id)''')
    op.execute('''CREATE INDEX ix_platform_common_status ON public.platform_common USING btree (status)''')
    op.execute('''CREATE INDEX ix_platform_common_sync_status ON public.platform_common USING btree (sync_status)''')
    op.execute('''CREATE UNIQUE INDEX platform_common_platform_external_unique ON public.platform_common USING btree (platform_name, external_id)''')
    op.execute('''CREATE UNIQUE INDEX platform_common_product_platform_unique ON public.platform_common USING btree (product_id, platform_name)''')
    op.execute('''CREATE UNIQUE INDEX unique_platform_external_id ON public.platform_common USING btree (platform_name, external_id)''')
    op.execute('''CREATE UNIQUE INDEX unique_product_mapping ON public.product_mappings USING btree (master_product_id, related_product_id)''')
    op.execute('''CREATE INDEX ix_products_is_stocked_item ON public.products USING btree (is_stocked_item)''')
    op.execute('''CREATE INDEX ix_products_status ON public.products USING btree (status)''')
    op.execute('''CREATE INDEX ix_reverb_categories_name ON public.reverb_categories USING btree (name)''')
    op.execute('''CREATE INDEX ix_reverb_categories_uuid ON public.reverb_categories USING btree (uuid)''')
    op.execute('''CREATE INDEX ix_reverb_listings_platform_id ON public.reverb_listings USING btree (platform_id)''')
    op.execute('''CREATE INDEX ix_reverb_listings_reverb_state ON public.reverb_listings USING btree (reverb_state)''')
    op.execute('''CREATE UNIQUE INDEX reverb_listings_item_unique ON public.reverb_listings USING btree (reverb_listing_id)''')
    op.execute('''CREATE INDEX ix_sales_platform_listing_id ON public.sales USING btree (platform_listing_id)''')
    op.execute('''CREATE INDEX ix_sales_product_id ON public.sales USING btree (product_id)''')
    op.execute('''CREATE INDEX ix_shipments_carrier ON public.shipments USING btree (carrier)''')
    op.execute('''CREATE INDEX ix_shipments_id ON public.shipments USING btree (id)''')
    op.execute('''CREATE INDEX ix_shipments_reference_number ON public.shipments USING btree (reference_number)''')
    op.execute('''CREATE INDEX ix_shipments_sale_id ON public.shipments USING btree (sale_id)''')
    op.execute('''CREATE INDEX ix_shipments_shipment_tracking_number ON public.shipments USING btree (shipment_tracking_number)''')
    op.execute('''CREATE INDEX ix_shipments_status ON public.shipments USING btree (status)''')
    op.execute('''CREATE INDEX ix_shipping_profiles_reverb_profile_id ON public.shipping_profiles USING btree (reverb_profile_id)''')
    op.execute('''CREATE INDEX ix_shopify_category_mappings_gid ON public.shopify_category_mappings USING btree (shopify_gid)''')
    op.execute('''CREATE INDEX ix_shopify_category_mappings_reverb_id ON public.shopify_category_mappings USING btree (reverb_category_id)''')
    op.execute('''CREATE INDEX ix_shopify_listings_category_gid ON public.shopify_listings USING btree (category_gid)''')
    op.execute('''CREATE INDEX ix_shopify_listings_handle ON public.shopify_listings USING btree (handle)''')
    op.execute('''CREATE INDEX ix_shopify_listings_shopify_legacy_id ON public.shopify_listings USING btree (shopify_legacy_id)''')
    op.execute('''CREATE INDEX ix_shopify_listings_shopify_product_id ON public.shopify_listings USING btree (shopify_product_id)''')
    op.execute('''CREATE INDEX ix_sync_events_change_type ON public.sync_events USING btree (change_type)''')
    op.execute('''CREATE INDEX ix_sync_events_external_id ON public.sync_events USING btree (external_id)''')
    op.execute('''CREATE INDEX ix_sync_events_id ON public.sync_events USING btree (id)''')
    op.execute('''CREATE INDEX ix_sync_events_platform_common_id ON public.sync_events USING btree (platform_common_id)''')
    op.execute('''CREATE INDEX ix_sync_events_platform_name ON public.sync_events USING btree (platform_name)''')
    op.execute('''CREATE INDEX ix_sync_events_product_id ON public.sync_events USING btree (product_id)''')
    op.execute('''CREATE INDEX ix_sync_events_status ON public.sync_events USING btree (status)''')
    op.execute('''CREATE INDEX ix_sync_events_sync_run_id ON public.sync_events USING btree (sync_run_id)''')
    op.execute('''CREATE UNIQUE INDEX ix_unique_pending_sync_event ON public.sync_events USING btree (platform_name, external_id, change_type) WHERE ((status)::text = 'pending'::text)''')
    op.execute('''CREATE INDEX ix_sync_stats_platform ON public.sync_stats USING btree (platform)''')
    op.execute('''CREATE INDEX ix_sync_stats_sync_run_id ON public.sync_stats USING btree (sync_run_id)''')
    op.execute('''CREATE INDEX ix_vr_accepted_brands_id ON public.vr_accepted_brands USING btree (id)''')
    op.execute('''CREATE UNIQUE INDEX ix_vr_accepted_brands_name ON public.vr_accepted_brands USING btree (name)''')
    op.execute('''CREATE UNIQUE INDEX ix_vr_accepted_brands_name_normalized ON public.vr_accepted_brands USING btree (name_normalized)''')
    op.execute('''CREATE UNIQUE INDEX ix_vr_accepted_brands_vr_brand_id ON public.vr_accepted_brands USING btree (vr_brand_id)''')
    op.execute('''CREATE INDEX ix_vr_category_mappings_reverb_id ON public.vr_category_mappings USING btree (reverb_category_id)''')
    op.execute('''CREATE INDEX ix_vr_category_mappings_vr_cat_id ON public.vr_category_mappings USING btree (vr_category_id)''')
    op.execute('''CREATE UNIQUE INDEX vr_listings_item_unique ON public.vr_listings USING btree (vr_listing_id)''')


def downgrade() -> None:
    # Drop all tables in reverse order
    op.drop_table('vr_listings')
    op.drop_table('vr_category_mappings')
    op.drop_table('vr_accepted_brands')
    op.drop_table('sync_stats')
    op.drop_table('sync_events')
    op.drop_table('shopify_listings')
    op.drop_table('shopify_category_mappings')
    op.drop_table('webhook_events')
    op.drop_table('users')
    op.drop_table('shipping_profiles')
    op.drop_table('shipments')
    op.drop_table('sales')
    op.drop_table('reverb_listings')
    op.drop_table('reverb_categories')
    op.drop_table('products')
    op.drop_table('product_merges')
    op.drop_table('product_mappings')
    op.drop_table('platform_status_mappings')
    op.drop_table('platform_policies')
    op.drop_table('platform_common')
    op.drop_table('platform_category_mappings')
    op.drop_table('orders')
    op.drop_table('ebay_listings')
    op.drop_table('ebay_category_mappings')
    op.drop_table('csv_import_logs')
    op.drop_table('category_mappings')
    op.drop_table('activity_log')

    # Drop enums
    op.execute('DROP TYPE IF EXISTS productcondition')
    op.execute('DROP TYPE IF EXISTS productstatus')
    op.execute('DROP TYPE IF EXISTS productstatus_old')
    op.execute('DROP TYPE IF EXISTS shipmentstatus')

    # Drop all sequences
    sequences = [
        'activity_log_id_seq',
        'category_mappings_id_seq',
        'csv_import_logs_id_seq',
        'ebay_category_mappings_id_seq',
        'ebay_listings_id_seq',
        'orders_id_seq',
        'platform_category_mappings_id_seq',
        'platform_common_id_seq',
        'platform_policies_id_seq',
        'platform_status_mappings_id_seq',
        'product_mappings_id_seq',
        'product_merges_id_seq',
        'products_id_seq',
        'reverb_categories_id_seq',
        'reverb_listings_id_seq',
        'sales_id_seq',
        'shipments_id_seq',
        'shipping_profiles_id_seq',
        'shopify_category_mappings_id_seq',
        'shopify_listings_id_seq',
        'sync_events_id_seq',
        'sync_stats_id_seq',
        'vr_accepted_brands_id_seq',
        'vr_category_mappings_id_seq',
        'vr_listings_id_seq',
        'users_id_seq',
        'webhook_events_id_seq'
    ]

    for seq in sequences:
        op.execute(f'DROP SEQUENCE IF EXISTS {seq}')
