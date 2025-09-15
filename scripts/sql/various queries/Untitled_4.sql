-- Clean up in proper order due to foreign keys

-- 1. Delete shopify_listings first
DELETE FROM shopify_listings;

-- 2. Delete platform_common records for shopify
DELETE FROM platform_common WHERE platform_name = 'shopify';

-- 3. Delete products that no longer have any platform records
DELETE FROM products 
WHERE id NOT IN (
    SELECT DISTINCT product_id 
    FROM platform_common 
    WHERE product_id IS NOT NULL
);