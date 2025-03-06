CREATE TABLE category_mappings (
    id SERIAL PRIMARY KEY,
    source_platform VARCHAR(20) NOT NULL,  -- e.g., 'reverb', 'internal', etc.
    source_id VARCHAR(36) NOT NULL,        -- ID in source platform
    source_name VARCHAR(255) NOT NULL,     -- Name for reference
    target_platform VARCHAR(20) NOT NULL,  -- e.g., 'vr', 'ebay', etc.
    target_id VARCHAR(36) NOT NULL,        -- ID in target platform
    target_subcategory_id VARCHAR(36),     -- Subcategory if needed
    target_tertiary_id VARCHAR(36),        -- Third level if needed
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Unique constraint to prevent duplicate mappings
CREATE UNIQUE INDEX idx_category_mapping_unique ON category_mappings
    (source_platform, source_id, target_platform);