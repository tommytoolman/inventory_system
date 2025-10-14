# Sync Process Context - 2025-09-04

## Current Task
Processing sync event 12259 - a Reverb "rogue listing" that needs to be imported and propagated to Shopify and VR.

## Key Fixes Applied Today

### 2025-10-12 – Reverb listing publication
- Files: `app/services/reverb_service.py`, `app/routes/inventory.py`
- Behavior: `create_listing_from_product` now publishes new Reverb listings immediately, polls until `state.slug == "live"`, and records `shipping_profile_id`, slug, pricing, and stats back into `reverb_listings`/`platform_common`.
- Form mapping: `/inventory/add` converts local `shipping_profiles.id` into the Reverb `reverb_profile_id` before calling the service.
- Notes: Service response includes `publish_errors` if Reverb delays publication; callers should surface these warnings.

### 1. Fixed eBay Category Parsing (`app/services/ebay/trading.py`)
- Issue: `'list' object has no attribute 'get'` error
- Cause: eBay API sometimes returns Category as a list instead of dict
- Fixed: Lines 964-1000, now handles both list and dict responses

### 2. Fixed Schema Mismatches in `scripts/process_sync_event.py`

#### Product Creation (lines 134-165):
- ❌ REMOVED non-existent fields:
  - `price_current` (changed to `base_price` and `price`)
  - `is_vintage` 
  - `is_sold_individually`
  - `media_urls`
- ✅ ADDED proper fields:
  - `primary_image` - extracted from Reverb photos[0]
  - `additional_images` - extracted from Reverb photos[1:]
  - `base_price` and `price` - from Reverb price.amount
- ✅ Fixed: Price must be float, not string (line 149-151)
- ✅ Fixed: ProductCondition.VERYGOOD not VERY_GOOD (line 127)

#### PlatformCommon Creation:
- Fixed ALL occurrences:
  - `last_sync_at` → `last_sync` 
  - `raw_data` → `platform_specific_data`
- Applied to Reverb (line 189), eBay (line 310), VR (line 448)
- Note: Shopify was already correct!
- ✅ Added listing_url for Reverb (line 182)

### 3. Outstanding Issues
- ❌ json.dumps error at line 474 - needs fixing
- ❌ VR doesn't return ID immediately - can't set listing_url
- ❌ Images not being saved to products table (missing preview icons)

## Database Schema Reference
Created `/docs/DATABASE_SCHEMA_REFERENCE.md` with exact column names for:
- products (40 columns)
- platform_common (11 columns) 
- reverb_listings (23 columns)
- ebay_listings (32 columns)
- shopify_listings (22 columns)
- vr_listings (15 columns)

## Current Test Status - Event 12259

### What Was Created (First Run - VR only):
- ✅ **products** - ID: 490, SKU: REV-91978760 (but images NOT saved!)
- ✅ **platform_common (reverb)** - ID: 2186, listing_url fixed manually
- ✅ **reverb_listings** - ID: 457
- ✅ **VR listing on website** - Created successfully
- ❌ **platform_common (vr)** - Deleted manually (was ID: 2187)
- ❌ **vr_listings** - Never created
- ❌ **Shopify** - Not attempted yet

### Database Cleanup Commands:
```sql
-- Reset sync event to pending
UPDATE sync_events SET status = 'pending', notes = '{"retry_count": 0}' WHERE id = 12259;

-- Delete VR platform_common (if VR listing deleted)
DELETE FROM platform_common 
WHERE platform_name = 'vr' 
AND product_id = (SELECT id FROM products WHERE sku = 'REV-91978760');

-- Fix missing Reverb URL
UPDATE platform_common 
SET listing_url = 'https://reverb.com/item/' || external_id
WHERE platform_name = 'reverb' AND listing_url IS NULL;

-- Check current state
SELECT pc.platform_name, pc.external_id, pc.listing_url 
FROM platform_common pc 
JOIN products p ON pc.product_id = p.id 
WHERE p.sku = 'REV-91978760';
```

## Commands to Run

