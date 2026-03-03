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
    bind = op.get_bind()
    is_postgresql = bind.dialect.name == 'postgresql'

    if is_postgresql:
        _upgrade_postgresql()
    else:
        _upgrade_sqlite()


def _upgrade_postgresql() -> None:
    """Original PostgreSQL-specific upgrade with raw SQL."""

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

    # Table: reverb_orders
    op.execute('''CREATE TABLE IF NOT EXISTS reverb_orders (
    id serial PRIMARY KEY,
    order_uuid character varying NOT NULL,
    order_number character varying,
    order_bundle_id character varying,
    reverb_listing_id character varying,
    title character varying,
    shop_name character varying,
    sku character varying,
    status character varying,
    order_type character varying,
    order_source character varying,
    shipment_status character varying,
    shipping_method character varying,
    payment_method character varying,
    local_pickup boolean,
    needs_feedback_for_buyer boolean,
    needs_feedback_for_seller boolean,
    shipping_taxed boolean,
    tax_responsible_party character varying,
    tax_rate numeric,
    quantity integer,
    buyer_id integer,
    buyer_name character varying,
    buyer_first_name character varying,
    buyer_last_name character varying,
    buyer_email character varying,
    shipping_name character varying,
    shipping_phone character varying,
    shipping_city character varying,
    shipping_region character varying,
    shipping_postal_code character varying,
    shipping_country_code character varying,
    created_at timestamp without time zone,
    paid_at timestamp without time zone,
    updated_at timestamp without time zone,
    amount_product numeric,
    amount_product_currency character varying,
    amount_product_subtotal numeric,
    amount_product_subtotal_currency character varying,
    shipping_amount numeric,
    shipping_currency character varying,
    tax_amount numeric,
    tax_currency character varying,
    total_amount numeric,
    total_currency character varying,
    direct_checkout_fee_amount numeric,
    direct_checkout_fee_currency character varying,
    direct_checkout_payout_amount numeric,
    direct_checkout_payout_currency character varying,
    tax_on_fees_amount numeric,
    tax_on_fees_currency character varying,
    shipping_address jsonb,
    order_notes jsonb,
    photos jsonb,
    links jsonb,
    presentment_amounts jsonb,
    raw_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    product_id integer,
    platform_listing_id integer,
    created_row_at timestamp without time zone NOT NULL DEFAULT timezone('utc'::text, now()),
    updated_row_at timestamp without time zone NOT NULL DEFAULT timezone('utc'::text, now()),
    sale_processed boolean NOT NULL DEFAULT false,
    sale_processed_at timestamp without time zone
);''')

    # Table: ebay_orders
    op.execute('''CREATE TABLE IF NOT EXISTS ebay_orders (
    id serial PRIMARY KEY,
    order_id character varying NOT NULL,
    extended_order_id character varying,
    order_status character varying,
    checkout_status jsonb,
    created_time timestamp without time zone,
    paid_time timestamp without time zone,
    shipped_time timestamp without time zone,
    buyer_user_id character varying,
    seller_user_id character varying,
    amount_paid numeric,
    amount_paid_currency character varying,
    total_amount numeric,
    total_currency character varying,
    shipping_cost numeric,
    shipping_currency character varying,
    subtotal_amount numeric,
    subtotal_currency character varying,
    item_id character varying,
    order_line_item_id character varying,
    transaction_id character varying,
    inventory_reservation_id character varying,
    sales_record_number character varying,
    primary_sku character varying,
    quantity_purchased integer,
    transaction_price numeric,
    transaction_currency character varying,
    tracking_number character varying,
    tracking_carrier character varying,
    shipping_service character varying,
    shipping_details jsonb,
    shipping_address jsonb,
    shipping_name character varying,
    shipping_country character varying,
    shipping_city character varying,
    shipping_state character varying,
    shipping_postal_code character varying,
    transactions jsonb,
    monetary_details jsonb,
    raw_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    product_id integer,
    platform_listing_id integer,
    created_at timestamp without time zone NOT NULL DEFAULT timezone('utc'::text, now()),
    updated_at timestamp without time zone NOT NULL DEFAULT timezone('utc'::text, now()),
    sale_processed boolean NOT NULL DEFAULT false,
    sale_processed_at timestamp without time zone
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
    id integer NOT NULL DEFAULT nextval('shopify_listings_id_seq'::regclass),
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


def _upgrade_sqlite() -> None:
    """SQLite-compatible upgrade using portable SQLAlchemy table definitions."""

    # -- activity_log --
    op.create_table('activity_log',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('action', sa.String(50), nullable=False),
        sa.Column('entity_type', sa.String(50), nullable=False),
        sa.Column('entity_id', sa.String(100), nullable=False),
        sa.Column('platform', sa.String(50)),
        sa.Column('details', sa.JSON()),
        sa.Column('user_id', sa.Integer()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )

    # -- category_mappings --
    op.create_table('category_mappings',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('source_platform', sa.String(20), nullable=False),
        sa.Column('source_id', sa.String(36), nullable=False),
        sa.Column('source_name', sa.String(255), nullable=False),
        sa.Column('target_platform', sa.String(20), nullable=False),
        sa.Column('target_id', sa.String(36), nullable=False),
        sa.Column('target_subcategory_id', sa.String(36)),
        sa.Column('target_tertiary_id', sa.String(36)),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )

    # -- csv_import_logs --
    op.create_table('csv_import_logs',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('timestamp', sa.DateTime()),
        sa.Column('filename', sa.String()),
        sa.Column('platform', sa.String()),
        sa.Column('total_rows', sa.Integer()),
        sa.Column('successful_rows', sa.Integer()),
        sa.Column('failed_rows', sa.Integer()),
        sa.Column('error_log', sa.JSON()),
    )

    # -- ebay_category_mappings --
    op.create_table('ebay_category_mappings',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('reverb_category_id', sa.Integer(), nullable=False),
        sa.Column('ebay_category_id', sa.String(), nullable=False),
        sa.Column('ebay_category_name', sa.String(), nullable=False),
        sa.Column('confidence_score', sa.Numeric(3, 2)),
        sa.Column('is_verified', sa.Boolean()),
        sa.Column('notes', sa.Text()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
    )

    # -- ebay_listings --
    op.create_table('ebay_listings',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('platform_id', sa.Integer()),
        sa.Column('ebay_item_id', sa.String()),
        sa.Column('listing_status', sa.String()),
        sa.Column('title', sa.String()),
        sa.Column('format', sa.String()),
        sa.Column('price', sa.Float()),
        sa.Column('quantity', sa.Integer()),
        sa.Column('quantity_available', sa.Integer()),
        sa.Column('quantity_sold', sa.Integer()),
        sa.Column('ebay_category_id', sa.String()),
        sa.Column('ebay_category_name', sa.String()),
        sa.Column('ebay_second_category_id', sa.String()),
        sa.Column('start_time', sa.DateTime()),
        sa.Column('end_time', sa.DateTime()),
        sa.Column('listing_url', sa.String()),
        sa.Column('ebay_condition_id', sa.String()),
        sa.Column('condition_display_name', sa.String()),
        sa.Column('gallery_url', sa.String()),
        sa.Column('picture_urls', sa.JSON()),
        sa.Column('item_specifics', sa.JSON()),
        sa.Column('payment_policy_id', sa.String()),
        sa.Column('return_policy_id', sa.String()),
        sa.Column('shipping_policy_id', sa.String()),
        sa.Column('transaction_id', sa.String()),
        sa.Column('order_line_item_id', sa.String()),
        sa.Column('buyer_user_id', sa.String()),
        sa.Column('paid_time', sa.DateTime()),
        sa.Column('payment_status', sa.String()),
        sa.Column('shipping_status', sa.String()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('last_synced_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('listing_data', sa.JSON()),
    )

    # -- orders --
    op.create_table('orders',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('order_reference', sa.String()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('platform_listing_id', sa.Integer()),
    )

    # -- reverb_orders --
    op.create_table('reverb_orders',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('order_uuid', sa.String(), nullable=False),
        sa.Column('order_number', sa.String()),
        sa.Column('order_bundle_id', sa.String()),
        sa.Column('reverb_listing_id', sa.String()),
        sa.Column('title', sa.String()),
        sa.Column('shop_name', sa.String()),
        sa.Column('sku', sa.String()),
        sa.Column('status', sa.String()),
        sa.Column('order_type', sa.String()),
        sa.Column('order_source', sa.String()),
        sa.Column('shipment_status', sa.String()),
        sa.Column('shipping_method', sa.String()),
        sa.Column('payment_method', sa.String()),
        sa.Column('local_pickup', sa.Boolean()),
        sa.Column('needs_feedback_for_buyer', sa.Boolean()),
        sa.Column('needs_feedback_for_seller', sa.Boolean()),
        sa.Column('shipping_taxed', sa.Boolean()),
        sa.Column('tax_responsible_party', sa.String()),
        sa.Column('tax_rate', sa.Numeric()),
        sa.Column('quantity', sa.Integer()),
        sa.Column('buyer_id', sa.Integer()),
        sa.Column('buyer_name', sa.String()),
        sa.Column('buyer_first_name', sa.String()),
        sa.Column('buyer_last_name', sa.String()),
        sa.Column('buyer_email', sa.String()),
        sa.Column('shipping_name', sa.String()),
        sa.Column('shipping_phone', sa.String()),
        sa.Column('shipping_city', sa.String()),
        sa.Column('shipping_region', sa.String()),
        sa.Column('shipping_postal_code', sa.String()),
        sa.Column('shipping_country_code', sa.String()),
        sa.Column('created_at', sa.DateTime()),
        sa.Column('paid_at', sa.DateTime()),
        sa.Column('updated_at', sa.DateTime()),
        sa.Column('amount_product', sa.Numeric()),
        sa.Column('amount_product_currency', sa.String()),
        sa.Column('amount_product_subtotal', sa.Numeric()),
        sa.Column('amount_product_subtotal_currency', sa.String()),
        sa.Column('shipping_amount', sa.Numeric()),
        sa.Column('shipping_currency', sa.String()),
        sa.Column('tax_amount', sa.Numeric()),
        sa.Column('tax_currency', sa.String()),
        sa.Column('total_amount', sa.Numeric()),
        sa.Column('total_currency', sa.String()),
        sa.Column('direct_checkout_fee_amount', sa.Numeric()),
        sa.Column('direct_checkout_fee_currency', sa.String()),
        sa.Column('direct_checkout_payout_amount', sa.Numeric()),
        sa.Column('direct_checkout_payout_currency', sa.String()),
        sa.Column('tax_on_fees_amount', sa.Numeric()),
        sa.Column('tax_on_fees_currency', sa.String()),
        sa.Column('shipping_address', sa.JSON()),
        sa.Column('order_notes', sa.JSON()),
        sa.Column('photos', sa.JSON()),
        sa.Column('links', sa.JSON()),
        sa.Column('presentment_amounts', sa.JSON()),
        sa.Column('raw_payload', sa.JSON(), nullable=False, server_default="'{}'"),
        sa.Column('product_id', sa.Integer()),
        sa.Column('platform_listing_id', sa.Integer()),
        sa.Column('created_row_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_row_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('sale_processed', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('sale_processed_at', sa.DateTime()),
    )

    # -- ebay_orders --
    op.create_table('ebay_orders',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('order_id', sa.String(), nullable=False),
        sa.Column('extended_order_id', sa.String()),
        sa.Column('order_status', sa.String()),
        sa.Column('checkout_status', sa.JSON()),
        sa.Column('created_time', sa.DateTime()),
        sa.Column('paid_time', sa.DateTime()),
        sa.Column('shipped_time', sa.DateTime()),
        sa.Column('buyer_user_id', sa.String()),
        sa.Column('seller_user_id', sa.String()),
        sa.Column('amount_paid', sa.Numeric()),
        sa.Column('amount_paid_currency', sa.String()),
        sa.Column('total_amount', sa.Numeric()),
        sa.Column('total_currency', sa.String()),
        sa.Column('shipping_cost', sa.Numeric()),
        sa.Column('shipping_currency', sa.String()),
        sa.Column('subtotal_amount', sa.Numeric()),
        sa.Column('subtotal_currency', sa.String()),
        sa.Column('item_id', sa.String()),
        sa.Column('order_line_item_id', sa.String()),
        sa.Column('transaction_id', sa.String()),
        sa.Column('inventory_reservation_id', sa.String()),
        sa.Column('sales_record_number', sa.String()),
        sa.Column('primary_sku', sa.String()),
        sa.Column('quantity_purchased', sa.Integer()),
        sa.Column('transaction_price', sa.Numeric()),
        sa.Column('transaction_currency', sa.String()),
        sa.Column('tracking_number', sa.String()),
        sa.Column('tracking_carrier', sa.String()),
        sa.Column('shipping_service', sa.String()),
        sa.Column('shipping_details', sa.JSON()),
        sa.Column('shipping_address', sa.JSON()),
        sa.Column('shipping_name', sa.String()),
        sa.Column('shipping_country', sa.String()),
        sa.Column('shipping_city', sa.String()),
        sa.Column('shipping_state', sa.String()),
        sa.Column('shipping_postal_code', sa.String()),
        sa.Column('transactions', sa.JSON()),
        sa.Column('monetary_details', sa.JSON()),
        sa.Column('raw_payload', sa.JSON(), nullable=False, server_default="'{}'"),
        sa.Column('product_id', sa.Integer()),
        sa.Column('platform_listing_id', sa.Integer()),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('sale_processed', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('sale_processed_at', sa.DateTime()),
    )

    # -- platform_category_mappings --
    op.create_table('platform_category_mappings',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('source_platform', sa.String(50), nullable=False),
        sa.Column('source_category_id', sa.String(100), nullable=False),
        sa.Column('source_category_name', sa.Text()),
        sa.Column('target_platform', sa.String(50), nullable=False),
        sa.Column('target_category_id', sa.String(100)),
        sa.Column('target_category_name', sa.Text()),
        sa.Column('shopify_gid', sa.String(255)),
        sa.Column('merchant_type', sa.String(255)),
        sa.Column('vr_category_id', sa.String(50)),
        sa.Column('vr_subcategory_id', sa.String(50)),
        sa.Column('vr_sub_subcategory_id', sa.String(50)),
        sa.Column('vr_sub_sub_subcategory_id', sa.String(50)),
        sa.Column('item_count', sa.Integer(), server_default='0'),
        sa.Column('confidence_score', sa.Numeric(3, 2)),
        sa.Column('is_verified', sa.Boolean(), server_default='0'),
        sa.Column('notes', sa.Text()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
    )

    # -- platform_common --
    op.create_table('platform_common',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('product_id', sa.Integer()),
        sa.Column('platform_name', sa.String()),
        sa.Column('external_id', sa.String()),
        sa.Column('status', sa.String()),
        sa.Column('last_sync', sa.DateTime()),
        sa.Column('sync_status', sa.String()),
        sa.Column('listing_url', sa.String()),
        sa.Column('platform_specific_data', sa.JSON()),
    )

    # -- platform_policies --
    op.create_table('platform_policies',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('platform', sa.String(50)),
        sa.Column('policy_type', sa.String(50)),
        sa.Column('policy_id', sa.String(100)),
        sa.Column('policy_name', sa.String(200)),
        sa.Column('is_default', sa.Boolean(), server_default='0'),
    )

    # -- platform_status_mappings --
    op.create_table('platform_status_mappings',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('platform_name', sa.String(50), nullable=False),
        sa.Column('platform_status', sa.String(100), nullable=False),
        sa.Column('central_status', sa.String(20), nullable=False),
        sa.Column('description', sa.Text()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
    )

    # -- product_mappings --
    op.create_table('product_mappings',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('master_product_id', sa.Integer(), nullable=False),
        sa.Column('related_product_id', sa.Integer(), nullable=False),
        sa.Column('match_confidence', sa.Float()),
        sa.Column('match_method', sa.String()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )

    # -- product_merges --
    op.create_table('product_merges',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('kept_product_id', sa.Integer(), nullable=False),
        sa.Column('merged_product_id', sa.Integer(), nullable=False),
        sa.Column('merged_product_data', sa.JSON()),
        sa.Column('merged_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('merged_by', sa.String(255)),
        sa.Column('reason', sa.String(255), server_default='Product matching'),
    )

    # -- products --
    op.create_table('products',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('sku', sa.String()),
        sa.Column('brand', sa.String()),
        sa.Column('model', sa.String()),
        sa.Column('year', sa.Integer()),
        sa.Column('decade', sa.Integer()),
        sa.Column('finish', sa.String()),
        sa.Column('category', sa.String()),
        sa.Column('condition', sa.String(), nullable=False),  # stored as text in SQLite
        sa.Column('base_price', sa.Float()),
        sa.Column('cost_price', sa.Float()),
        sa.Column('price', sa.Float()),
        sa.Column('price_notax', sa.Float()),
        sa.Column('collective_discount', sa.Float()),
        sa.Column('offer_discount', sa.Float()),
        sa.Column('status', sa.String()),  # stored as text in SQLite
        sa.Column('is_sold', sa.Boolean()),
        sa.Column('in_collective', sa.Boolean()),
        sa.Column('in_inventory', sa.Boolean()),
        sa.Column('in_reseller', sa.Boolean()),
        sa.Column('free_shipping', sa.Boolean()),
        sa.Column('buy_now', sa.Boolean()),
        sa.Column('show_vat', sa.Boolean()),
        sa.Column('local_pickup', sa.Boolean()),
        sa.Column('available_for_shipment', sa.Boolean()),
        sa.Column('primary_image', sa.String()),
        sa.Column('additional_images', sa.JSON()),
        sa.Column('video_url', sa.String()),
        sa.Column('external_link', sa.String()),
        sa.Column('processing_time', sa.Integer()),
        sa.Column('shipping_profile_id', sa.Integer()),
        sa.Column('package_type', sa.String(50)),
        sa.Column('package_weight', sa.Float()),
        sa.Column('package_dimensions', sa.JSON()),
        sa.Column('description', sa.String()),
        sa.Column('title', sa.String()),
        sa.Column('is_stocked_item', sa.Boolean(), server_default='0', nullable=False),
        sa.Column('quantity', sa.Integer()),
    )

    # -- reverb_categories --
    op.create_table('reverb_categories',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('uuid', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('full_path', sa.String()),
        sa.Column('parent_uuid', sa.String()),
        sa.Column('item_count', sa.Integer()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
    )

    # -- reverb_listings --
    op.create_table('reverb_listings',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('platform_id', sa.Integer()),
        sa.Column('reverb_listing_id', sa.String()),
        sa.Column('reverb_slug', sa.String()),
        sa.Column('reverb_category_uuid', sa.String()),
        sa.Column('condition_rating', sa.Float()),
        sa.Column('inventory_quantity', sa.Integer()),
        sa.Column('has_inventory', sa.Boolean()),
        sa.Column('offers_enabled', sa.Boolean()),
        sa.Column('is_auction', sa.Boolean()),
        sa.Column('list_price', sa.Float()),
        sa.Column('listing_currency', sa.String()),
        sa.Column('shipping_profile_id', sa.String()),
        sa.Column('shop_policies_id', sa.String()),
        sa.Column('reverb_state', sa.String()),
        sa.Column('view_count', sa.Integer()),
        sa.Column('watch_count', sa.Integer()),
        sa.Column('reverb_created_at', sa.DateTime()),
        sa.Column('reverb_published_at', sa.DateTime()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('last_synced_at', sa.DateTime()),
        sa.Column('extended_attributes', sa.JSON()),
        sa.Column('handmade', sa.Boolean()),
    )

    # -- sales --
    op.create_table('sales',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('product_id', sa.Integer(), nullable=False),
        sa.Column('platform_listing_id', sa.Integer(), nullable=False),
        sa.Column('platform_name', sa.String()),
        sa.Column('sale_date', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('sale_price', sa.Float()),
        sa.Column('original_list_price', sa.Float()),
        sa.Column('platform_fees', sa.Float()),
        sa.Column('shipping_cost', sa.Float()),
        sa.Column('net_amount', sa.Float()),
        sa.Column('days_to_sell', sa.Integer()),
        sa.Column('payment_method', sa.String()),
        sa.Column('shipping_method', sa.String()),
        sa.Column('buyer_location', sa.String()),
        sa.Column('platform_data', sa.JSON()),
    )

    # -- shipments --
    op.create_table('shipments',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('carrier', sa.String()),
        sa.Column('carrier_account', sa.String()),
        sa.Column('shipment_tracking_number', sa.String()),
        sa.Column('status', sa.String()),  # stored as text in SQLite
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('origin_address', sa.JSON()),
        sa.Column('destination_address', sa.JSON()),
        sa.Column('package_weight', sa.Float()),
        sa.Column('package_length', sa.Float()),
        sa.Column('package_width', sa.Float()),
        sa.Column('package_height', sa.Float()),
        sa.Column('package_description', sa.String()),
        sa.Column('is_international', sa.Boolean()),
        sa.Column('reference_number', sa.String()),
        sa.Column('customs_value', sa.Float()),
        sa.Column('customs_currency', sa.String()),
        sa.Column('carrier_response', sa.JSON()),
        sa.Column('label_data', sa.Text()),
        sa.Column('label_format', sa.String()),
        sa.Column('order_id', sa.Integer()),
        sa.Column('sale_id', sa.Integer()),
        sa.Column('platform_listing_id', sa.Integer()),
    )

    # -- shipping_profiles --
    op.create_table('shipping_profiles',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('reverb_profile_id', sa.String()),
        sa.Column('ebay_profile_id', sa.String()),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.String()),
        sa.Column('is_default', sa.Boolean(), server_default='0'),
        sa.Column('package_type', sa.String()),
        sa.Column('weight', sa.Float()),
        sa.Column('dimensions', sa.JSON()),
        sa.Column('carriers', sa.JSON()),
        sa.Column('options', sa.JSON()),
        sa.Column('rates', sa.JSON()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
    )

    # -- users --
    op.create_table('users',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('username', sa.String(), nullable=False, unique=True),
        sa.Column('email', sa.String(), nullable=False, unique=True),
        sa.Column('hashed_password', sa.String(), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default='1'),
        sa.Column('is_superuser', sa.Boolean(), server_default='0'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime()),
    )

    # -- webhook_events --
    op.create_table('webhook_events',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('event_type', sa.String()),
        sa.Column('platform', sa.String()),
        sa.Column('payload', sa.JSON()),
        sa.Column('processed', sa.Boolean(), server_default='0'),
        sa.Column('processed_at', sa.DateTime()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )

    # -- shopify_category_mappings --
    op.create_table('shopify_category_mappings',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('reverb_category_id', sa.Integer(), nullable=False),
        sa.Column('shopify_gid', sa.String(), nullable=False),
        sa.Column('shopify_category_name', sa.String(), nullable=False),
        sa.Column('merchant_type', sa.String()),
        sa.Column('confidence_score', sa.Numeric(3, 2)),
        sa.Column('is_verified', sa.Boolean()),
        sa.Column('notes', sa.Text()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
    )

    # -- shopify_listings --
    op.create_table('shopify_listings',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('platform_id', sa.Integer()),
        sa.Column('seo_title', sa.String()),
        sa.Column('seo_description', sa.String()),
        sa.Column('seo_keywords', sa.JSON()),
        sa.Column('featured', sa.Boolean()),
        sa.Column('custom_layout', sa.String()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('last_synced_at', sa.DateTime()),
        sa.Column('shopify_product_id', sa.String(50)),
        sa.Column('shopify_legacy_id', sa.String(20)),
        sa.Column('handle', sa.String(255)),
        sa.Column('title', sa.String(255)),
        sa.Column('status', sa.String(20)),
        sa.Column('category_gid', sa.String(100)),
        sa.Column('category_name', sa.String(255)),
        sa.Column('category_full_name', sa.String(500)),
        sa.Column('category_assigned_at', sa.DateTime()),
        sa.Column('category_assignment_status', sa.String(20)),
        sa.Column('extended_attributes', sa.JSON()),
        sa.Column('vendor', sa.String(255)),
        sa.Column('price', sa.Float()),
    )

    # -- sync_events --
    op.create_table('sync_events',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('sync_run_id', sa.String(), nullable=False),  # UUID stored as text in SQLite
        sa.Column('platform_name', sa.String(), nullable=False),
        sa.Column('product_id', sa.Integer()),
        sa.Column('platform_common_id', sa.Integer()),
        sa.Column('external_id', sa.String(), nullable=False),
        sa.Column('change_type', sa.String(), nullable=False),
        sa.Column('change_data', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('detected_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('processed_at', sa.DateTime()),
        sa.Column('notes', sa.Text()),
    )

    # -- sync_stats --
    op.create_table('sync_stats',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('sync_run_id', sa.String()),
        sa.Column('platform', sa.String()),
        sa.Column('total_events_processed', sa.BigInteger(), server_default='0'),
        sa.Column('total_sales', sa.BigInteger(), server_default='0'),
        sa.Column('total_listings_created', sa.BigInteger(), server_default='0'),
        sa.Column('total_listings_updated', sa.BigInteger(), server_default='0'),
        sa.Column('total_listings_removed', sa.BigInteger(), server_default='0'),
        sa.Column('total_price_changes', sa.BigInteger(), server_default='0'),
        sa.Column('total_errors', sa.BigInteger(), server_default='0'),
        sa.Column('total_partial_syncs', sa.BigInteger(), server_default='0'),
        sa.Column('total_successful_syncs', sa.BigInteger(), server_default='0'),
        sa.Column('run_events_processed', sa.Integer(), server_default='0'),
        sa.Column('run_sales', sa.Integer(), server_default='0'),
        sa.Column('run_listings_created', sa.Integer(), server_default='0'),
        sa.Column('run_listings_updated', sa.Integer(), server_default='0'),
        sa.Column('run_listings_removed', sa.Integer(), server_default='0'),
        sa.Column('run_price_changes', sa.Integer(), server_default='0'),
        sa.Column('run_errors', sa.Integer(), server_default='0'),
        sa.Column('run_duration_seconds', sa.Integer()),
        sa.Column('metadata_json', sa.JSON()),
    )

    # -- vr_accepted_brands --
    op.create_table('vr_accepted_brands',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('vr_brand_id', sa.Integer(), unique=True),
        sa.Column('name', sa.String(), nullable=False, unique=True),
        sa.Column('name_normalized', sa.String(), nullable=False, unique=True),
    )

    # -- vr_category_mappings --
    op.create_table('vr_category_mappings',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('reverb_category_id', sa.Integer(), nullable=False),
        sa.Column('vr_category_id', sa.String(), nullable=False),
        sa.Column('vr_category_name', sa.String()),
        sa.Column('vr_subcategory_id', sa.String()),
        sa.Column('vr_subcategory_name', sa.String()),
        sa.Column('vr_sub_subcategory_id', sa.String()),
        sa.Column('vr_sub_subcategory_name', sa.String()),
        sa.Column('vr_sub_sub_subcategory_id', sa.String()),
        sa.Column('vr_sub_sub_subcategory_name', sa.String()),
        sa.Column('confidence_score', sa.Numeric(3, 2)),
        sa.Column('is_verified', sa.Boolean()),
        sa.Column('notes', sa.Text()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
    )

    # -- vr_listings --
    op.create_table('vr_listings',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('platform_id', sa.Integer()),
        sa.Column('in_collective', sa.Boolean()),
        sa.Column('in_inventory', sa.Boolean()),
        sa.Column('in_reseller', sa.Boolean()),
        sa.Column('collective_discount', sa.Float()),
        sa.Column('price_notax', sa.Float()),
        sa.Column('show_vat', sa.Boolean()),
        sa.Column('processing_time', sa.Integer()),
        sa.Column('vr_listing_id', sa.String()),
        sa.Column('inventory_quantity', sa.Integer()),
        sa.Column('vr_state', sa.String()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('last_synced_at', sa.DateTime()),
        sa.Column('extended_attributes', sa.JSON()),
    )

    # -- SQLite-compatible indexes (no schema prefix, no USING btree) --
    op.create_index('ix_activity_log_action', 'activity_log', ['action'])
    op.create_index('ix_activity_log_created_at', 'activity_log', ['created_at'])
    op.create_index('ix_activity_log_entity_id', 'activity_log', ['entity_id'])
    op.create_index('ix_activity_log_entity_type', 'activity_log', ['entity_type'])
    op.create_index('ix_activity_log_platform', 'activity_log', ['platform'])
    op.create_index('ix_ebay_category_mappings_ebay_id', 'ebay_category_mappings', ['ebay_category_id'])
    op.create_index('ix_ebay_category_mappings_reverb_id', 'ebay_category_mappings', ['reverb_category_id'])
    op.create_index('ebay_listings_item_unique', 'ebay_listings', ['ebay_item_id'], unique=True)
    op.create_index('ix_ebay_listings_ebay_category_id', 'ebay_listings', ['ebay_category_id'])
    op.create_index('ix_ebay_listings_listing_status', 'ebay_listings', ['listing_status'])
    op.create_index('ix_ebay_listings_platform_id', 'ebay_listings', ['platform_id'])
    op.create_index('ix_orders_platform_listing_id', 'orders', ['platform_listing_id'])
    op.create_index('idx_category_mappings_source', 'platform_category_mappings', ['source_platform', 'source_category_id'])
    op.create_index('idx_category_mappings_target', 'platform_category_mappings', ['target_platform'])
    op.create_index('idx_category_mappings_verified', 'platform_category_mappings', ['is_verified'])
    op.create_index('ix_platform_common_product_id', 'platform_common', ['product_id'])
    op.create_index('ix_platform_common_status', 'platform_common', ['status'])
    op.create_index('ix_platform_common_sync_status', 'platform_common', ['sync_status'])
    op.create_index('platform_common_platform_external_unique', 'platform_common', ['platform_name', 'external_id'], unique=True)
    op.create_index('platform_common_product_platform_unique', 'platform_common', ['product_id', 'platform_name'], unique=True)
    op.create_index('unique_product_mapping', 'product_mappings', ['master_product_id', 'related_product_id'], unique=True)
    op.create_index('ix_products_is_stocked_item', 'products', ['is_stocked_item'])
    op.create_index('ix_products_status', 'products', ['status'])
    op.create_index('ix_reverb_categories_name', 'reverb_categories', ['name'])
    op.create_index('ix_reverb_categories_uuid', 'reverb_categories', ['uuid'])
    op.create_index('ix_reverb_listings_platform_id', 'reverb_listings', ['platform_id'])
    op.create_index('ix_reverb_listings_reverb_state', 'reverb_listings', ['reverb_state'])
    op.create_index('reverb_listings_item_unique', 'reverb_listings', ['reverb_listing_id'], unique=True)
    op.create_index('ix_sales_platform_listing_id', 'sales', ['platform_listing_id'])
    op.create_index('ix_sales_product_id', 'sales', ['product_id'])
    op.create_index('ix_shipments_carrier', 'shipments', ['carrier'])
    op.create_index('ix_shipments_reference_number', 'shipments', ['reference_number'])
    op.create_index('ix_shipments_sale_id', 'shipments', ['sale_id'])
    op.create_index('ix_shipments_shipment_tracking_number', 'shipments', ['shipment_tracking_number'])
    op.create_index('ix_shipments_status', 'shipments', ['status'])
    op.create_index('ix_shipping_profiles_reverb_profile_id', 'shipping_profiles', ['reverb_profile_id'])
    op.create_index('ix_shopify_category_mappings_gid', 'shopify_category_mappings', ['shopify_gid'])
    op.create_index('ix_shopify_category_mappings_reverb_id', 'shopify_category_mappings', ['reverb_category_id'])
    op.create_index('ix_shopify_listings_category_gid', 'shopify_listings', ['category_gid'])
    op.create_index('ix_shopify_listings_handle', 'shopify_listings', ['handle'])
    op.create_index('ix_shopify_listings_shopify_legacy_id', 'shopify_listings', ['shopify_legacy_id'])
    op.create_index('ix_shopify_listings_shopify_product_id', 'shopify_listings', ['shopify_product_id'])
    op.create_index('ix_sync_events_change_type', 'sync_events', ['change_type'])
    op.create_index('ix_sync_events_external_id', 'sync_events', ['external_id'])
    op.create_index('ix_sync_events_platform_common_id', 'sync_events', ['platform_common_id'])
    op.create_index('ix_sync_events_platform_name', 'sync_events', ['platform_name'])
    op.create_index('ix_sync_events_product_id', 'sync_events', ['product_id'])
    op.create_index('ix_sync_events_status', 'sync_events', ['status'])
    op.create_index('ix_sync_events_sync_run_id', 'sync_events', ['sync_run_id'])
    op.create_index('ix_sync_stats_platform', 'sync_stats', ['platform'])
    op.create_index('ix_sync_stats_sync_run_id', 'sync_stats', ['sync_run_id'])
    op.create_index('ix_vr_category_mappings_reverb_id', 'vr_category_mappings', ['reverb_category_id'])
    op.create_index('ix_vr_category_mappings_vr_cat_id', 'vr_category_mappings', ['vr_category_id'])
    op.create_index('vr_listings_item_unique', 'vr_listings', ['vr_listing_id'], unique=True)


def downgrade() -> None:
    # Drop all tables in reverse order (works for both dialects)
    tables = [
        'vr_listings', 'vr_category_mappings', 'vr_accepted_brands',
        'sync_stats', 'sync_events', 'shopify_listings',
        'shopify_category_mappings', 'webhook_events', 'users',
        'shipping_profiles', 'shipments', 'sales', 'reverb_listings',
        'reverb_categories', 'products', 'product_merges',
        'product_mappings', 'platform_status_mappings',
        'platform_policies', 'platform_common',
        'platform_category_mappings', 'ebay_orders', 'reverb_orders',
        'orders', 'ebay_listings',
        'ebay_category_mappings', 'csv_import_logs',
        'category_mappings', 'activity_log',
    ]
    for table in tables:
        op.drop_table(table)

    # PostgreSQL-only cleanup
    bind = op.get_bind()
    if bind.dialect.name == 'postgresql':
        # Drop enums
        op.execute('DROP TYPE IF EXISTS productcondition')
        op.execute('DROP TYPE IF EXISTS productstatus')
        op.execute('DROP TYPE IF EXISTS productstatus_old')
        op.execute('DROP TYPE IF EXISTS shipmentstatus')

        # Drop all sequences
        sequences = [
            'activity_log_id_seq', 'category_mappings_id_seq',
            'csv_import_logs_id_seq', 'ebay_category_mappings_id_seq',
            'ebay_listings_id_seq', 'orders_id_seq',
            'platform_category_mappings_id_seq', 'platform_common_id_seq',
            'platform_policies_id_seq', 'platform_status_mappings_id_seq',
            'product_mappings_id_seq', 'product_merges_id_seq',
            'products_id_seq', 'reverb_categories_id_seq',
            'reverb_listings_id_seq', 'sales_id_seq',
            'shipments_id_seq', 'shipping_profiles_id_seq',
            'shopify_category_mappings_id_seq', 'shopify_listings_id_seq',
            'sync_events_id_seq', 'sync_stats_id_seq',
            'vr_accepted_brands_id_seq', 'vr_category_mappings_id_seq',
            'vr_listings_id_seq', 'users_id_seq', 'webhook_events_id_seq',
        ]
        for seq in sequences:
            op.execute(f'DROP SEQUENCE IF EXISTS {seq}')
