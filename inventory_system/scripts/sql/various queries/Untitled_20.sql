-- Check what products are being counted multiple times
WITH platform_totals AS (
    SELECT pc.platform_name, COUNT(*) as total_products
    FROM products p
    JOIN platform_common pc ON p.id = pc.product_id
    GROUP BY pc.platform_name
),
multi_platform AS (
    SELECT pc.platform_name, COUNT(DISTINCT p.id) as multi_count
    FROM products p
    JOIN platform_common pc ON p.id = pc.product_id
    WHERE p.id IN (
        SELECT product_id 
        FROM platform_common 
        GROUP BY product_id 
        HAVING COUNT(DISTINCT platform_name) > 1
    )
    GROUP BY pc.platform_name
),
manual_matched AS (
    SELECT pc.platform_name, COUNT(DISTINCT p.id) as manual_count
    FROM products p
    JOIN platform_common pc ON p.id = pc.product_id
    WHERE p.id IN (
        SELECT DISTINCT kept_product_id FROM product_merges WHERE merged_at IS NOT NULL
        UNION
        SELECT DISTINCT merged_product_id FROM product_merges WHERE merged_at IS NOT NULL
    )
    GROUP BY pc.platform_name
)
SELECT 
    pt.platform_name,
    pt.total_products,
    COALESCE(mp.multi_count, 0) as multi_platform_count,
    COALESCE(mm.manual_count, 0) as manual_match_count
FROM platform_totals pt
LEFT JOIN multi_platform mp ON pt.platform_name = mp.platform_name  
LEFT JOIN manual_matched mm ON pt.platform_name = mm.platform_name
ORDER BY pt.platform_name;