### Test Resume Capability (Shopify + VR):
```bash
# Process event 12259 for Shopify and VR (will find existing product/reverb)
python scripts/process_sync_event.py --event-id 12259 --platforms shopify vr --retry-errors

# With VR visible for debugging
python scripts/process_sync_event.py --event-id 12259 --platforms shopify vr --vr-no-headless --retry-errors
```

## Verification Queries
```sql
-- Full status check
SELECT 
    'Product' as type, p.id, p.sku, p.brand, p.model,
    CASE WHEN p.primary_image IS NOT NULL THEN '✅' ELSE '❌' END as has_images
FROM products p WHERE p.sku = 'REV-91978760'
UNION ALL
SELECT 
    'Platform: ' || pc.platform_name, pc.id, pc.external_id, '', '',
    CASE WHEN pc.listing_url IS NOT NULL THEN '✅' ELSE '❌' END
FROM platform_common pc
JOIN products p ON pc.product_id = p.id
WHERE p.sku = 'REV-91978760'
UNION ALL
SELECT 'Reverb Listing', rl.id::text, rl.reverb_listing_id, '', '', '✅'
FROM reverb_listings rl WHERE rl.reverb_listing_id = '91978760'
UNION ALL
SELECT 'Shopify Listing', sl.id::text, sl.shopify_product_id, '', '', '✅'
FROM shopify_listings sl
JOIN platform_common pc ON sl.platform_id = pc.id
WHERE pc.product_id = (SELECT id FROM products WHERE sku = 'REV-91978760');
```

## Architecture Notes
- Sync is PULL-first: Detect changes on platforms → Reconcile locally → Push to others
- Platform truth: Sales/status changes trust platform, price anomalies trust central system
- Currently in hybrid sandbox/production testing phase
- Resume capability: Script can find existing records and continue where it left off

## Files Modified Today
1. `/app/services/ebay/trading.py` - Fixed category parsing
2. `/scripts/process_sync_event.py` - Fixed schema mismatches, added Reverb URL
3. `/docs/DATABASE_SCHEMA_REFERENCE.md` - Created schema reference
4. `/TODO.md` - Updated with completed tasks
5. `/docs/sync_process_context_2025-09-04.md` - This file (session backup)

## Latest Updates (Post-restart)

### Fixed json.dumps Issue (lines 477-488)
- Problem: `reverb_listing.id` referenced but variable not always defined
- Solution: Check if `reverb_listing` exists before accessing its id
- Changed to build notes_data dict first, conditionally add reverb_listing_id

### Successful Test Run - Event 12259 Complete
- ✅ **Shopify**: Created successfully (ID: 12234361438548)  
- ✅ **VR**: Created successfully
- ✅ **Product**: ID 490, SKU: REV-91978760
- ❌ **eBay**: Failed as expected (shipping configuration issue)

### Quick SQL Status Check
```sql
-- Shorter query to show all info
SELECT 
    'Product' as type, p.id, p.sku, p.brand || ' ' || p.model as name,
    CASE WHEN p.primary_image IS NOT NULL THEN '✅' ELSE '❌' END as images
FROM products p WHERE p.sku = 'REV-91978760'
UNION ALL
SELECT 
    'Platform: ' || pc.platform_name, pc.id, pc.external_id, 
    SUBSTRING(pc.listing_url, 1, 50) as url, pc.sync_status
FROM platform_common pc
JOIN products p ON pc.product_id = p.id
WHERE p.sku = 'REV-91978760'
ORDER BY type;
```

## Known Issues to Address
1. **Images still not saving to products table** - primary_image and additional_images remain NULL despite being extracted
2. **VR listing_url missing** - VR doesn't return ID immediately after creation
3. **vr_listings table entry missing** - Platform common created but not the platform-specific record
4. **User mentioned "some issues"** - To be explained after restart

## Next Steps After VSCode Restart
1. Investigate why images aren't persisting to database
2. Debug vr_listings table population issue
3. Address the unspecified issues user mentioned
4. Test with a completely fresh event (not 12259) to verify full flow
5. Implement VR ID resolution for listing_url

---
*Context updated at 15:45 UTC - Ready for VSCode restart if needed*
