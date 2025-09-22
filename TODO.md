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

### Dropbox Integration Improvements (2025-09-22)
- [x] Fix cache loading error ("too many values to unpack")
- [x] Implement folder structure persistence across server restarts
- [x] Add automatic token refresh and sharing between instances
- [x] Remove token file storage for security (only use env vars)
- [x] Add rate limit handling with exponential backoff
- [x] Auto-load Dropbox folders when Images & Media section opens
- [x] Style folders as square tiles (5 per row) for better UX
- [x] Create cache cleanup script for managing temporary links
- [x] Ensure cache directory is in .gitignore

## 🔴 Critical Issues (Priority 1)

### UI Integration Tasks
- [ ] **Implement ending item logic in UI**
  - Add end listing buttons/actions to product detail pages
  - Create bulk end listing functionality for multiple items
  - Show confirmation dialogs before ending
  - Update status displays after ending
  - Handle platform-specific ending requirements

- [ ] **Complete Add Product item creation flow**
  - Fix "Create Listing" button functionality
  - Implement payload generation and submission
  - Add loading states during creation
  - Show success/error messages
  - Navigate to product detail after creation
  - Handle multi-platform listing creation

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

## ~~OLD TODO CONTENT (Archived 2025-09-17)~~

<details>
<summary>Click to view archived content</summary>

~~The content above has been superseded by the consolidated TODO list below.~~

</details>

---

# CONSOLIDATED TODO LIST - CURRENT
*Last Updated: 2025-09-17*

## ✅ COMPLETED TASKS

### Architecture & Infrastructure
- [x] Set up basic FastAPI application
- [x] Configure PostgreSQL database
- [x] Create initial models
- [x] Deprecate integration abstraction layer
- [x] Move `app/integrations_old` to `old/` directory
- [x] Remove StockManager references from webhook_processor.py
- [x] Extract StockUpdateEvent to `app/core/events.py`
- [x] Update test files to remove integration layer references
- [x] Delete obsolete integration test files
- [x] Verify system still works after cleanup
- [x] Replace all migrations with squashed initial migration (Railway deployment)
- [x] Add basic HTTP authentication to all routes
- [x] Export/import local database to Railway (12,498 rows)
- [x] Fix background image not showing on deployed app
- [x] Remove .env.test from git history
- [x] Remove ebay_tokens.json from git history
- [x] Implement secure in-memory token storage for eBay
- [x] Update token generation scripts to not use JSON files
- [x] Delete all remaining token JSON files

### VR Service Fixes
- [x] Add timeout configuration (180s) to VR inventory download
- [x] Add Selenium browser cleanup method
- [x] Add pre-operation temp file cleanup
- [x] Fix DataFrame comparison error (check type before comparing to string)
- [x] Fix VR reconciliation column name mismatches (spaces vs underscores)
- [x] Fix missing extended_attributes and last_synced_at in reconciliation
- [x] Fix price_notax field - use `product_price` from CSV
- [x] Create one-off script to fix missing vr_listings entries

### UI Improvements
- [x] Add consistent status color scheme across list and detail pages
- [x] Apply title case to brand names in templates
- [x] Apply title case to status displays
- [x] Add configurable dropdown sorting (categories by count, brands alphabetical)
- [x] Document dropdown configuration in README

### Platform Integrations
- [x] Set up Reverb API client
- [x] Create basic CSV handler
- [x] Implement VintageAndRare import
- [x] Fixed Shopify Extended Attributes (were empty, now store full API data)
- [x] Enhanced eBay Service for flexibility (sandbox support, shipping profiles)
- [x] Generated new eBay sandbox tokens

### Data Models
- [x] Create Product model
- [x] Create PlatformListing model

## 🔴 CRITICAL ISSUES (Priority 1 - Blocking Production)

### eBay Service Issues
- [ ] **Fix eBay category parsing error** - `'list' object has no attribute 'get'` in test_ebay_conditions.py
  - Quick win - should be easy fix in response parsing
  - Blocking: Ability to validate item conditions before listing

- [ ] **Consolidate eBay service implementations**
  - Current state: 3 competing implementations
    - `importer.py`: Async + Raw SQL (used by `scripts/ebay/import_ebay.py`)
    - `inventory.py`: Sync + ORM (EbayInventorySync class)
    - `service.py`: Async + ORM (incomplete, has placeholder product_id=1)
  - Decision needed: Keep `importer.py` for import script, refactor others to single async ORM approach
  - Risk: Data consistency issues, race conditions

### eBay Shipping Configuration
- [ ] **Fix eBay Shipping Mismatch**
  - Inventory Route: Uses use_shipping_profile=True with hardcoded Business Policy IDs - WORKS
  - Sync Service: Uses use_shipping_profile=False trying to map Reverb shipping inline - FAILS
  - Solution: Update sync service to use Business Policies or fix inline shipping mapping
  - Move hardcoded policy IDs to configuration settings

### Sync Event Processing
- [ ] **Fix Partial Status Processing for eBay**
  - Sync events with status 'partial' are being skipped
  - Event ID 12292 can be used as test case
  - Ensure --retry-errors flag works for 'partial' status

## 🟡 IMPORTANT ISSUES (Priority 2 - Needed for Full Functionality)

### Platform Stats Updates
- [ ] **Implement Stats Updates During Sync**
  - Platform stats (views, watches, offers) aren't being updated
  - Available data:
    - Reverb: view_count, watch_count
    - eBay: WatchCount
    - VR: stats: {views: 257, watches: 26}
    - Shopify: Likely available via GraphQL
  - Solution: Implement "silent" sync that updates stats without creating sync events

