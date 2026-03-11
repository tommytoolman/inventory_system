# Database Schema Reference
*Generated: 2025-09-04*

This is the authoritative source for all column names in our 6 core tables.

## 1. products (40 columns)
**Key Fields:**
- `id` (integer, PK, NOT NULL)
- `sku` (varchar, UNIQUE)
- `brand` (varchar)
- `model` (varchar)
- `status` (USER-DEFINED enum)
- `condition` (USER-DEFINED enum, NOT NULL)
- `is_stocked_item` (boolean, NOT NULL, default: false)
- `quantity` (integer, nullable)

**Price Fields:**
- `base_price` (float)
- `cost_price` (float)
- `price` (float)
- `price_notax` (float)
- `collective_discount` (float)
- `offer_discount` (float)

**Descriptive Fields:**
- `title` (varchar)
- `description` (varchar)
- `year` (integer)
- `decade` (integer)
- `finish` (varchar)
- `category` (varchar)

**Media Fields:**
- `primary_image` (varchar)
- `additional_images` (jsonb)
- `video_url` (varchar)
- `external_link` (varchar)

**Flags:**
- `is_sold` (boolean)
- `in_collective` (boolean)
- `in_inventory` (boolean)
- `in_reseller` (boolean)
- `free_shipping` (boolean)
- `buy_now` (boolean)
- `show_vat` (boolean)
- `local_pickup` (boolean)
- `available_for_shipment` (boolean)

**Shipping Fields:**
- `shipping_profile_id` (integer)
- `package_type` (varchar(50))
- `package_weight` (float)
- `package_dimensions` (jsonb)
- `processing_time` (integer)

**Timestamps:**
- `created_at` (timestamp, NOT NULL)
- `updated_at` (timestamp, NOT NULL)

## 2. platform_common (11 columns)
**Bridge table linking products to platform-specific tables**

- `id` (integer, PK, NOT NULL)
- `product_id` (integer, FK to products)
- `platform_name` (varchar) - 'ebay', 'reverb', 'shopify', 'vr'
- `external_id` (varchar) - The platform's ID for this listing
- `status` (varchar) - Platform listing status
- `sync_status` (varchar) - Sync state
- `last_sync` (timestamp)
- `listing_url` (varchar)
- `platform_specific_data` (jsonb)
- `created_at` (timestamp, NOT NULL)
- `updated_at` (timestamp, NOT NULL)

## 3. reverb_listings (23 columns)
- `id` (integer, PK, NOT NULL)
- `platform_id` (integer, FK to platform_common)
- `reverb_listing_id` (varchar) - Reverb's ID
- `reverb_slug` (varchar)
- `reverb_category_uuid` (varchar)
- `condition_rating` (float)
- `inventory_quantity` (integer)
- `has_inventory` (boolean)
- `offers_enabled` (boolean)
- `is_auction` (boolean)
- `list_price` (float)
- `listing_currency` (varchar)
- `shipping_profile_id` (varchar)
- `shop_policies_id` (varchar)
- `reverb_state` (varchar)
- `view_count` (integer)
- `watch_count` (integer)
- `handmade` (boolean)
- `reverb_created_at` (timestamp)
- `reverb_published_at` (timestamp)
- `created_at` (timestamp, NOT NULL)
- `updated_at` (timestamp, NOT NULL)
- `last_synced_at` (timestamp)
- `extended_attributes` (jsonb)

