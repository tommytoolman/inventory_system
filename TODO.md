# Project TODO – Inventory Management System
*Last updated: 2025-03-09*

> We only tick or strike items once we have confirmed they are done in production.

## 🔴 High Priority (Production blockers)
- [ ] **Sold item email alerts** – send notification emails to 2-3 configured recipients whenever a product transitions into a sold state.
- [ ] **Reverb new listing flow fails** – diagnose current API/CSV path so new products publish end-to-end without manual intervention.
- [ ] **eBay shipping profiles out of sync** – align listing UI and background sync with the correct Business Policy IDs (Adam to supply new profiles) and expose configuration instead of hardcoding.
- [ ] **eBay condition/category parsing** – fix the `'list' object has no attribute "get"` error, consolidate service modules, and flesh out the remaining condition/category mappings.
- [ ] **Inventorised items workflow broken** – verify the new propagation with a full sale test (sync event should recognise stocked items and fan out quantity changes).
- [ ] **VR removal logic** – treat VR “not found on API” sync events as `REMOVED` (not sold) unless Reverb also signals an end; surface “List Item” on detail pages while keeping VR sales events authoritative.

## 🟡 Medium Priority (Stability and automation)
- [ ] **Category mapping migration** – move the JSON mappings into a database table with Alembic migrations and seeding.
- [ ] **Platform error handling standardisation** – unify logging/alerts and ensure retries work the same across eBay, Reverb, VR, and Shopify.
- [ ] **"Where sold" logic improvements** – refine attribution so reporting shows the definitive sale source for each SKU (tie into sold notifications and sale channel attribution).
- [ ] **Async listing publication flow** – move manual listing actions (especially VR create/update) into the same background queue model so operators aren’t blocked during long Selenium/HTTP cycles.
- [ ] **Reverb YouTube embed parity** – ensure listing creation/edit stores the video URL in both the dedicated field and description so embeds render.
- [ ] **Title/description sync coverage** – confirm the new edit propagation pushes title/description updates to Shopify, eBay, Reverb, and VR end-to-end.
- [ ] **Reverb item creation pricing drift** – update the default Reverb price recommendation to reflect the new fee structure while keeping manual overrides available.
- [ ] **Dropbox media refresh is inconsistent** – stabilise cache refresh, keep folder tiles a consistent size, and reduce redundant re-renders after multiple reloads.
- [ ] **Fully automate sync pipeline** – move from operator-triggered runs to scheduled execution; confirm cronjob/worker (including Dropbox refresh) is running and instrument failure alerts.
- [x] **Offload platform sync workloads** – move long-running sync jobs (especially Vintage & Rare) into background workers/threads so the FastAPI app stays responsive during imports and item creation.
- [ ] **Sync-all queue follow-up** – reconcile the queued `/api/sync/all` background orchestrator with the current batched implementation (status polling, history retention, websocket notifications) so the endpoint remains non-blocking without regressing the latest changes.
- [ ] **Platform stats ingestion gaps** – fill in watches/likes/views for eBay, Shopify, VR, matching the partial Reverb feed and surface them on dashboards.
- [ ] **Field coverage audit** – verify every sync run populates mandatory listing fields (shipping, condition, attributes, compliance text) across platforms.
- [ ] **eBay listing backfill script** – write a job that refreshes ebay_listings rows from master product data, preserves/detects CrazyLister payloads, and keeps descriptions in sync (e.g., item 257112518866).
- [ ] **Activity report tidy-up** – debug the report pipeline and trim noisy or duplicate rows so it is usable for daily review.
- [ ] **Recent activity & sales report fixes** – address the minor bugs observed in the activity feeds and sales summaries.
- [x] **Price sync on edits** – re-run outbound pricing syncs whenever an operator updates a product’s pricing fields.

## 🔵 Low Priority (Enhancements)
- [ ] **VR reconciliation improvements** – capture listing IDs reliably (current process is brittle), compare download inventory against `vr_listings`, share creation helpers, and add retry logic.
- [ ] **Testing & verification rebuild** – restore integration coverage for sync flows, add regression tests for the high-risk services, and document the verification checklist.
- [ ] **Populate Shopify archive gallery** – build the historical gallery view using the archive dataset so users can review past listings.
- [ ] **CrazyLister integration discovery** – investigate feasibility, fix description stripping on edits, and decide whether to proceed.
- [ ] **Sold date surfaces** – expose the confirmed sold timestamp on product detail pages and reports when available.
- [ ] **Additional user access** – review authentication/authorization stack to add more user accounts with appropriate roles.
- [ ] **NPI clustering report** – add a New Product Introduction cluster view grouped by category for merch planning.
- [ ] **Document CLI sync utilities** – in addition to API routes, catalogue every `scripts/` entry point (imports, event processors, VR helpers) that touches the sync flow so the docs cover both web and command-line usage.

## 🟣 Backlog (Track, revisit as time allows)

## ✅ Completed
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

---

Add new items directly under the matching priority heading; keep finished work in a separate "Completed" section only after verification.
