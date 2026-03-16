# RIFF Inventory Management System — Architecture

> **Status:** Phase 0 (Stabilisation) — single-tenant, pre-SaaS
> **Last updated:** 2026-03-16

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Directory Structure](#2-directory-structure)
3. [Core Services](#3-core-services)
4. [Data Flow](#4-data-flow)
5. [Database Schema](#5-database-schema)
6. [Authentication & Security](#6-authentication--security)
7. [Sync Scheduling](#7-sync-scheduling)
8. [Platform Integrations](#8-platform-integrations)
9. [API Endpoints Overview](#9-api-endpoints-overview)
10. [Testing Strategy](#10-testing-strategy)
11. [Key Design Decisions](#11-key-design-decisions)
12. [Known Limitations](#12-known-limitations)
13. [Multi-Tenancy Transition](#13-multi-tenancy-transition)

---

## 1. Project Overview

RIFF is a **real-time multi-platform inventory management system** for a musical instrument retailer. It keeps stock levels, pricing, and listings synchronised across five sales platforms:

| Platform | Role | API Style |
|---|---|---|
| **Reverb** | Primary source of truth | REST (httpx async) |
| **eBay** | Secondary marketplace | Legacy XML (Trading API) |
| **Shopify** | E-commerce storefront | GraphQL + REST hybrid |
| **Vintage & Rare (V&R)** | Specialist marketplace | Selenium + Cloudflare bypass |
| **WooCommerce** | Self-hosted store | REST (httpx async) |

The system is built with **FastAPI** (async throughout) backed by **PostgreSQL** via **SQLAlchemy 2.0 async ORM**.

---

## 2. Directory Structure

```
WooCommerce-Integration/
├── ARCHITECTURE.md          # This file
├── MULTI_TENANT_IMPLEMENTATION_PLAN.md
├── .pre-commit-config.yaml  # black + isort + flake8 hooks
│
└── inventory_system/
    ├── CLAUDE.md            # Developer instructions & schema reference
    ├── alembic/             # Database migrations
    │   └── versions/
    ├── app/
    │   ├── main.py          # FastAPI app, lifespan, router registration
    │   ├── database.py      # Async engine, session factory, get_session
    │   ├── models.py        # All 25 SQLAlchemy ORM models
    │   ├── core/
    │   │   ├── config.py          # Pydantic Settings (env vars)
    │   │   ├── security.py        # HTTP Basic Auth helpers
    │   │   ├── templates.py       # Jinja2 template instance
    │   │   ├── logging_config.py  # Root logger configuration
    │   │   └── discord_logger.py  # Discord webhook log handler
    │   ├── routes/
    │   │   ├── dashboard.py       # Home dashboard
    │   │   ├── inventory.py       # Core inventory CRUD (6,725 lines)
    │   │   ├── inventory_dropbox.py  # Dropbox file management (1,328 lines)
    │   │   ├── inventory_inspection.py  # Payload inspection/testing
    │   │   ├── orders.py          # Order management UI
    │   │   ├── reports.py         # Sales & activity reports
    │   │   ├── insights.py        # Analytics & insights
    │   │   ├── shipping.py        # Shipping label/profile management
    │   │   ├── settings.py        # App settings UI
    │   │   ├── admin.py           # Admin tools
    │   │   ├── errors.py          # Error page routes
    │   │   ├── health.py          # /health endpoint (no auth)
    │   │   ├── webhooks.py        # Generic inbound webhooks
    │   │   ├── websockets.py      # WebSocket connections
    │   │   └── platforms/
    │   │       ├── ebay.py
    │   │       ├── reverb.py
    │   │       ├── shopify.py
    │   │       ├── vr.py
    │   │       ├── woocommerce.py   # Main WC routes + webhook_router + store_router
    │   │       └── sync_all.py
    │   ├── services/
    │   │   ├── sync_services.py          # SyncService: core orchestration (~2,879 lines)
    │   │   ├── event_processor.py        # EventProcessor: UI-triggered processing
    │   │   ├── reverb_service.py         # ReverbService + ReverbClient
    │   │   ├── shopify_service.py        # ShopifyService + ShopifyGraphQLClient
    │   │   ├── woocommerce_service.py    # WooCommerceService + WooCommerceClient
    │   │   ├── log_review_service.py     # Daily email log aggregation
    │   │   ├── order_processors/
    │   │   │   └── order_sale_processor.py  # OrderSaleProcessor (System A)
    │   │   ├── ebay/
    │   │   │   ├── client.py             # EbayTradingLegacyAPI (XML)
    │   │   │   ├── importer.py           # eBay order importer
    │   │   │   └── ...
    │   │   ├── vintageandrare/
    │   │   │   ├── client.py             # VintageAndRareClient (Selenium)
    │   │   │   ├── inspect_form.py       # Form field introspection
    │   │   │   └── ...
    │   │   └── dropbox/
    │   │       ├── dropbox_async_service.py  # AsyncDropboxClient
    │   │       └── scheduled_sync.py         # DropboxSyncScheduler
    │   ├── static/          # CSS, JS, images
    │   └── templates/       # Jinja2 HTML templates
    ├── scripts/
    │   ├── run_sync_scheduler.py   # Entry point for background scheduler
    │   └── reverb/
    │       └── sync_stocked_orders.py  # One-off order import script
    └── tests/
        ├── conftest.py             # Shared fixtures
        ├── unit/                   # Pure unit tests
        ├── test_routes/            # Route integration tests (in-process)
        └── integration/            # Live API tests (excluded from CI)
```

---

## 3. Core Services

### 3.1 SyncService (`app/services/sync_services.py`)

The central orchestration engine (~2,879 lines). Responsible for:

- **Detection phase**: polling each platform for changes (new listings, price changes, sold items, delisted items)
- **Reconciliation phase**: propagating confirmed local state to all other platforms
- **SyncEvent creation**: writing audit records for every detected change

Key methods:

| Method | Purpose |
|---|---|
| `detect_reverb_changes()` | Poll Reverb listings; emit SyncEvents for diffs |
| `detect_ebay_changes()` | Poll eBay active listings |
| `detect_shopify_changes()` | Poll Shopify products via GraphQL |
| `detect_woocommerce_changes()` | Poll WooCommerce products |
| `reconcile_platform_state()` | Push local state to out-of-sync platforms |
| `process_sync_event()` | Standalone function; process one SyncEvent (used by EventProcessor) |

### 3.2 EventProcessor (`app/services/event_processor.py`)

Thin wrapper around `process_sync_event()` used by UI-triggered actions (e.g. "Re-process" button on the dashboard). Provides structured result objects for display.

### 3.3 OrderSaleProcessor — System A (`app/services/order_processors/order_sale_processor.py`)

Handles the full order-to-sale lifecycle:

1. Inbound order webhook / import → creates `orders` record
2. Marks `products` as sold
3. Creates `sales` record
4. Triggers cross-platform delist

This is the **only** path for order/sale processing. The old `_handle_order_sale` method in SyncService was removed in T0.1.

### 3.4 ReverbService (`app/services/reverb_service.py`)

Wraps `ReverbClient` (httpx async). Key responsibilities:

- Listing CRUD (create, update, end)
- Price and condition synchronisation
- Order polling and import
- Condition slug mapping: `brand-new → NEW`, `excellent → EXCELLENT`, etc.

### 3.5 Platform Clients

| Client | Transport | Notes |
|---|---|---|
| `ReverbClient` | httpx async | OAuth token in env |
| `EbayTradingLegacyAPI` | requests (sync, XML) | Legacy Trading API |
| `ShopifyGraphQLClient` | httpx async | GraphQL primary; REST fallback |
| `WooCommerceClient` | httpx async | Per-store credentials in `woocommerce_stores` table |
| `VintageAndRareClient` | Selenium + curl_cffi | Cloudflare bypass via `tls_client` |

### 3.6 DropboxService (`app/services/dropbox/`)

`AsyncDropboxClient` manages product image storage in Dropbox. A folder-structure cache is loaded at startup and refreshed on a schedule by `DropboxSyncScheduler`. Images are served via temporary links stored in `app/cache/dropbox/temp_links.json`.

---

## 4. Data Flow

### 4.1 Detection Flow (Platform → Local)

```
Scheduler (every 15 min)
    │
    ▼
SyncService.detect_<platform>_changes()
    │
    ├── Fetch listings from platform API
    ├── Compare against local DB state
    └── Emit SyncEvent(type, platform, product_id, payload)
            │
            ▼
        sync_events table (audit log)
```

### 4.2 Reconciliation Flow (Local → Other Platforms)

```
Scheduler (every 15 min) OR UI action
    │
    ▼
SyncService.reconcile_platform_state()
    │
    ├── Query unprocessed SyncEvents
    ├── Determine authoritative local state
    └── Push updates to each out-of-sync platform
            │
            ├── ReverbService.update_listing()
            ├── EbayClient.update_item()
            ├── ShopifyService.update_product()
            ├── WooCommerceService.update_product()
            └── VRClient.update_listing()
```

### 4.3 Order / Sale Flow

```
Platform webhook OR scheduled poll
    │
    ▼
OrderSaleProcessor
    │
    ├── Upsert orders record
    ├── Mark product sold (products.status = 'sold')
    ├── Create sales record
    └── Trigger delist on all active platforms
```

### 4.4 Startup Sequence

```
lifespan()
    ├── configure_logging()
    ├── LogAggregatorHandler (daily email)
    ├── DiscordLogHandler (real-time alerts, WARNING+)
    ├── Run Alembic migrations (if RUN_MIGRATIONS=true)
    ├── Load Dropbox cache from disk
    ├── asyncio.create_task(periodic_dropbox_refresh)
    ├── asyncio.create_task(DailyLogReviewScheduler.run)
    └── ThreadPoolExecutor for V&R Selenium workers
```

---

## 5. Database Schema

All models are in `app/models.py`. PostgreSQL via asyncpg.

### Core Tables

| Table | Model | Description |
|---|---|---|
| `products` | `Product` | Master product catalogue; one row per physical item |
| `platform_common` | `PlatformCommon` | Shared cross-platform listing state (price, status, condition) |
| `sync_events` | `SyncEvent` | Audit log of every detected platform change |
| `sales` | `Sale` | Completed sales records |
| `orders` | `Order` | Inbound orders from any platform |
| `shipments` | `Shipment` | Shipping label + tracking records |
| `shipping_profiles` | `ShippingProfile` | Reusable shipping cost templates |
| `activity_log` | `ActivityLog` | UI-visible activity feed |
| `sync_stats` | `SyncStats` | Per-run sync statistics |
| `sync_errors` | `SyncError` | Persisted sync error details |
| `jobs` | `Job` | Background job tracking |
| `vr_jobs` | `VRJob` | V&R specific Selenium job queue |
| `platform_preferences` | `PlatformPreferences` | Per-platform feature flags and defaults |
| `users` | `User` | Application users (single-tenant: one record) |

### Platform Listing Tables

| Table | Model | Platform |
|---|---|---|
| `reverb_listings` | `ReverbListing` | Reverb active listing state |
| `ebay_listings` | `EbayListing` | eBay active listing state |
| `shopify_listings` | `ShopifyListing` | Shopify product state |
| `vr_listings` | `VRListing` | Vintage & Rare listing state |
| `woocommerce_listings` | `WooCommerceListing` | WooCommerce product state |
| `woocommerce_stores` | `WooCommerceStore` | Multi-store WC credentials |
| `reverb_historical_listings` | `ReverbHistoricalListing` | Archived Reverb listings |

### Platform Order Tables

| Table | Model | Platform |
|---|---|---|
| `reverb_orders` | `ReverbOrder` | Reverb order details |
| `ebay_orders` | `EbayOrder` | eBay order details |
| `shopify_orders` | `ShopifyOrder` | Shopify order details |
| `woocommerce_orders` | `WooCommerceOrder` | WooCommerce order details |

### Key Relationships

```
products (1) ──── (1) platform_common
products (1) ──── (0..1) reverb_listings
products (1) ──── (0..1) ebay_listings
products (1) ──── (0..1) shopify_listings
products (1) ──── (0..1) vr_listings
products (1) ──── (0..1) woocommerce_listings
products (1) ──── (*) sync_events
products (1) ──── (0..1) sales
products (1) ──── (*) shipments
```

---

## 6. Authentication & Security

### Current (Phase 0)

HTTP Basic Auth on all routes except:
- `/health` — unauthenticated health check
- `/webhooks/*` — HMAC-verified inbound webhooks
- `/wc/webhooks/*` — WooCommerce HMAC webhooks
- WebSocket connections — token in query param

Credentials are set via environment variables:
```
BASIC_AUTH_USERNAME=<username>
BASIC_AUTH_PASSWORD=<password>
```

Security helper: `app/core/security.py`
- `get_current_username()` — Depends-injectable Basic Auth check
- `require_auth()` — convenience wrapper returning `[Depends(get_current_username)]`

### Phase 2 Target

Replace HTTP Basic Auth with **Supabase JWT** tokens for multi-tenant user management. All routes will gain a `tenant_id` scope from the JWT claims.

---

## 7. Sync Scheduling

Entry point: `scripts/run_sync_scheduler.py`

The scheduler uses interval-aligned jobs (fires at wall-clock multiples of the interval, not relative to start time).

| Job | Interval | Description |
|---|---|---|
| Reverb detection | 15 min | Detect Reverb listing changes |
| eBay detection | 15 min | Detect eBay listing changes |
| Shopify detection | 15 min | Detect Shopify product changes |
| WooCommerce detection | 15 min | Detect WooCommerce product changes |
| V&R detection | 15 min | Detect V&R listing changes (Selenium) |
| Reverb reconciliation | 15 min | Push local state → Reverb |
| eBay reconciliation | 15 min | Push local state → eBay |
| Shopify reconciliation | 15 min | Push local state → Shopify |
| WooCommerce reconciliation | 15 min | Push local state → WooCommerce |
| V&R reconciliation | 15 min | Push local state → V&R |
| Reverb order sync | 30 min | Import new Reverb orders |
| State reconciliation (full) | 6 hours | Cross-platform state audit |

---

## 8. Platform Integrations

### 8.1 Reverb

- **Client**: httpx async, bearer token auth
- **Key features**: listing CRUD, order polling, condition mapping
- **Condition slug mapping** (critical — see known limitations):
  ```python
  'brand-new' → 'NEW'
  'mint'      → 'EXCELLENT'
  'excellent' → 'EXCELLENT'
  'very-good' → 'VERY_GOOD'
  'good'      → 'GOOD'
  'fair'      → 'FAIR'
  'poor'      → 'POOR'
  ```
- **Webhook**: inbound sold/order events at `/webhooks/reverb`

### 8.2 eBay

- **Client**: `EbayTradingLegacyAPI` — synchronous requests, XML serialisation
- **Auth**: App ID + Cert ID + Auth token (env vars)
- **Key features**: GetMyeBaySelling, ReviseInventoryStatus, EndItems
- **Note**: Runs in `ThreadPoolExecutor` to avoid blocking the async event loop

### 8.3 Shopify

- **Client**: `ShopifyGraphQLClient` — httpx async, Admin API
- **Auth**: Shopify access token per store
- **Key features**: product create/update/archive via GraphQL mutations; inventory level management via REST
- **Webhook**: inbound order events at `/webhooks/shopify`

### 8.4 Vintage & Rare (V&R)

- **Client**: `VintageAndRareClient` — Selenium WebDriver + curl_cffi for Cloudflare TLS bypass
- **Auth**: username/password login (browser automation)
- **Key features**: listing create/update, price change, delist
- **Threading**: runs in dedicated `ThreadPoolExecutor` (`app.state.vr_executor`, 1 worker)
- **Job queue**: `vr_jobs` table; jobs are claimed by the worker, executed, then marked complete/failed

### 8.5 WooCommerce

- **Client**: `WooCommerceClient` — httpx async, consumer key/secret per store
- **Multi-store**: credentials stored per-store in `woocommerce_stores` table
- **Key features**: product create/update/delete, order import
- **Routers in main.py**:
  - `woocommerce_router` — main product management (auth required)
  - `wc_webhook_router` — inbound webhooks (HMAC verified, no auth)
  - `wc_store_router` — store credential management (auth required)

---

## 9. API Endpoints Overview

All routes require HTTP Basic Auth unless noted.

### Dashboard & Core
| Method | Path | Description |
|---|---|---|
| GET | `/` | Redirect → `/inventory` |
| GET | `/dashboard` | Main dashboard |
| GET | `/health` | Health check (no auth) |
| GET | `/db-test` | Database connectivity test |

### Inventory
| Method | Path | Description |
|---|---|---|
| GET | `/inventory` | Inventory list view |
| GET | `/inventory/{id}` | Product detail view |
| POST | `/inventory` | Create product |
| PUT | `/inventory/{id}` | Update product |
| DELETE | `/inventory/{id}` | Delete product |
| POST | `/inventory/{id}/sync` | Trigger manual sync |
| GET | `/inventory/api/products` | JSON product list |

### Dropbox (image management)
| Method | Path | Description |
|---|---|---|
| GET | `/inventory/api/dropbox/folders` | List folder structure |
| GET | `/inventory/api/dropbox/images` | List images for folder |
| POST | `/inventory/api/dropbox/init` | Trigger Dropbox scan |
| POST | `/inventory/api/dropbox/refresh` | Force cache refresh |

### Platform Routes
| Method | Path | Description |
|---|---|---|
| POST | `/reverb/sync` | Sync all to Reverb |
| POST | `/ebay/sync` | Sync all to eBay |
| POST | `/shopify/sync` | Sync all to Shopify |
| POST | `/vr/sync` | Sync all to V&R |
| POST | `/woocommerce/sync` | Sync all to WooCommerce |
| POST | `/sync-all` | Trigger full multi-platform sync |

### Orders
| Method | Path | Description |
|---|---|---|
| GET | `/orders` | Order list view |
| GET | `/orders/{id}` | Order detail |
| POST | `/orders/{id}/process` | Process order → sale |

### Reports & Insights
| Method | Path | Description |
|---|---|---|
| GET | `/reports` | Sales reports |
| GET | `/reports/sales` | Sales data (JSON) |
| GET | `/insights` | Analytics dashboard |

### Webhooks (no auth — HMAC verified)
| Method | Path | Description |
|---|---|---|
| POST | `/webhooks/reverb` | Reverb sold/order events |
| POST | `/webhooks/shopify` | Shopify order events |
| POST | `/wc/webhooks/order` | WooCommerce order events |
| POST | `/wc/webhooks/product` | WooCommerce product events |

### Admin
| Method | Path | Description |
|---|---|---|
| GET | `/admin` | Admin panel |
| POST | `/admin/fix-conditions` | Bulk condition repair |
| POST | `/admin/reprocess-events` | Bulk SyncEvent reprocess |

---

## 10. Testing Strategy

### Structure

```
tests/
├── conftest.py           # Fixtures: async_client, db_session, mock settings
├── unit/                 # 8 files — pure logic tests (no DB, no HTTP)
├── test_routes/          # 23 files — route tests via TestClient/AsyncClient
└── integration/          # Live API tests — excluded from CI
```

### Running Tests

```bash
# Standard run (from inventory_system/)
SECRET_KEY="test" DATABASE_URL="sqlite+aiosqlite:///:memory:" \
  pytest tests/ \
  --ignore=tests/integration \
  --ignore=tests/unit/test_ebay_item_specifics.py \
  -v
```

### Key Fixtures (`conftest.py`)

| Fixture | Scope | Purpose |
|---|---|---|
| `async_client` | function | HTTPX AsyncClient with in-memory DB |
| `db_session` | function | Isolated async DB session (rolled back after test) |
| `mock_settings` | function | Patched Settings with test credentials |
| `auth_headers` | function | Basic Auth headers for test requests |

### Coverage

- **Overall: 18%** (29,080 statements, 5,229 covered) as of Phase 0
- `app/services/sync_services.py`: 8% (critical path undertested)
- `app/routes/inventory.py`: 14%
- `app/models.py`: 95% (models fully covered by route tests)
- See `coverage_report.txt` for per-module breakdown

### Known Test Issues

- `tests/unit/test_ebay_item_specifics.py`: `ModuleNotFoundError: No module named 'app.services.ebay.spec_fields'` — always skip
- `tests/integration/`: require live API keys — always exclude from CI
- Pre-existing failures: 53 tests fail on the baseline (pre-Phase-0) — no regressions introduced by Phase 0

---

## 11. Key Design Decisions

### Single Source of Truth: Reverb

Reverb is treated as the authoritative source for product state. When a conflict is detected, Reverb's data wins. All other platforms are kept in sync with Reverb's state.

### SyncEvent Pattern

Every detected change is recorded as a `SyncEvent` before any action is taken. This provides:
- Full audit trail
- Reprocessing capability (UI "re-process" button)
- Decoupling of detection from reconciliation
- Visibility into what changed and when

### Two-Phase Sync

Detection and reconciliation are separate phases run by independent scheduler jobs. This means:
- Detection failures don't block reconciliation
- Reconciliation can be triggered manually without re-detecting
- Each phase can be scaled independently

### Async Throughout (Except eBay + V&R)

FastAPI + SQLAlchemy 2.0 async + asyncpg gives full async I/O. eBay (legacy XML) and V&R (Selenium) are synchronous and run in `ThreadPoolExecutor` pools to avoid blocking the event loop.

### Per-Store WooCommerce

WooCommerce supports multiple stores via the `woocommerce_stores` table. Each store has its own API credentials. This was the original motivation for the multi-tenancy work.

---

## 12. Known Limitations

### Reverb Condition Bug (partially fixed)

Brian May guitars stored with wrong condition (`GOOD` instead of `NEW`) because the condition slug `brand-new` was not in the mapping. Fixed in commit `d945150`. However:

- Existing affected products need manual remediation via `fix_brian_may_condition.py`
- A Reverb re-sync is needed to push corrected conditions

### Low Test Coverage

At 18% overall, large portions of critical sync logic are not tested. In particular:
- `sync_services.py` at 8% means reconciliation logic has almost no test coverage
- V&R Selenium paths are effectively untestable without a running browser

### V&R Fragility

Vintage & Rare automation relies on browser automation against a live website. Any V&R site update can break the integration. The Cloudflare bypass (`curl_cffi`) requires periodic maintenance.

### Sales Report Duplicates

The sales report queries `sync_events` partitioned by `(product_id, DATE)`. An item sold on multiple days (e.g. relisted and resold) appears multiple times. The partial unique index only prevents duplicate *pending* events; processed events can recur. See `memory/sales_duplicates_diagnosis.md`.

### eBay Legacy API

eBay's Trading API (XML-based) is deprecated. Migration to the newer REST API is needed but not yet planned.

---

## 13. Multi-Tenancy Transition

The full transition plan is in `MULTI_TENANT_IMPLEMENTATION_PLAN.md`. The high-level phases:

| Phase | Description | Status |
|---|---|---|
| **Phase 0** | Code cleanup & stabilisation | In progress |
| **Phase 1** | Database schema — add `tenant_id` to all tables | Not started |
| **Phase 2** | Authentication — replace Basic Auth with Supabase JWT | Not started |
| **Phase 3** | Service layer — tenant-scoped queries everywhere | Not started |
| **Phase 4** | Platform credentials — per-tenant API key storage | Not started |
| **Phase 5** | UI — tenant onboarding, settings, billing | Not started |

### Phase 0 Constraints (must not be violated until Phase 1+)

- No `tenant_id` columns added yet
- All queries remain single-tenant
- All env vars remain global (not per-tenant)
- Backward compatibility maintained throughout

### Key Migration Risks

1. **SyncEvent fan-out**: adding `tenant_id` to sync_events requires careful migration to avoid re-processing historical events
2. **V&R Selenium**: inherently single-tenant (one browser session); multi-tenant V&R requires a job queue per tenant
3. **Reverb "source of truth" assumption**: in a multi-tenant world, each tenant has their own Reverb account — the conflict resolution logic needs rethinking
