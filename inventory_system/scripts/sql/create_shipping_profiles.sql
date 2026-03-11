-- Create shipping_profiles table if it doesn't exist
CREATE TABLE IF NOT EXISTS shipping_profiles (
    id SERIAL PRIMARY KEY,
    name VARCHAR NOT NULL,
    description VARCHAR,
    is_default BOOLEAN DEFAULT FALSE,
    package_type VARCHAR,
    weight DOUBLE PRECISION,
    dimensions JSONB,  -- Store length, width, height as a JSON object
    carriers JSONB,    -- Stores array of carrier codes
    options JSONB,     -- Stores insurance, signature, etc.
    rates JSONB,       -- Stores regional rates
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Add a unique constraint on the name column (with proper PostgreSQL syntax)
DO $$ 
BEGIN
    -- Check if the constraint already exists
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint 
        WHERE conname = 'shipping_profiles_name_key' 
        AND conrelid = 'shipping_profiles'::regclass
    ) THEN
        ALTER TABLE shipping_profiles 
        ADD CONSTRAINT shipping_profiles_name_key UNIQUE (name);
    END IF;
END $$;

-- Add shipping-related columns to products table if they don't exist
DO $$ 
BEGIN
    -- Add shipping_profile_id column if it doesn't exist
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                WHERE table_name='products' AND column_name='shipping_profile_id') THEN
        ALTER TABLE products ADD COLUMN shipping_profile_id INTEGER REFERENCES shipping_profiles(id);
    END IF;

    -- Add package_dimensions if it doesn't exist
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                WHERE table_name='products' AND column_name='package_dimensions') THEN
        ALTER TABLE products ADD COLUMN package_dimensions JSONB;
    END IF;

    -- Add package_weight if it doesn't exist
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                WHERE table_name='products' AND column_name='package_weight') THEN
        ALTER TABLE products ADD COLUMN package_weight DOUBLE PRECISION;
    END IF;
    
    -- Add package_type if it doesn't exist
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                WHERE table_name='products' AND column_name='package_type') THEN
        ALTER TABLE products ADD COLUMN package_type VARCHAR;
    END IF;
END $$;

-- Insert standard shipping profiles
INSERT INTO shipping_profiles
    (name, description, package_type, weight, dimensions, carriers, options, rates, is_default)
VALUES
    ('Guitar Box', 'Standard guitar shipping box (135x60x20 cm, 10kg)', 'guitar_case', 10.0, 
     '{"length": 135.0, "width": 60.0, "height": 20.0, "unit": "cm"}'::jsonb, 
     '["dhl", "fedex"]'::jsonb, 
     '{"require_signature": true, "insurance": true, "fragile": true}'::jsonb,
     '{"uk": 25.00, "europe": 50.00, "usa": 75.00, "row": 90.00}'::jsonb,
     false),
     
    ('Guitar Amp Head', 'Amp head shipping package (70x45x45 cm, 27kg)', 'amp_head', 27.0,
     '{"length": 70.0, "width": 45.0, "height": 45.0, "unit": "cm"}'::jsonb,
     '["dhl", "fedex"]'::jsonb,
     '{"require_signature": true, "insurance": true, "fragile": true}'::jsonb,
     '{"uk": 35.00, "europe": 65.00, "usa": 95.00, "row": 120.00}'::jsonb,
     false),
     
    ('4x12 Cabinet', 'Speaker cabinet (79x79x45 cm, 44kg)', 'amp_cab', 44.0,
     '{"length": 79.0, "width": 79.0, "height": 45.0, "unit": "cm"}'::jsonb,
     '["dhl"]'::jsonb,
     '{"require_signature": true, "insurance": true, "fragile": true}'::jsonb,
     '{"uk": 45.00, "europe": 85.00, "usa": 120.00, "row": 150.00}'::jsonb,
     false),
     
    ('Effects Pedal', 'Small effects pedal box (30x30x15 cm, 1kg)', 'pedal_small', 1.0,
     '{"length": 30.0, "width": 30.0, "height": 15.0, "unit": "cm"}'::jsonb,
     '["dhl", "fedex", "tnt"]'::jsonb,
     '{"require_signature": false, "insurance": true, "fragile": true}'::jsonb,
     '{"uk": 10.00, "europe": 15.00, "usa": 20.00, "row": 25.00}'::jsonb,
     false),
     
    ('2x12 Combo', '2x12 combo amp (79x68x45 cm, 35kg)', 'amp_combo', 35.0,
     '{"length": 79.0, "width": 68.0, "height": 45.0, "unit": "cm"}'::jsonb,
     '["dhl"]'::jsonb,
     '{"require_signature": true, "insurance": true, "fragile": true}'::jsonb,
     '{"uk": 40.00, "europe": 75.00, "usa": 110.00, "row": 140.00}'::jsonb,
     false),
     
    ('Badges', 'Small item package (30x6x6 cm, 1kg)', 'small_box', 1.0,
     '{"length": 30.0, "width": 6.0, "height": 6.0, "unit": "cm"}'::jsonb,
     '["dhl", "fedex", "tnt"]'::jsonb,
     '{"require_signature": false, "insurance": false, "fragile": false}'::jsonb,
     '{"uk": 5.00, "europe": 10.00, "usa": 15.00, "row": 20.00}'::jsonb,
     false),
     
    ('Printed Material', 'Flat package (30x30x1 cm, 0.5kg)', 'envelope', 0.5,
     '{"length": 30.0, "width": 30.0, "height": 1.0, "unit": "cm"}'::jsonb,
     '["dhl", "fedex", "tnt"]'::jsonb,
     '{"require_signature": false, "insurance": false, "fragile": false}'::jsonb,
     '{"uk": 3.00, "europe": 8.00, "usa": 12.00, "row": 15.00}'::jsonb,
     false),
     
    ('Amp Panel', 'Long thin package (68x6x6 cm, 1kg)', 'custom', 1.0,
     '{"length": 68.0, "width": 6.0, "height": 6.0, "unit": "cm"}'::jsonb,
     '["dhl"]'::jsonb,
     '{"require_signature": false, "insurance": true, "fragile": true}'::jsonb,
     '{"uk": 12.00, "europe": 20.00, "usa": 30.00, "row": 40.00}'::jsonb,
     false)
ON CONFLICT (name) DO UPDATE
SET description = EXCLUDED.description,
    package_type = EXCLUDED.package_type,
    weight = EXCLUDED.weight,
    dimensions = EXCLUDED.dimensions,
    carriers = EXCLUDED.carriers,
    options = EXCLUDED.options,
    rates = EXCLUDED.rates,
    updated_at = CURRENT_TIMESTAMP;