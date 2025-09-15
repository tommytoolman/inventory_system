-- SELECT 
--     platform_name, 
--     external_id, 
--     listing_url, 
--     sync_status 
-- FROM platform_common 
-- WHERE platform_name = 'vr' 
-- ORDER BY created_at DESC 
-- LIMIT 5;

        SELECT 
            p.id as product_id,
            p.sku,
            p.brand,
            p.model,
            
            p.base_price,
            p.primary_image,
            p.additional_images,
            p.category,
            p.condition,
            p.year,
            p.finish,
            r.reverb_state,
            r.reverb_listing_id,
            r.updated_at as reverb_updated,
            pc_r.external_id as reverb_external_id,
			p.description
        FROM products p
        JOIN platform_common pc_r ON p.id = pc_r.product_id AND pc_r.platform_name = 'reverb'
        JOIN reverb_listings r ON pc_r.id = r.platform_id
        LEFT JOIN platform_common pc_s ON p.id = pc_s.product_id AND pc_s.platform_name = 'shopify'
        WHERE pc_s.id IS NULL AND reverb_state = 'live' -- No existing Shopify listing
