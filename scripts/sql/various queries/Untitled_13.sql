SELECT 
        CASE 
            WHEN LOWER(listing_status) = 'active' THEN 'active'
            WHEN LOWER(listing_status) IN ('sold', 'completed') THEN 'sold'
            WHEN LOWER(listing_status) = 'unsold' THEN 'unsold'
            WHEN LOWER(listing_status) IN ('ended', 'cancelled', 'suspended') THEN 'ended'
            WHEN LOWER(listing_status) IN ('draft', 'scheduled') THEN 'draft'
            ELSE 'other'
        END as status_category,
        COUNT(*) as count
    FROM ebay_listings 
    GROUP BY status_category	