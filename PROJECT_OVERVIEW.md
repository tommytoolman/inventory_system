# RIFF — Project Overview

> **RIFF** = **Realtime Inventory Fast Flow**
>
> Generated from source code analysis on 2026-03-12. Every claim below is verified from the codebase; nothing is assumed.

---

## 1. What the Product Is

RIFF is a **multi-platform inventory management system** built for a single independent music-gear retailer (currently one client). It acts as a central hub that synchronises product listings, stock levels, prices, and orders across five online marketplaces:

- **Reverb** (primary/source-of-truth marketplace for musical instruments)
- **eBay UK**
- **Shopify**
- **Vintage & Rare (V&R)** (specialist vintage instruments marketplace)
- **WooCommerce** (self-hosted e-commerce)

**Who uses it:** The retailer's staff access RIFF via a browser-based dashboard to manage their inventory, monitor sync status, process orders, view analytics, and trigger cross-platform operations. There is no public-facing storefront — RIFF is a back-office tool.

**What problem it solves:** Without RIFF, the retailer would need to manually update listings across five marketplaces every time stock changes, a product sells, or a price is adjusted. RIFF detects changes on each platform, reconciles them against the master product record, and propagates updates to all other platforms — preventing overselling, keeping prices consistent, and eliminating hours of manual data entry.

---

## 2. Core Features

### Inventory Management
- Central product database with 40+ fields (brand, model, SKU, pricing, condition, images, shipping, etc.)
- Product CRUD via web UI and REST API
- Auto-generated SKU sequences
- Draft/active/sold/archived lifecycle management
- Stocked-item support with quantity tracking (vs. one-off items)
- Image management via Dropbox integration (folder scanning, temporary link generation, scheduled sync)

### Multi-Platform Sync Engine
- **Detect → Reconcile → Propagate** pipeline: pulls data from each platform, compares against local DB, generates sync events, then pushes changes outward
- Sync event types: new listings, status changes, price changes, quantity changes, removed listings
- Per-platform status normalisation (e.g., eBay "Completed" → "sold", Reverb "live" → "active")
- Cross-platform sale propagation (item sold on Reverb → end listing on eBay, archive on Shopify, mark sold on V&R)
- Concurrent sync orchestration with configurable parallelism (1–10 platforms)
- Retry with exponential backoff on network failures
- Sync event audit trail (every detected change is logged as a `SyncEvent` record)

### Listing Creation
- Create listings on any platform from the master product record
- Platform-specific field mapping (eBay Item Specifics, Shopify metafields, V&R form fields, WooCommerce meta_data)
- Category mapping across platforms (Reverb → eBay, Reverb → Shopify, V&R → Shopify, eBay → Shopify) via JSON mapping files
- Condition mapping across platforms
- Per-platform price markup calculations
- eBay HTML listing template with conditional "Artist Owned" badge, auto-formatted descriptions
- Payload inspection/preview before creating live listings

### Order Management
- Unified order view across eBay, Reverb, Shopify, WooCommerce
- Order detail pages with shipping information
- DHL Express shipping label generation (shipper config, rate calculation, label PDF download)
- Sale processing: stock decrement, cross-platform propagation, email alerts
- Webhook receivers for real-time order notifications (Shopify HMAC, WooCommerce HMAC, website signature)

### Reports & Analytics
- **Sync Events Viewer**: browse, filter, and manually process pending sync events
- **Platform Coverage**: which products are listed on which platforms
- **Status Mismatches**: products with inconsistent statuses across platforms
- **Listing Health**: traffic-light health check (images, descriptions, completeness)
- **CrazyLister Coverage**: eBay template migration tracking
- **Price Inconsistencies**: cross-platform price discrepancy detection with one-click fix
- **Sales & Ended Listings**: sales report with CSV/PDF export
- **Non-Performing Inventory**: aged stock analysis with recommendations
- **Inventory Reconciliation**: detect and resolve data drift
- **Listing Engagement**: views/watches tracking over time
- **V&R Image Health**: V&R-specific image validation
- **Archive Status Sync**: bulk archival of sold/ended products
- **Sync Statistics**: per-platform sync run history and metrics

### Insights Dashboard
- Category velocity benchmarks (from Reverb historical data)
- Inventory health summary (age distribution, platform coverage, total value)
- Aged inventory identification with actionable recommendations (missing platforms, overpriced, low engagement, dead stock)

### Product Matching
- Heuristic matching of external platform listings to local products
- Scoring: SKU match (1.0 confidence), then brand (0.35), model (0.35), title (0.2), year (0.1), price (0.1), description (0.05)
- Manual confirm/merge UI for ambiguous matches
- Match history tracking

### Settings & Administration
- Per-user platform visibility preferences (show/hide platforms on dashboard)
- Admin sync event management (query, delete)
- Batch eBay template application
- Health check endpoints (DB connectivity, migration status, schema audit)

### Notifications & Logging
- **Discord**: Real-time WARNING+ log alerts via webhook, batched every 5 seconds, with rate-limit handling and sensitive field redaction
- **Email**: SMTP-based sale alert notifications
- **Activity Log**: Auditable record of all system actions (syncs, sales, etc.)
- **Sync Error Tracking**: Persistent error records with resolution workflow (error ID, stack trace, platform, operation, resolve with notes)
- **WebSocket**: Real-time sync progress updates to browser UI

---

## 3. Architecture Overview

### Tech Stack

