-- Find products where different platforms show different statuses
WITH platform_statuses AS (
    SELECT 
        p.id as product_id,
        p.sku,
        p.title,
        -- Get status from each platform's listing table
        COALESCE(rl.reverb_state, 'not_listed') as reverb_status,
        COALESCE(el.listing_status, 'not_listed') as ebay_status, 
        COALESCE(sl.status, 'not_listed') as shopify_status,
        COALESCE(vl.vr_state, 'not_listed') as vr_status
    FROM products p
    LEFT JOIN platform_common pc_reverb ON p.id = pc_reverb.product_id AND pc_reverb.platform_name = 'reverb'
    LEFT JOIN reverb_listings rl ON pc_reverb.id = rl.platform_id
    LEFT JOIN platform_common pc_ebay ON p.id = pc_ebay.product_id AND pc_ebay.platform_name = 'ebay'  
    LEFT JOIN ebay_listings el ON pc_ebay.id = el.platform_id
    LEFT JOIN platform_common pc_shopify ON p.id = pc_shopify.product_id AND pc_shopify.platform_name = 'shopify'
    LEFT JOIN shopify_listings sl ON pc_shopify.id = sl.platform_id
    LEFT JOIN platform_common pc_vr ON p.id = pc_vr.product_id AND pc_vr.platform_name = 'vr'
    LEFT JOIN vr_listings vl ON pc_vr.id = vl.platform_id
)
SELECT *
FROM platform_statuses
WHERE (
    -- Look for inconsistencies where one platform shows sold/ended but others show active
    (reverb_status IN ('sold', 'ended') AND ebay_status = 'active') OR
    (reverb_status IN ('sold', 'ended') AND shopify_status = 'ACTIVE') OR
    (reverb_status IN ('sold', 'ended') AND vr_status = 'active') OR
    (ebay_status IN ('sold', 'unsold') AND reverb_status = 'live') OR
    (ebay_status IN ('sold', 'unsold') AND shopify_status = 'ACTIVE') OR
    (ebay_status IN ('sold', 'unsold') AND vr_status = 'active')
    -- Add more combinations as needed
);