# RIFF Tech Stack & Onboarding Guide

**Last Updated**: 2026-01-27
**Target Audience**: Junior developers, potential acquirers, technical partners

---

## Executive Summary

RIFF is a multi-platform inventory management system built for music gear retailers. It synchronizes product listings across Reverb, eBay, Shopify, and Vintage & Rare from a single source of truth. Built with modern Python async frameworks, it handles ~500+ active listings with hourly syncs, order processing, and cross-platform quantity propagation.

---

## Complete Tech Stack

### Core Framework
- **FastAPI 0.115.8** - Modern async Python web framework
  - Auto-generated OpenAPI docs
  - Native async/await support
  - Pydantic validation
- **Uvicorn 0.34.0** - ASGI server
- **Python 3.12** - Language runtime

### Database
- **PostgreSQL** - Primary RDBMS (production hosted on Railway)

### ORM & Migrations (Libraries)
- **SQLAlchemy 2.0.37** - Async ORM library
- **Alembic 1.14.1** - Database migration tool
- **asyncpg 0.30.0** - Async PostgreSQL driver
- **psycopg2-binary 2.9.9** - Sync PostgreSQL driver (for migrations/scripts)

### Frontend
- **Jinja2 3.1.4** - Server-side HTML templating
- **TailwindCSS** - Utility classes via CDN (no separate .css files)
- **Vanilla JavaScript** - Single file (`inventory.js`), class-based, ~500 lines
- **Inline CSS** - Custom styles in `<style>` blocks, no preprocessors

### Other Languages
- **SQL** - PostgreSQL queries, migrations, views (`scripts/sql/*.sql`)
- **Bash** - Setup/deployment scripts (`scripts/**/*.sh`)
- **XML** - eBay Trading API responses (parsed via xmltodict)
- **JSON** - API payloads, JSONB database columns
- **CSV** - Import/export (pandas)
- **INI** - Alembic config
- **ENV** - Secrets/config (60+ variables)
- **Markdown** - Documentation

**Intentionally NOT used:**
- ❌ TypeScript, React/Vue/Angular, CSS preprocessors, Webpack/Vite
- ❌ Keeps codebase simple, no build step, easy onboarding

### Platform Integrations

#### eBay
- **ebaysdk 2.2.0** - Official Python SDK
- **Trading API (XML)** - Legacy API for listing management
- **OAuth 2.0** - Authentication (refresh tokens stored encrypted)
- **Item Specifics System** - Category-specific required fields
- **Shipping Profiles** - Business policies for shipping

#### Reverb
- **Custom REST client** (httpx-based)
- **API v3** - RESTful JSON API
- **Personal Access Token** - Auth via bearer token
- **WebSocket support** - For real-time order notifications (planned)

#### Shopify
- **GraphQL API (Admin API 2024-01)** - Primary API
- **Custom Python client** - Built on httpx
- **App-based authentication** - Access token per store
- **Inventory Location API** - Multi-location support
- **Metafields** - For custom attributes and SEO

#### Vintage & Rare
- **Selenium 4.21.0** - Browser automation (no public API)
- **undetected-chromedriver 3.5.5** - Cloudflare bypass
- **BeautifulSoup4 4.12.3** - HTML parsing
- **curl_cffi** - TLS fingerprint matching for scraping

### Data Processing
- **pandas 2.2.2** - CSV import/export, data transformations
- **numpy 1.26.4** - Numerical operations
- **fuzzywuzzy 0.18.0** - String matching for duplicate detection
- **python-Levenshtein 0.25.1** - Fast edit distance

### Media & Storage
- **Dropbox SDK 12.0.2** - Cloud storage integration
  - Thumbnail API for bandwidth optimization (~98% savings)
  - Lazy full-res fetch on selection
  - Token refresh handling
- **Pillow 10.4.0** - Image processing
- **Local filesystem** - Fallback for uploads

### HTTP & Async
- **httpx 0.27.0** - Async HTTP client (primary)
- **aiohttp 3.9.5** - Alternative async client
- **requests 2.32.3** - Sync HTTP (legacy scripts)
- **aiofiles 24.1.0** - Async file I/O

