# API Endpoints

This document captures every entry point involved in inventory synchronisation, reconciliation, and manual listing actions.

## Sync Detection Entry Points

| Route | Module | Description |
| ---   | ---    | ---         |
| `POST /api/sync/all` | `app/routes/platforms/sync_all.py` | Kicks off parallel detection-only imports for the requested platforms (no reconciliation). |
| `POST /api/sync/all` | `app/routes/sync_scheduler.py` | Two-phase helper: runs all detection tasks then calls reconciliation in-process. |
| `POST /api/sync/reverb` | `app/routes/platforms/reverb.py` | Background task that invokes `ReverbService.run_import_process`. |
| `POST /api/sync/ebay` | `app/routes/platforms/ebay.py` | Background task that invokes `EbayService.run_import_process`. |
| `POST /api/sync/shopify` | `app/routes/platforms/shopify.py` | Background task that invokes `ShopifyService.run_import_process`. |
| `POST /api/sync/vr` | `app/routes/platforms/vr.py` | Background task that invokes `VRService.run_import_process`. |
| `scripts/process_sync_event.py` | CLI | Loads `EventProcessor.process_sync_event` to materialise queued sync events. |

Each platform helper ultimately calls `<Platform>Service.run_import_process`, which fetches remote data, compares against local state, and logs differences to `sync_events` without touching the platform-specific tables.

## Reconciliation & Event Processing

| Route / Script | Module | Description |
| --- | --- | --- |
| `SyncService.reconcile_sync_run` | `app/services/sync_services.py` | Consumes pending `sync_events` for a run, updates `products`, `platform_common`, and platform `_listings`, and triggers notifications. |
| `EventProcessor.process_sync_event` | `app/services/event_processor.py` | Single-event processor used by the CLI and UI to create listings or propagate changes. |

During reconciliation we call helper methods such as `_create_ebay_listing_entry`, `_create_reverb_listing_entry`, `_create_shopify_listing_entry`, and `VRService.create_or_update_listing`, ensuring all platform tables are updated through a consistent service layer.

## Manual Listing Actions

Inventory UI routes call into the same service helpers that reconciliation uses:

| Action | Module | Notes |
| --- | --- | --- |
| List on Reverb | `app/routes/inventory.py` → `ReverbService.create_draft_listing` | Writes both `platform_common` and `reverb_listings`. |
| List on eBay | `app/routes/inventory.py` → `EbayService.create_listing_from_product` → `_create_ebay_listing_entry` | Uses the same snapshot builder as reconciliation. |
| List on Shopify | `app/routes/inventory.py` → `ShopifyService.publish_product` | Persists via `platform_common` and `shopify_listings`. |
| List on Vintage & Rare | `app/routes/inventory.py` → `VRService.create_listing_from_product` | Automates Selenium flow and records to `vr_listings`. |

## Background Job Considerations

- Long-running sync or creation flows (especially V&R) currently execute on the main FastAPI event loop. We have a medium-priority TODO to move these into background workers so they no longer block the app.
- Websocket notifications are emitted from each platform background task (`app/services/websockets/manager.py`).
- Activity logging is centralised via `ActivityLogger` to keep audit trails for every sync trigger.

Keep this document updated whenever a new sync entry point, reconciliation helper, or manual route is introduced.
