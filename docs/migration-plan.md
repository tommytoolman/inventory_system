# RIFF Multi-Tenant Transformation: Project Action Chart

## Context

RIFF is a working single-tenant inventory management system (61K lines Python, 152 files, 34 tables, 4 platform integrations) deployed on Railway. The goal is to evolve it to serve 500+ customers while maintaining all current features. This plan covers 4 phases: cleanup, multi-tenant foundation, onboarding/billing, and infrastructure migration.

**Key constraint:** AI-assisted development compresses timescales dramatically. Mechanical refactoring (adding tenant_id, updating queries, generating migrations) is hours not weeks.

---

## PHASE 0: CODE CLEANUP (Est. 2-3 days)

Strip dead weight before adding multi-tenant complexity. Every line of dead code is a line that needs tenant isolation for no reason.

### 0.1 Remove Dead Methods
| # | Action | File | Lines | Detail |
|---|--------|------|-------|--------|
| 0.1.1 | Delete `_handle_price_change_old()` | `app/services/sync_services.py` | 1045-1087 | Zero callers anywhere. Replaced by `_handle_price_change()` at line 1089 |
| 0.1.2 | Delete `_handle_order_sale()` | `app/services/sync_services.py` | 1598-1796 | 199 lines. Unreachable — OrderSaleProcessor marks `sale_processed=True` before events are created |
| 0.1.3 | Delete `create_sync_events_for_stocked_orders()` | `app/services/reverb_service.py` | 665-779 | 115 lines. Events never created due to flag ordering with OrderSaleProcessor |
| 0.1.4 | Remove commented price propagation block | `app/services/sync_services.py` | 1072-1081 | 10 lines of commented code inside the now-deleted `_old` method |
| 0.1.5 | Remove commented root redirect | `app/main.py` | 175-185 | 11 lines. Dashboard handles `/` already |

### 0.2 Consolidate EventProcessor into SyncService
| # | Action | File | Detail |
|---|--------|------|--------|
| 0.2.1 | Audit all callers of `EventProcessor` | `app/services/event_processor.py` | Map every route/script that instantiates EventProcessor |
| 0.2.2 | Identify canonical implementation per event type | Both files | For each of: new_listing, status_change, price_change — pick SyncService version as canonical |
| 0.2.3 | Redirect all EventProcessor callers to SyncService | Routes, scripts | Update imports and calls |
| 0.2.4 | Delete `app/services/event_processor.py` | `event_processor.py` | ~1,635 lines removed after consolidation |
| 0.2.5 | Test all sync event processing paths | Manual + pytest | Verify: new_listing import, status_change (sold/ended), price_change, relist detection |

### 0.3 Split inventory.py (8,089 lines)
| # | Action | New File | Functions Moving | Approx Lines |
|---|--------|----------|-----------------|-------------|
| 0.3.1 | Extract product CRUD | `app/routes/products.py` | `list_products`, `product_detail`, `add_product_form`, `add_product`, `edit_product_form`, `update_product`, `update_product_stock`, drafts | ~3,000 |
| 0.3.2 | Extract platform listing ops | `app/routes/listings.py` | `relist_product`, `refresh_stale_listing`, `handle_create_platform_listing_from_detail`, `ebay_template_preview`, image refresh/fix | ~1,000 |
| 0.3.3 | Extract Dropbox management | `app/routes/dropbox.py` | 15 Dropbox functions (`get_dropbox_folders` through `get_dropbox_full_res_link`) | ~1,500 |
| 0.3.4 | Extract data/search APIs | `app/routes/data_api.py` | `get_ebay_category_aspects`, `get_shipping_profiles`, `get_platform_categories`, `search_reverb_categories`, `get_category_mappings` | ~500 |
| 0.3.5 | Keep core in inventory.py | `app/routes/inventory.py` | Helpers, utilities, VR sync forms | ~2,000 remaining |

### 0.4 Clean Up Scripts
| # | Action | Detail |
|---|--------|--------|
| 0.4.1 | Delete `manual_create_order_sync_events 2.py` | Exact duplicate |
| 0.4.2 | Audit all `scripts/test_*.py` files | List which ones duplicate endpoint functionality |
| 0.4.3 | Delete confirmed orphaned test scripts | After audit in 0.4.2 |
| 0.4.4 | Move useful debug scripts to `scripts/debug/` | Organize remaining |

