# Project TODO – Inventory Management System
*Last updated: 2026-02-16*
> We only tick or strike items once we have confirmed they are done in production.

## ✅ Security & Configuration Hardening
- [ ] **Review User Authentication:** Acknowledge existing internal authentication. Further formal review of auth/auth stack (User model, require_auth dependency) needed to ensure robustness and proper role management, especially for additional user access. _(Deferred by user for now)_

## 🔴 High Priority (Production blockers)
- [x] **Sync event automation** – _Completed 2026-02-14:_ Auto-processing now live for `order_sale` events (stocked items) and `status_change` events where new state is `ended` or `sold` (all platforms). Events still logged to `sync_events` table as audit trail (status=`processed` or `error`). Works for both scheduled syncs and manual UI syncs. Shopify DB consistency also fixed — `create_listing_from_product()` now creates its own `platform_common` + `shopify_listings` rows like the other 3 platforms. eBay price change detection no longer fires for ended listings. See session handoff `docs/new_session_handoff_prompt.md` for details.
- [ ] **Database schema constraints (race condition fix)** – _Progress 2026-01-26:_ Fixed race condition that created orphaned platform listings by cleaning up 31 orphaned records (24 eBay, 7 VR) and adding NOT NULL constraints to `platform_id` columns on all platform-specific tables (`ebay_listings`, `reverb_listings`, `vr_listings`, `shopify_listings`). **Remaining:** Constraints were applied directly in production database via SQL but need to be codified in an Alembic migration so they're tracked in version control and can be applied to future environments/deployments. Migration should add `ALTER TABLE {table} ALTER COLUMN platform_id SET NOT NULL` for each platform table.
- [ ] **Shopify-only products image persistence** – _Background 2026-01-26:_ During sync event cleanup, discovered 18 Shopify products created directly in Shopify (e.g., part-payment products, custom items) that don't have corresponding RIFF product records. These create recurring new_listing sync events because they can't be matched to local inventory. Current workaround is Skip button to mark events as skipped. **Remaining:** Need systemic solution: Either (1) Auto-import Shopify-only products into RIFF inventory with special SKU prefix (SHOP-ONLY-{id}) and sync images from Shopify to local storage, OR (2) Create permanent exclusion list/filter to suppress new_listing events for known Shopify-only SKUs. Consider impact on reporting and inventory counts.

