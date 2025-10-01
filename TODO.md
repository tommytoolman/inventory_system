# Project TODO – Inventory Management System
*Last updated: 2025-03-09*

> We only tick or strike items once we have confirmed they are done in production.

## 🔴 High Priority (Production blockers)
- [ ] **Reverb new listing flow fails** – diagnose current API/CSV path so new products publish end-to-end without manual intervention.
- [ ] **eBay shipping profiles out of sync** – align listing UI and background sync with the correct Business Policy IDs and expose configuration instead of hardcoding.
- [ ] **eBay condition/category parsing** – fix the `'list' object has no attribute "get"` error and consolidate the competing eBay service modules into a single supported implementation.
- [ ] **Inventorised items workflow broken** – ensure repeatable SKUs (e.g., British Pedal Company pedals) stay in stock, carry correct quantities, and sync updates to every platform.

## 🟡 Medium Priority (Stability and automation)
- [ ] **Dropbox media refresh is inconsistent** – stabilise cache refresh, keep folder tiles a consistent size, and reduce redundant re-renders after multiple reloads.
- [ ] **Fully automate sync pipeline** – move from operator-triggered runs to scheduled execution; confirm cronjob/worker is running and instrument failure alerts.
- [ ] **Platform stats ingestion gaps** – fill in watches/likes/views for eBay, Shopify, VR, matching the partial Reverb feed and surface them on dashboards.
- [ ] **Field coverage audit** – verify every sync run populates mandatory listing fields (shipping, condition, attributes, compliance text) across platforms.
- [ ] **Activity report tidy-up** – debug the report pipeline and trim noisy or duplicate rows so it is usable for daily review.
- [ ] **eBay condition mapping & extra item details** – complete the attribute mapping for instruments and expand payloads with missing specifics.
- [ ] **EU data hard-code review** – remove any remaining hard-coded EU shipping/tax details and move to configuration or platform data.

## 🔵 Low Priority (Enhancements)
- [ ] **Shopify archive build-out** – populate the archive dataset and surface "archived" status in the dashboard for Shopify listings.
- [ ] **CrazyLister integration discovery** – investigate feasibility and value before committing to implementation.
- [ ] **"Where sold" logic improvements** – refine attribution so reporting shows the definitive sale source for each SKU.

## 🟣 Backlog (Track, revisit as time allows)
- [ ] **VR reconciliation improvements** – capture listing IDs reliably, share creation helpers, and add retry logic for unstable responses.
- [ ] **Category mapping migration** – move the JSON mappings into a database table with Alembic migrations and seeding.
- [ ] **Platform error handling standardisation** – unify logging/alerts and ensure retries work the same across eBay, Reverb, VR, and Shopify.
- [ ] **Testing & verification rebuild** – restore integration coverage for sync flows, add regression tests for the high-risk services, and document the verification checklist.

---

Add new items directly under the matching priority heading; keep finished work in a separate "Completed" section only after verification.