### 0.5 Fix Unused Imports
| # | File | Unused Imports |
|---|------|---------------|
| 0.5.1 | `app/routes/inventory.py` | `math`, `timedelta`, `distinct`, `Session` |
| 0.5.2 | `app/services/sync_services.py` | `NamedTuple`, `Enum` from typing |
| 0.5.3 | `app/routes/reports.py` | `desc`, `SyncStats` (verify) |

---

## PHASE 1: MULTI-TENANT FOUNDATION (Est. 5-7 days)

### 1.1 New Database Tables
| # | Table | Key Columns | Purpose |
|---|-------|-------------|---------|
| 1.1.1 | `tenants` | `id` (UUID PK), `name`, `slug` (unique), `is_active`, `plan_tier`, `created_at` | Tenant identity |
| 1.1.2 | `tenant_users` | `id`, `tenant_id` (FK), `email`, `password_hash`, `role` (owner/staff/readonly), `is_active` | Replace current User model + add tenant binding |
| 1.1.3 | `tenant_platform_credentials` | `id`, `tenant_id` (FK), `platform_name`, `credentials` (jsonb, encrypted), `is_active`, `last_verified` | Per-tenant API keys replacing env vars |
| 1.1.4 | `tenant_settings` | `id`, `tenant_id` (FK), `settings` (jsonb) | Per-tenant config: pricing markups, DHL details, notification emails, branding |
| 1.1.5 | `tenant_sync_configs` | `id`, `tenant_id` (FK), `platform_name`, `enabled`, `interval_minutes`, `last_sync` | Per-tenant sync scheduling |

### 1.2 Add `tenant_id` to Existing Tables (20 tables)
| # | Table | Migration Detail |
|---|-------|-----------------|
| 1.2.1 | `products` | Add `tenant_id` UUID NOT NULL FK, add composite index `(tenant_id, sku)`, drop old unique on `sku` alone |
| 1.2.2 | `platform_common` | Add `tenant_id`, composite index `(tenant_id, product_id, platform_name)` |
| 1.2.3 | `reverb_listings` | Add `tenant_id`, index |
| 1.2.4 | `ebay_listings` | Add `tenant_id`, index |
| 1.2.5 | `shopify_listings` | Add `tenant_id`, index |
| 1.2.6 | `vr_listings` | Add `tenant_id`, index |
| 1.2.7 | `reverb_orders` | Add `tenant_id`, index |
| 1.2.8 | `ebay_orders` | Add `tenant_id`, index |
| 1.2.9 | `shopify_orders` | Add `tenant_id`, index |
| 1.2.10 | `orders` | Add `tenant_id`, index |
| 1.2.11 | `sales` | Add `tenant_id`, index |
| 1.2.12 | `sync_events` | Add `tenant_id`, composite index `(tenant_id, created_at)` — this is the largest table at scale |
| 1.2.13 | `shipments` | Add `tenant_id` |
| 1.2.14 | `shipping_profiles` | Add `tenant_id` |
| 1.2.15 | `vr_jobs` | Add `tenant_id` |
| 1.2.16 | `activity_log` | Add `tenant_id`, composite index `(tenant_id, created_at)` |
| 1.2.17 | `listing_stats_history` | Add `tenant_id` — second largest table at scale |
| 1.2.18 | `sync_stats` | Add `tenant_id` |
| 1.2.19 | `category_stats` | Add `tenant_id` |
| 1.2.20 | `jobs` | Add `tenant_id` |

**Shared reference tables (NO tenant_id needed):** `reverb_categories`, `ebay_category_mappings`, `shopify_category_mappings`, `vr_category_mappings`, `condition_mappings`, `platform_status_mappings`

### 1.3 Migration Strategy
| # | Action | Detail |
|---|--------|--------|
| 1.3.1 | Create "Tenant Zero" migration | Insert a default tenant row for Hanks (current customer). Set all existing rows' `tenant_id` to this default. |
| 1.3.2 | Generate Alembic migration | Single migration file adding all 20 `tenant_id` columns + 5 new tables |
| 1.3.3 | Test on DB clone | `pg_dump` production → restore to test DB → run migration → verify |
| 1.3.4 | Run on production | During low-traffic window. Backfill all existing rows with Tenant Zero ID |

