SELECT 
    CASE WHEN listing_status IS NULL THEN 'NULL' ELSE listing_status END as status,
    COUNT(*) as count
FROM ebay_listings 
GROUP BY listing_status 
ORDER BY count DESC;
