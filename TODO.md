# Project TODO – Inventory Management System
*Last updated: 2025-03-09*

> We only tick or strike items once we have confirmed they are done in production.

## 🔴 High Priority (Production blockers)
- [ ] **Reverb item creation pricing drift** – update the default Reverb price recommendation to reflect the new fee structure while keeping manual overrides available.
- [ ] **Sold item email alerts** – send notification emails to 2-3 configured recipients whenever a product transitions into a sold state.
- [ ] **Title/description sync coverage** – extend the cross-platform sync so title and description changes propagate alongside price/status updates.
- [ ] **Reverb YouTube embed parity** – duplicate the video URL into both the dedicated tag and the description payload so Reverb renders embeds reliably.
- [ ] **Inventory edit sync wiring** – connect the edit form’s platform checkboxes to real sync calls so saving a product can push updates immediately.
- [ ] **Reverb new listing flow fails** – diagnose current API/CSV path so new products publish end-to-end without manual intervention.
- [ ] **eBay shipping profiles out of sync** – align listing UI and background sync with the correct Business Policy IDs and expose configuration instead of hardcoding.
- [ ] **eBay condition/category parsing** – fix the `'list' object has no attribute "get"` error and consolidate the competing eBay service modules into a single supported implementation.
- [ ] **Inventorised items workflow broken** – ensure repeatable SKUs (e.g., British Pedal Company pedals) stay in stock, carry correct quantities, and sync updates to every platform.
- [ ] **Shopify pricing parity** – when cloning Reverb listings, discount Shopify price by 5% and round up to the nearest £x,999 (e.g., £17,499 → £16,999) across all creation paths.
- [ ] **VR removal logic** – treat VR “not found on API” sync events as `REMOVED` (not sold) unless Reverb also signals an end; surface “List Item” on detail pages while keeping VR sales events authoritative.

## 🟡 Medium Priority (Stability and automation)
- [ ] **Dropbox media refresh is inconsistent** – stabilise cache refresh, keep folder tiles a consistent size, and reduce redundant re-renders after multiple reloads.
- [ ] **Fully automate sync pipeline** – move from operator-triggered runs to scheduled execution; confirm cronjob/worker is running and instrument failure alerts.
- [ ] **Platform stats ingestion gaps** – fill in watches/likes/views for eBay, Shopify, VR, matching the partial Reverb feed and surface them on dashboards.
- [ ] **Field coverage audit** – verify every sync run populates mandatory listing fields (shipping, condition, attributes, compliance text) across platforms.
- [ ] **eBay listing backfill script** – write a job that refreshes ebay_listings rows from master product data to fill missing metadata (e.g., item 257112518866).
- [ ] **Activity report tidy-up** – debug the report pipeline and trim noisy or duplicate rows so it is usable for daily review.
- [ ] **eBay condition mapping & extra item details** – complete the attribute mapping for instruments and expand payloads with missing specifics.
- [ ] **EU data hard-code review** – remove any remaining hard-coded EU shipping/tax details and move to configuration or platform data.
- [ ] **Image draft persistence** – ensure draft uploads are stored on Railway (or other web-accessible storage) so templates and Reverb creation always have public URLs.
- [ ] **Recent activity & sales report fixes** – address the minor bugs observed in the activity feeds and sales summaries.
- [ ] **Price sync on edits** – re-run outbound pricing syncs whenever an operator updates a product’s pricing fields.

## 🔵 Low Priority (Enhancements)
- [ ] **Shopify archive build-out** – populate the archive dataset and surface "archived" status in the dashboard for Shopify listings.
- [ ] **CrazyLister integration discovery** – investigate feasibility and value before committing to implementation.
- [ ] **"Where sold" logic improvements** – refine attribution so reporting shows the definitive sale source for each SKU.
- [ ] **eBay CrazyLister detection** – flag eBay listings using the template (identify via HTML markers) so we can decide whether to refresh content.
- [ ] **Sold date surfaces** – expose the confirmed sold timestamp on product detail pages and reports when available.
- [ ] **Additional user access** – review authentication/authorization stack to add more user accounts with appropriate roles.
- [ ] **NPI clustering report** – add a New Product Introduction cluster view grouped by category for merch planning.
- [ ] **Product grid layout tweak** – cap category column width on the Products table so “View”/status controls remain visible without horizontal scrolling.

## 🟣 Backlog (Track, revisit as time allows)
- [ ] **VR reconciliation improvements** – capture listing IDs reliably, share creation helpers, and add retry logic for unstable responses.
- [ ] **Category mapping migration** – move the JSON mappings into a database table with Alembic migrations and seeding.
- [ ] **Platform error handling standardisation** – unify logging/alerts and ensure retries work the same across eBay, Reverb, VR, and Shopify.
- [ ] **Testing & verification rebuild** – restore integration coverage for sync flows, add regression tests for the high-risk services, and document the verification checklist.
- [ ] **Sale channel attribution** – formalise logic that tags each sale as Offline vs. Shopify vs. VR vs. eBay vs. Reverb for downstream reporting.

## ✅ Completed
- [x] **Editor description rendering mismatch** – ensure the product edit view loads descriptions into the TinyMCE editor instead of raw HTML.
- [x] **Shopify archived count** – display the count of archived Shopify SKUs on the dashboard overview card.

---

Add new items directly under the matching priority heading; keep finished work in a separate "Completed" section only after verification.