### Background Jobs
- **Custom scheduler** (`scripts/run_sync_scheduler.py`)
  - Interval-based job scheduling
  - Per-platform sync jobs (hourly)
  - Stats collection (daily)
  - Auto-archive (weekly)
- **asyncio** - Native Python async primitives
- **No Celery/RQ** - Keeps deployment simple

### Shipping Integration
- **DHL API** - Label generation (85% complete)
- **reportlab 4.0.8** - PDF generation for invoices

### Configuration & Validation
- **pydantic-settings 2.7.1** - Settings management from environment
- **python-dotenv 1.0.1** - .env file loading
- **Pydantic 2.9.1** - Data validation and serialization

### Testing
- **pytest** - Test framework
- **pytest-asyncio** - Async test support
- **pytest-mock** - Mocking utilities
- **200+ tests** - Unit and integration tests

### Utilities
- **xmltodict 0.13.0** - XML parsing (eBay responses)
- **iso8601 2.1.0** - Date parsing
- **tabulate 0.9.0** - CLI table formatting

### Deployment
- **Docker** - Containerized deployment
  - Python 3.12-slim base image
  - Non-root user for security
  - Multi-stage build for optimization
- **Railway.app** - Production hosting (PaaS)
  - Auto-deploy from GitHub main branch
  - Environment variable management
  - PostgreSQL addon
  - $20-30/month cost
- **GitHub** - Version control and CI/CD trigger

### Monitoring & Logging
- **Python logging** - Structured logging
- **Activity logger** - Custom service for user-facing audit trail
- **Railway logs** - Centralized log aggregation
- **No APM yet** - Sentry/DataDog planned for multi-tenant

---

## System Architecture

### Request Flow
```
User Browser
    ↓
FastAPI Route (/inventory, /reports, /orders)
    ↓
Service Layer (ebay_service, reverb_service, etc.)
    ↓
Database (SQLAlchemy async session)
    ↓
External APIs (eBay, Reverb, Shopify, V&R)
```

### Database Schema Pattern
```
products (core inventory)
    ↓
platform_common (platform linkages)
    ├── reverb_listings (Reverb-specific fields)
    ├── ebay_listings (eBay-specific fields)
    ├── shopify_listings (Shopify-specific fields)
    └── vr_listings (V&R-specific fields)

sync_events (change detection)
    ↓
Event processing → API updates → Local DB sync
```

### Key Design Patterns
- **Schema-per-platform** - Each platform gets dedicated table for unique fields
- **Async everywhere** - All I/O is async (DB, HTTP, file)
- **Service layer** - Business logic isolated from routes
- **Direct platform services** - No abstraction layer (tried and abandoned)
- **Sync events** - Change detection creates actionable events
- **Stocked vs non-stocked** - Dual inventory model (quantities vs unique items)

---

## Directory Structure

