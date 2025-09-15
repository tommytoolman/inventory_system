-- Compare SQLAlchemy Models with Actual Database Schema
-- This query shows all tables and their columns in the database

-- Get all tables and columns
SELECT 
    t.table_name,
    t.table_type,
    array_agg(
        c.column_name || ' (' || 
        c.data_type || 
        CASE 
            WHEN c.character_maximum_length IS NOT NULL 
            THEN '(' || c.character_maximum_length || ')' 
            ELSE '' 
        END ||
        CASE 
            WHEN c.is_nullable = 'NO' THEN ' NOT NULL' 
            ELSE '' 
        END ||
        ')' ORDER BY c.ordinal_position
    ) AS columns
FROM information_schema.tables t
LEFT JOIN information_schema.columns c 
    ON t.table_name = c.table_name 
    AND t.table_schema = c.table_schema
WHERE t.table_schema = 'public' 
    AND t.table_type IN ('BASE TABLE')
    AND t.table_name NOT LIKE 'alembic%'
GROUP BY t.table_name, t.table_type
ORDER BY t.table_name;

-- Key tables to check:
-- products, platform_common, reverb_listings, ebay_listings, 
-- shopify_listings, vr_listings, sync_events