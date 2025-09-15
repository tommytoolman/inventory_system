-- Get category mapping data
-- SELECT 
--     reverb_category_uuid,
--     extended_attributes->'categories'->0->>'full_name' as category_name,
--     COUNT(*) as count
-- FROM reverb_listings 
-- WHERE extended_attributes->'categories' IS NOT NULL
-- GROUP BY reverb_category_uuid, extended_attributes->'categories'->0->>'full_name'
-- ORDER BY count DESC;

SELECT 
    reverb_listing_id,
    extended_attributes->'categories' as categories,
    extended_attributes->'categories'->0->>'uuid' as first_category_uuid,
    extended_attributes->'categories'->0->>'full_name' as first_category_name
FROM reverb_listings 
WHERE extended_attributes IS NOT NULL 
  AND extended_attributes->'categories' IS NOT NULL
ORDER BY id DESC 
LIMIT 5;