### VR Service Issues
- [ ] **Fix VR Reconciliation Failure**
  - VR listings created successfully but reconciliation can't find VR ID
  - Need retry mechanism as VR can be unreliable
  - Fix VR service to properly capture and store listing ID after creation

- [ ] **Rename `price_notax` field** to `price` or `vr_price` in vr_listings table
- [ ] **Consolidate VR listing creation logic** - Currently duplicated in multiple files
- [ ] **Add VR listing URL resolution** - VR doesn't return ID immediately
- [ ] **Improve VR reconciliation matching** - Currently uses brand/model/price

### Product Update Sync
- [ ] **Enable Product Update Sync to Platforms**
  - Editing product details doesn't sync changes to platforms
  - Edit UI works but platform sync is disabled due to errors
  - Implement proper update sync that pushes changes to all platforms

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
- [ ] **eBay ItemSpecifics for Niche Categories** - Musical instruments need specific attributes

### Database & Models
- [ ] Set up database migrations properly (Alembic)
- [ ] Add validation rules to models
- [ ] Create database indices for performance
- [ ] Add audit trail functionality
- [ ] Create models for tables without them:
  - csv_import_logs
  - platform_category_mappings
  - platform_policies
  - product_merges
- [ ] **Implement eBay Listings Table Entry** after successful API call

### Security & Authentication
- [ ] Implement proper user authentication (beyond basic auth)
- [ ] Add user roles and permissions

## 🔵 NICE TO HAVE (Priority 3 - Quality of Life Improvements)

### Code Organization
- [ ] Remove empty files: `ebay/schemas.py`, `ebay/sync.py`, `ebay/__init__.py`
- [ ] Rename `ebay/service.py` → `ebay_repository.py`
- [ ] Move `ebay_data_analysis.py` to scripts/developer/
- [ ] Remove duplicate `EbayTradingAPIOld` class from `trading.py`
- [ ] Clean up old token management scripts (consolidated into new system)

### Category Mapping Database Migration
- [ ] Create SQLAlchemy model for `category_mappings` table
- [ ] Write Alembic migration to create table
- [ ] Write seeding script from `reverb_to_ebay_categories.json`
- [ ] Update platform services to query DB instead of JSON file

### Frontend Improvements
- [ ] Create base templates
- [ ] Implement comprehensive dashboard
- [ ] Add CSV upload interface
- [ ] Create advanced product management views
- [ ] Add platform sync status controls
- [ ] Implement error reporting interface
- [ ] Add loading states/spinners for sync operations
- [ ] Implement progress indicators for bulk operations
- [ ] Create platform sync status dashboard
- [ ] Add real-time status updates via WebSockets
- [ ] Add drag-and-drop support for images
- [ ] Add image compression before upload

### Documentation
- [ ] Update API documentation
- [ ] Create user guides for each platform integration
- [ ] Document platform-specific behaviors
- [ ] Add example usage to all docstrings
- [ ] Set up Sphinx documentation generation
- [ ] Create deployment documentation
- [ ] Document platform sync frequency and hierarchy

### CSV Processing
- [ ] Add export functionality
- [ ] Implement batch processing
- [ ] Add progress tracking for large imports
- [ ] Create error recovery system

### Testing
- [ ] Set up comprehensive testing framework
- [ ] Write model tests
- [ ] Write CSV handler tests
- [ ] Create platform integration tests
- [ ] Add frontend tests
- [ ] Create CI/CD pipeline
- [ ] Rebuild integration tests after architecture change
- [ ] Add unit tests for platform services
- [ ] Create end-to-end tests for sync processes
- [ ] Test error handling paths

### Monitoring & Operations
- [ ] Set up monitoring system (Sentry DSN configured)
- [ ] Configure backup system
- [ ] Create disaster recovery plan
- [ ] Set up staging environment
- [ ] Add logging system throughout application

### Advanced Features
- [ ] Add bulk operations API
- [ ] Implement advanced search
- [ ] Add comprehensive reporting system:
  - Price Performance Analysis
  - Platform Arbitrage Finder
  - Inventory Velocity Dashboard
  - Dead Stock Liquidation Planner
- [ ] Create analytics dashboard
- [ ] Add inventory forecasting
- [ ] Implement automated pricing system

## 📊 Current State Summary

### Working Well
- Clean architecture post-cleanup
- Comprehensive platform API clients (eBay REST + Trading, Reverb, V&R, Shopify)
- Good async/await patterns
- StockUpdateEvent system ready for cross-platform sync
- Basic authentication implemented
- Deployed to Railway with data migrated
- Secure token management (no more JSON files)
- All syncs working remotely (as of 2025-09-17)

### Needs Immediate Attention
- eBay service implementation consolidation
- eBay category parsing error fix
- eBay shipping configuration standardization
- Stats updates during sync
- VR reconciliation reliability
- Product update sync to platforms

## 🚀 Recommended Next Steps

1. **Fix eBay category parsing error** - Quick win, unblocks testing
2. **Consolidate eBay service implementations** - Choose async ORM approach
3. **Standardize eBay shipping configuration** - Use Business Policies consistently
4. **Implement stats updates** - Keep engagement metrics current
5. **Fix VR reconciliation** - Add retry logic for reliability
6. **Enable product update sync** - Complete the CRUD cycle

## 📝 Notes

- Need end-to-end testing before tackling remaining bugs
- Platform hierarchy for sales: First platform to sell wins
- Sync frequency target: 2x daily status checks
- About half a dozen bugs remain to be fixed after testing

---
*Last Updated: 2025-09-17*