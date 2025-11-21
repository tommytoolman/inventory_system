# Project TODO – Inventory Management System
*Last updated: 2025-11-03*
> We only tick or strike items once we have confirmed they are done in production.

## 🔴 High Priority (Production blockers)
- [ ] **VR handling performance** – address sluggish VR listing creation and inventory sync by offloading slow Selenium/API work to background workers and smoothing operator workflows.
- [ ] **VR historical shipping profiles** – audit legacy VR listings and update shipping profiles to match the current configuration. _[Track on VR branch]_
- [ ] **VR pending status investigation** – identify why freshly created VR listings remain `pending` instead of `active` and patch the flow. _[VR branch]_
- [ ] **Capture handedness & artist ownership** – add non-mandatory fields to product add/edit flows, defaulting to right-handed / not artist owned, propagate to relevant APIs, and verify Shopify continues to write the correct product metafield.
- [ ] **Inventorised items workflow validation** – run a live stocked-item sale test to confirm the recent fixes propagate quantity/status updates correctly across platforms, restore the DB flagging for inventorised items that was lost previously, and enforce VR-specific rules (do nothing when other platforms sell while stock >1, end the VR listing only when quantity hits 0, and mark + relist VR sales when remaining quantity >0) so sync detects sales without prematurely ending multi-quantity listings.
- [ ] **VR removal logic verification** – confirm the updated handling marks "not found on API" as REMOVED (unless corroborated by Reverb) and that the “List Item” UI path reflects the latest logic.
- [ ] **Shopify shipping profile readiness** – document and validate the pre-launch process for assigning shipping profiles within Shopify.
- [ ] **Per-platform shipping profile edits** – surface Shopify/eBay shipping policy selectors on the product edit form and ensure changes propagate to live listings, not just Reverb/V&R.
- [ ] **Left-handed category integrity** – review `platform_category_mappings` to ensure left-handed SKUs use the dedicated categories on every platform (while Reverb uses technical attributes, eBay/Shopify/VR must stay mapped via category).
- [ ] **Category mapping database migration & audit** – move VR and cross-platform mappings into Alembic-managed tables and validate coverage post-migration.
- [ ] **Sync event automation** – confirm which sync events write to `_listings` tables (persistence audit) and add gradual automation so reconciled events publish without manual nudges. Includes gradually automating the sync pipeline so sold/ended propagation runs unattended.

## 🟡 Medium Priority (Stability & automation)
- [ ] **Platform error handling standardisation** – unify logging/alerts and ensure retries work the same across eBay, Reverb, VR, and Shopify.
- [ ] **"Where sold" attribution & sales orders** – refine sale-source attribution for each SKU and align the reporting logic with the upcoming `sales_orders` schema/workflow.
- [ ] **Dropbox media refresh is inconsistent** – stabilise cache refresh, keep folder tiles a consistent size, and reduce redundant re-renders after multiple reloads.
- [ ] **Sync-all queue follow-up** – reconcile the queued `/api/sync/all` background orchestrator with the current batched implementation (status polling, history retention, websocket notifications) so the endpoint remains non-blocking without regressing the latest changes. Also confirm the worker is truly threaded and not blocking the main process.
- [ ] **Platform stats ingestion gaps** – fill in watches/likes/views for eBay, Shopify, VR, matching the partial Reverb feed and surface them on dashboards.
- [ ] **Review database field coverage** – audit all key tables to ensure required fields are populated across platforms and identify any lingering gaps plus run the broader table integrity/backfill sweep to patch any gaps found.
- [ ] **eBay listing backfill script** – job already written; now schedule/automate it to run daily so ebay_listings rows stay current, CrazyLister payloads persist, and descriptions (e.g., 257112518866) keep matching master data.
- [ ] **Activity report tidy-up** – debug the report pipeline and trim noisy or duplicate rows so it is usable for daily review.
- [ ] **Recent activity & sales report fixes** – address the minor bugs observed in the activity feeds and sales summaries.
- [ ] **VR listing ID capture from instruments/show** – after Selenium submits a listing, scrape the authenticated `/instruments/show` page to grab the new product ID before falling back to the CSV export. Current approach works but feels inefficient; explore cleaner shortcuts.
- [ ] **Design consolidated `sales_orders` table** – align sale-source attribution, schema, and payload ingestion (see "Where sold" attribution work) before making DB changes.
- [ ] **Review price propagation** – CODED, needs user validation that platform markups stay intact on edit and no uniform pricing is forced.
- [ ] **Validate Shopify listing URLs** – audit all stored `listing_url` values for Shopify listings and backfill any missing entries.
- [ ] **Payload persistence safeguards** – confirm queuing/storage logic prevents duplicate listing creation across platforms.
- [ ] **Status casing consistency** – ensure status fields use canonical casing (e.g., `ACTIVE`, `SYNCED`) across services and the database.
- [ ] **Sold logic review** – produce queries/reports to validate how sale events propagate through all tables.
- [ ] **Shopify auto-archive workflow** – automate moving stale Shopify listings to archive after the agreed threshold.