| Layer | Technology |
|-------|-----------|
| **Language** | Python 3.12 |
| **Web Framework** | FastAPI 0.115.8 + Uvicorn 0.34.0 |
| **Database** | PostgreSQL (via asyncpg 0.30.0) |
| **ORM** | SQLAlchemy 2.0.37 (async, declarative) |
| **Migrations** | Alembic 1.14.1 (async) |
| **Templating** | Jinja2 3.1.4 |
| **Frontend** | Server-rendered HTML + TailwindCSS (CDN) + vanilla JavaScript |
| **HTTP Clients** | httpx 0.27.0 (async), requests 2.32.3, aiohttp 3.9.5 |
| **Data Processing** | pandas 2.2.2, numpy 1.26.4 |
| **String Matching** | fuzzywuzzy 0.18.0 + python-Levenshtein |
| **Image Processing** | Pillow 10.4.0 |
| **PDF Generation** | ReportLab 4.0.8 |
| **XML Parsing** | xmltodict 0.13.0 (for eBay Trading API) |
| **Web Scraping** | Selenium 4.21.0, curl_cffi (Cloudflare bypass) |
| **Cloud Storage** | Dropbox SDK 12.0.2 |
| **eBay SDK** | ebaysdk 2.2.0 (Trading XML API) |
| **Testing** | pytest + pytest-asyncio + pytest-mock |
| **Containerisation** | Docker (python:3.12-slim) |
| **Hosting** | Railway |
| **Notifications** | Discord webhooks (TypeScript service), SMTP email |

### Backend Structure

```
inventory_system/app/
├── main.py                  # FastAPI app, lifespan, middleware, router mounting
├── database.py              # Async SQLAlchemy engine + session factory
├── dependencies.py          # FastAPI dependency injection (DB session)
│
├── core/                    # Cross-cutting concerns
│   ├── config.py            # Pydantic Settings (all env vars)
│   ├── auth.py              # HTTP Basic Auth verification
│   ├── security.py          # Multi-user auth with env var parsing
│   ├── enums.py             # ProductStatus, ProductCondition, ListingStatus, etc.
│   ├── exceptions.py        # Exception hierarchy
│   ├── events.py            # StockUpdateEvent model
│   ├── discord_logger.py    # Discord webhook log handler
│   ├── logging_config.py    # Centralised logging setup
│   ├── templates.py         # Jinja2 template initialisation
│   └── utils.py             # ImageTransformer, pagination, eBay HTML cleaner
│
├── models/                  # SQLAlchemy ORM models (27 tables)
├── schemas/                 # Pydantic request/response validation
├── routes/                  # FastAPI routers (22 routers, ~217 endpoints)
│   └── platforms/           # Per-platform API routes
├── services/                # Business logic layer
│   ├── ebay/                # eBay API client, auth, importer, trading API
│   ├── reverb/              # Reverb API client, auth, sync, importer
│   ├── shopify/             # Shopify GraphQL/REST client, auth, sync, importer
│   ├── woocommerce/         # WooCommerce REST client, auth, sync, importer, errors
│   ├── vintageandrare/      # V&R Selenium client, brand validator, CSV export
│   ├── dropbox/             # Dropbox image sync (sync + async clients)
│   ├── shipping/            # Multi-carrier shipping (DHL, UPS, FedEx stubs)
│   ├── category_mappings/   # JSON mapping files between platforms
│   ├── websockets/          # WebSocket connection manager
│   ├── sync_services.py     # Central sync coordinator
│   ├── event_processor.py   # Cross-platform event processing
│   ├── order_sale_processor.py  # Sale detection + stock propagation
│   ├── pricing.py           # Per-platform markup calculations
│   ├── match_utils.py       # Fuzzy product matching
│   ├── notification_service.py  # Email alerts
│   ├── error_logger.py      # Sync error persistence + Discord forwarding
│   └── vr_job_queue.py      # Async job queue for V&R Selenium operations
│
├── templates/               # Jinja2 HTML templates (server-rendered pages)
├── static/                  # CSS, JS, images, uploads
└── data/                    # Static data files (spec_fields.py)
```

### Data Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                        EXTERNAL PLATFORMS                            │
│  Reverb API  │  eBay Trading/REST API  │  Shopify GraphQL  │  V&R  │  WooCommerce REST  │
└──────┬───────┴──────────┬──────────────┴─────────┬─────────┴───┬───┴──────────┬──────────┘
       │                  │                        │             │              │
       ▼                  ▼                        ▼             ▼              ▼
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│                              PLATFORM CLIENTS                                             │
│  ReverbClient  │  EbayClient/EbayTradingLegacyAPI  │  ShopifyGraphQLClient  │            │
│                │                                    │                        │  VRClient  │  WCClient
└──────┬─────────┴──────────────┬─────────────────────┴───────────┬────────────┴──────┬─────┘
       │                        │                                 │                   │
       ▼                        ▼                                 ▼                   ▼
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│                            PLATFORM SERVICES (Facades)                                    │
│  ReverbService  │  EbayService  │  ShopifyService  │  VRService  │  WooCommerceService    │
└──────┬──────────┴──────┬────────┴──────────┬───────┴──────┬─────┴──────────┬─────────────┘
       │                 │                   │              │                │
       ▼                 ▼                   ▼              ▼                ▼
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│                         SYNC & EVENT PROCESSING                                           │
│  SyncService (detect → reconcile → propagate)                                             │
│  EventProcessor (cross-platform listing creation)                                         │
│  OrderSaleProcessor (sale detection, stock decrement, propagation)                        │
└──────┬──────────────────────────────────────────────────────────────────────────────┬─────┘
       │                                                                              │
       ▼                                                                              ▼
