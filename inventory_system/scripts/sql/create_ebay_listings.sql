-- Drop the existing table
DROP TABLE IF EXISTS ebay_listings;

-- Create the new table with the updated schema
CREATE TABLE ebay_listings (
    id SERIAL PRIMARY KEY,
    ebay_item_id VARCHAR UNIQUE,
    listing_status VARCHAR,
    title VARCHAR,
    format VARCHAR,
    price FLOAT,
    quantity INTEGER,
    quantity_available INTEGER,
    quantity_sold INTEGER DEFAULT 0,
    ebay_category_id VARCHAR,
    ebay_category_name VARCHAR,
    ebay_second_category_id VARCHAR,
    start_time TIMESTAMP,
    end_time TIMESTAMP,
    listing_url VARCHAR,
    ebay_condition_id VARCHAR,
    condition_display_name VARCHAR,
    gallery_url VARCHAR,
    picture_urls JSONB,
    item_specifics JSONB,
    payment_policy_id VARCHAR,
    return_policy_id VARCHAR,
    shipping_policy_id VARCHAR,
    transaction_id VARCHAR,
    order_line_item_id VARCHAR,
    buyer_user_id VARCHAR,
    paid_time TIMESTAMP,
    payment_status VARCHAR,
    shipping_status VARCHAR,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    listing_data JSONB
);

-- Create the necessary indexes
CREATE INDEX idx_ebay_listings_ebay_item_id ON ebay_listings(ebay_item_id);
CREATE INDEX idx_ebay_listings_listing_status ON ebay_listings(listing_status);
CREATE INDEX idx_ebay_listings_ebay_category_id ON ebay_listings(ebay_category_id);

-- Grant permissions to the application user
GRANT SELECT, INSERT, UPDATE, DELETE ON ebay_listings TO inventory_user;
GRANT USAGE, SELECT ON SEQUENCE ebay_listings_id_seq TO inventory_user;