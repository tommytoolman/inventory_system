-- Delete products where SKU does NOT begin with 'REV-'
DELETE FROM products 
WHERE sku NOT LIKE 'REV-%' 
   OR sku IS NULL;

-- First, find product IDs that have Shopify platform_common records
DELETE FROM products 
WHERE id IN (
    SELECT DISTINCT product_id 
    FROM platform_common 
    WHERE platform_name = 'shopify'
);