┌───────────────────────┐                                              ┌───────────────────────┐
│     PostgreSQL DB      │                                              │   Notifications        │
│  Products              │                                              │   Discord webhooks     │
│  PlatformCommon        │                                              │   Email (SMTP)         │
│  *_listings (x5)       │                                              │   WebSocket (browser)  │
│  *_orders (x4)         │                                              └───────────────────────┘
│  SyncEvents            │
│  SyncErrors            │
│  ActivityLog           │
└───────────────────────┘
```

**Sync cycle (triggered via API or background scheduler):**
1. Platform client fetches current listings from external API
2. Importer compares against local DB records
3. Differences generate `SyncEvent` records (type: new_listing, status_change, price_change, quantity_change, removed)
4. `SyncService.reconcile_sync_run()` processes pending events
5. For each event, `EventProcessor` determines required actions on other platforms
6. Platform services push changes outward (create/update/end listings)
7. Results logged to `ActivityLog`, errors to `SyncErrorRecord`, progress via WebSocket

---

## 4. Current Integrations

### Reverb
- **Protocol:** REST API v3 via httpx (async)
- **Auth:** Bearer token (API key from env var `REVERB_API_KEY`)
- **Capabilities:** Full CRUD — list/create/update/end/publish listings, fetch orders, categories, conditions, shipping profiles
- **Currency:** GBP (`X-Display-Currency: GBP`)
- **Data pulled:** Active listings, sold orders (with pagination + retry), listing stats (views/watches)
- **Status:** Production-ready, primary integration

### eBay UK
- **Protocol:** Dual — XML Trading API (legacy, via ebaysdk) + REST Inventory API v1 (via httpx)
- **Auth:** OAuth 2.0 — refresh token in env, access token refreshed in-memory with 5-min expiry buffer. Credentials: `EBAY_CLIENT_ID`, `EBAY_CLIENT_SECRET`, `EBAY_DEV_ID`, `EBAY_RU_NAME`, `EBAY_REFRESH_TOKEN`
- **Marketplace:** EBAY_GB (site ID 3)
- **Capabilities:** Full CRUD — inventory items, offers, publish/unpublish, orders, categories, category aspects, listing policies
- **Special:** Custom HTML listing template replacing CrazyLister, with "Artist Owned" badge and auto-formatted descriptions
- **Status:** Production-ready

### Shopify
- **Protocol:** Hybrid GraphQL Admin API + REST Admin API (via httpx)
- **Auth:** Access token (`X-Shopify-Access-Token` header) from env var `SHOPIFY_ACCESS_TOKEN`
- **Capabilities:** Product CRUD (GraphQL), variant/inventory updates (REST), webhook receiver (HMAC-SHA256 validated)
- **Webhooks:** Order creation webhook with `X-Shopify-Hmac-Sha256` signature verification
- **Metafields:** `custom` namespace for: country_of_origin, artist_owned, artist_names, handedness, colour_finish, year, condition
- **Status:** Production-ready

### Vintage & Rare (V&R)
- **Protocol:** No official API — Selenium browser automation + HTTP requests with Cloudflare bypass
- **Auth:** Form-based login, cookies stored as base64 in env var `VR_COOKIES_BASE64`. Cloudflare bypass via `curl_cffi` (Chrome TLS fingerprint) or Selenium
- **Capabilities:** Login, inventory CSV download/parse, listing creation (Selenium form automation), mark sold/delete (AJAX endpoints), brand validation (AJAX)
- **Job Queue:** Async queue (`vr_jobs` table) because Selenium operations are slow and can only run one at a time (semaphore-controlled)
- **Cookie Harvest:** API endpoints to trigger Selenium-based cookie refresh
- **Known constraint:** Cloudflare `cf_clearance` cookie has ~1 year validity; needs manual refresh via browser or Selenium
- **Status:** Production-ready but fragile (Cloudflare-dependent)

### WooCommerce
- **Protocol:** REST API v3 via httpx (async, persistent connection pool)
- **Auth:** Basic Auth (HTTPS) or query-string auth (HTTP). Credentials: `WC_STORE_URL`, `WC_CONSUMER_KEY`, `WC_CONSUMER_SECRET`
- **Multi-tenant:** `WooCommerceStore` model supports multiple WC stores with per-store credentials
- **Capabilities:** Products CRUD (including batch), categories, orders, webhooks, system status, inventory levels
- **Webhooks:** HMAC-SHA256 signature verification, delivery ID deduplication cache
- **Error handling:** Typed exception hierarchy (auth, connection, rate-limit, validation, etc.) with `WCErrorTracker` per sync run
- **Status:** Production-ready, most recently built integration (extensive 3-pass audit)

### Dropbox
- **Protocol:** Dropbox API v2 via official SDK (sync) + aiohttp (async)
- **Auth:** OAuth2 refresh token flow
- **Capabilities:** Recursive folder scanning, temporary link generation (with caching and 50-worker parallel fetching), change polling via longpoll/cursor, scheduled daily sync (3:00 AM)
- **Purpose:** Product image storage — images are stored in Dropbox folders, RIFF generates temporary links for display and platform uploads
- **Status:** Production-ready

### DHL Express
- **Protocol:** REST API via httpx
- **Auth:** Configured via `DHL_SHIPPER_*` env vars
- **Capabilities:** Rate calculation, shipment creation, label PDF generation, tracking
- **Product codes:** N (Domestic), P (Worldwide Package Express), U (Express Easy), D (Express Documents)
- **Status:** ~85% complete (POST route for label creation and live testing still pending)

### Discord
- **Protocol:** Webhook HTTP POST
- **Implementation:** Separate TypeScript/Node.js service (`discord-logger/`) + Python handler in core
- **Features:** Batched messages (every 5s), queue max 1000, 3x retry with exponential backoff, 429 rate-limit handling, sensitive field redaction
- **Purpose:** Real-time operational alerts (WARNING+ level logs)
- **Status:** Production-ready

---

## 5. Messaging System

### Inbound (Platform → RIFF)
- **Shopify order webhooks:** POST to `/api/webhooks/orders`, HMAC-SHA256 validated via `X-Shopify-Hmac-Sha256`
- **WooCommerce webhooks:** POST to WooCommerce webhook endpoints, HMAC-SHA256 validated, delivery ID deduplication
- **Website sale webhooks:** POST to `/webhooks/website/sale`, validated via `X-Website-Signature` header (currently noted as legacy — "moving to Shopify")
- **Polling-based sync:** All platforms are also polled via their respective sync endpoints (triggered manually or by background scheduler)

### Internal (RIFF ↔ Browser)
- **WebSocket** at `/ws`: Real-time sync progress updates pushed to connected browser clients
- **Toast notifications** in UI: success/error/info with auto-dismiss (3s info, 5s error)

### Outbound (RIFF → External)
- **Discord webhook:** WARNING+ log messages batched and sent to a Discord channel for operational monitoring
- **Email (SMTP):** Sale alert notifications with product details, price, platform info, and which other platforms were updated
- **API calls to platforms:** All outbound sync operations (create/update/end listings, update inventory, etc.)

The messaging is primarily **one-way inbound** (webhooks) or **polling-based**, with outbound limited to notifications (Discord, email) and platform API calls. There is no message queue infrastructure (no RabbitMQ, Redis, Celery, etc.) — sync operations are handled via FastAPI background tasks and the V&R job queue table.

---

## 6. Authentication & User Model

### Application Auth
- **HTTP Basic Auth**: All dashboard and management routes require Basic Auth via `require_auth()` dependency
- **Multi-user support:** `BASIC_AUTH_CREDENTIALS` env var contains comma-separated `user:pass` pairs (parsed at startup)
- **Users table** exists in DB (`users` model with `username`, `email`, `hashed_password`, `is_active`, `is_superuser`) but is **not actively used for auth** — the env-var-based Basic Auth is the primary mechanism
- **Per-user preferences:** `platform_preferences` table stores per-username platform visibility settings

### Platform Auth
| Platform | Auth Method | Credential Storage |
|----------|------------|-------------------|
| Reverb | Bearer token (API key) | `REVERB_API_KEY` env var |
| eBay | OAuth 2.0 (refresh token → access token) | `EBAY_CLIENT_ID`, `EBAY_CLIENT_SECRET`, `EBAY_REFRESH_TOKEN` env vars |
| Shopify | Access token | `SHOPIFY_ACCESS_TOKEN` env var |
| V&R | Form login + cookies | `VR_USERNAME`, `VR_PASSWORD`, `VR_COOKIES_BASE64` env vars |
| WooCommerce | Basic Auth (consumer key/secret) | `WC_CONSUMER_KEY`, `WC_CONSUMER_SECRET` env vars (or per-store in `woocommerce_stores` table) |
| Dropbox | OAuth2 refresh token | `DROPBOX_REFRESH_TOKEN`, `DROPBOX_APP_KEY`, `DROPBOX_APP_SECRET` env vars |
| DHL | Shipper credentials | `DHL_SHIPPER_*` env vars |
| Discord | Webhook URL | `DISCORD_WEBHOOK_URL` env var |

### Multi-Tenancy Status
- **Current state:** Single-tenant. One retailer, one set of platform credentials.
- **WooCommerce multi-tenant foundation:** The `woocommerce_stores` table supports multiple WC stores with per-store credentials, price markup, and sync status. `wc_store_id` FK added to `woocommerce_listings` and `woocommerce_orders`.
- **Full multi-tenant roadmap** exists in `docs/multi-tenant-roadmap.md` (schema-per-tenant, JWT auth, tenant middleware, Stripe billing) but is **not implemented** beyond the WC store model.

---

## 7. Database Schema

### PostgreSQL (async via asyncpg)

**27 tables** in the current schema. Core tables and relationships:

```
products (40 cols)
  ├── 1:N → platform_common (bridge table linking product to platform listings)
  │         ├── 1:1 → reverb_listings (23 cols)
  │         ├── 1:1 → ebay_listings (32 cols)
  │         ├── 1:1 → shopify_listings (22 cols)
  │         ├── 1:1 → vr_listings (15 cols)
  │         └── 1:1 → woocommerce_listings (20+ cols)
  ├── 1:N → sync_events (audit trail of detected changes)
  ├── 1:N → sync_errors (error records with stack traces)
  ├── 1:N → vr_jobs (V&R Selenium job queue)
  ├── 1:N → listing_stats_history (daily engagement snapshots)
  ├── 1:N → reverb_orders
  ├── 1:N → ebay_orders
  ├── 1:N → shopify_orders
  └── 1:N → woocommerce_orders

