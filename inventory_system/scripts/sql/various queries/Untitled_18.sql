-- SELECT 
--     CASE WHEN platform_name IS NULL THEN 'NULL' ELSE platform_name END as status,
--     COUNT(*) as count
-- FROM platform_common 
-- GROUP BY platform_name 
-- ORDER BY count DESC;

SELECT column_name, data_type 
FROM information_schema.columns 
WHERE table_name = 'reverb_listings' 
ORDER BY ordinal_position;