### 1.4 Authentication System
| # | Action | File(s) | Detail |
|---|--------|---------|--------|
| 1.4.1 | Choose auth provider | Decision | **Options:** Auth0/Clerk (buy) vs roll-own JWT. Recommendation: roll-own JWT for now (simpler, no external dependency, can add Auth0 later) |
| 1.4.2 | Add auth packages | `requirements.txt` | `python-jose[cryptography]`, `passlib[bcrypt]` |
| 1.4.3 | Create `app/core/auth.py` | New file | JWT token creation/validation, password hashing, tenant extraction from token |
| 1.4.4 | Rewrite `app/core/security.py` | Lines 50-118 | `get_current_user()` returns `(user_id, tenant_id, role)` from JWT. Replace Basic Auth. |
| 1.4.5 | Create login endpoint | `app/routes/auth.py` | `POST /auth/login` → returns JWT with tenant_id claim |
| 1.4.6 | Create login template | `app/templates/auth/login.html` | Login form (email + password) |
| 1.4.7 | Update `require_auth()` | `app/core/security.py` | Extract tenant_id from JWT, set on `request.state.tenant_id` |

### 1.5 Tenant Context Middleware
| # | Action | File | Detail |
|---|--------|------|--------|
| 1.5.1 | Create `contextvars` tenant var | `app/core/tenant.py` | `current_tenant_id: ContextVar[str]` |
| 1.5.2 | Create tenant middleware | `app/main.py` | After auth, set `current_tenant_id` from JWT claim |
| 1.5.3 | Modify `get_session()` | `app/database.py` | After yielding session, execute `SET LOCAL app.current_tenant = :tenant_id` for RLS |
| 1.5.4 | Add PostgreSQL RLS policies | Alembic migration | `CREATE POLICY tenant_isolation ON products USING (tenant_id = current_setting('app.current_tenant')::uuid)` — defence-in-depth |

### 1.6 Credential Injection Refactor
| # | Action | Detail |
|---|--------|--------|
| 1.6.1 | Create `CredentialManager` service | `app/services/credential_manager.py` — fetches encrypted credentials from `tenant_platform_credentials`, decrypts, caches (60s TTL) |
| 1.6.2 | Refactor Reverb credential reads | 6 locations → `await cred_mgr.get_credentials(tenant_id, 'reverb')` |
| 1.6.3 | Refactor eBay credential reads | 19 locations → credential manager |
| 1.6.4 | Refactor VR credential reads | 33 locations → credential manager (highest count) |
| 1.6.5 | Refactor Shopify credential reads | 7 locations → credential manager |
| 1.6.6 | Remove `londonvintagegts` hardcode | `app/services/ebay_service.py:78` → fetch from tenant credentials |
| 1.6.7 | Remove hardcoded DHL shipper | `app/core/config.py:164-173` → fetch from `tenant_settings` |

### 1.7 Service Layer Tenant Awareness
| # | Action | Files | Detail |
|---|--------|-------|--------|
| 1.7.1 | Add `tenant_id` param to all service constructors | All 24 top-level services | `def __init__(self, db, tenant_id)` |
| 1.7.2 | Filter all queries by tenant_id | 110+ `get_session()` calls | Add `.where(Model.tenant_id == self.tenant_id)` |
| 1.7.3 | Tenant-scope all INSERT operations | All service writes | Set `tenant_id` on new objects |
| 1.7.4 | Update global caches | `ebay_service.py:47` | Cache key format: `{tenant_id}:{category_id}` |

### 1.8 Background Scheduler Rewrite
| # | Action | File | Detail |
|---|--------|------|--------|
| 1.8.1 | Add `arq` + Redis dependency | `requirements.txt` | `arq`, `redis` |
| 1.8.2 | Create tenant-aware job definitions | `app/jobs/` (new directory) | One job per sync type: `sync_reverb(tenant_id)`, `sync_ebay(tenant_id)`, etc. |
| 1.8.3 | Create scheduler loop | `scripts/run_scheduler.py` | Query active tenants → check `tenant_sync_configs` → enqueue due jobs to Redis via arq |
| 1.8.4 | Create worker process | `scripts/run_worker.py` | arq worker that picks up jobs and executes with tenant context |
| 1.8.5 | Deprecate old scheduler | `scripts/run_sync_scheduler.py` | Keep but mark deprecated. New scheduler runs alongside initially. |

