# Project TODO – Inventory Management System
*Last updated: 2025-12-30*
> We only tick or strike items once we have confirmed they are done in production.

## ✅ Security & Configuration Hardening
- [x] **TinyMCE API Key Secure:** Removed hardcoded API key from `base.html` and moved to `TINYMCE_API_KEY` environment variable.
- [x] **Admin Password Enforced:** Removed insecure default from `config.py` requiring `ADMIN_PASSWORD` environment variable.
- [ ] **Review User Authentication:** Acknowledge existing internal authentication. Further formal review of auth/auth stack (User model, require_auth dependency) needed to ensure robustness and proper role management, especially for additional user access. _(Deferred by user for now)_

## 🔴 High Priority (Production blockers)
- [ ] **Sync event automation** – confirm which sync events write to `_listings` tables (persistence audit) and add gradual automation so reconciled events publish without manual nudges. Includes gradually automating the sync pipeline so sold/ended propagation runs unattended.
- [x] **Inventorised items workflow validation** – run a live stocked-item sale test to confirm the recent fixes propagate quantity/status updates correctly across platforms, restore the DB flagging for inventorised items that was lost previously, and enforce VR-specific rules (do nothing when other platforms sell while stock >1, end the VR listing only when quantity hits 0, and mark + relist VR sales when remaining quantity >0) so sync detects sales without prematurely ending multi-quantity listings. _Completed 2025-12-27: Added Inventory Reconciliation report with smart reconciliation (only updates out-of-sync platforms), order_sale sync events for stocked items, sale email alerts for inventorised stock._

## 🟡 Medium Priority (Stability & automation)
- [ ] **Category / platform attributes and category mapping** – _Progress 2025-12-29:_ Added UI infrastructure for spec capture: category-based auto-population (body_type, number_of_strings, handedness), "Additional Specs" section in Further Information with predefined options from `spec_fields.py` plus custom specs, all stored in `extra_attributes` JSONB and included in description template. Dynamic eBay condition validation via API also added. **Remaining:** (1) Expand `spec_fields.py` for non-guitar categories: Amps (wattage, tube/solid state, speaker config), Effects Pedals (true bypass, analog/digital), Pro Audio/Microphones (polar pattern, phantom power). (2) Map captured specs to eBay Item Specifics and Shopify tags/metafields during listing creation. (3) End-to-end category mapping audit.
- [x] **Dropbox media refresh is inconsistent** – _Completed 2025-12-30:_ Complete refactor of Dropbox integration: switched to thumbnail API for browsing (~98% bandwidth savings), added lazy full-res fetch on selection, fixed token persistence, parallel batch fetching, instant visual feedback (green border, checkmark, 50% opacity), two-way sync between browser and preview, smart Select All/Clear toggle button with parallel fetch.
- [ ] **Platform stats ingestion gaps** – Shopify/VR don't expose engagement stats via API (confirmed). For Reverb: add daily detailed refresh (like eBay metadata feed) to update `view_count`/`watch_count` - code exists in `reverb/client.py` (`get_all_listings_detailed`), needs scheduling + upsert logic. For eBay: extract `WatchCount` from `listing_data.Raw.Item` to dedicated column during metadata refresh.
- [ ] **Shopify archive** – create archive gallery view for historical listings AND implement auto-archive workflow (e.g., archive after 10 days of no activity).
- [ ] **DHL API integration** – wire up the tested DHL API to the orders workflow for shipping label generation and tracking. API is tested and ready, just needs UI integration.

## 🔵 Low Priority (Enhancements)
- [ ] **Fix image toast message state** – ensure the success banner dismisses correctly after refresh. Confirm colour palette and that UI reverts cleanly after multiple create flows (e.g., after adding 4 images).
- [ ] **Testing & verification rebuild** – restore integration coverage for sync flows, add regression tests for the high-risk services, and document the verification checklist.
- [ ] **NPI clustering report** – add a New Product Introduction cluster view grouped by category for merch planning.
- [ ] **Redundant code clean-up** – tidy up/deprecate old sync forms, placeholder routers, and other dead code paths.
- [ ] **Review database field coverage** – audit all key tables to ensure required fields are populated across platforms and identify any lingering gaps plus run the broader table integrity/backfill sweep to patch any gaps found.

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
- [ ] (Verify) Add loading spinner for image uploads.
- [ ] **Mobile optimisation** – ensure key inventory and sync workflows render well on mobile devices.
- [ ] **Multi-shop Reverb support** – plan how to ingest and manage listings across two Reverb shops.
- [ ] **Auto-relist at 180 days** – define and automate the policy for relisting stale inventory.
- [ ] **Additional user access** – review authentication/authorization stack to add more user accounts with appropriate roles.

## ✅ Completed
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