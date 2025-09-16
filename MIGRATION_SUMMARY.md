# Migration Summary

## What We've Done

1. **Analyzed the database vs models discrepancy**
   - Found 26 tables in database vs 23 in models
   - Identified missing models for: csv_import_logs, platform_category_mappings, platform_policies, product_merges
   - Identified models without tables: users, webhook_events

2. **Created a squashed migration from the actual database**
   - Generated from existing database schema to ensure accuracy
   - Added users and webhook_events tables for future capabilities
   - Total tables in new migration: 27

## Tables Included in Squashed Migration

1. activity_log
2. category_mappings
3. csv_import_logs
4. ebay_category_mappings
5. ebay_listings
6. orders
7. platform_category_mappings
8. platform_common
9. platform_policies
10. platform_status_mappings
11. product_mappings
12. product_merges
13. products
14. reverb_categories
15. reverb_listings
16. sales
17. shipments
18. shipping_profiles
19. shopify_category_mappings
20. shopify_listings
21. sync_events
22. sync_stats
23. vr_accepted_brands
24. vr_category_mappings
25. vr_listings
26. users (new)
27. webhook_events (new)

## Next Steps for Railway Deployment

1. **Migration cleanup completed**: ✅
   - All old migrations are backed up in `alembic/versions_backup/` for reference
   - New squashed migration is at `alembic/versions/001_initial_schema.py`
   - The `versions` directory now contains only the clean initial schema

2. **Commit and push**:
   ```bash
   git add -A
   git commit -m "Replace all migrations with squashed initial migration"
   git push
   ```

3. **Run migration on Railway**:
   ```bash
   curl -X POST https://riff.up.railway.app/health/migrate
   ```

## Note on Missing Models

The following tables exist in the database but don't have corresponding models:
- csv_import_logs
- platform_category_mappings
- platform_policies
- product_merges

Consider creating models for these tables if they're actively used in the application.