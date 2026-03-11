# SQL Reference Guide

## Table Management

### Drop and Recreate Tables
```sql
-- Example: Recreate platform_category_mappings
DROP TABLE IF EXISTS platform_category_mappings CASCADE;
CREATE TABLE platform_category_mappings (
    id SERIAL PRIMARY KEY,
    source_platform VARCHAR(50),
    source_category_id VARCHAR(100),
    source_category_name TEXT,
    target_platform VARCHAR(50),
    target_category_id VARCHAR(100),
    target_category_name TEXT,
    item_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);
```

### Check Table Structure
```sql
-- View all columns in a table
SELECT 
    column_name, 
    data_type, 
    character_maximum_length,
    is_nullable,
    column_default
FROM information_schema.columns 
WHERE table_name = 'platform_category_mappings'
ORDER BY ordinal_position;
```

## Data Queries

### Sync Events Analysis
```sql
-- View pending new_listing events
SELECT 
    platform_name,
    status,
    COUNT(*) as count,
    MIN(detected_at) as earliest,
    MAX(detected_at) as latest
FROM sync_events 
WHERE change_type = 'new_listing'
GROUP BY platform_name, status
ORDER BY platform_name, status;

-- Find specific product's sync events
SELECT * FROM sync_events 
WHERE change_data->>'sku' = 'REV-12345'
ORDER BY detected_at DESC;
```

### Product Status Overview
```sql
-- Count products by status across platforms
SELECT 
    p.status,
    COUNT(DISTINCT p.id) as product_count,
    COUNT(DISTINCT pc.id) as listing_count
FROM products p
LEFT JOIN platform_common pc ON p.id = pc.product_id
GROUP BY p.status
ORDER BY product_count DESC;

-- Find products with different statuses across platforms
SELECT 
    p.sku,
    p.status as product_status,
    pc.platform_name,
    pc.status as platform_status
FROM products p
JOIN platform_common pc ON p.id = pc.product_id
WHERE p.status != pc.status
ORDER BY p.sku, pc.platform_name;
```

### Platform-Specific Queries

#### Reverb
```sql
-- Find Reverb listings without local products
SELECT 
    rl.reverb_id,
    rl.reverb_sku,
    rl.title,
    rl.reverb_state
FROM reverb_listings rl
LEFT JOIN products p ON p.sku = 'REV-' || rl.reverb_id
WHERE p.id IS NULL
AND rl.reverb_state = 'live';
```

#### eBay
```sql
-- Check eBay category usage
SELECT 
    target_category_id,
    target_category_name,
    COUNT(*) as usage_count
FROM platform_category_mappings
WHERE target_platform = 'ebay'
GROUP BY target_category_id, target_category_name
ORDER BY usage_count DESC
LIMIT 20;
```

#### Shopify
```sql
-- Find Shopify products by status
SELECT 
    COUNT(*) as count,
    status
FROM shopify_listings
GROUP BY status;
```

## Maintenance Queries

### Database Size
```sql
-- Check table sizes
SELECT 
    schemaname,
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;
```

### Clean Up Old Data
```sql
-- Archive processed sync_events older than 30 days
DELETE FROM sync_events 
WHERE status = 'processed' 
AND processed_at < NOW() - INTERVAL '30 days';

-- Find duplicate products by SKU
SELECT sku, COUNT(*) as count
FROM products
GROUP BY sku
HAVING COUNT(*) > 1;
```

## Useful Joins

### Product with All Platform Data
```sql
SELECT 
    p.id,
    p.sku,
    p.brand,
    p.model,
    p.status,
    pc.platform_name,
    pc.external_id,
    pc.status as platform_status,
    pc.last_synced_at
FROM products p
LEFT JOIN platform_common pc ON p.id = pc.product_id
WHERE p.sku = 'REV-12345'
ORDER BY pc.platform_name;
```

### Full Product Details with Platform-Specific Data
```sql
-- Get complete product info including Reverb details
SELECT 
    p.*,
    rl.reverb_state,
    rl.price as reverb_price,
    rl.inventory_quantity,
    sl.shopify_status,
    sl.shopify_product_id,
    el.ebay_item_id,
    el.ebay_listing_status
FROM products p
LEFT JOIN reverb_listings rl ON rl.reverb_sku = REPLACE(p.sku, 'REV-', '')
LEFT JOIN shopify_listings sl ON sl.sku = p.sku
LEFT JOIN ebay_listings el ON el.sku = p.sku
WHERE p.id = 123;
```

## Index Management

### Create Indexes for Performance
```sql
-- Common indexes for better query performance
CREATE INDEX idx_products_sku ON products(sku);
CREATE INDEX idx_products_status ON products(status);
CREATE INDEX idx_sync_events_status ON sync_events(status, change_type);
CREATE INDEX idx_platform_common_product ON platform_common(product_id, platform_name);
```

### Check Existing Indexes
```sql
SELECT 
    schemaname,
    tablename,
    indexname,
    indexdef
FROM pg_indexes
WHERE schemaname = 'public'
ORDER BY tablename, indexname;
```

## Backup Commands (Run from terminal)

```bash
# Backup entire database
pg_dump -U inventory_user -d inventory > backup_$(date +%Y%m%d).sql

# Backup specific table
pg_dump -U inventory_user -d inventory -t platform_category_mappings > mappings_backup.sql

# Restore from backup
psql -U inventory_user -d inventory < backup_20250902.sql
```

---
*Last updated: 2025-09-02*