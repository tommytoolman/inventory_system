-- SELECT pg_get_viewdef('product_status_summary', true);

	CREATE OR REPLACE VIEW product_status_summary AS
	SELECT 
    -- Products table counts
    (SELECT COUNT(*) FROM products WHERE status = 'ACTIVE') as products_active,
    (SELECT COUNT(*) FROM products WHERE status = 'SOLD') as products_sold,
	(SELECT COUNT(*) FROM products WHERE status = 'DRAFT') AS products_draft,
    (SELECT COUNT(*) FROM products WHERE status = 'ARCHIVED') as products_archived,
    (SELECT COUNT(*) FROM products) as products_total,
    
    -- Reverb counts
    (SELECT COUNT(DISTINCT pc.product_id) 
     FROM platform_common pc 
     WHERE pc.platform_name = 'reverb' AND pc.status IN ('ACTIVE', 'active')) as reverb_platform_common_active,
    (SELECT COUNT(*) 
     FROM reverb_listings rl 
     WHERE rl.reverb_state IN ('live', 'active', 'ACTIVE', 'LIVE')) as reverb_listings_live,
    
    -- eBay counts
    (SELECT COUNT(DISTINCT pc.product_id) 
     FROM platform_common pc 
     WHERE pc.platform_name = 'ebay' AND pc.status IN ('ACTIVE', 'active')) as ebay_platform_common_active,
    (SELECT COUNT(*) 
	 FROM ebay_listings el
	 WHERE el.listing_status IN ('ACTIVE', 'active')) as ebay_listings_live,
    
    -- Shopify counts
    (SELECT COUNT(DISTINCT pc.product_id) 
     FROM platform_common pc 
     WHERE pc.platform_name = 'shopify' AND pc.status IN ('ACTIVE', 'active')) as shopify_platform_common_active,
    (SELECT COUNT(*) FROM shopify_listings WHERE status = 'ACTIVE') as shopify_listings_active,
    
    -- VR counts
    (SELECT COUNT(DISTINCT pc.product_id) 
     FROM platform_common pc 
     WHERE pc.platform_name = 'vr' AND pc.status IN ('ACTIVE', 'active')) as vr_platform_common_active,
    (SELECT COUNT(*) FROM vr_listings) as vr_listings_total;