## 🔵 Low Priority (Enhancements)
- [ ] **Fix image toast message state** – ensure the success banner dismisses correctly after refresh. Confirm colour palette and that UI reverts cleanly after multiple create flows (e.g., after adding 4 images).
- [ ] **Ongoing UI tweaks** – e.g. image dividers, vertical alignment adjustments.
- [ ] **Testing & verification rebuild** – restore integration coverage for sync flows, add regression tests for the high-risk services, and document the verification checklist.
- [ ] **Populate Shopify archive gallery** – build the historical gallery view using the archive dataset so users can review past listings. Confirm with Adam whether thousands of gallery entries are actually required.
- [ ] **CrazyLister integration discovery** – investigate feasibility, fix description stripping on edits, and decide whether to proceed.
- [ ] **Sold date surfaces** – expose the confirmed sold timestamp on product detail pages and reports when available.
- [ ] **Additional user access** – review authentication/authorization stack to add more user accounts with appropriate roles.
- [ ] **NPI clustering report** – add a New Product Introduction cluster view grouped by category for merch planning.
- [ ] **Redundant code clean-up** – tidy up/deprecate old sync forms, placeholder routers, and other dead code paths.

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
- [ ] (Verify) Add bulk operations API.
- [ ] (Verify) Implement advanced search.
- [X] (Verify) Add reporting system.
- [X] (Verify) Create analytics dashboard.
- [X] (Verify) Add inventory forecasting. (Not feasible)
- [X] (Verify) Implement automated pricing system.
- [ ] (Verify) Add loading spinner for image uploads.
- [X] (Verify) Add drag-and-drop support for images.
- [X] (Verify) Add image compression before upload.
- [ ] **Mobile optimisation** – ensure key inventory and sync workflows render well on mobile devices.
- [ ] **Multi-shop Reverb support** – plan how to ingest and manage listings across two Reverb shops.
- [ ] **VR queue/threading improvements** – revisit VR queue handling to keep long-running jobs responsive.
- [ ] **Auto-relist at 180 days** – define and automate the policy for relisting stale inventory.

## 🧱 Platform & infrastructure foundations (needs validation)
### Core system
- [x] Set up basic FastAPI application.
- [x] Configure PostgreSQL database.
- [x] Create initial models.
- [x] Set up database migrations end-to-end.
- [x] Implement user authentication (HTTP Basic via app/core/security.py).
- [ ] (Verify) Add centralised logging/observability.
### Data models
- [x] Create `Product` model.
- [x] Create `PlatformListing` model.
- [ ] (Verify) Add validation rules.
- [ ] (Verify) Create database indices for performance hotspots.
- [ ] (Verify) Add audit trail functionality.
- [ ] (Verify) Create error recovery system.
### Platform integrations
- Vintage & Rare
  - [ ] (Verify) Implement automated CSV processing end-to-end.
  - [ ] (Verify) Add Selenium/headless hardening.
  - [ ] (Verify) Create scheduling system.
- eBay
  - [ ] (Verify) Confirm API client coverage and token refresh.
  - [ ] (Verify) Close remaining listing sync gaps.
  - [ ] (Verify) Add inventory update handling.
- Reverb
  - [x] Set up API client.
  - [ ] (Verify) Close remaining listing sync gaps.
  - [ ] (Verify) Add inventory update handling.
  - [ ] Review `reverb_listings` schema for duplicates/oddities.
- Shopify
  - [ ] (Verify) Design API interface/client documentation.
  - [ ] (Verify) Implement sync system coverage.
  - [ ] (Verify) Add error handling parity.
### Frontend
- [ ] (Verify) Refresh base templates/components for consistency.
- [ ] (Verify) Confirm dashboard covers current KPIs.
- [ ] (Verify) Polish CSV upload interface and UX.
- [ ] (Verify) Ensure product management views cover current workflows.
- [ ] (Verify) Add platform sync controls where gaps remain.
- [ ] (Verify) Implement error reporting surface for operators.
### Testing & deployment
- [ ] (Verify) Ensure testing framework coverage is complete.
- [ ] (Verify) Write/refresh model tests.
- [ ] (Verify) Write CSV handler tests.
- [ ] (Verify) Create platform integration tests.
- [ ] (Verify) Add frontend tests.
- [ ] (Verify) Create CI/CD pipeline.
- [ ] (Verify) Create deployment documentation.
- [ ] (Verify) Set up monitoring/alerting.
- [ ] (Verify) Configure backup system.
- [ ] (Verify) Create disaster recovery plan.
- [ ] (Verify) Set up staging environment.

## ✅ Completed
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
- [x] **eBay shipping profiles out of sync** – align listing UI and background sync with the correct Business Policy IDs (Adam to supply new profiles) and expose configuration instead of hardcoding.
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
