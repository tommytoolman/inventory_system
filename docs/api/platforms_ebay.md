# eBay Synchronisation Map

This reference tracks every in-repo flow that touches eBay listings, including
sync detection, reconciliation, manual actions, and supporting tables.

## 1. Triggers

| Trigger | Location | Notes |
| --- | --- | --- |
| `POST /api/sync/all` | `app/routes/platforms/sync_all.py:24` | Adds the eBay background task during parallel detection. |
| `POST /api/sync/all` (scheduler) | `app/routes/sync_scheduler.py:18` | Runs the background task then calls reconciliation. |
| `POST /api/sync/ebay` | `app/routes/platforms/ebay.py:24` | Queues `run_ebay_sync_background`. |
| CLI `scripts/process_sync_event.py` | `scripts/process_sync_event.py:1` | Loads `EventProcessor.process_sync_event` for individual events. |
| Inventory UI "List on eBay" | `app/routes/inventory.py` around the `platform_slug == "ebay"` branch | Calls `EbayService.create_listing_from_product`. |
| Sync reconciliation | `app/routes/sync_scheduler.py:48` → `SyncService.reconcile_sync_run` | Consumes pending events after detection. |

## 2. Detection Pipeline

1. **Background wrapper** – `run_ebay_sync_background` (`app/routes/platforms/ebay.py:49`) logs activity,
   emits websocket notifications, and instantiates `EbayService`.
2. **Import process** – `EbayService.run_import_process` (`app/services/ebay_service.py:316`) verifies
   credentials then fetches active/sold/unsold listings using `EbayTradingLegacyAPI`.
3. **Normalisation** – `_prepare_api_data` and `_prepare_db_data` (same module) translate API payloads and
   existing DB rows into comparable dictionaries keyed by `ItemID`.
4. **Diffing** – `_calculate_changes` classifies items into create/update/remove cohorts.
5. **Event logging** – `_batch_create_products`, `_batch_update_products`, `_batch_mark_removed`
   (`app/services/ebay_service.py:571`) insert rows into `sync_events` with `change_type`
   values `new_listing`, `price`, `status_change`, and `removed_listing`. No platform tables are
   modified during detection.
6. **Bookkeeping** – the background task updates `platform_common.last_sync` for every eBay entry and
   records the run in `activity_log` (`app/routes/platforms/ebay.py:90`).

**Tables touched:** `sync_events` (inserted rows), `platform_common` (`last_sync`, `sync_status` columns
via bulk `UPDATE`).

## 3. Reconciliation

### Event Processor (single-event path)

* Entry point: `EventProcessor.process_sync_event` (`app/services/event_processor.py:38`).
* New listing handler `_create_ebay_listing` constructs product data from Reverb metadata when
  needed, ensures/creates the `products` record, then delegates to `_create_ebay_listing_entry`.
* Status/price handlers update `products`, `platform_common`, and call eBay API helpers when
  propagating price changes or ending listings.

### Sync Service (batch path)

* `SyncService.reconcile_sync_run` (`app/services/sync_services.py:330`) groups pending events by product.
* `_handle_coordinated_events` handles multi-platform or multi-event cases: decrements `products.quantity`
  for stocked items, toggles `ProductStatus`, and updates linked `platform_common` statuses.
* `_process_single_event` invokes the same per-platform helpers the event processor uses for isolated
  events.

### eBay listing creation helper

`EbayService._create_ebay_listing_entry` (`app/services/ebay_service.py:1174`) is the single writer used by
both automated reconciliation and manual publishing. It inserts/updates:

- `platform_common` – ensures a row for the product + platform with `external_id`, `status`,
  `listing_url`, message, and timestamps.
- `ebay_listings` – stores pricing, condition, policy IDs, image arrays, item specifics, and the full
  `listing_data` JSONB (either the fresh `GetItem` payload or a synthesised snapshot when the API call fails).

**Tables touched during reconciliation:** `products`, `platform_common`, `ebay_listings`, `sync_events`
(status/notes updates), `activity_log` (via `SyncService`).

## 4. Manual Listing & Update Flows

* Inventory route branch `platform_slug == "ebay"` (`app/routes/inventory.py` near line 1130) builds an
  enriched payload, selects business policies, then calls `EbayService.create_listing_from_product`, which
  funnels into `_create_ebay_listing_entry`.
* Price updates requested from the UI or reconciliation call `EbayService.update_listing_price`
  (`app/services/ebay_service.py:1260`), which in turn updates `platform_common` and `ebay_listings` after
  the API call succeeds.
* Ending listings uses `EbayService.mark_item_as_sold` to communicate with eBay before flipping
  `platform_common.status` and `ebay_listings.listing_status`.

## 5. Supporting CLI Utilities

