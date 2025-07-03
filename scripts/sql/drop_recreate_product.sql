DROP TABLE IF EXISTS products CASCADE;

CREATE TABLE products (
    -- Primary Key & Timestamps (NOT NULL as per model)
    id SERIAL PRIMARY KEY,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT timezone('utc', now()) NOT NULL,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT timezone('utc', now()) NOT NULL,
    
    -- Core Identifiers (logical early positions)
    sku VARCHAR UNIQUE,
    brand VARCHAR,
    model VARCHAR,
    year INTEGER,
    decade INTEGER,
    finish VARCHAR,
    category VARCHAR,
    condition productcondition NOT NULL,
    
    -- Pricing Fields  
    base_price DOUBLE PRECISION,
    cost_price DOUBLE PRECISION,
    price DOUBLE PRECISION,
    price_notax DOUBLE PRECISION,
    collective_discount DOUBLE PRECISION,
    offer_discount DOUBLE PRECISION,
    
    -- Status and Business Flags
    status productstatus DEFAULT 'DRAFT',
    is_sold BOOLEAN DEFAULT false,
    in_collective BOOLEAN DEFAULT false,
    in_inventory BOOLEAN DEFAULT true,
    in_reseller BOOLEAN DEFAULT false,
    free_shipping BOOLEAN DEFAULT false,
    buy_now BOOLEAN DEFAULT true,
    show_vat BOOLEAN DEFAULT true,
    local_pickup BOOLEAN DEFAULT false,
    available_for_shipment BOOLEAN DEFAULT true,
    
    -- Media and Links
    primary_image VARCHAR,
    additional_images JSONB DEFAULT '[]'::jsonb,
    video_url VARCHAR,
    external_link VARCHAR,
    
    -- Logistics
    processing_time INTEGER,
    shipping_profile_id INTEGER,
    package_type VARCHAR(50),
    package_weight DOUBLE PRECISION,
    package_dimensions JSONB,
    
    -- Description LAST (for pgAdmin readability)
    description TEXT
);

-- Recreate indexes
CREATE INDEX idx_products_status ON products(status);
CREATE UNIQUE INDEX idx_products_sku ON products(sku);