woocommerce_stores (multi-tenant WC credentials)
  ├── 1:N → woocommerce_listings
  └── 1:N → woocommerce_orders

category_mappings (cross-platform category links)
platform_preferences (per-user UI settings)
shipping_profiles (predefined shipping configs)
shipments + shipment_items + shipping_rates + label_files
activity_log (system audit)
users (DB-backed user model — not actively used for auth)
orders (simple order reference — legacy)
sales (platform sale events)
webhook_events (legacy — not actively used)
sync_stats (cumulative sync statistics)
product_mappings (duplicate product linking)
category_velocity_stats + inventory_health_snapshots (analytics)
reverb_historical_listings (historical data for benchmarks)
```

### Key Table Schemas

**products** (40 columns):
`id`, `sku` (unique), `brand`, `model`, `category`, `year`, `decade`, `finish`, `description`, `base_price`, `cost_price`, `price`, `price_notax`, `collective_discount`, `offer_discount`, `status` (enum: DRAFT/ACTIVE/SOLD/ARCHIVED/DELETED), `condition` (enum: NEW/EXCELLENT/VERYGOOD/GOOD/FAIR/POOR), `is_sold`, `in_collective`, `in_inventory`, `in_reseller`, `free_shipping`, `buy_now`, `show_vat`, `local_pickup`, `available_for_shipment`, `is_stocked_item`, `quantity`, `shipping_profile_id`, `serial_number`, `handedness` (enum), `artist_owned`, `artist_names`, `manufacturing_country` (enum), `inventory_location` (enum), `storefront` (enum), `case_status` (enum), `case_details`, `extra_attributes` (JSONB), `primary_image`, `additional_images` (Text), `video_url`, `external_link`, `processing_time`, `platform_data` (JSONB), `created_at`, `updated_at`

**platform_common** (11 columns):
`id`, `product_id` (FK), `platform_name`, `external_id`, `status`, `sync_status`, `listing_url`, `platform_specific_data` (JSONB), `last_sync`, `created_at`, `updated_at`

**sync_events**:
`id`, `product_id` (FK), `platform`, `event_type` (enum: new_listing/status_change/price_change/quantity_change/removed/order_sale), `old_value`, `new_value`, `sync_status` (pending/processed/failed/skipped), `sync_run_id`, `details` (JSONB), `created_at`, `processed_at`

### Custom PostgreSQL Enums
`productstatus`, `productcondition`, `listingstatus`, `syncstatus`, `synceventtype`, `shipmentstatus`, `handedness`

---

## 8. Infrastructure

### Hosting
- **Platform:** Railway (PaaS)
- **Container:** Docker (python:3.12-slim)
- **Port:** 8080 (Railway convention)
- **Entry point:** `python -m uvicorn app.main:app --host 0.0.0.0 --port 8080`

### Database
- **PostgreSQL** hosted on Railway
- **Connection:** `DATABASE_URL` env var (converted to `postgresql+asyncpg://` at runtime)
- **Migrations:** Alembic, optionally auto-run on startup via `RUN_MIGRATIONS=true` env var, also triggerable via `/health/migrate` endpoint (requires `MIGRATE_SECRET`)