```
inventory_system/
├── app/
│   ├── core/               # Config, utilities, constants
│   │   ├── config.py       # Settings (60+ env vars)
│   │   └── utils.py        # Image transformers, helpers
│   ├── database.py         # Async session factory
│   ├── dependencies.py     # FastAPI dependency injection
│   ├── main.py             # App entry point
│   ├── models/             # SQLAlchemy ORM models (25+ models)
│   │   ├── product.py
│   │   ├── platform_common.py
│   │   ├── reverb.py, ebay.py, shopify.py, vr.py
│   │   ├── sync_event.py
│   │   └── *_order.py (reverb_order, ebay_order, shopify_order)
│   ├── routes/             # FastAPI routes
│   │   ├── inventory.py    # Main inventory UI (3700+ lines, needs refactor)
│   │   ├── reports.py      # Reporting endpoints
│   │   ├── orders.py       # Order management
│   │   └── platforms/      # Platform-specific routes
│   ├── services/           # Business logic (30+ services)
│   │   ├── ebay_service.py         # 128KB - eBay listing CRUD
│   │   ├── reverb_service.py       # 130KB - Reverb listing CRUD
│   │   ├── shopify_service.py      # 100KB - Shopify GraphQL
│   │   ├── order_sale_processor.py # Order → inventory sync
│   │   ├── event_processor.py      # Sync event handling
│   │   ├── ebay/           # eBay submodules
│   │   │   ├── trading.py  # Trading API wrapper
│   │   │   ├── spec_fields.py # Item Specifics (category-based)
│   │   │   └── category_mapper.py
│   │   ├── reverb/         # Reverb submodules
│   │   ├── shopify/        # Shopify submodules
│   │   └── dropbox/        # Dropbox integration
│   ├── templates/          # Jinja2 HTML templates
│   │   ├── inventory/      # Product list, detail, add/edit
│   │   ├── reports/        # Sync events, reconciliation
│   │   ├── orders/         # Order list, shipping
│   │   └── base.html       # Base template
│   └── static/             # CSS, JS, images (minimal)
├── scripts/                # Maintenance & sync scripts
│   ├── run_sync_scheduler.py  # Main background job scheduler
│   ├── reverb/             # Reverb-specific scripts
│   ├── ebay/               # eBay-specific scripts
│   │   ├── auth_token/     # OAuth flow helpers
│   │   └── get_ebay_orders.py
│   ├── shopify/            # Shopify-specific scripts
│   │   └── auto_archive.py # Weekly archive job
│   └── backup/             # DB backup utilities
├── alembic/                # Database migrations
│   └── versions/           # Migration scripts
├── docs/                   # Documentation
│   ├── todo.md             # Current priorities
│   ├── multi-tenant-roadmap.md
│   ├── dhl-integration.md
│   └── api/                # API documentation
├── requirements.txt        # Python dependencies
├── Dockerfile              # Production container
├── .env.example            # Environment variables template
└── README.md               # Project overview
```

---

## Junior Developer Onboarding Process

### Prerequisites
**Required Skills:**
- Python 3.10+ (async/await, type hints)
- SQL basics (SELECT, JOIN, WHERE)
- HTTP/REST API concepts
- Git version control
- Command line comfort

**Helpful Skills:**
- FastAPI or Flask experience
- SQLAlchemy ORM
- JavaScript (vanilla)
- HTML/CSS basics
- Docker fundamentals

### Week 1: Environment Setup & Codebase Exploration

#### Day 1: Local Environment
1. **Install dependencies:**
   ```bash
   # Install Python 3.12
   brew install python@3.12  # macOS

   # Clone repo
   git clone https://github.com/tommytoolman/inventory_system.git
   cd inventory_system

   # Create virtual environment
   python3.12 -m venv venv
   source venv/bin/activate

   # Install packages
   pip install -r requirements.txt
   ```

2. **Set up PostgreSQL:**
   ```bash
   # Install PostgreSQL
   brew install postgresql@14  # macOS
   brew services start postgresql@14

   # Create database
   createdb riff_inventory_dev
   ```

3. **Configure environment:**
   ```bash
   # Copy example
   cp .env.example .env

   # Edit .env - minimum required:
   DATABASE_URL=postgresql+asyncpg://localhost/riff_inventory_dev
   SECRET_KEY=dev-secret-key-change-in-production
   ADMIN_PASSWORD=admin123  # Local only

   # Optional platform credentials (can skip initially):
   REVERB_API_KEY=...
   EBAY_REFRESH_TOKEN=...
   SHOPIFY_ADMIN_API_ACCESS_TOKEN=...
   ```

4. **Run migrations:**
   ```bash
   alembic upgrade head
   ```

5. **Start dev server:**
   ```bash
   uvicorn app.main:app --reload --port 8000
   ```

6. **Verify:**
   - Visit http://localhost:8000
   - Login with ADMIN_PASSWORD
   - Should see empty inventory list