## 4. ebay_listings (32 columns)
- `id` (integer, PK, NOT NULL)
- `platform_id` (integer, FK to platform_common)
- `ebay_item_id` (varchar) - eBay's ItemID
- `listing_status` (varchar)
- `title` (varchar)
- `format` (varchar) - AUCTION, BUY_IT_NOW
- `price` (float)
- `quantity` (integer)
- `quantity_available` (integer)
- `quantity_sold` (integer)
- `ebay_category_id` (varchar)
- `ebay_category_name` (varchar)
- `ebay_second_category_id` (varchar)
- `start_time` (timestamp)
- `end_time` (timestamp)
- `listing_url` (varchar)
- `ebay_condition_id` (varchar)
- `condition_display_name` (varchar)
- `gallery_url` (varchar)
- `picture_urls` (jsonb)
- `item_specifics` (jsonb)
- `payment_policy_id` (varchar)
- `return_policy_id` (varchar)
- `shipping_policy_id` (varchar)
- `transaction_id` (varchar)
- `order_line_item_id` (varchar)
- `buyer_user_id` (varchar)
- `paid_time` (timestamp)
- `payment_status` (varchar)
- `shipping_status` (varchar)
- `created_at` (timestamp, NOT NULL)
- `updated_at` (timestamp, NOT NULL)
- `last_synced_at` (timestamp, NOT NULL)
- `listing_data` (jsonb)

## 5. shopify_listings (22 columns)
**NOTE: Uses sequence 'website_listings_id_seq' (legacy name)**

- `id` (integer, PK, NOT NULL)
- `platform_id` (integer, FK to platform_common)
- `shopify_product_id` (varchar(50)) - GID format
- `shopify_legacy_id` (varchar(20)) - Numeric ID
- `handle` (varchar(255))
- `title` (varchar(255))
- `vendor` (varchar(255))
- `status` (varchar(20)) - ACTIVE, DRAFT, ARCHIVED
- `price` (float)
- `category_gid` (varchar(100))
- `category_name` (varchar(255))
- `category_full_name` (varchar(500))
- `category_assigned_at` (timestamp)
- `category_assignment_status` (varchar(20)) - PENDING, ASSIGNED, FAILED
- `seo_title` (varchar)
- `seo_description` (varchar)
- `seo_keywords` (jsonb)
- `featured` (boolean)
- `custom_layout` (varchar)
- `created_at` (timestamp, NOT NULL)
- `updated_at` (timestamp, NOT NULL)
- `last_synced_at` (timestamp)
- `extended_attributes` (jsonb)

## 6. vr_listings (15 columns)
- `id` (integer, PK, NOT NULL)
- `platform_id` (integer, FK to platform_common)
- `vr_listing_id` (varchar)
- `vr_state` (varchar)
- `inventory_quantity` (integer)
- `in_collective` (boolean)
- `in_inventory` (boolean)
- `in_reseller` (boolean)
- `collective_discount` (float)
- `price_notax` (float)
- `show_vat` (boolean)
- `processing_time` (integer)
- `created_at` (timestamp, NOT NULL)
- `updated_at` (timestamp, NOT NULL)
- `last_synced_at` (timestamp)
- `extended_attributes` (jsonb)

## Key Relationships

```
products (1) → (N) platform_common
                    ↓
    platform_common.id = platform_id (FK)
                    ↓
    (1) reverb_listings  OR
    (1) ebay_listings    OR
    (1) shopify_listings OR
    (1) vr_listings
```

## Important Notes

1. **platform_common** is the bridge - ALWAYS has `product_id` and `external_id`
2. **external_id** in platform_common = The platform's ID (reverb_listing_id, ebay_item_id, etc.)
3. All platform-specific tables link via `platform_id` → `platform_common.id`
4. **shopify_listings** uses legacy sequence name 'website_listings_id_seq'
5. **products.sku** is UNIQUE - critical for RIFF- vs REV- prefixes
6. **products.is_stocked_item** + **quantity** for multi-quantity items

## Common Query Patterns

### Find all Shopify listings without shopify_product_id:
```sql
SELECT pc.*, sl.*
FROM platform_common pc
LEFT JOIN shopify_listings sl ON pc.id = sl.platform_id
WHERE pc.platform_name = 'shopify'
AND sl.shopify_product_id IS NULL;
```

### Find products with platform mismatches:
```sql
SELECT p.sku, p.status as product_status, 
       pc.platform_name, pc.status as platform_status
FROM products p
JOIN platform_common pc ON p.id = pc.product_id
WHERE p.status != pc.status;
```