### Background Processing
- **No dedicated task queue** (no Celery, Redis, or similar)
- **FastAPI BackgroundTasks** for async sync operations
- **Custom scheduler:** `DropboxSyncScheduler` (daily 3:00 AM sync), `DailyLogReviewScheduler`
- **V&R job queue:** Database-backed (`vr_jobs` table) with `SKIP LOCKED` row-level locking, semaphore-controlled single concurrency
- **ThreadPoolExecutor(max_workers=1)** for V&R Selenium worker

### External Services
| Service | Purpose |
|---------|---------|
| Railway | Hosting (app + PostgreSQL) |
| Dropbox | Product image storage |
| Discord | Operational alerts via webhook |
| SMTP server | Sale notification emails |
| DHL Express API | Shipping labels (partially complete) |

### DNS/CDN
- No CDN configuration found in the codebase
- TailwindCSS loaded from CDN (`cdn.tailwindcss.com`)
- eBay badge images self-hosted or base64 data URIs

### Monitoring
- `/health` — basic health check
- `/health/db` — database connectivity + table listing
- `/health/db-audit` — comprehensive schema audit (columns, types, indexes, FKs, enums)
- Discord webhook alerts for WARNING+ log messages
- Sync error tracking UI (`/errors/sync`)
- No external APM or monitoring service integration found

---

## 9. Current Limitations & Gaps

### Incomplete / Stubbed Out

1. **DHL shipping integration** (~85% complete): Missing POST route for label creation, Railway env var setup, and live testing. Paused pending DHL password reset.
2. **UPS and FedEx carriers**: Factory pattern exists in `shipping/factory.py` but only DHL is implemented. `BaseCarrier` ABC defined but UPS/FedEx are stubs.
3. **`webhook_events` table**: Marked as "Currently not being used. Was for old website, moving to Shopify." Legacy, not wired up.
4. **`users` table**: Full model exists but auth runs on env-var-based Basic Auth, not DB-backed users. `is_superuser` field unused.
5. **`docs/api/` documentation**: `architecture.md`, `models.md`, `platform_integration.md` are all empty placeholder files.
6. **`docs/user_guide/` documentation**: All four files (`faq.md`, `getting_started.md`, `inventory_management.md`, `troubleshooting.md`) are empty placeholders.
7. **`webhook_processor.py`**: `sync_stock_to_platforms()` is a TODO placeholder.
8. **`platform_rules/` directory**: Empty `__init__.py` only — no platform rules implemented.
9. **Multi-tenant SaaS**: Extensive roadmap documented (`docs/multi-tenant-roadmap.md`, `docs/migration-plan.md`) but only the WooCommerce store model is implemented.
10. **Relist automation** (`docs/relist-automation-plan.md`): Designed but not fully implemented. Shopify `relist_listing()` exists; eBay `RelistFixedPriceItem` and V&R relist need work.
11. **Toast notification standardisation**: Audit completed (`docs/toast-notifications-audit.md`), 6 inconsistent implementations found, but standardisation not yet applied.
12. **Dockerfile runs as root**: `USER appuser` directive is commented out ("for debugging").