### 1.9 Template Branding
| # | Action | File | Lines | Detail |
|---|--------|------|-------|--------|
| 1.9.1 | Remove hardcoded "Hanks" | `app/templates/base.html` | 215, 337 | Replace with `{{ tenant.name }}` from request context |
| 1.9.2 | Remove hardcoded Shopify URL | `app/templates/base.html` | 217, 330 | Replace with `{{ tenant.shopify_admin_url }}` |
| 1.9.3 | Remove hardcoded Railway URL | `app/templates/base.html` | 222, 340 | Only show for admin/superuser |
| 1.9.4 | Make app title configurable | `app/templates/base.html` | 46 | `{{ tenant.app_name or "RIFF" }}` |

---

## PHASE 2: ONBOARDING & BILLING (Est. 3-4 days)

### 2.1 Tenant Registration Flow
| # | Action | Detail |
|---|--------|--------|
| 2.1.1 | Create signup endpoint | `POST /auth/signup` → creates tenant + first user (owner role) |
| 2.1.2 | Create signup template | `app/templates/auth/signup.html` — business name, email, password |
| 2.1.3 | Generate tenant slug | From business name, check uniqueness |
| 2.1.4 | Send welcome email | Via `notification_service.py` |

### 2.2 Platform Connection Wizard
| # | Action | Detail |
|---|--------|--------|
| 2.2.1 | Create platform connection page | `/settings/platforms` — shows connected/disconnected status per platform |
| 2.2.2 | Reverb OAuth flow | Redirect to Reverb OAuth → callback saves token to `tenant_platform_credentials` |
| 2.2.3 | eBay OAuth flow | Redirect to eBay OAuth → callback. Most complex (expires, refresh tokens) |
| 2.2.4 | Shopify OAuth flow | Redirect to Shopify install → callback. App install flow. |
| 2.2.5 | VR manual credentials | Username/password form (no API, scraping-based). Store encrypted. |
| 2.2.6 | Credential validation | Test each platform connection after saving. Show success/failure. |

### 2.3 Initial Import Wizard
| # | Action | Detail |
|---|--------|--------|
| 2.3.1 | Create import wizard page | `/onboarding/import` — step-by-step first inventory pull |
| 2.3.2 | "Pull from Reverb" trigger | Run first Reverb sync for new tenant, show progress |
| 2.3.3 | Category mapping step | Show unmapped categories, suggest mappings (could use LLM) |
| 2.3.4 | Review & confirm step | Show imported products, allow corrections before going live |

### 2.4 Billing (Stripe Integration)
| # | Action | Detail |
|---|--------|--------|
| 2.4.1 | Add Stripe dependency | `stripe` package |
| 2.4.2 | Create Stripe products/prices | 4 tiers: Starter (£29), Growth (£59), Pro (£99), Enterprise (£199) |
| 2.4.3 | Create billing page | `/settings/billing` — current plan, upgrade/downgrade, payment method |
| 2.4.4 | Stripe webhook handler | `POST /webhooks/stripe` — handle subscription changes |
| 2.4.5 | Plan enforcement middleware | Check tenant plan limits (listing count, platform count) before creating listings |
| 2.4.6 | Trial period logic | 14-day free trial on signup, then require plan selection |

### 2.5 Tenant Admin Settings
| # | Action | Detail |
|---|--------|--------|
| 2.5.1 | Create settings page | `/settings/general` — business name, branding, notification emails |
| 2.5.2 | Pricing configuration | `/settings/pricing` — per-platform markup percentages |
| 2.5.3 | Sync configuration | `/settings/sync` — enable/disable platforms, sync intervals |
| 2.5.4 | Team management | `/settings/team` — invite users, set roles (owner/staff/readonly) |

---

## PHASE 3: INFRASTRUCTURE MIGRATION (Est. 1 day)

### 3.1 Redis Setup
| # | Action | Detail |
|---|--------|--------|
| 3.1.1 | Add Redis to Railway | Railway plugin or external Redis provider |
| 3.1.2 | Configure arq connection | `REDIS_URL` env var |
| 3.1.3 | Test job queue | Enqueue and process a test job |

