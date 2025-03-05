
-- Drop the table if it exists
DROP TABLE IF EXISTS vr_listings;

-- Create the table with the complete schema
CREATE TABLE vr_listings (
    id SERIAL PRIMARY KEY,
    platform_id INTEGER REFERENCES platform_common(id),
    in_collective BOOLEAN DEFAULT FALSE,
    in_inventory BOOLEAN DEFAULT TRUE,
    in_reseller BOOLEAN DEFAULT FALSE,
    collective_discount DOUBLE PRECISION,
    price_notax DOUBLE PRECISION,
    show_vat BOOLEAN DEFAULT TRUE,
    processing_time INTEGER,
    
    -- Enhanced fields
    vr_listing_id VARCHAR,
    inventory_quantity INTEGER DEFAULT 1,
    vr_state VARCHAR,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_synced_at TIMESTAMP,
    
    extended_attributes JSONB DEFAULT '{}'::jsonb
);