#### Day 2-3: Code Reading
**Focus areas:**
1. Read `docs/todo.md` - understand current priorities
2. Read `docs/multi-tenant-roadmap.md` - understand future direction
3. Read `README.md` - system overview
4. Browse `app/models/` - understand data model
5. Read `app/routes/inventory.py` lines 1-500 - core product CRUD
6. Run existing tests: `pytest tests/ -v`

**Exercise:**
- Create a test product via UI
- Follow code path from route → service → database
- Add a print statement in `product_service.py` and see it in logs

#### Day 4-5: First PR - Small Bug Fix
**Suggested starter tasks:**
1. Fix a typo in UI text
2. Add validation to prevent duplicate SKUs
3. Improve error message on failed sync
4. Add a missing field to CSV export

**PR Guidelines:**
- Branch from `main`: `git checkout -b fix/your-task-name`
- Write clear commit messages
- Test locally before pushing
- Ask for code review

### Week 2: Platform Integration Deep Dive

**Pick ONE platform to master:**
- **Reverb** (easiest) - REST API, good docs
- **Shopify** (medium) - GraphQL, modern
- **eBay** (hard) - XML APIs, complex OAuth

**Tasks:**
1. Read platform's official API docs
2. Trace a listing creation flow end-to-end
3. Make a test API call from Python REPL
4. Understand error handling for that platform
5. Add logging to debug a sync issue

### Week 3-4: Feature Implementation

**First real feature (choose based on todo.md):**
- Add a new report
- Implement a missing filter
- Improve sync event UI
- Add a new product field with platform propagation

**Mentorship needed:**
- Daily 15-min standup
- Code review within 24 hours
- Pair programming for complex logic

---

## Setting Up a New Retailer

### Option A: Clone & Customize (Current - Single Tenant)
**Use case:** Set up RIFF for one new customer manually

**Time estimate:** 4-8 hours
**Technical skill needed:** Intermediate Python, PostgreSQL

#### Steps:

1. **Infrastructure Setup (30 min)**
   - Create Railway account (or Heroku/Render)
   - Provision PostgreSQL addon
   - Create project from GitHub repo fork
   - Set environment variables (60+ vars)

2. **Platform Credentials (1-2 hours)**
   - **Reverb:**
     - Create Reverb developer account
     - Generate Personal Access Token
     - Add to `REVERB_API_KEY`

   - **eBay:**
     - Create eBay Developer account
     - Create Production App keys
     - Run OAuth flow to get refresh token
     - Add `EBAY_CLIENT_ID`, `EBAY_CLIENT_SECRET`, `EBAY_REFRESH_TOKEN`

   - **Shopify:**
     - Create Shopify custom app
     - Grant Admin API permissions
     - Generate access token
     - Add `SHOPIFY_ADMIN_API_ACCESS_TOKEN`, `SHOPIFY_SHOP_URL`

   - **Vintage & Rare:**
     - Get customer's V&R login credentials
     - Add to `VINTAGE_AND_RARE_USERNAME/PASSWORD`

3. **Initial Data Import (1-2 hours)**
   - Choose primary platform (usually Reverb)
   - Run import script:
     ```bash
     python scripts/reverb/import_all_listings.py --dry-run
     python scripts/reverb/import_all_listings.py  # Real import
     ```
   - Verify products in database
   - Check images synced correctly

4. **Category & Brand Mapping (1-2 hours)**
   - Review imported categories
   - Map to eBay category IDs (hardest part)
   - Test listing creation to each platform
   - Fix any mapping errors

5. **Enable Background Sync (30 min)**
   - Deploy `run_sync_scheduler.py` as separate process
   - Configure Railway to run scheduler alongside web server
   - Verify hourly syncs running
   - Check logs for errors

6. **Testing & Handoff (1-2 hours)**
   - Create test listing
   - Sync to all platforms
   - Sell test item on one platform
   - Verify quantity propagation
   - Train customer on UI

**Total cost for new customer:**
- Railway hosting: ~$25/month
- Developer time: 6-10 hours initial setup
- Ongoing: ~2 hours/month for support

**Challenges:**
- eBay OAuth is painful (expires, complex setup)
- Category mapping is manual and tedious
- Each retailer has unique categories/brands
- Credentials must be manually gathered
- No self-service onboarding

