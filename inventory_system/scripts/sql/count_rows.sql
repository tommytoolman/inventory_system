\echo '\n=== Table Row Counts ===\n'
\pset format wrapped
\pset border 2
\pset columns 2000

SELECT 'ebay_listings' AS table_name, COUNT(*) AS row_count FROM ebay_listings
UNION ALL
SELECT 'reverb_listings' AS table_name, COUNT(*) AS row_count FROM reverb_listings
UNION ALL
SELECT 'vr_listings' AS table_name, COUNT(*) AS row_count FROM vr_listings
UNION ALL
SELECT 'product_merges' AS table_name, COUNT(*) AS row_count FROM product_merges
UNION ALL
SELECT 'platform_common' AS table_name, COUNT(*) AS row_count FROM platform_common
UNION ALL
SELECT 'products' AS table_name, COUNT(*) AS row_count FROM products
ORDER BY table_name;