## 🟡 Medium Priority (Stability & automation)
- [ ] **Full code audit** – Comprehensive audit of codebase to identify redundant code, unused imports, dead functions, commented-out blocks, duplicate logic, and opportunities for consolidation. Review services, routes, models, and scripts for technical debt. Document findings and create cleanup plan. Focus areas: (1) Unused/duplicate service methods, (2) Commented code blocks, (3) Orphaned scripts in `/scripts`, (4) Duplicate business logic across services, (5) Unused models/fields, (6) Import optimization.
- [ ] **Category / platform attributes and category mapping** – _Progress 2026-01-10:_ Comprehensive category-specific item specifics now implemented in `app/services/ebay/spec_fields.py`. Covers 30 eBay categories including guitars, bass, amps, synths, effects pedals. Auto-populates required fields (Type, Amplifier Type, etc.) via guessing from title/category. Shopify sync added for `extra_attributes` → metafields. **Status: NEEDS TESTING** - See `docs/category-item-specifics-testing.md` for test plan. Test by editing a bass/amp and syncing to eBay, then verify Item Specifics on the listing.
- [ ] **Shopify archive** – _Progress 2026-01-04:_ Auto-archive workflow implemented (`scripts/shopify/auto_archive.py`) - runs weekly via scheduler, archives ended items 14+ days old. Audit scripts created for discrepancy checks. **Remaining:** Create archive gallery view for historical listings.
- [ ] **Insights Dashboard (incl. NPI clustering)** – test and fine-tune the insights dashboard; includes New Product Introduction cluster view grouped by category for merch planning.
- [ ] **DHL API integration** – _Progress 2026-01-04:_ Built `DHLPayloadBuilder` service, added shipper config settings, created shipping page UI at `/orders/{platform}/{id}/ship`, added shipping icons to orders list. POST route for label creation complete (`/orders/{platform}/{id}/ship/create`), ship_result.html template done, API credentials validated, shipper details configured, Railway env vars added. **Remaining:** (1) Confirm workflow with Adam (labels only vs full shipping?), (2) Live test with real order. See `docs/dhl-integration.md` for full details.
- [ ] **User sync recovery tools** – Empower users to diagnose and fix sync issues without tech support. Enhance sync reporting to show what happened (and didn't happen), with actionable intervention options. **Needed:** (1) Expanded sync events report with filtering by status/platform/date, (2) "Retry failed" and "Force resync" buttons per event, (3) Bulk reconciliation actions, (4) Clear visibility into pending vs stuck vs completed events.
- [ ] **Admin settings UI** – User-accessible settings page to reduce dependency on tech support. Balance empowerment with safety - expose configurable options without giving "keys to the kingdom". **Safe to expose:** (1) Product categories (add/edit/reorder), (2) UI preferences (search debounce, items per page, default views), (3) Notification recipients, (4) Default values (processing time, archive threshold days). **With confirmation:** (5) Sync schedule adjustments, (6) Platform enable/disable toggles. **Keep locked:** API credentials, database settings, core business logic. Store in database `settings` table with audit trail.
- [ ] **Local eBay token expired** – Local `.env` has invalid/expired `EBAY_REFRESH_TOKEN`. Production (Railway) works fine. Fix by either copying token from Railway or generating fresh token via OAuth flow. Scripts available in `scripts/ebay/auth_token/`.
- [ ] **NPI clearance tracking** – Track progress toward £100k pre-2024 inventory clearance target. Internal/admin only (not user-visible). See `docs/npi-clearance-methodology.md` for full methodology and implementation options.

## 🔵 Low Priority (Enhancements)
_(No items currently)_

## 🧪 Testing
- [x] **Test suite cleanup** – _Completed 2026-01-03:_ Audited 17,356 lines of test code across 219 tests. Deleted broken/stale tests (4 files with import errors referencing deleted modules), removed 4,129-line VR local state mega-file, removed stub shipping tests. Result: **200 tests, 11,108 lines** – all collecting cleanly with 0 errors.
- [ ] **Smoke test maintenance** – keep critical path tests (route tests, product service, core sync) up to date. Run `pytest tests/` before major deploys. No CI integration planned.

## 🚀 Future: Multi-Tenant SaaS
- [ ] **Multi-tenant roadmap** – See `docs/multi-tenant-roadmap.md` for full analysis of path from single-tenant to SaaS product. Key phases: (A) Complete single-tenant polish, (B) Multi-tenant foundation (schema-per-tenant, auth, tenant context), (C) Onboarding & self-service (OAuth flows, import wizard, billing), (D) Beta launch.

## 🟠 Documentation & knowledge base
- [ ] Add example usage to docstrings across core services and routers.
- [ ] Set up Sphinx (or equivalent) documentation generation and publish API docs.
- [ ] Flesh out `docs/api/architecture.md` with the current service topology, background workers, and data flows.
- [ ] Flesh out `docs/api/models.md` with a model catalogue and relationship diagrams.
- [ ] Flesh out `docs/api/platform_integration.md` with per-platform sync behaviour (Shopify, Reverb, eBay, Vintage & Rare).
- [ ] Expand `docs/api/endpoints.md` once background worker changes land so runtime paths stay accurate.
- [ ] Create user guides for each platform integration under `docs/user_guide/`.
- [ ] Document CLI sync utilities and other scripts that touch the sync flow.
- [ ] Refresh `docs/project-summary.md` to reflect the current platform status and ordering of next steps.

## 🆕 New Functionality
- [x] **eBay template: Artist Owned badge** – _Completed 2026-02-16:_ Conditional "Artist Owned" badge on eBay listing template for products with `artist_owned = True`. Flex layout with badge image (225px, scaled to 193px) alongside centred intro + title. CSS `mix-blend-mode: multiply` handles non-transparent PNGs. Mobile responsive. Badge image passed via route context (`artist_badge_url`). Badge PNGs in `app/static/ebay/`.
- [x] **eBay template: Description auto-formatting** – _Completed 2026-02-16:_ `_clean_ebay_description_html()` filter in `inventory.py` corrects common Reverb/CMS import issues: removes empty `<p>&nbsp;</p>` paragraphs, merges fragmented `<strong>` tags (e.g. `<strong>Year</strong>&nbsp;<strong>of</strong>` → `<strong>Year of</strong>`), auto-bolds first paragraph if not already, adds `<hr>` divider before EU footer block. Also fixed Open Sans 700 weight not loading (bold was invisible), and added `text-wrap: balance` to title for even line wrapping.
- [ ] **Standardise toast/notification messages** – refactor inline notifications to use global `showNotification()` from base.html; align timing and styling across all templates. See `docs/toast-notifications-audit.md` for full audit and implementation plan.
- [ ] **Database table healthchecker** – build a report that goes beyond `/reports/listing-health` to show field population stats across all key tables (products, platform_common, platform-specific tables). Summarise NULL/populated counts per field to identify data gaps.
- [ ] (Verify) Add bulk operations API.
- [ ] (Verify) Implement advanced search.
- [ ] (Verify) Add loading spinner for image uploads.
- [ ] **Mobile optimisation** – ensure key inventory and sync workflows render well on mobile devices.
- [ ] **Multi-shop Reverb support** – plan how to ingest and manage listings across two Reverb shops.
- [ ] **Auto-relist at 180 days** – define and automate the policy for relisting stale inventory.
- [ ] **Additional user access** – review authentication/authorization stack to add more user accounts with appropriate roles.

## ✅ Completed
- [x] **Stocked inventory quantity sync investigation** – _Completed 2026-01-27:_ Fixed multiple stocked item bugs: (1) Inventory reconciliation endpoint now correctly updates Shopify quantities (removed save/restore logic in Reverb block), (2) Added status filter to skip quantity_change sync events for ended/sold eBay listings, (3) Added Skip button for non-Reverb new_listing events to handle legitimate Shopify-only products, (4) Fixed duplicate sync event creation by checking for existing events regardless of status, (5) **Final fix:** `OrderSaleProcessor` now updates source platform's local DB after order processing - added `_update_source_platform_local_db()` method to update `reverb_listings.inventory_quantity`, `ebay_listings.quantity_available`, and `shopify_listings.extended_attributes.totalInventory` after decrementing RIFF quantity. All platforms (source and targets) now stay in sync when stocked items sell.
- [x] **Redundant code clean-up** – _Completed 2026-01-03:_ Removed ~1,100 lines of dead code including: 688-line commented `EbayTradingLegacyAPIOLD` class from `trading.py`, 120-line commented class from `category_mapping_service.py`, deleted orphaned `.old` backup files (`sync_scheduler.py.old`, `sync_scheduler.py`, `repository.py.old`).
- [x] **Listing Engagement Report & Stats Ingestion** – _Completed 2026-01-01:_ Added Listing Engagement Report at `/reports/listing-engagement` aggregating Reverb + eBay views/watches by product. Implemented `listing_stats_history` table with daily scheduled refresh for both platforms (`reverb_stats_daily`, `ebay_stats_daily` jobs). Report features sortable columns, platform breakdown (R:X | E:Y), 7-day change tracking, system icons for platform links. Also fixed VR relist to update `platform_common.status`.
- [x] **TinyMCE API Key Secure:** Removed hardcoded API key from `base.html` and moved to `TINYMCE_API_KEY` environment variable.
- [x] **Admin Password Enforced:** Removed insecure default from `config.py` requiring `ADMIN_PASSWORD` environment variable.
- [x] **Inventorised items workflow validation** – _Completed 2025-12-27, enhanced 2026-01-06:_ Added Inventory Reconciliation report with smart reconciliation (only updates out-of-sync platforms), order_sale sync events for stocked items, sale email alerts for inventorised stock. **2026-01-06:** Fixed `OrderSaleProcessor` to actually call platform APIs when propagating quantity changes (was only logging). Fixed method names for Reverb/Shopify to use `apply_product_update()`. Fixed reconciliation report to pass settings to services. Added page reload after successful reconciliation.
- [x] **Dropbox media integration overhaul** – _Completed 2025-12-30:_ Complete refactor using thumbnail API (~98% bandwidth savings), lazy full-res fetch, token persistence, parallel fetching, instant visual feedback, two-way selection sync, smart Select All/Clear button.
- [x] **Platform error handling standardisation** – error handling across all platform services now graceful and consistent. _Completed 2025-12-24._
- [x] **"Where sold" attribution & sales orders** – sale-source attribution in sales report correctly identifies platform vs OFFLINE; aligned with orders workflow. _Completed 2025-12-24._
- [x] **Sold date surfaces** – exposed sold timestamp on product detail pages via `get_sale_info()` in inventory.py; shows sale platform and date. _Completed 2025-12-24._
- [x] **Batch VR item creation** – job queue batches multiple VR listings, resolves IDs via single CSV download. _Completed 2025-12-15._
- [x] **Left-handed tagging** – determine how we consistently label and surface left-handed instruments.
- [x] **Retrofix missing product titles** – write a script to backfill `products.title` entries where historical edits failed to persist.
- [x] **Product sold flag parity** – think this is covered elsewhere but the original requirement was unclear; monitor reporting for regressions.
- [x] **Reverb item creation pricing drift** – update the default Reverb price recommendation to reflect the new fee structure while keeping manual overrides available.
- [x] **Title/description sync coverage** – confirm the new edit propagation pushes title/description updates to Shopify, eBay, Reverb, and VR end-to-end.
- [x] **Reverb YouTube embed parity** – ensure listing creation/edit stores the video URL in both the dedicated field and description so embeds render.
- [x] Detect missing images on Shopify/eBay before running refresh jobs.
- [x]] Download the canonical gallery to temporary storage and normalise filenames.
- [x]] Re-upload missing images to Shopify/eBay using the refreshed gallery.
- [x]] Update local records (`platform_common` plus platform tables) after uploads.
- [x]] Integrate the backend flow with the UI “Check Images” control.