---

### Option B: Multi-Tenant SaaS (Roadmap)
**Use case:** Scale to 10-100 retailers with self-service

**Prerequisites:**
- Complete items in `docs/multi-tenant-roadmap.md`
- 8-12 weeks development effort
- $5k-15k investment (or 200-300 hours)

#### High-Level Changes Required:

1. **Database Architecture (2-3 weeks)**
   - Implement schema-per-tenant (PostgreSQL schemas)
   - Add `tenant_id` to all queries via middleware
   - Tenant-scoped background jobs
   - Credential encryption per tenant

2. **Authentication System (1-2 weeks)**
   - Replace single admin password with user accounts
   - Email/password registration
   - OAuth providers (Google, GitHub)
   - Role-based access (owner, staff, read-only)
   - Consider Auth0/Clerk to save time

3. **Platform OAuth Flows (2 weeks)**
   - **Reverb OAuth:**
     - Build OAuth callback handler
     - Store access token per tenant
     - Handle token refresh

   - **eBay OAuth:**
     - Existing flow works, needs per-tenant storage
     - Automate token refresh

   - **Shopify OAuth:**
     - Build app installation flow
     - Store credentials per shop

   - **V&R:**
     - Still username/password (no OAuth)

4. **Onboarding Wizard (2 weeks)**
   ```
   Sign Up → Email Verify → Connect Platforms → Import Listings → Go Live
   ```
   - Step-by-step UI
   - Progress tracking
   - Preview before commit
   - Tutorial tooltips

5. **Billing Integration (1 week)**
   - Stripe Checkout for subscriptions
   - Tiered pricing (see roadmap)
   - Usage tracking (listing count)
   - Invoicing and receipts

6. **Self-Service Tools (2 weeks)**
   - Platform connection management
   - Re-import wizard
   - Sync diagnostics
   - Settings UI
   - Knowledge base

**New Customer Flow (Self-Service):**
1. Sign up at riff-app.com (5 min)
2. Connect Reverb via OAuth (3 min)
3. Import listings (10 min)
4. Connect secondary platforms (15 min)
5. Enable sync (1 min)
6. Enter payment info (3 min)

**Total:** 37 minutes (vs 6+ hours manual)

**Ongoing Cost per Tenant:**
- Shared infrastructure: $2-5/month/tenant
- No manual setup time
- Support: ~1 hour/month/tenant (knowledge base reduces this)

---

## Key Technical Challenges for New Developers

### 1. Async Everywhere
**Challenge:** All database and HTTP calls are async

**Example:**
```python
# WRONG - sync code in async context
def get_product(product_id):
    result = db.execute(select(Product).where(Product.id == product_id))
    return result.scalar_one()

# RIGHT - async code
async def get_product(db: AsyncSession, product_id: int):
    result = await db.execute(select(Product).where(Product.id == product_id))
    return result.scalar_one()
```

**Learning:** Read FastAPI async guide, practice with asyncio

### 2. Platform API Differences
**Challenge:** Each platform has different data models, terminology, quirks

**Example:**
| RIFF Field | Reverb | eBay | Shopify |
|------------|--------|------|---------|
| Quantity | `inventory` | `QuantityAvailable` | `inventoryItem.tracked` + `inventoryLevel` |
| Status | `state` (live/sold/ended) | `ListingStatus` (Active/Ended) | `status` (active/archived) |
| Price | `price.amount` | `StartPrice` | `variants[0].price` |

**Learning:** Read each platform's API docs, trace code for one platform end-to-end

### 3. Database Schema Relationships
**Challenge:** Many joins across platform tables

**Example:**
```python
# To get all platforms for a product:
product = await db.get(Product, product_id)
result = await db.execute(
    select(PlatformCommon).where(PlatformCommon.product_id == product.id)
)
platform_links = result.scalars().all()

for link in platform_links:
    if link.platform_name == "reverb":
        # Get reverb-specific fields
        rev_result = await db.execute(
            select(ReverbListing).where(ReverbListing.platform_id == link.id)
        )
        reverb_listing = rev_result.scalar_one_or_none()
```