Beyond the canonical detection + reconciliation pipeline, the `scripts/ebay/` directory contains
utility scripts (`import_ebay.py`, `update_ebay_listing.py`, `backfill_missing_ebay_entries.py`, etc.) that
leverage the same services for one-off maintenance. During Stage 1 the authoritative flow is the
`run_import_process` → `sync_events` → `reconcile_sync_run`/`process_sync_event` path summarised above; the
legacy utilities should be audited separately before reuse in production.

## 6. Table Interaction Summary

| Table | When Updated | Source |
| --- | --- | --- |
| `sync_events` | Detection logs create/update/remove/price events | `EbayService._batch_*` |
| `products` | During reconciliation when sales or new items require SKU creation/quantity updates | `EventProcessor`, `SyncService` |
| `platform_common` | Creation, status transitions, last sync timestamps | `_create_ebay_listing_entry`, reconciliation helpers, background task |
| `ebay_listings` | Full payload snapshot after reconciliation or manual publish | `_create_ebay_listing_entry` |
| `activity_log` | Operational breadcrumbs for sync runs | Background task & `SyncService` |

## 7. Stage 2 – API → Database Mapping

This section documents what the detection pipeline captures from eBay and how
reconciliation persists that data.

### 7.1 Detection Payload (`EbayService._prepare_api_data`)

| API Source | Stored in | Notes |
| --- | --- | --- |
| `ItemID` | `change_data['item_id']` & `external_id` | Primary key for reconciliation. |
| `SellingStatus.ListingStatus` | `change_data['status']` | Normalised to `active`, `sold`, `ended`, etc. |
| `SellingStatus.CurrentPrice.#text` | `change_data['price']` | Always cast to float for comparisons. |
| `Quantity` / `QuantityAvailable` | `change_data['quantity_total']` / `change_data['quantity_available']` | Used to detect inventory deltas for stocked items. |
| `SellingStatus.QuantitySold` | `change_data['quantity_sold']` | Helps derive remaining available quantity. |
| Whole `Item` dict | `change_data['raw_data']` | Persisted so reconciliation can rebuild the full snapshot. |
| `ListingDetails.ViewItemURL` | `change_data['listing_url']` | Used when creating `platform_common.listing_url`. |

Detection writes only to `sync_events`; it never touches the listing tables. The
raw payload captured here is the canonical source-of-truth for the reconciliation
step.

### 7.2 Reconciliation Writes

| Database Field | Source | Notes |
| --- | --- | --- |
| `platform_common.external_id` | `ItemID` | Ensures one row per product/platform. |
| `platform_common.status` | `SellingStatus.ListingStatus` | Normalised to our enum (`ACTIVE`, `SOLD`, `ENDED`). |
| `platform_common.last_sync` | Reconciliation timestamp | Updated whenever we reconcile successfully. |
| `products.quantity` | `Product.is_stocked_item` + sync events | Decremented for stocked items; single items flip to `SOLD`. |
| `products.status` | Derived from quantity/status | Sets `SOLD`, `ARCHIVED`, or keeps `ACTIVE`. |
| `ebay_listings.title` | `Item.Title` | Truncated to 255 characters. |
| `ebay_listings.price` | `SellingStatus.CurrentPrice` | Stored as float. |
| `ebay_listings.picture_urls` | `PictureDetails.PictureURL[]` | Saved as JSON array. |
| `ebay_listings.item_specifics` | `ItemSpecifics.NameValueList` | Converted to JSONB. |
| `ebay_listings.listing_data` | Entire `raw_data` | The full `GetItem` payload when available. |
| `ebay_listings.quantity_available` | Derived from `Quantity`/`QuantityAvailable` | Mirrors the platform’s remaining stock count. |

If `EbayService._create_ebay_listing_entry` cannot retrieve the full `GetItem`
response (e.g. transient API failure), it now retries with exponential backoff.
Only when the API never returns a payload do we store a fallback snapshot, and
that fallback preserves the submitted description so CrazyLister detection keeps
working.

### 7.3 Stocked Item Behaviour

`SyncService._handle_coordinated_events` and `_process_single_event` honour
`Product.is_stocked_item`:

- When `is_stocked_item` is `True`, the reconciliation loop decrements
  `Product.quantity` on each sold event and only marks the platform listing as
  `SOLD` when quantity reaches zero.
- For single-quantity items (`is_stocked_item == False`), the product and all
  linked listings are marked `SOLD` immediately.

Stage 3 will tighten this logic so every flow (manual and automated) respects the
same quantity rules and we never end a listing prematurely for inventorised
items.

Quantity changes are now logged explicitly via `sync_events.change_type == 'quantity_change'`
and reconciled before we propagate any end-listing actions.

Keep this document up to date whenever a new route, script, or helper touches eBay listings so the
sequence remains authoritative for future stages of the cleanup.
