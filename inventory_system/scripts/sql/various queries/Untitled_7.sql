SELECT pc.id as platform_common_id, rl.list_price as price
            FROM platform_common pc
            JOIN reverb_listings rl ON CONCAT('REV-', pc.external_id) = rl.reverb_listing_id
            WHERE pc.platform_name = 'reverb'