**Learning:** Draw ER diagrams, use PostgreSQL `\d` commands to explore schema

### 4. Background Job Scheduling
**Challenge:** No Celery/RQ, custom scheduler

**Example:**
```python
# scripts/run_sync_scheduler.py
jobs = [
    ScheduledJob("reverb_sync", interval_minutes=60, coro=run_reverb_sync),
    ScheduledJob("ebay_sync", interval_minutes=60, coro=run_ebay_sync),
    ScheduledJob("stats_daily", interval_minutes=1440, coro=collect_stats),
]

# Runs in infinite loop checking job.next_run
```

**Learning:** Read `run_sync_scheduler.py`, understand Railway runs web + scheduler as separate processes

### 5. Image Handling Across Platforms
**Challenge:** Each platform has different image requirements

- Reverb: 2048x2048 max, CDN URLs
- eBay: Self-hosted URLs, specific formats
- Shopify: GraphQL upload, variant images
- V&R: Selenium file upload

**Learning:** Trace `ImageTransformer` class, understand Dropbox lazy fetch pattern

---

## Common Gotchas

1. **Conda vs venv:** Never use conda, always `source venv/bin/activate`
2. **Database session management:** Use `async with get_session() as db:`, not `Depends(get_session)`
3. **eBay XML quirks:** Dates are in ISO8601, booleans are strings "true"/"false"
4. **Shopify GraphQL IDs:** Use gid://shopify/Product/12345, not just 12345
5. **V&R Selenium:** Runs headless in production, needs Chrome installed in Docker
6. **Sync events vs direct updates:** Some flows create events, some update directly
7. **Stocked vs non-stocked:** Different logic for quantity tracking vs unique items
8. **Platform status mapping:** Each platform has different status values (live/active/published)
9. **Case sensitivity:** SKUs are case-insensitive, use LOWER() in SQL
10. **Reverb API rate limits:** 120 requests/minute, implement backoff

---

## Resources for New Developers

### Internal Documentation
- `docs/todo.md` - Current priorities and progress
- `docs/multi-tenant-roadmap.md` - Future SaaS architecture
- `docs/dhl-integration.md` - Shipping integration details
- `docs/api/platform_integration.md` - Platform-specific quirks
- `CLAUDE.md` - Critical reminders for AI assistants (also useful for humans!)

### External Documentation
- **FastAPI:** https://fastapi.tiangolo.com/async/
- **SQLAlchemy 2.0 async:** https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html
- **Reverb API:** https://reverb.com/page/api
- **eBay Trading API:** https://developer.ebay.com/devzone/xml/docs/reference/ebay/index.html
- **Shopify GraphQL:** https://shopify.dev/api/admin-graphql
- **Railway deployment:** https://docs.railway.app/

### Development Workflow
1. Pick task from `docs/todo.md`
2. Create branch: `git checkout -b feature/task-name`
3. Write code + tests
4. Test locally: `pytest tests/`
5. Commit with clear message
6. Push and create PR
7. Deploy to Railway on merge to main (automatic)

---

## Success Criteria for Onboarded Developer

After 4 weeks, developer should be able to:
- [ ] Set up local environment from scratch (30 min)
- [ ] Create a test product and sync to all platforms
- [ ] Debug a failed sync event using logs
- [ ] Add a new field to Product model with migration
- [ ] Implement a basic report with SQL query
- [ ] Fix a bug end-to-end (route → service → DB → platform API)
- [ ] Write a test for new functionality
- [ ] Deploy a change to production via GitHub

---

## Next Steps

1. **For hiring junior dev:** Send this doc + `docs/todo.md`, ask them to set up locally
2. **For handoff to agency:** Include this + `docs/multi-tenant-roadmap.md` + codebase access
3. **For potential acquirer:** This doc + financial model + customer interviews
4. **For technical co-founder:** This doc + pair programming session + roadmap discussion