### Known Bugs / Technical Debt

1. **Sales report duplicates** (Issue #14): Query partitions by `(product_id, DATE)` — same item on multiple days produces duplicates. No `sales_and_ended` table; reads from `sync_events`.
2. **`inventory.py` is ~8,000 lines**: Acknowledged in migration plan as needing split into 5 files.
3. **eBay client creates new `httpx.AsyncClient` per request**: No connection pooling (unlike WooCommerce client which pools).
4. **`runtime.txt` says Python 3.11.x** but Dockerfile uses 3.12-slim (mismatch).
5. **DB schema constraints**: Some needed Alembic migrations for constraints still pending (noted in `docs/todo.md`).
6. **Shopify-only products**: 18 products creating recurring sync events (noted in `docs/todo.md`).
7. **Local eBay token expired**: Noted as a pending issue in `docs/todo.md`.
8. **`aiofiles` listed twice** in `requirements.txt`.
9. **Some routes lack auth**: Several API endpoints (product_api, inventory_inspection, matching, some platform routes) don't require authentication.

### Architecture Constraints

1. **No message queue**: All background processing uses FastAPI BackgroundTasks or DB-backed job queue. No Redis/Celery.
2. **V&R integration is Selenium-based**: Fragile, slow, single-threaded. Cloudflare bypass requires periodic cookie refresh.
3. **Single-process deployment**: No worker processes, no horizontal scaling infrastructure.
4. **No caching layer**: No Redis, Memcached, or similar. Some in-memory caches exist (eBay category features with 24hr TTL, V&R brand validator LRU, Dropbox temp links).

---

## 10. File Tree

```
WooCommerce-Integration/
├── .claude/
│   └── settings.local.json
├── .gitignore
├── DEVELOPMENT.md
├── PROJECT_OVERVIEW.md                    # ← This document
├── REPO_SETUP_REPORT.md
│
├── inventory_system/                      # Core application
│   ├── .claude/                           # AI prompts & audit docs
│   │   ├── 01-MASTER-CLAUDE-CODE-PROMPT.md
│   │   ├── 02-technical-specifications.md
│   │   ├── 03-testing-strategy.md
│   │   ├── 04-handover-oauth-implementation.md
│   │   ├── Prompts-for-bugs/             # Bug diagnosis/fix prompts
│   │   │   ├── CrazyLister/
│   │   │   ├── Gibson_Guitar_VR/
│   │   │   ├── Listing_Health/
│   │   │   └── Platform_Coverage/
│   │   └── Security_audit/
│   │
│   ├── alembic/                           # Database migrations
│   │   ├── env.py
│   │   └── versions/                      # 22+ active migrations
│   │       ├── 001_initial_schema.py
│   │       ├── add_woocommerce_tables.py
│   │       ├── add_woocommerce_stores_table.py
│   │       ├── add_sync_errors_table.py
│   │       ├── add_listing_stats_history.py
│   │       └── old/                       # 30+ legacy migrations
│   │
│   ├── app/                               # Main application code
│   │   ├── main.py                        # FastAPI entry point (312 lines)
│   │   ├── database.py                    # Async DB engine + sessions
│   │   ├── dependencies.py                # DI providers
│   │   │
│   │   ├── core/                          # Cross-cutting concerns
│   │   │   ├── config.py                  # Pydantic Settings (268 lines)
│   │   │   ├── auth.py                    # Basic Auth
│   │   │   ├── security.py               # Multi-user auth
│   │   │   ├── enums.py                   # All enumerations
│   │   │   ├── exceptions.py              # Exception hierarchy
│   │   │   ├── events.py                  # Stock update events
│   │   │   ├── discord_logger.py          # Discord webhook handler
│   │   │   ├── logging_config.py          # Logging setup
│   │   │   ├── templates.py               # Jinja2 init
│   │   │   └── utils.py                   # Helpers (360 lines)
│   │   │
│   │   ├── models/                        # ORM models (~25 files)
│   │   │   ├── product.py                 # Core product (204 lines, 40 cols)
│   │   │   ├── platform_common.py         # Platform bridge table
│   │   │   ├── reverb.py                  # Reverb listings
│   │   │   ├── ebay.py                    # eBay listings
│   │   │   ├── shopify.py                 # Shopify listings
│   │   │   ├── vr.py                      # V&R listings
│   │   │   ├── woocommerce.py             # WC listings
│   │   │   ├── woocommerce_store.py       # Multi-tenant WC stores
│   │   │   ├── reverb_order.py            # Reverb orders
│   │   │   ├── ebay_order.py              # eBay orders
│   │   │   ├── shopify_order.py           # Shopify orders
│   │   │   ├── woocommerce_order.py       # WC orders
│   │   │   ├── sync_event.py              # Sync event audit
│   │   │   ├── sync_error.py              # Error tracking
│   │   │   ├── sync_stats.py              # Sync statistics
│   │   │   ├── activity_log.py            # Activity audit
│   │   │   ├── user.py                    # User model (not used for auth)
│   │   │   ├── shipping.py                # Shipments + profiles
│   │   │   ├── vr_job.py                  # V&R job queue
│   │   │   ├── webhook.py                 # Legacy webhooks
│   │   │   ├── category_mapping.py        # Cross-platform categories
│   │   │   ├── condition_mapping.py       # Cross-platform conditions
│   │   │   ├── platform_preference.py     # User UI preferences
│   │   │   ├── product_mapping.py         # Duplicate linking
│   │   │   ├── listing_stats_history.py   # Engagement metrics
│   │   │   └── reverb_historical.py       # Analytics historical data
│   │   │
│   │   ├── schemas/                       # Pydantic schemas
│   │   │   ├── base.py                    # BaseSchema + TimestampedSchema
│   │   │   ├── product.py                 # Product CRUD schemas
│   │   │   └── platform/                  # Per-platform DTOs
│   │   │       ├── common.py
│   │   │       ├── combined.py
│   │   │       ├── ebay.py
│   │   │       ├── reverb.py
│   │   │       ├── shopify.py
│   │   │       ├── vr.py
│   │   │       └── woocommerce.py
│   │   │
│   │   ├── routes/                        # API endpoints (~22 routers)
│   │   │   ├── dashboard.py               # Main dashboard
│   │   │   ├── inventory.py               # Product CRUD UI (~8000 lines)
│   │   │   ├── inventory_inspection.py    # Payload preview
│   │   │   ├── reports.py                 # All reports (51+ endpoints)
│   │   │   ├── orders.py                  # Order management + DHL shipping
│   │   │   ├── insights.py               # Analytics dashboard
│   │   │   ├── matching.py               # Product matching UI
│   │   │   ├── product_api.py            # Product REST API
│   │   │   ├── shipping.py               # Shipping API
│   │   │   ├── webhooks.py               # Website sale webhooks
│   │   │   ├── websockets.py             # WebSocket endpoint
│   │   │   ├── settings.py               # User settings
│   │   │   ├── admin.py                  # Admin operations
│   │   │   ├── errors.py                 # Sync error UI + API
│   │   │   ├── health.py                 # Health checks
│   │   │   └── platforms/                # Per-platform sync routes
│   │   │       ├── ebay.py
│   │   │       ├── reverb.py
│   │   │       ├── shopify.py
│   │   │       ├── vr.py
│   │   │       ├── woocommerce.py
│   │   │       └── sync_all.py
│   │   │
│   │   ├── services/                      # Business logic (~45 files)
│   │   │   ├── sync_services.py           # Central sync coordinator
│   │   │   ├── event_processor.py         # Cross-platform event processing
│   │   │   ├── order_sale_processor.py    # Sale processing
│   │   │   ├── reconciliation_service.py  # Reconciliation logic
│   │   │   ├── pricing.py                # Platform markup calculations
│   │   │   ├── match_utils.py            # Fuzzy product matching
│   │   │   ├── product_service.py        # Product CRUD service
│   │   │   ├── notification_service.py   # Email alerts
│   │   │   ├── error_logger.py           # Error persistence + Discord
│   │   │   ├── activity_logger.py        # Activity audit
│   │   │   ├── analytics_service.py      # Insights calculations
│   │   │   ├── csv_handler.py            # V&R CSV processing
│   │   │   ├── vr_job_queue.py           # V&R Selenium job queue
│   │   │   ├── webhook_processor.py      # Legacy webhook handler
│   │   │   ├── ebay/                     # eBay (6 files)
│   │   │   │   ├── client.py             # REST Inventory API client
│   │   │   │   ├── auth.py               # OAuth 2.0 flow
│   │   │   │   ├── token_manager.py      # In-memory token cache
│   │   │   │   ├── trading.py            # XML Trading API (legacy)
│   │   │   │   ├── importer.py           # Bulk import
│   │   │   │   └── metadata_utils.py     # Item specifics extraction
│   │   │   ├── reverb/                   # Reverb (4 files)
│   │   │   │   ├── client.py             # REST API v3 client
│   │   │   │   ├── auth.py               # Bearer token auth
│   │   │   │   ├── importer.py           # Bulk import
│   │   │   │   └── sync.py               # Sync logic
│   │   │   ├── shopify/                  # Shopify (4 files)
│   │   │   │   ├── client.py             # GraphQL + REST client
│   │   │   │   ├── auth.py               # Access token auth
│   │   │   │   ├── importer.py           # Bulk import
│   │   │   │   └── sync.py               # Sync logic
│   │   │   ├── woocommerce/              # WooCommerce (7 files)
│   │   │   │   ├── client.py             # REST API v3 client (pooled)
│   │   │   │   ├── auth.py               # Basic Auth
│   │   │   │   ├── importer.py           # Bulk import (multi-tenant)
│   │   │   │   ├── sync.py               # Sync logic
│   │   │   │   ├── errors.py             # Typed exception hierarchy
│   │   │   │   ├── error_tracker.py      # Per-run error collector
│   │   │   │   └── error_logger.py       # Rotating file logger
│   │   │   ├── vintageandrare/           # V&R (5 files)
│   │   │   │   ├── client.py             # Selenium + curl_cffi client
│   │   │   │   ├── auth.py               # Form login + cookies
│   │   │   │   ├── brand_validator.py    # Brand validation
│   │   │   │   ├── export.py             # CSV export
│   │   │   │   └── sync.py               # Sync logic
│   │   │   ├── dropbox/                  # Dropbox (3 files)
│   │   │   │   ├── dropbox_service.py    # Sync client
│   │   │   │   ├── dropbox_async_service.py  # Async client
│   │   │   │   └── scheduled_sync.py     # Daily scheduler
│   │   │   ├── shipping/                 # Shipping (multi-carrier)
│   │   │   │   ├── service.py            # Multi-carrier facade
│   │   │   │   ├── base.py               # Abstract carrier
│   │   │   │   ├── factory.py            # Carrier factory
│   │   │   │   └── carriers/             # DHL implemented, UPS/FedEx stubs
│   │   │   ├── category_mappings/        # JSON mapping files (6 files)
│   │   │   └── websockets/               # WebSocket manager
│   │   │
│   │   ├── templates/                     # Jinja2 HTML templates
│   │   │   ├── base.html                 # Layout with nav, toast, TailwindCSS
│   │   │   ├── ebay/                     # eBay listing templates
│   │   │   ├── errors/                   # Error pages
│   │   │   ├── insights/                 # Analytics pages
│   │   │   ├── inventory/                # Product management pages
│   │   │   ├── matching/                 # Product matching pages
│   │   │   ├── orders/                   # Order management pages
│   │   │   └── reports/                  # Report pages
│   │   │
│   │   ├── static/                        # Frontend assets
│   │   │   ├── js/                       # JavaScript files
│   │   │   ├── images/                   # Logos, badges
│   │   │   ├── data/                     # Static JSON data
│   │   │   └── uploads/                  # User uploads
│   │   │
│   │   └── data/
│   │       └── spec_fields.py            # eBay Item Specifics field definitions
│   │
│   ├── data/                              # Import/export data
│   │   ├── ebay/
│   │   ├── reverb/
│   │   ├── vr/
│   │   └── website_export/
│   │
│   ├── docs/                              # Documentation (~30 files)
│   │   ├── COMMERCIALIZATION_STRATEGY.md
│   │   ├── DATABASE_SCHEMA_REFERENCE.md
│   │   ├── TECH_STACK_AND_ONBOARDING.md
│   │   ├── multi-tenant-roadmap.md
│   │   ├── migration-plan.md
│   │   ├── field-mapping.md
│   │   ├── todo.md
│   │   └── ...
│   │
│   ├── scripts/                           # Utility scripts (~170 files)
│   │   ├── sql/                          # SQL scripts & views
│   │   └── utilities/                    # Setup & maintenance scripts
│   │
│   ├── tests/                             # Test suite (~46 files, 200 tests)
│   │   ├── conftest.py                   # Test DB setup, fixtures
│   │   ├── unit/                         # Unit tests per service
│   │   ├── test_routes/                  # Route tests
│   │   └── fixtures/                     # Test data fixtures
│   │
│   ├── logs/                              # Application logs
│   ├── old/                               # Legacy/archived code
│   │
│   ├── Dockerfile
│   ├── .dockerignore
│   ├── alembic.ini
│   ├── requirements.txt                   # 63 Python dependencies
│   ├── runtime.txt                        # python-3.11.x (stale)
│   ├── pytest.ini
│   ├── start.sh                           # Railway startup script
│   ├── start_app.py                       # Uvicorn launcher
│   ├── CLAUDE.md                          # AI dev instructions + schema ref
│   ├── AGENTS.md                          # Agent guidelines
│   ├── CODEX.md                           # Architecture notes
│   └── readme.md                          # Project README
│
├── discord-logger/                        # TypeScript Discord service
│   ├── src/utils/
│   │   ├── discordLogger.ts              # Main implementation
│   │   └── discordLogger.test.ts         # Tests
│   ├── package.json
│   ├── tsconfig.json
│   ├── jest.config.js
│   ├── .env.example
│   ├── example.ts
│   └── README.md
│
├── bugfixes/                              # Bug fix WIP
├── changes/                               # Refactoring WIP
├── features/                              # Feature WIP
└── snapshots/                             # Versioned project snapshots (~460MB)
```

---

## Appendix: Environment Variables

All environment variables are defined in `app/core/config.py` via Pydantic Settings:

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | PostgreSQL connection string |
| `REVERB_API_KEY` | Reverb API authentication |
| `EBAY_CLIENT_ID`, `EBAY_CLIENT_SECRET`, `EBAY_DEV_ID`, `EBAY_RU_NAME`, `EBAY_REFRESH_TOKEN` | eBay OAuth 2.0 |
| `EBAY_ENVIRONMENT` | `sandbox` or `production` |
| `SHOPIFY_STORE_URL`, `SHOPIFY_ACCESS_TOKEN`, `SHOPIFY_API_VERSION`, `SHOPIFY_WEBHOOK_SECRET` | Shopify integration |
| `VR_USERNAME`, `VR_PASSWORD`, `VR_COOKIES_BASE64`, `VR_BASE_URL` | Vintage & Rare |
| `WC_STORE_URL`, `WC_CONSUMER_KEY`, `WC_CONSUMER_SECRET`, `WC_WEBHOOK_SECRET` | WooCommerce |
| `DROPBOX_REFRESH_TOKEN`, `DROPBOX_APP_KEY`, `DROPBOX_APP_SECRET` | Dropbox image storage |
| `DHL_SHIPPER_*` (10+ vars) | DHL Express shipping |
| `DISCORD_WEBHOOK_URL` | Discord notifications |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `NOTIFICATION_EMAIL` | Email notifications |
| `BASIC_AUTH_CREDENTIALS` | Application auth (comma-separated `user:pass`) |
| `MIGRATE_SECRET` | Migration endpoint auth |
| `RUN_MIGRATIONS` | Auto-run Alembic on startup |
| `REVERB_PRICE_MARKUP`, `EBAY_PRICE_MARKUP`, `VR_PRICE_MARKUP`, `SHOPIFY_PRICE_MARKUP`, `WC_PRICE_MARKUP` | Per-platform price multipliers |
| `PORT` | Server port (Railway) |