- [x] **Reinstate Shopify SEO keyword generator button** – revert the auto-fill experiment and restore the manual generate flow (with richer keyword logic) once requirements are clarified. FIXED – currently hidden from users until next UX pass.
- [x] **eBay condition/category parsing** – fix the 'list' object has no attribute "get" error, consolidate service modules, and flesh out the remaining condition/category mappings.
- [x] **eBay shipping profiles out of sync** – align listing UI and background sync with the correct Business Policy IDs (Adam to supply new profiles) and validate configuration is exposed instead of hardcoding.
- [x] **Reverb new listing flow fails** – diagnose current API/CSV path so new products publish end-to-end without manual intervention.
- [x] **Sold item email alerts** – implemented via `EmailNotificationService.send_sale_alert` and invoked from `SyncService` sale handling flow.
- [x] **Offload platform sync workloads** – move long-running sync jobs (especially Vintage & Rare) into background workers/threads so the FastAPI app stays responsive during imports and item creation.
- [x] **Price sync on edits** – re-run outbound pricing syncs whenever an operator updates a product’s pricing fields.
- [x] **Shopify archive build-out** – populate the archive dataset and surface "archived" status in the dashboard for Shopify listings.
- [x] **Inventory edit sync wiring** – connect the edit form’s platform checkboxes to real sync calls so saving a product can push updates immediately.
- [x] **VR inventorised sales handling** – ensure VR sale events decrement inventory, fan out quantity changes, and keep VR listings active until stock hits zero.
- [x] **Editor description rendering mismatch** – ensure the product edit view loads descriptions into the TinyMCE editor instead of raw HTML.
- [x] **Shopify archived count** – display the count of archived Shopify SKUs on the dashboard overview card.
- [x] **Shopify pricing parity** – apply a 5% discount when cloning Reverb listings, rounding up to the nearest £x,999 across all Shopify creation paths.
- [x] **eBay CrazyLister detection** – flag eBay listings that use the CrazyLister template via HTML markers so we can prioritise refreshes.
- [x] **Draft media persistence** – store draft uploads in shared storage per draft and clean up orphaned files after edits so drafts survive machine or redeploy changes.
- [x] **Image draft persistence** – ensure draft uploads are stored on Railway (or other web-accessible storage) so templates and Reverb creation always have public URLs.
- [x] **Product grid layout tweak** – cap category column width on the Products table so “View”/status controls remain visible without horizontal scrolling.
- [x] **EU data hard-code review** – remove any remaining hard-coded EU shipping/tax details and move to configuration or platform data.
- [x] **VR handling performance** – offload Selenium/API VR work to background queue + worker and keep the app responsive.
- [x] **VR pending status investigation** – addressed the pending -> active flow; queue + worker now process VR listings end-to-end.
- [x] **Capture handedness & artist ownership** – non-mandatory fields defaulted and propagated to APIs; Shopify metafield verified.
- [x] **VR removal logic verification** – handling marks "not found on API" as REMOVED (unless corroborated by Reverb) and UI path reflects the logic.
- [x] **Sync-all queue follow-up** – reconciled background orchestrator with batched implementation; non-blocking endpoint confirmed.
- [x] **eBay listing backfill script** – automated to keep ebay_listings current with CrazyLister payloads and descriptions.
- [x] **Activity report tidy-up** – reduced noisy/duplicate rows.
- [x] **VR listing ID capture from instruments/show** – capture via authenticated page before CSV fallback.
- [x] **Review price propagation** – validated markups stay intact on edit; no uniform pricing forced.
- [x] **Validate Shopify listing URLs** – audited/backfilled missing listing_url entries.
- [x] **Payload persistence safeguards** – ensured queuing/storage prevents duplicate listing creation.
- [x] **Sold logic review** – queries/reports validate sale event propagation.
- [x] **CrazyLister integration discovery** – feasibility reviewed; description stripping fixed; decision recorded.
- [x] **VR historical shipping profiles** – audited all VR listings, identified 268 discrepancies, batch-fixed 227 items (0 errors). Scripts in `scripts/vr/`.
- [x] **Shopify shipping profile readiness** – documented and validated shipping profile assignment process.
- [x] **Per-platform shipping profile edits** – eBay shipping policy selectors done; VR tracked separately.
- [x] **Reverb double listing guard** – multi-layer duplicate protection: local DB check, remote Reverb API SKU search, auto-SKU regeneration for RIFF products.
- [x] Set up basic FastAPI application.
- [x] Configure PostgreSQL database.
- [x] Create initial models.
- [x] Create `Product` model.
- [x] Create `PlatformListing` model.
- [x] Create basic CSV handler.
- [x] Implement Vintage & Rare import.
- [x] Set up API client for Reverb.

---

**Note:** Handedness/artist-owned feature will require: Alembic migration + `Product` model update; default backfill; Pydantic schema & API adjustments; form/template inputs on add/edit; detail view surfacing; platform payload updates; tests/docs refresh.