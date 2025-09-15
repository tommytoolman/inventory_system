# Project TODO - Inventory Management System

## ✅ Completed Tasks

### Architecture & Cleanup
- [x] Deprecate integration abstraction layer
- [x] Move `app/integrations_old` to `old/` directory
- [x] Remove StockManager references from webhook_processor.py
- [x] Extract StockUpdateEvent to `app/core/events.py`
- [x] Update test files to remove integration layer references
- [x] Delete obsolete integration test files
- [x] Verify system still works after cleanup

### VR Service Fixes (2025-09-05)
- [x] Add timeout configuration (180s) to VR inventory download
- [x] Add Selenium browser cleanup method
- [x] Add pre-operation temp file cleanup
- [x] Fix DataFrame comparison error (check type before comparing to string)
- [x] Fix VR reconciliation column name mismatches (spaces vs underscores)
- [x] Fix missing extended_attributes and last_synced_at in reconciliation
- [x] Fix price_notax field - use `product_price` from CSV (not `product_price_notax` which doesn't exist)
- [x] Create one-off script to fix missing vr_listings entries

### UI Improvements (2025-09-06)
- [x] Add consistent status color scheme across list and detail pages (Sold=red, Draft=yellow, Archived=purple, Active=green)
- [x] Apply title case to brand names in templates
- [x] Apply title case to status displays
- [x] Add configurable dropdown sorting (categories by count, brands alphabetical)
- [x] Document dropdown configuration in README

## 🔴 Critical Issues (Priority 1)

### eBay Service Issues
- [ ] **Fix eBay category parsing error** - `'list' object has no attribute 'get'` in test_ebay_conditions.py
  - Quick win - should be easy fix in response parsing
  - Blocking: Ability to validate item conditions before listing

- [ ] **Consolidate eBay service implementations** 
  - Current state: 3 competing implementations
    - `importer.py`: Async + Raw SQL (used by `scripts/ebay/import_ebay.py`)
    - `inventory.py`: Sync + ORM (EbayInventorySync class)
    - `service.py`: Async + ORM (incomplete, has placeholder product_id=1)
  - Decision needed: Keep `importer.py` for import script, remove others?
  - Risk: Data consistency issues, race conditions

## 🟡 Important Issues (Priority 2)

### Testing & Verification
- [ ] Implement sync verification system for hybrid testing phase
- [ ] Create "To Do" list generation for manual verification
- [ ] Add conflict resolution for external listings detected
- [ ] Verify sync operations correctly update local DB

### Platform Implementations
- [ ] Complete V&R service missing methods
- [ ] Finish Shopify integration (uncomment sync triggers)
- [ ] Standardize platform-specific error handling
- [ ] Implement cross-platform sync after sales

### VR Service Technical Debt
- [ ] **Rename `price_notax` field** to `price` or `vr_price` in vr_listings table (confusing name)
- [ ] **Consolidate VR listing creation logic** - Currently duplicated in:
  - `scripts/process_sync_event.py` (reconciliation)
  - `app/services/vr_service.py` (import)
  - Should create shared method: `create_vr_listing_from_csv_row()`
- [ ] **Add VR listing URL resolution** - VR doesn't return ID immediately on creation
- [ ] **Improve VR reconciliation matching** - Currently uses brand/model/price, could be more robust

## 🔵 Nice to Have (Priority 3)

### Code Organization
- [ ] Remove empty files: `ebay/schemas.py`, `ebay/sync.py`, `ebay/__init__.py`
- [ ] Rename `ebay/service.py` → `ebay_repository.py`
- [ ] Move `ebay_data_analysis.py` to scripts/developer/
- [ ] Remove duplicate `EbayTradingAPIOld` class from `trading.py`

### Documentation
- [ ] Update API documentation
- [ ] Create user guides for each platform integration
- [ ] Document platform-specific behaviors
- [ ] Add example usage to all docstrings

### Frontend Improvements
- [ ] Add loading states/spinners for sync operations
- [ ] Implement progress indicators for bulk operations
- [ ] Create platform sync status dashboard
- [ ] Add real-time status updates

### Testing
- [ ] Rebuild integration tests after architecture change
- [ ] Add unit tests for platform services
- [ ] Create end-to-end tests for sync processes
- [ ] Test error handling paths

## Category Mapping Strategy

### Current State (Intermediate Solution)
We are currently using a static JSON file (`reverb_to_ebay_categories.json`) to store the category mappings.

**Advantages:**
- Decouples the mapping data from the application code.
- Can be updated without requiring a code deployment.
- Sufficient for the current, single-platform mapping requirement.

### Long-Term Goal (Database Solution)

The most robust and scalable long-term solution is to store these mappings in a dedicated database table.

**Rationale / Advantages:**
- **Easy Maintenance**: Mappings can be updated via a simple admin interface (or directly in the database) by non-developers without touching the application code.
- **Scalability**: The same table can easily be extended to handle mappings for all platforms (e.g., Reverb -> Shopify, Reverb -> V&R) by changing the `source_platform` and `target_platform` values.
- **Data Integrity**: The database can enforce rules, and the data becomes part of regular backups.
- **Centralization**: It creates a single, queryable source of truth for all services that need to perform category mapping.

### Proposed Database Schema

A new table, `category_mappings`, will be created with the following structure:

| Column | Type | Description |
| :--- | :--- | :--- |
| `id` | `INTEGER` | Primary Key |
| `source_platform` | `TEXT` | e.g., "reverb" |
| `source_category_id` | `TEXT` | e.g., The Reverb category UUID |
| `source_category_name`| `TEXT`| e.g., "Electric Guitars / Solid Body" |
| `target_platform` | `TEXT` | e.g., "ebay" |
| `target_category_id` | `TEXT` | e.g., The eBay numeric ID ("33034") |
| `target_category_name`| `TEXT`| e.g., "Musical Instruments & Gear / Guitars & Basses / Electric Guitars" |
| `notes` | `TEXT` | Optional notes about the mapping. |

### Action Items

- [ ] Create a new SQLAlchemy model for the `category_mappings` table.
- [ ] Write a database migration (using Alembic) to create the table in the database.
- [ ] Write a one-time seeding script to populate the new table from the `reverb_to_ebay_categories.json` file.
- [ ] Update the platform service methods (e.g., `EbayService._get_ebay_category_from_reverb_uuid`) to query this new table instead of reading from the JSON file.

## 📊 Current State Summary

### Working Well
- Clean architecture post-cleanup
- Comprehensive platform API clients (eBay REST + Trading, Reverb, V&R, Shopify)
- Good async/await patterns
- StockUpdateEvent system ready for cross-platform sync

### Needs Attention
- eBay service implementation chaos
- Missing production-ready sync verification
- Incomplete error handling and conflict resolution
- Testing infrastructure needs rebuild

## 🚀 Next Steps

1. **Fix eBay category parsing** - Should be quick, unblocks testing
2. **Decide on eBay service consolidation strategy** - Keep importer.py, refactor others?
3. **Implement sync verification** - Critical for production
4. **Complete platform gaps** - V&R and Shopify methods
5. **Database improvements** - Category mappings, indexes

## 📝 Notes

- Currently in hybrid sandbox/production testing phase
- eBay importer.py is actively used by import script
- Platform hierarchy for sales: First platform to sell wins
- Sync frequency target: 2x daily status checks

---
*Last Updated: 2025-09-04*