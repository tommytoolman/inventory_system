-- -- Check if product_merges has ANY data
SELECT COUNT(*) as total_merges FROM product_merges;

-- -- Check if Reverb/Shopify products exist but aren't in merges
-- SELECT 
--     pc.platform_name,
--     COUNT(*) as total_products,
--     COUNT(pm.product_id) as in_merges
-- FROM products p
-- JOIN platform_common pc ON p.id = pc.product_id
-- LEFT JOIN product_merges pm ON p.id = pm.product_id
-- WHERE pc.platform_name IN ('reverb', 'shopify')
-- GROUP BY pc.platform_name;