### 3.2 Database Optimization
| # | Action | Detail |
|---|--------|--------|
| 3.2.1 | Add PgBouncer | Connection pooling for multi-tenant (transaction mode) |
| 3.2.2 | Add composite indexes | All `(tenant_id, ...)` indexes from Phase 1 |
| 3.2.3 | Plan table partitioning | `sync_events` by month (trigger: >10M rows), `listing_stats_history` by month (trigger: >50M rows) |

### 3.3 Monitoring
| # | Action | Detail |
|---|--------|--------|
| 3.3.1 | Add Sentry | Error tracking with tenant context tags |
| 3.3.2 | Add UptimeRobot | External health check on `/health` endpoint |
| 3.3.3 | Per-tenant metrics | Dashboard showing sync health per tenant |

### 3.4 Platform Migration Readiness (Future — at 30 customers)
| # | Action | Detail |
|---|--------|--------|
| 3.4.1 | Document Render migration path | `pg_dump` → `pg_restore`, update env vars, test |
| 3.4.2 | Document DigitalOcean migration path | Same process, London region available |
| 3.4.3 | Decide trigger criteria | When to pull trigger on Railway → Render/DO (SLA needs, connection pooling, read replicas) |

---

## DECISION LOG

These are the architectural decisions and their resolutions:

| # | Decision | Options | Resolution |
|---|----------|---------|------------|
| D1 | Auth system | Auth0/Clerk (buy) vs roll-own JWT | Roll-own JWT first. Add Auth0 later if needed. Less moving parts. |
| D2 | Tenant routing | Subdomain (`hanks.riff.app`) vs path prefix (`/t/hanks/...`) vs JWT claim only | JWT claim only (simplest). Add subdomains later for white-label. |
| D3 | VR at scale | Browser pool vs negotiate API access vs premium-only tier | Premium tier only. Selenium doesn't scale to 500 concurrent. Offer to top-tier customers. |
| D4 | Encryption for credentials | Fernet (symmetric) vs AWS KMS vs Vault | Fernet with key in env var. Simple, portable, sufficient for now. |
| D5 | Job queue | arq (Redis, async-native) vs Celery (heavier, more ecosystem) vs keep custom | arq — async-native, lightweight, Redis-backed. Perfect fit for FastAPI. |
| D6 | Do Phase 0 cleanup destroy the current single-tenant before Phase 1 is ready? | Parallel dev branch vs sequential | Sequential. Phase 0 changes are backwards-compatible. Clean up, deploy, then start Phase 1. |

---

## VERIFICATION PLAN

After each phase:

**Phase 0:** Run `pytest tests/`. Manual test: trigger a sync, process a sale, relist a product. All existing flows must work identically.

**Phase 1:** Create a second tenant via admin script. Log in as tenant 2. Verify: cannot see tenant 1 data. Create a product. Verify: tenant 1 cannot see it. Run sync for tenant 2 (if test credentials available).

**Phase 2:** Full signup flow: register → connect Reverb → import inventory → view dashboard. Stripe test mode for billing.

**Phase 3:** Load test with 10 simulated tenants running concurrent syncs. Monitor connection pool, job queue depth, response times.

---

## PROGRESS TRACKING

### Phase 0
- [ ] 0.1 Remove Dead Methods
- [ ] 0.2 Consolidate EventProcessor into SyncService
- [ ] 0.3 Split inventory.py
- [ ] 0.4 Clean Up Scripts
- [ ] 0.5 Fix Unused Imports

### Phase 1
- [ ] 1.1 New Database Tables
- [ ] 1.2 Add tenant_id to Existing Tables
- [ ] 1.3 Migration Strategy
- [ ] 1.4 Authentication System
- [ ] 1.5 Tenant Context Middleware
- [ ] 1.6 Credential Injection Refactor
- [ ] 1.7 Service Layer Tenant Awareness
- [ ] 1.8 Background Scheduler Rewrite
- [ ] 1.9 Template Branding

### Phase 2
- [ ] 2.1 Tenant Registration Flow
- [ ] 2.2 Platform Connection Wizard
- [ ] 2.3 Initial Import Wizard
- [ ] 2.4 Billing (Stripe Integration)
- [ ] 2.5 Tenant Admin Settings

### Phase 3
- [ ] 3.1 Redis Setup
- [ ] 3.2 Database Optimization
- [ ] 3.3 Monitoring
- [ ] 3.4 Platform Migration Readiness
