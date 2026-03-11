-- Get the column names and check for NULL values
SELECT 
    column_name,
    data_type,
    is_nullable
FROM information_schema.columns 
WHERE table_name = 'shopify_listings' 
ORDER BY ordinal_position;
