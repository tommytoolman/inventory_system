# RIFF Multi-Tenant SaaS Transformation
## Implementation Roadmap & Project Plan

**Version:** 1.0
**Date:** 14 March 2026
**Prepared for:** RIFF Development Team & Stakeholders
**Scope:** Transform RIFF from single-tenant inventory system to multi-tenant SaaS serving up to 20 independent music gear retail organisations

---

## Section 1: Executive Summary

### Overview

RIFF is a production-grade, single-tenant inventory management system (20,500+ lines of service code, 27 database tables, ~217 API endpoints, 38 Jinja2 templates) currently serving one music gear retailer (Hanks/Rockers Guitars). This plan details the transformation into a shared-infrastructure, multi-tenant SaaS platform supporting up to 20 independent retail organisations.

The transformation involves six major workstreams:

1. **Code Cleanup** — Remove dead code, split the 8,029-line `inventory.py` monolith, consolidate duplicated logic
2. **Database Multi-Tenancy** — Add `tenant_id` to ~20 tables, create 5 new tenant management tables, implement Row-Level Security
3. **Authentication Overhaul** — Replace HTTP Basic Auth with Supabase JWT authentication, tenant-scoped sessions
4. **Query Scoping & Credential Injection** — Tenant-filter all 110+ database access points, replace 65+ hardcoded credential reads with a `CredentialManager`
5. **Background Job Isolation** — Replace custom scheduler with tenant-aware job queue (arq + Redis)
6. **Frontend Migration** — Migrate 38 Jinja2 templates to Next.js with tenant-scoped API layer

### Key Phases and Durations

| Phase | Name | Duration | Effort |
|-------|------|----------|--------|
| 0 | Code Cleanup & Stabilisation | 1–2 weeks | 40–60 hours |
| 1 | Database Schema & Migration | 1–2 weeks | 30–50 hours |
| 2 | Authentication (Supabase) | 2–3 weeks | 50–70 hours |
| 3 | Query Scoping & Tenant Middleware | 2–3 weeks | 60–90 hours |
| 4 | Credential Management & Platform Isolation | 2–3 weeks | 50–80 hours |
| 5 | Background Jobs & Sync Scheduling | 1–2 weeks | 30–50 hours |
| 6 | Frontend (Next.js) | 4–6 weeks | 120–180 hours |
| 7 | Onboarding, Billing & Admin | 2–3 weeks | 50–70 hours |
| 8 | Testing, Hardening & Pilot Launch | 2–3 weeks | 50–70 hours |
| **Total** | | **17–27 weeks** | **480–720 hours** |

### Critical Path

```
Phase 0 (Cleanup)
    → Phase 1 (Schema)
        → Phase 2 (Auth) ←── BLOCKING: All subsequent work depends on tenant identity
            → Phase 3 (Query Scoping) + Phase 4 (Credentials) [PARALLEL]
                → Phase 5 (Jobs)
                    → Phase 6 (Frontend) [can start partially during Phase 3]
                        → Phase 7 (Onboarding/Billing)
                            → Phase 8 (Pilot Launch)
```

**The single longest blocking dependency is Phase 2 (Authentication).** Until Supabase JWT is functional and producing `tenant_id` claims, no query scoping or credential injection can be tested end-to-end.

### Major Risks

| Risk | Impact | Likelihood |
|------|--------|------------|
| **eBay OAuth per-tenant** — each org needs its own eBay Developer App or consent flow | High | High |
| **V&R Selenium at scale** — single-session Cloudflare bypass cannot serve 20 concurrent tenants | High | High |
| **Next.js rewrite scope** — 38 templates with embedded business logic = large surface area | Medium | High |
| **Data leakage during transition** — incomplete query scoping exposes cross-tenant data | Critical | Medium |
| **Existing client disruption** — schema migration or auth change breaks production for Hanks | Critical | Low (if planned) |

---

## Section 2: Pre-Implementation Checklist

All items below must be resolved **before coding begins** on Phase 1.

### Infrastructure Decisions

- [ ] **[DECISION] Database hosting strategy** — Stay on Railway PostgreSQL or migrate to Supabase Postgres? If Supabase, the database and auth are co-located (simpler). If Railway, Supabase auth connects to an external DB (more moving parts). **Recommendation:** Use Supabase-hosted PostgreSQL for new multi-tenant database; keep Railway PostgreSQL for legacy/migration period.
- [ ] **[DECISION] Frontend hosting** — Vercel (natural fit for Next.js) or Railway? **Recommendation:** Vercel for Next.js frontend, Railway for FastAPI backend API.
- [ ] **[DECISION] Redis provider** — Railway Redis addon, Upstash (serverless), or Supabase Edge Functions? **Recommendation:** Upstash (serverless Redis, pay-per-use, no idle costs at 20 tenants).
- [ ] **[DECISION] DNS & domain strategy** — `app.riff.tools`, `{tenant}.riff.tools`, or path-based routing? **Recommendation:** Single domain `app.riff.tools` with JWT-based tenant routing (simplest for 20 tenants). Add subdomain routing later for white-label.

### Tool Setup

- [ ] Create Supabase project (free tier sufficient initially)
- [ ] Configure Supabase Auth (email/password provider, JWT secret)
- [ ] Create Vercel project linked to new Next.js repo
- [ ] Provision Redis instance (Upstash or Railway addon)
- [ ] Set up staging environment (separate Supabase project + separate Railway service)

### Security Decisions

- [ ] **[DECISION] Credential encryption** — Fernet (symmetric, key in env var) vs Supabase Vault vs AWS KMS. **Recommendation:** Fernet with `ENCRYPTION_KEY` in env var. Simple, portable, sufficient for 20 tenants. Upgrade to KMS if scaling past 50.
- [ ] **[DECISION] JWT claim structure** — What claims does Supabase JWT carry? Minimum: `sub` (user_id), `tenant_id`, `role`, `email`. Store tenant_id in Supabase `raw_user_meta_data` or custom claims via database function.
- [ ] **[DECISION] Row-Level Security (RLS)** — Use PostgreSQL RLS as defence-in-depth alongside application-level filtering? **Recommendation:** Yes. Belt-and-braces approach for tenant isolation.

### Scope Clarifications

- [ ] **[BLOCKER] eBay OAuth model** — Does each retailer need their own eBay Developer App (requires eBay approval per app), or can RIFF register as a single eBay Partner app with multi-user consent? **Research required.** If single-app model works, this is 1 week. If per-tenant app, this is 3–4 weeks and may require eBay partnership.
- [ ] **[BLOCKER] Shopify OAuth model** — Same question. Shopify supports multi-tenant apps natively (Shopify App Store model), so this is likely simpler. Confirm: will RIFF be a public Shopify app or unlisted?
- [ ] **[DECISION] V&R strategy** — Options: (A) Premium-tier only (limit to 3–5 tenants), (B) Selenium browser pool with tenant rotation, (C) Drop V&R for MVP. **Recommendation:** Option A — premium tier only, with explicit warning about fragility.
- [ ] **[DECISION] Billing model** — Tiered subscription (£29/£59/£99/£199) as per roadmap? Confirm tiers, listing limits, and platform limits.
- [ ] **[DECISION] MVP platform set** — All 5 platforms for first pilot, or subset? **Recommendation:** Reverb + eBay + Shopify for MVP. WooCommerce has multi-tenant foundation already. V&R deferred to premium tier.

### Team & Resource Decisions

- [ ] **[DECISION] Development model** — Solo developer (AI-assisted), small team (2–3), or outsource phases? Estimates in this plan assume 1 senior developer with AI assistance.
- [ ] **[DECISION] Pilot client selection** — Identify 2–3 beta retailers before development starts. Ideal: existing contacts, 50–200 listings, Reverb-primary, willing to tolerate rough edges.

---

## Section 3: Phase-by-Phase Breakdown

---

### Phase 0: Code Cleanup & Stabilisation

**Duration:** 1–2 weeks
**Objective:** Remove dead code, split monolithic files, and consolidate duplicated logic so that multi-tenant changes touch a clean, well-organised codebase.
**Dependencies:** None (can start immediately)

#### Tasks

| ID | Task | Effort | Success Criteria | Risk |
|----|------|--------|-----------------|------|
| T0.1 | Delete dead methods in `sync_services.py` (`_handle_price_change_old`, `_handle_order_sale`) | 2h | Methods removed, `pytest` passes | Low |
| T0.2 | Delete dead method in `reverb_service.py` (`create_sync_events_for_stocked_orders`) | 1h | 115 lines removed, tests pass | Low |
| T0.3 | Remove commented code blocks in `sync_services.py`, `main.py` | 1h | No commented-out code in production files | Low |
| T0.4 | Audit all `EventProcessor` callers and redirect to `SyncService` | 4h | Zero imports of `EventProcessor` remain | Medium — must verify each call site handles same interface |
| T0.5 | Delete `event_processor.py` after consolidation | 1h | File deleted, ~1,635 lines removed, tests pass | Low (blocked on T0.4) |
| T0.6 | Extract product CRUD routes from `inventory.py` → `routes/products.py` | 6h | ~3,000 lines moved, all product routes functional | Medium — template paths, URL references |
| T0.7 | Extract platform listing operations → `routes/listings.py` | 4h | ~1,000 lines moved, listing creation works | Medium |
| T0.8 | Extract Dropbox management → `routes/dropbox.py` | 3h | ~1,500 lines moved, image operations work | Low |
| T0.9 | Extract data/search APIs → `routes/data_api.py` | 2h | ~500 lines moved, category/shipping APIs work | Low |
| T0.10 | Clean up orphaned scripts in `scripts/` | 2h | Duplicate scripts deleted, useful scripts in `scripts/debug/` | Low |
| T0.11 | Fix unused imports across route and service files | 1h | No unused import warnings | Low |
| T0.12 | Run full test suite, fix any regressions | 4h | `pytest tests/` — all 369 tests pass | Low |
| T0.13 | Manual smoke test: sync, sale processing, relist, image refresh | 3h | All critical paths work identically to pre-cleanup | Low |

**Deliverables:**
- `inventory.py` reduced from 8,029 to ~2,000 lines
- `event_processor.py` deleted (~1,635 lines removed)
- ~500 lines of dead code removed from services
- Clean, modular route structure ready for tenant-scoping

**Testing Strategy:** Full `pytest` run + manual smoke test of sync cycle, sale processing, and listing creation on all platforms.

**Rollback Plan:** All changes are on a feature branch. If any regression is found, `git revert` the merge commit. No database changes in this phase.

---

### Phase 1: Database Schema & Migration

**Duration:** 1–2 weeks
**Objective:** Create tenant management tables, add `tenant_id` to all data tables, backfill existing data as "Tenant Zero" (Hanks), and establish RLS policies.
**Dependencies:** Phase 0 complete (clean codebase)

#### Tasks

| ID | Task | Effort | Success Criteria | Risk |
|----|------|--------|-----------------|------|
| T1.1 | Design and create `tenants` table | 3h | Table exists: `id` (UUID PK), `name`, `slug` (unique), `is_active`, `plan_tier`, `settings` (JSONB), `created_at`, `updated_at` | Low |
| T1.2 | Design and create `tenant_users` table | 3h | Table exists: `id`, `tenant_id` (FK), `supabase_user_id` (unique), `email`, `role` (owner/staff/readonly), `is_active`, timestamps | Low |
| T1.3 | Design and create `tenant_platform_credentials` table | 4h | Table exists: `id`, `tenant_id` (FK), `platform_name`, `credentials` (JSONB, encrypted), `is_active`, `last_verified_at`, timestamps | Low |
| T1.4 | Design and create `tenant_sync_configs` table | 2h | Table exists: `id`, `tenant_id` (FK), `platform_name`, `enabled`, `interval_minutes`, `last_sync_at` | Low |
| T1.5 | Add `tenant_id` (UUID, FK) to `products` table | 2h | Column added, composite index on `(tenant_id, sku)`, old unique constraint on `sku` alone dropped | Medium — SKU uniqueness now per-tenant |
| T1.6 | Add `tenant_id` to `platform_common` | 1h | Column added, composite index on `(tenant_id, product_id, platform_name)` | Low |
| T1.7 | Add `tenant_id` to all 5 listing tables (`reverb_listings`, `ebay_listings`, `shopify_listings`, `vr_listings`, `woocommerce_listings`) | 3h | Columns added with indexes | Low |
| T1.8 | Add `tenant_id` to all 4 order tables (`reverb_orders`, `ebay_orders`, `shopify_orders`, `woocommerce_orders`) | 2h | Columns added with indexes | Low |
| T1.9 | Add `tenant_id` to event/audit tables (`sync_events`, `sync_errors`, `activity_log`, `sync_stats`) | 2h | Columns added, composite index `(tenant_id, created_at)` on `sync_events` and `activity_log` | Low |
| T1.10 | Add `tenant_id` to remaining operational tables (`vr_jobs`, `shipping_profiles`, `shipments`, `listing_stats_history`) | 2h | Columns added with indexes | Low |
| T1.11 | Create "Tenant Zero" — insert default tenant for Hanks/Rockers | 1h | Tenant row exists with known UUID | Low |
| T1.12 | Write backfill migration — set all existing rows' `tenant_id` to Tenant Zero UUID | 3h | Zero NULL `tenant_id` values across all tables | **[RISK]** Large tables may lock during update |
| T1.13 | Add NOT NULL constraint to all `tenant_id` columns (after backfill) | 1h | Constraints enforced | Low (blocked on T1.12) |
| T1.14 | Update all SQLAlchemy ORM models to include `tenant_id` column | 4h | All 20+ model files updated, relationships defined | Medium — must match migration exactly |
| T1.15 | Write RLS policies for all tenant-scoped tables | 4h | `CREATE POLICY tenant_isolation ON {table} USING (tenant_id = current_setting('app.current_tenant')::uuid)` for each table | Medium — RLS debugging can be tricky |
| T1.16 | Test migration on cloned database (`pg_dump` production → restore → migrate → verify) | 3h | Migration completes without errors, data integrity verified | Low |

**Shared reference tables (NO `tenant_id` needed):** `category_mappings`, `condition_mapping`, `platform_preference`, `woocommerce_stores` (already has its own multi-tenant model)

**Deliverables:**
- 5 new tenant management tables
- `tenant_id` added to ~20 existing tables with indexes
- All existing data backfilled under Tenant Zero
- RLS policies for defence-in-depth
- Updated ORM models

**Testing Strategy:**
1. Clone production DB → run migration → verify row counts unchanged
2. Verify Tenant Zero UUID present on all rows
3. Test RLS: connect as two different `SET LOCAL app.current_tenant` values, confirm isolation
4. Run `pytest` with Tenant Zero context

**Rollback Plan:** The Alembic migration includes a `downgrade()` that drops `tenant_id` columns and new tables. If migration fails midway, `alembic downgrade` to previous revision. **Critical:** Test on clone first, never run untested migrations on production.

---

### Phase 2: Authentication (Supabase)

**Duration:** 2–3 weeks
**Objective:** Replace HTTP Basic Auth with Supabase JWT authentication. Every request carries a validated JWT with `tenant_id` claim. Dual-auth period allows existing client to continue on Basic Auth while new system is validated.
**Dependencies:** Phase 1 complete (tenant tables exist)

#### Tasks

| ID | Task | Effort | Success Criteria | Risk |
|----|------|--------|-----------------|------|
| T2.1 | Configure Supabase Auth project — email/password provider, custom JWT claims hook | 4h | Supabase project returns JWTs with `tenant_id` in claims | Low |
| T2.2 | Create Supabase database function for custom JWT claims | 3h | `auth.jwt()` includes `tenant_id` from `tenant_users` table lookup | Medium — Supabase custom claims require database trigger |
| T2.3 | Add `supabase-py` and `python-jose[cryptography]` to `requirements.txt` | 1h | Packages installed and importable | Low |
| T2.4 | Create `app/core/supabase_auth.py` — JWT validation, user extraction | 6h | `verify_supabase_jwt(token)` returns `(user_id, tenant_id, role, email)` | Medium |
| T2.5 | Create `app/core/tenant.py` — `contextvars` for `current_tenant_id` | 2h | `current_tenant_id: ContextVar[str]` accessible throughout request lifecycle | Low |
| T2.6 | Create tenant context middleware in `app/main.py` | 4h | After JWT validation, `current_tenant_id` set from JWT claim; available to all downstream code | Medium |
| T2.7 | Modify `get_session()` in `app/database.py` — execute `SET LOCAL app.current_tenant = :tenant_id` on each session | 3h | PostgreSQL session variable set for RLS enforcement | Medium — must handle session pooling correctly |
| T2.8 | Rewrite `app/core/security.py` — `get_current_user()` returns user from Supabase JWT | 6h | Replaces `BASIC_AUTH_USERNAME/PASSWORD` pattern | **[RISK]** Must maintain backward compatibility during transition |
| T2.9 | Implement dual-auth: accept both Basic Auth (Tenant Zero) AND Supabase JWT | 4h | Existing client continues working with Basic Auth; new clients use JWT | Medium |
| T2.10 | Create login API endpoint `POST /auth/login` — proxies to Supabase | 3h | Returns Supabase access + refresh tokens | Low |
| T2.11 | Create signup API endpoint `POST /auth/signup` — creates Supabase user + tenant record | 6h | New user created in Supabase, linked to new tenant via `tenant_users` | Medium |
| T2.12 | Update `require_auth()` decorator across all routes | 4h | All ~217 endpoints use new auth; `request.state.tenant_id` available | Medium — large surface area |
| T2.13 | Create Supabase user + tenant_user record for existing Hanks operators | 2h | Existing users can log in via Supabase with same email | Low |
| T2.14 | Test dual-auth: Basic Auth still works for Hanks, JWT works for new tenant | 4h | Both auth paths verified end-to-end | Low |

**Deliverables:**
- Supabase project configured with custom JWT claims
- FastAPI middleware extracting `tenant_id` from every request
- Dual-auth period (Basic Auth + JWT) for zero-downtime transition
- Login/signup API endpoints
- PostgreSQL RLS activated via session variable

**Testing Strategy:**
1. Unit test JWT validation with valid/invalid/expired tokens
2. Unit test tenant context middleware sets correct `tenant_id`
3. Integration test: login as Tenant Zero user → access products → only Tenant Zero data visible
4. Integration test: create Tenant One user → access products → empty (no data yet)
5. Regression test: Basic Auth still works for all existing routes

**Rollback Plan:** Dual-auth design means rollback is simply disabling the Supabase path and reverting `security.py` to Basic Auth only. No data loss, no schema changes required.

---

### Phase 3: Query Scoping & Tenant Middleware

**Duration:** 2–3 weeks
**Objective:** Every database query in the application filters by `tenant_id`. Every INSERT sets `tenant_id`. No cross-tenant data leakage is possible.
**Dependencies:** Phase 2 complete (tenant context available on every request)

#### Tasks

| ID | Task | Effort | Success Criteria | Risk |
|----|------|--------|-----------------|------|
| T3.1 | Create `TenantScopedSession` wrapper — auto-adds `.where(Model.tenant_id == current_tenant_id)` to all SELECT queries | 8h | Wrapper tested with all model types; zero manual filtering needed for reads | **[RISK]** Complex SQLAlchemy customisation; must handle joins, subqueries, aggregations |
| T3.2 | Audit and scope all queries in `reverb_service.py` (136K) | 6h | All 30+ queries filtered by `tenant_id` | Medium — largest service file |
| T3.3 | Audit and scope all queries in `ebay_service.py` (134K) | 6h | All 30+ queries filtered | Medium |
| T3.4 | Audit and scope all queries in `shopify_service.py` (109K) | 5h | All 25+ queries filtered | Medium |
| T3.5 | Audit and scope all queries in `woocommerce_service.py` (55K) | 3h | All 15+ queries filtered (partially done — `wc_store_id` pattern exists) | Low |
| T3.6 | Audit and scope all queries in `vr_service.py` (76K) | 4h | All 20+ queries filtered | Medium |
| T3.7 | Audit and scope all queries in `sync_services.py` (141K) | 6h | All 25+ queries filtered | Medium |
| T3.8 | Audit and scope all queries in `order_sale_processor.py` (27K) | 3h | All 10+ queries filtered | Medium |
| T3.9 | Audit and scope all queries in route files (`inventory.py`, `reports.py`, `orders.py`, platform routes) | 8h | All route-level queries filtered (~50 locations) | Medium |
| T3.10 | Scope all INSERT operations — set `tenant_id` on new objects | 6h | No object can be created without `tenant_id` | Medium |
| T3.11 | Scope analytics/reporting queries (`analytics_service.py`, `reports.py`) | 4h | Reports show only current tenant's data | Low |
| T3.12 | Update global in-memory caches to be tenant-keyed | 3h | Cache key format: `{tenant_id}:{original_key}` (e.g., eBay category cache in `ebay_service.py:47`) | Low |
| T3.13 | **Tenant isolation verification test suite** | 8h | Automated tests: create data as Tenant A, query as Tenant B → zero results | **Critical** |
| T3.14 | Penetration testing for tenant leakage | 4h | Manual testing of 20 critical endpoints with cross-tenant tokens | **Critical** |

**Deliverables:**
- All 110+ database access points scoped by `tenant_id`
- All INSERT operations set `tenant_id`
- In-memory caches tenant-keyed
- Comprehensive tenant isolation test suite

**Testing Strategy:**
1. Create two test tenants with known data
2. For every service method: call as Tenant A, verify only Tenant A data returned
3. Attempt cross-tenant access via manipulated JWT → must return 403 or empty results
4. RLS as second layer catches any application-level filtering misses

**Rollback Plan:** Query scoping changes are additive (adding `.where()` clauses). If a scoping change breaks a query, the fix is to correct the filter, not remove it. Rollback = revert to unscoped query temporarily, flag as security issue.

---

### Phase 4: Credential Management & Platform Isolation

**Duration:** 2–3 weeks (can run **in parallel** with Phase 3)
**Objective:** Replace all hardcoded environment variable credential reads with a `CredentialManager` service that fetches encrypted, per-tenant credentials from the database.
**Dependencies:** Phase 2 complete (tenant context available)

#### Tasks

| ID | Task | Effort | Success Criteria | Risk |
|----|------|--------|-----------------|------|
| T4.1 | Create `CredentialManager` service (`app/services/credential_manager.py`) | 8h | Fetches encrypted credentials from `tenant_platform_credentials`, decrypts with Fernet, caches (60s TTL) | Low |
| T4.2 | Create credential encryption/decryption utilities | 3h | `encrypt_credentials(data: dict) → str`, `decrypt_credentials(cipher: str) → dict` | Low |
| T4.3 | Create admin CLI script to seed credentials for existing tenant | 2h | `python scripts/seed_credentials.py --tenant=hanks --platform=reverb --key=...` | Low |
| T4.4 | Refactor Reverb credential reads (6 locations) | 3h | All reads via `await cred_mgr.get('reverb')` | Low |
| T4.5 | Refactor eBay credential reads (19 locations) | 6h | All reads via credential manager; handle OAuth token refresh per tenant | **[RISK]** eBay OAuth token refresh must be tenant-scoped |
| T4.6 | Refactor Shopify credential reads (7 locations) | 3h | All reads via credential manager | Low |
| T4.7 | Refactor V&R credential reads (33 locations — highest count) | 8h | All reads via credential manager; handle cookie storage per tenant | Medium — V&R uses cookies, not just API keys |
| T4.8 | Refactor WooCommerce credential reads | 2h | Already partially tenant-scoped via `woocommerce_stores`; align with `CredentialManager` interface | Low |
| T4.9 | Remove hardcoded `londonvintagegts` from `ebay_service.py:78` | 1h | Fetched from tenant settings | Low |
| T4.10 | Move DHL shipper details from `config.py` to `tenant_settings` | 2h | `DHL_SHIPPER_*` read from per-tenant settings | Low |
| T4.11 | Move email/notification config to per-tenant settings | 2h | `NOTIFICATION_EMAILS`, `ADMIN_EMAIL` etc. from tenant settings | Low |
| T4.12 | Move pricing markups to per-tenant settings | 2h | `REVERB_PRICE_MARKUP_PERCENT` etc. from tenant settings | Low |
| T4.13 | Create platform credential validation endpoints | 4h | `POST /api/settings/platforms/{platform}/test` → test connectivity with tenant's credentials | Low |
| T4.14 | Fallback logic: if no tenant credentials, fall back to env vars (Tenant Zero only) | 2h | Tenant Zero backward compatibility maintained | Low |

**Deliverables:**
- `CredentialManager` service with encrypted storage and caching
- All 65+ credential reads migrated from env vars to database
- Per-tenant platform configuration (markups, DHL, notifications)
- Credential validation endpoints
- Backward compatibility for Tenant Zero

**Testing Strategy:**
1. Seed test credentials for Tenant One
2. Call each platform's ping endpoint as Tenant One → success
3. Call as Tenant Two (no credentials) → graceful error, not crash
4. Verify Tenant Zero still works via env var fallback
5. Test credential cache invalidation (update credential → next call uses new value)

**Rollback Plan:** The `CredentialManager` includes a fallback path to env vars. If credential injection fails, the fallback ensures Tenant Zero continues operating. The fallback can be made the default temporarily by setting a feature flag.

---

### Phase 5: Background Jobs & Sync Scheduling

**Duration:** 1–2 weeks
**Objective:** Replace the single-tenant custom scheduler with a tenant-aware job queue that can run syncs for multiple organisations without interference or rate-limit collision.
**Dependencies:** Phases 3 and 4 complete (queries scoped, credentials injected)

#### Tasks

| ID | Task | Effort | Success Criteria | Risk |
|----|------|--------|-----------------|------|
| T5.1 | Add `arq` and `redis` to `requirements.txt` | 1h | Packages installed | Low |
| T5.2 | Provision Redis instance (Upstash or Railway) | 1h | `REDIS_URL` configured, connectivity verified | Low |
| T5.3 | Create `app/jobs/` directory with tenant-aware job definitions | 6h | Jobs: `sync_reverb(tenant_id)`, `sync_ebay(tenant_id)`, `sync_shopify(tenant_id)`, `sync_vr(tenant_id)`, `sync_woocommerce(tenant_id)`, `collect_stats(tenant_id)`, `auto_archive(tenant_id)` | Medium |
| T5.4 | Create scheduler loop (`scripts/run_scheduler.py`) | 6h | Queries all active tenants → checks `tenant_sync_configs` → enqueues due jobs to Redis | Medium |
| T5.5 | Create arq worker process (`scripts/run_worker.py`) | 4h | Picks up jobs, sets tenant context, executes sync with correct credentials | Medium |
| T5.6 | Implement rate-limit coordination across tenants | 4h | If Reverb allows 120 req/min, 20 tenants share this budget fairly (6 req/min/tenant, or stagger sync times) | **[RISK]** Platform rate limits are the hard constraint |
| T5.7 | Implement sync locking per tenant per platform | 3h | Two concurrent syncs for same tenant+platform → second is rejected | Low |
| T5.8 | Create admin endpoint to view job queue status | 3h | `GET /api/admin/jobs` → shows pending, running, completed, failed jobs per tenant | Low |
| T5.9 | Migrate existing scheduled jobs to new system | 3h | All 7 scheduled job types running via arq | Low |
| T5.10 | Deprecate old scheduler (keep as fallback) | 1h | `run_sync_scheduler.py` marked deprecated; new scheduler runs alongside | Low |

**Deliverables:**
- Redis-backed job queue via arq
- Tenant-aware scheduler that checks `tenant_sync_configs`
- Rate-limit budget sharing across tenants
- Per-tenant sync locking
- Admin job monitoring endpoint

**Testing Strategy:**
1. Enqueue a test job for Tenant One → verify it executes with correct tenant context
2. Enqueue jobs for Tenant One and Tenant Two → verify they don't interfere
3. Simulate rate limit hit → verify backoff and fair sharing
4. Kill worker mid-job → verify job retries on restart

**Rollback Plan:** Run old scheduler alongside new one during transition. If arq fails, old scheduler takes over for Tenant Zero. Feature flag `USE_NEW_SCHEDULER` controls which system is active.

---

### Phase 6: Frontend Migration (Next.js)

**Duration:** 4–6 weeks
**Objective:** Migrate from 38 server-rendered Jinja2 templates to a Next.js frontend application with client-side routing, Supabase auth integration, and tenant-scoped API calls.
**Dependencies:** Phases 2–4 substantially complete (API is tenant-scoped and authenticated)

**Note:** This is the largest single phase. It can begin partially during Phase 3 (API design and component library can start before all backend scoping is complete).

#### Tasks

| ID | Task | Effort | Success Criteria | Risk |
|----|------|--------|-----------------|------|
| T6.1 | Scaffold Next.js project (App Router, TypeScript, Tailwind CSS) | 4h | Project builds, deploys to Vercel | Low |
| T6.2 | Set up Supabase client-side auth (login, signup, session management) | 6h | Users can log in, JWT stored in cookie, auto-refresh on expiry | Low |
| T6.3 | Create auth-guarded layout with tenant context provider | 4h | All pages wrapped in auth check; tenant info available via React context | Low |
| T6.4 | Design and build shared component library (tables, forms, modals, toasts, navigation) | 12h | Reusable components matching current Tailwind aesthetic | Low |
| T6.5 | Convert FastAPI routes to JSON-only API endpoints (remove Jinja2 rendering) | 8h | All routes return JSON, not HTML. Template rendering removed. API contract documented. | Medium — large surface area |
| T6.6 | Build Dashboard page (`dashboard.html` → Next.js) | 8h | Recent products, recent orders, pending syncs, platform status | Low |
| T6.7 | Build Inventory List page (`inventory/list.html` → Next.js) | 10h | Product grid with search, filters, pagination, platform icons | Medium — complex existing UI |
| T6.8 | Build Product Detail page (`inventory/detail.html` → Next.js) | 10h | Full product view with platform listings, pricing, images, action buttons | Medium |
| T6.9 | Build Add Product page (`inventory/add.html` → Next.js) | 10h | Multi-step form with platform selection, image upload, Dropbox integration | **[RISK]** Complex form with many conditional fields |
| T6.10 | Build Edit Product page (`inventory/edit.html` → Next.js) | 8h | Edit form with sync-on-save to selected platforms | Medium |
| T6.11 | Build Orders pages (`orders/list.html`, `orders/detail.html`) | 6h | Order list and detail views | Low |
| T6.12 | Build Reports pages (12 report templates) | 16h | Sync events, sales, listing health, price inconsistencies, platform coverage, etc. | Medium — many specialized pages |
| T6.13 | Build Settings pages (general, platforms, pricing, sync, team) | 10h | Tenant admin settings management | Low |
| T6.14 | Build Sync UI with WebSocket progress | 6h | Real-time sync progress via WebSocket connection | Medium |
| T6.15 | Build Error pages (sync errors, 404, 500) | 3h | Error display and resolution UI | Low |
| T6.16 | Build eBay template preview | 4h | Render eBay HTML listing template for preview | Low |
| T6.17 | Implement Dropbox image picker in React | 6h | Thumbnail browsing, lazy full-res, selection sync | Medium |
| T6.18 | Implement responsive/mobile layout | 6h | Key workflows usable on mobile | Low |

**Deliverables:**
- Complete Next.js application replicating all 38 Jinja2 templates
- Supabase auth integrated (login, signup, session management)
- Tenant-scoped API calls via Bearer token
- WebSocket integration for real-time sync progress
- Responsive design

**Testing Strategy:**
1. Visual regression testing: screenshot each page, compare old Jinja2 vs new Next.js
2. Functional testing: all CRUD operations work end-to-end
3. Auth testing: unauthenticated access redirects to login
4. Tenant isolation: Tenant A's data never visible to Tenant B
5. Mobile testing: key workflows on iPhone/Android viewport

**Rollback Plan:** During transition, both Jinja2 and Next.js frontends can run simultaneously (different URLs). If Next.js has critical issues, users switch back to Jinja2 at `api.riff.tools` (FastAPI serves HTML) while `app.riff.tools` (Next.js) is fixed.

---

### Phase 7: Onboarding, Billing & Admin

**Duration:** 2–3 weeks
**Objective:** Enable self-service tenant registration, platform connection, initial import, and Stripe billing.
**Dependencies:** Phase 6 substantially complete (frontend exists)

#### Tasks

| ID | Task | Effort | Success Criteria | Risk |
|----|------|--------|-----------------|------|
| T7.1 | Build tenant registration flow (signup → email verify → create tenant) | 6h | New user can register and access empty dashboard | Low |
| T7.2 | Build Reverb OAuth flow (redirect → callback → store token) | 6h | User connects Reverb account, token stored encrypted | Medium |
| T7.3 | Build eBay OAuth flow (redirect → callback → store tokens) | 8h | User connects eBay account, refresh token stored | **[BLOCKER]** Requires eBay App approval |
| T7.4 | Build Shopify OAuth/install flow | 6h | User connects Shopify store | Medium |
| T7.5 | Build V&R manual credential entry (username/password form) | 2h | Credentials stored encrypted, connectivity tested | Low |
| T7.6 | Build initial import wizard (choose platform → pull listings → review → confirm) | 10h | First-time import from primary platform | Medium |
| T7.7 | Integrate Stripe: create products/prices for 4 tiers | 4h | Stripe products configured in test mode | Low |
| T7.8 | Build billing page (current plan, upgrade, payment method) | 6h | Users can subscribe and manage billing | Low |
| T7.9 | Create Stripe webhook handler (`POST /webhooks/stripe`) | 4h | Subscription changes update tenant `plan_tier` | Low |
| T7.10 | Implement plan enforcement middleware (listing/platform limits) | 4h | Exceeding plan limits shows upgrade prompt | Low |
| T7.11 | Build team management page (invite users, set roles) | 6h | Tenant owner can invite staff members | Low |
| T7.12 | Build super-admin dashboard (all tenants, health, usage) | 6h | RIFF operators can view/manage all tenants | Low |
| T7.13 | Create tenant onboarding email sequence (welcome, setup guide, tips) | 3h | Automated emails via SMTP or Supabase hooks | Low |

**Deliverables:**
- Self-service tenant registration and onboarding
- OAuth flows for Reverb, eBay, Shopify
- Stripe billing integration with 4 tiers
- Team management
- Super-admin dashboard

**Testing Strategy:**
1. Full onboarding flow: register → connect Reverb → import → subscribe → view dashboard
2. Stripe test mode for all billing scenarios (upgrade, downgrade, cancel, failed payment)
3. OAuth flow testing with each platform's sandbox/test environment
4. Plan enforcement: attempt to exceed limits → verify rejection

**Rollback Plan:** Onboarding features are additive. If OAuth flows break, tenants can be onboarded manually (admin seeds credentials). Stripe operates in test mode until launch.

---

### Phase 8: Testing, Hardening & Pilot Launch

**Duration:** 2–3 weeks
**Objective:** Comprehensive testing, security audit, performance validation, and soft launch with 2–3 pilot clients.
**Dependencies:** All previous phases complete

#### Tasks

| ID | Task | Effort | Success Criteria | Risk |
|----|------|--------|-----------------|------|
| T8.1 | Comprehensive tenant isolation audit — automated | 8h | Test suite covers all 217 endpoints for cross-tenant access | **Critical** |
| T8.2 | Security review: JWT handling, credential encryption, RLS policies | 6h | No vulnerabilities found in auth/authz chain | Medium |
| T8.3 | Performance testing: 10 simulated tenants, concurrent syncs | 6h | Response times < 2s for UI, sync completes < 5 min per platform per tenant | Medium |
| T8.4 | Load testing: connection pool, job queue depth, memory under load | 4h | No connection exhaustion, no memory leaks, queue depth stays manageable | Medium |
| T8.5 | Migrate Hanks/Rockers from Basic Auth to Supabase JWT | 4h | Existing client fully on new auth system | Medium |
| T8.6 | Remove dual-auth (Basic Auth path) | 2h | Only Supabase JWT accepted | Low (blocked on T8.5) |
| T8.7 | Onboard Pilot Client 1 — guided walkthrough | 8h | Client operational with real data and real syncs | Medium |
| T8.8 | Onboard Pilot Client 2 — semi-guided | 6h | Client mostly self-service with support | Low |
| T8.9 | Monitor pilot clients for 2 weeks — fix issues | 20h | Zero data leaks, < 5 support tickets per client per week | Medium |
| T8.10 | Gather pilot feedback, prioritise fixes | 4h | Feedback documented, P0 issues fixed | Low |
| T8.11 | Prepare for general availability: documentation, knowledge base, support process | 8h | Public-facing docs complete, support email/ticketing set up | Low |

**Deliverables:**
- Comprehensive test suite (400+ tests including isolation tests)
- Security audit completed
- Performance benchmarks established
- 2–3 pilot clients operational
- Documentation and knowledge base
- GA readiness checklist completed

**Testing Strategy:** See Section 7 for full QA plan.

**Rollback Plan:** Pilot clients can be rolled back to manual operation (standalone RIFF instances) if the multi-tenant system fails critically. This is a high-effort rollback and would only be used in emergency.

---

## Section 4: Detailed Task Breakdown

### Flattened Task List (All Phases)

| Task ID | Task Name | Phase | Effort | Dependencies | Acceptance Criteria |
|---------|-----------|-------|--------|-------------|-------------------|
| **T0.1** | Delete `_handle_price_change_old` + `_handle_order_sale` | 0 | 2h | — | Methods removed, pytest passes |
| **T0.2** | Delete `create_sync_events_for_stocked_orders` | 0 | 1h | — | 115 lines removed, tests pass |
| **T0.3** | Remove commented code blocks | 0 | 1h | — | Zero commented-out blocks in production files |
| **T0.4** | Audit & redirect EventProcessor callers | 0 | 4h | — | All callers use SyncService directly |
| **T0.5** | Delete `event_processor.py` | 0 | 1h | T0.4 | File deleted, ~1,635 lines removed |
| **T0.6** | Extract product CRUD → `routes/products.py` | 0 | 6h | — | ~3,000 lines moved, product routes functional |
| **T0.7** | Extract listing ops → `routes/listings.py` | 0 | 4h | — | ~1,000 lines moved, listing creation works |
| **T0.8** | Extract Dropbox → `routes/dropbox.py` | 0 | 3h | — | ~1,500 lines moved, image operations work |
| **T0.9** | Extract data APIs → `routes/data_api.py` | 0 | 2h | — | Category/shipping APIs work |
| **T0.10** | Clean up orphaned scripts | 0 | 2h | — | Duplicates deleted, useful scripts organised |
| **T0.11** | Fix unused imports | 0 | 1h | — | No import warnings |
| **T0.12** | Run full test suite | 0 | 4h | T0.1–T0.11 | All 369 tests pass |
| **T0.13** | Manual smoke test | 0 | 3h | T0.12 | All critical paths verified |
| **T1.1** | Create `tenants` table | 1 | 3h | Phase 0 | Table exists with correct schema |
| **T1.2** | Create `tenant_users` table | 1 | 3h | T1.1 | Table exists, FK to tenants |
| **T1.3** | Create `tenant_platform_credentials` table | 1 | 4h | T1.1 | Table exists, encrypted JSONB column |
| **T1.4** | Create `tenant_sync_configs` table | 1 | 2h | T1.1 | Table exists |
| **T1.5** | Add `tenant_id` to `products` | 1 | 2h | T1.1 | Column + composite index added |
| **T1.6** | Add `tenant_id` to `platform_common` | 1 | 1h | T1.1 | Column + index added |
| **T1.7** | Add `tenant_id` to 5 listing tables | 1 | 3h | T1.1 | Columns + indexes added |
| **T1.8** | Add `tenant_id` to 4 order tables | 1 | 2h | T1.1 | Columns + indexes added |
| **T1.9** | Add `tenant_id` to event/audit tables | 1 | 2h | T1.1 | Columns + composite indexes added |
| **T1.10** | Add `tenant_id` to operational tables | 1 | 2h | T1.1 | Columns + indexes added |
| **T1.11** | Create Tenant Zero (Hanks) | 1 | 1h | T1.1 | Default tenant row exists |
| **T1.12** | Backfill all existing rows with Tenant Zero ID | 1 | 3h | T1.5–T1.11 | Zero NULL tenant_id values |
| **T1.13** | Add NOT NULL constraint to all tenant_id columns | 1 | 1h | T1.12 | Constraints enforced |
| **T1.14** | Update all SQLAlchemy ORM models | 1 | 4h | T1.5–T1.10 | Models match migration |
| **T1.15** | Write RLS policies | 1 | 4h | T1.13 | Policies active on all tenant tables |
| **T1.16** | Test migration on cloned DB | 1 | 3h | T1.12 | Migration verified on clone |
| **T2.1** | Configure Supabase Auth project | 2 | 4h | Phase 1 | JWT with tenant_id claim |
| **T2.2** | Custom JWT claims database function | 2 | 3h | T2.1 | tenant_id in JWT payload |
| **T2.3** | Add auth packages to requirements | 2 | 1h | — | Packages installed |
| **T2.4** | Create `supabase_auth.py` | 2 | 6h | T2.1, T2.3 | JWT validation works |
| **T2.5** | Create `tenant.py` with contextvars | 2 | 2h | — | ContextVar accessible |
| **T2.6** | Create tenant context middleware | 2 | 4h | T2.4, T2.5 | tenant_id set on every request |
| **T2.7** | Modify `get_session()` for RLS | 2 | 3h | T2.6, T1.15 | SET LOCAL executed per session |
| **T2.8** | Rewrite `security.py` | 2 | 6h | T2.4 | New auth replaces Basic Auth |
| **T2.9** | Implement dual-auth | 2 | 4h | T2.8 | Both auth methods work |
| **T2.10** | Create login endpoint | 2 | 3h | T2.4 | Returns Supabase tokens |
| **T2.11** | Create signup endpoint | 2 | 6h | T2.4, T1.1, T1.2 | Creates user + tenant |
| **T2.12** | Update `require_auth` on all routes | 2 | 4h | T2.8 | All 217 endpoints use new auth |
| **T2.13** | Create Supabase user for Hanks operators | 2 | 2h | T2.1, T1.11 | Existing users can log in |
| **T2.14** | Test dual-auth end-to-end | 2 | 4h | T2.9, T2.13 | Both paths verified |
| **T3.1** | Create TenantScopedSession wrapper | 3 | 8h | Phase 2 | Auto-filtering tested |
| **T3.2** | Scope queries in `reverb_service.py` | 3 | 6h | T3.1 | 30+ queries scoped |
| **T3.3** | Scope queries in `ebay_service.py` | 3 | 6h | T3.1 | 30+ queries scoped |
| **T3.4** | Scope queries in `shopify_service.py` | 3 | 5h | T3.1 | 25+ queries scoped |
| **T3.5** | Scope queries in `woocommerce_service.py` | 3 | 3h | T3.1 | 15+ queries scoped |
| **T3.6** | Scope queries in `vr_service.py` | 3 | 4h | T3.1 | 20+ queries scoped |
| **T3.7** | Scope queries in `sync_services.py` | 3 | 6h | T3.1 | 25+ queries scoped |
| **T3.8** | Scope queries in `order_sale_processor.py` | 3 | 3h | T3.1 | 10+ queries scoped |
| **T3.9** | Scope queries in all route files | 3 | 8h | T3.1 | ~50 locations scoped |
| **T3.10** | Scope all INSERT operations | 3 | 6h | T3.1 | All inserts set tenant_id |
| **T3.11** | Scope analytics/reporting queries | 3 | 4h | T3.1 | Reports show tenant data only |
| **T3.12** | Tenant-key in-memory caches | 3 | 3h | Phase 2 | Cache isolation verified |
| **T3.13** | Tenant isolation test suite | 3 | 8h | T3.2–T3.11 | Automated tests pass |
| **T3.14** | Penetration testing | 3 | 4h | T3.13 | 20 critical endpoints verified |
| **T4.1** | Create CredentialManager service | 4 | 8h | Phase 2 | Encrypted fetch + cache working |
| **T4.2** | Encryption utilities | 4 | 3h | — | Encrypt/decrypt roundtrip works |
| **T4.3** | Credential seeding script | 4 | 2h | T4.1, T4.2 | CLI seeds credentials for tenant |
| **T4.4** | Refactor Reverb credentials (6 locations) | 4 | 3h | T4.1 | All via CredentialManager |
| **T4.5** | Refactor eBay credentials (19 locations) | 4 | 6h | T4.1 | All via CredentialManager |
| **T4.6** | Refactor Shopify credentials (7 locations) | 4 | 3h | T4.1 | All via CredentialManager |
| **T4.7** | Refactor V&R credentials (33 locations) | 4 | 8h | T4.1 | All via CredentialManager |
| **T4.8** | Align WooCommerce credentials | 4 | 2h | T4.1 | Aligned with CredentialManager |
| **T4.9** | Remove hardcoded eBay seller ID | 4 | 1h | T4.1 | From tenant settings |
| **T4.10** | Move DHL config to tenant settings | 4 | 2h | T4.1 | Per-tenant DHL config |
| **T4.11** | Move notification config to tenant settings | 4 | 2h | T4.1 | Per-tenant email recipients |
| **T4.12** | Move pricing markups to tenant settings | 4 | 2h | T4.1 | Per-tenant platform markups |
| **T4.13** | Credential validation endpoints | 4 | 4h | T4.1 | Test connectivity per platform |
| **T4.14** | Env var fallback for Tenant Zero | 4 | 2h | T4.1 | Backward compatible |
| **T5.1** | Add arq + redis to requirements | 5 | 1h | — | Packages installed |
| **T5.2** | Provision Redis | 5 | 1h | — | REDIS_URL configured |
| **T5.3** | Create tenant-aware job definitions | 5 | 6h | Phases 3, 4 | 7 job types defined |
| **T5.4** | Create scheduler loop | 5 | 6h | T5.3 | Scheduler queries tenants, enqueues jobs |
| **T5.5** | Create arq worker | 5 | 4h | T5.3 | Worker processes jobs with tenant context |
| **T5.6** | Rate-limit coordination | 5 | 4h | T5.4 | Fair budget sharing across tenants |
| **T5.7** | Sync locking per tenant/platform | 5 | 3h | T5.5 | Concurrent sync protection |
| **T5.8** | Job queue admin endpoint | 5 | 3h | T5.5 | Job status visible |
| **T5.9** | Migrate existing jobs | 5 | 3h | T5.3 | All 7 job types running via arq |
| **T5.10** | Deprecate old scheduler | 5 | 1h | T5.9 | Old scheduler marked deprecated |
| **T6.1** | Scaffold Next.js project | 6 | 4h | — | Project builds on Vercel |
| **T6.2** | Supabase client-side auth | 6 | 6h | T2.1 | Login/signup working |
| **T6.3** | Auth-guarded layout + tenant context | 6 | 4h | T6.2 | All pages protected |
| **T6.4** | Shared component library | 6 | 12h | T6.1 | Tables, forms, modals, toasts |
| **T6.5** | Convert FastAPI to JSON-only API | 6 | 8h | Phase 3 | All routes return JSON |
| **T6.6** | Dashboard page | 6 | 8h | T6.4, T6.5 | Dashboard functional |
| **T6.7** | Inventory List page | 6 | 10h | T6.4, T6.5 | Search, filter, paginate |
| **T6.8** | Product Detail page | 6 | 10h | T6.4, T6.5 | Full product view |
| **T6.9** | Add Product page | 6 | 10h | T6.4, T6.5 | Multi-platform form |
| **T6.10** | Edit Product page | 6 | 8h | T6.4, T6.5 | Edit + sync-on-save |
| **T6.11** | Orders pages | 6 | 6h | T6.4, T6.5 | List + detail |
| **T6.12** | Reports pages (12 reports) | 6 | 16h | T6.4, T6.5 | All reports functional |
| **T6.13** | Settings pages | 6 | 10h | T6.4, T6.5 | Admin settings UI |
| **T6.14** | Sync UI + WebSocket | 6 | 6h | T6.4, T6.5 | Real-time sync progress |
| **T6.15** | Error pages | 6 | 3h | T6.4 | 404, 500, sync errors |
| **T6.16** | eBay template preview | 6 | 4h | T6.4 | Template renders correctly |
| **T6.17** | Dropbox image picker in React | 6 | 6h | T6.4 | Thumbnails, selection, upload |
| **T6.18** | Responsive/mobile layout | 6 | 6h | T6.6–T6.17 | Mobile-friendly |
| **T7.1** | Tenant registration flow | 7 | 6h | Phase 6 | Self-service signup |
| **T7.2** | Reverb OAuth flow | 7 | 6h | T4.1 | Token stored encrypted |
| **T7.3** | eBay OAuth flow | 7 | 8h | T4.1 | **[BLOCKER]** eBay App approval |
| **T7.4** | Shopify OAuth flow | 7 | 6h | T4.1 | App install flow |
| **T7.5** | V&R credential entry | 7 | 2h | T4.1 | Credentials stored |
| **T7.6** | Initial import wizard | 7 | 10h | T7.2–T7.5 | First-time import |
| **T7.7** | Stripe products/prices setup | 7 | 4h | — | 4 tiers configured |
| **T7.8** | Billing page | 7 | 6h | T7.7, T6.13 | Subscription management |
| **T7.9** | Stripe webhook handler | 7 | 4h | T7.7 | Plan updates on payment |
| **T7.10** | Plan enforcement middleware | 7 | 4h | T7.9 | Limits enforced |
| **T7.11** | Team management | 7 | 6h | T6.13 | Invite/manage users |
| **T7.12** | Super-admin dashboard | 7 | 6h | T6.4 | All-tenant overview |
| **T7.13** | Onboarding email sequence | 7 | 3h | T7.1 | Automated welcome emails |
| **T8.1** | Automated isolation audit | 8 | 8h | All phases | All 217 endpoints tested |
| **T8.2** | Security review | 8 | 6h | All phases | No vulnerabilities |
| **T8.3** | Performance testing (10 tenants) | 8 | 6h | All phases | Meets SLAs |
| **T8.4** | Load testing | 8 | 4h | All phases | No resource exhaustion |
| **T8.5** | Migrate Hanks to Supabase JWT | 8 | 4h | T2.13 | Hanks on new auth |
| **T8.6** | Remove dual-auth | 8 | 2h | T8.5 | Only JWT accepted |
| **T8.7** | Onboard Pilot Client 1 | 8 | 8h | All phases | Client operational |
| **T8.8** | Onboard Pilot Client 2 | 8 | 6h | T8.7 | Semi-self-service |
| **T8.9** | Monitor pilots (2 weeks) | 8 | 20h | T8.7, T8.8 | Zero leaks, low support |
| **T8.10** | Gather feedback, fix P0s | 8 | 4h | T8.9 | Feedback documented |
| **T8.11** | GA preparation (docs, support) | 8 | 8h | T8.10 | Ready for remaining clients |

**Total tasks: 102**
**Total effort: 480–720 hours** (range accounts for complexity variance and debugging time)

---

## Section 5: Critical Path Analysis

### Longest Dependent Chain

```
T0.4 (EventProcessor audit, 4h)
  → T0.5 (delete event_processor, 1h)
    → T0.12 (full test suite, 4h)
      → T1.1 (tenants table, 3h)
        → T1.5 (products tenant_id, 2h)
          → T1.12 (backfill, 3h)
            → T1.13 (NOT NULL, 1h)
              → T1.15 (RLS policies, 4h)
                → T2.1 (Supabase config, 4h)
                  → T2.4 (JWT validation, 6h)
                    → T2.6 (tenant middleware, 4h)
                      → T2.8 (rewrite security.py, 6h)
                        → T3.1 (TenantScopedSession, 8h)
                          → T3.2-T3.9 (scope all queries, ~46h)
                            → T3.13 (isolation test suite, 8h)
                              → T5.3 (job definitions, 6h)
                                → T5.4 (scheduler, 6h)
                                  → T8.1 (isolation audit, 8h)
                                    → T8.7 (pilot client 1, 8h)
                                      → T8.9 (monitor 2 weeks, 20h)
```

**Critical path duration: ~149 hours** (approximately 4–5 weeks of focused work at 30–35 productive hours/week)

### Parallelisation Opportunities

| Parallel Set | Tasks | Why parallel? |
|-------------|-------|--------------|
| **Phase 3 + Phase 4** | Query scoping + credential injection | Both depend on Phase 2 but not on each other |
| **T3.2–T3.8** | Scoping individual service files | Each service file is independent |
| **T6.1–T6.4** | Next.js scaffold, auth, components | Can begin during Phase 3 backend work |
| **T7.2–T7.5** | OAuth flows for each platform | Each platform's OAuth is independent |
| **T4.4–T4.8** | Credential refactors per platform | Each platform's refactor is independent |

### Tasks That Cannot Be Parallelised

| Task | Why sequential? |
|------|----------------|
| T1.12 (backfill) → T1.13 (NOT NULL) | Must backfill data before constraining column |
| T2.4 (JWT validation) → T2.6 (middleware) → T2.8 (security rewrite) | Each layer builds on the previous |
| T3.1 (TenantScopedSession) → T3.2–T3.9 (scoping) | Wrapper must exist before services use it |
| T8.7 (pilot 1) → T8.8 (pilot 2) | Learn from first pilot before second |

### Timeline-Critical Tasks

If any of these tasks slip, the overall timeline extends:

1. **T2.4 (JWT validation)** — All subsequent work depends on working auth
2. **T3.1 (TenantScopedSession)** — All query scoping depends on this wrapper
3. **T7.3 (eBay OAuth)** — **[BLOCKER]** Requires eBay Developer approval, which has unpredictable timelines (2–6 weeks)
4. **T8.7 (Pilot Client 1)** — Reveals real-world issues that may require backtracking

---

## Section 6: Risk Register & Mitigation

| # | Risk | Likelihood | Impact | Mitigation | Owner | Contingency |
|---|------|-----------|--------|------------|-------|-------------|
| **R1** | **eBay OAuth per-tenant approval** — eBay may require individual Developer App per retailer, each requiring approval | High | High | Research eBay's multi-tenant app model early (Phase 0). Contact eBay Developer support. Apply for "Compatible Application" status. | Developer | If per-tenant apps required: offer eBay as premium tier only, guide retailers through their own app setup, store their credentials |
| **R2** | **V&R Selenium cannot scale** — Single Cloudflare `cf_clearance` cookie, one browser session at a time, cookies expire | High | High | Designate V&R as premium-tier feature (max 3–5 tenants). Implement tenant rotation with cooldown periods. | Developer | Drop V&R from MVP. Offer as manual/assisted service. Investigate V&R API partnership. |
| **R3** | **Tenant data leakage** — A missed `.where(tenant_id == ...)` filter exposes another tenant's data | Medium | Critical | Double-layer protection: application-level filtering + PostgreSQL RLS. Comprehensive isolation test suite (T3.13). Code review checklist. | Developer | Emergency: disable affected endpoint immediately. RLS catches leaks that app layer misses. |
| **R4** | **Existing client disruption during migration** — Schema changes or auth migration breaks Hanks' production | Low | Critical | Dual-auth period. Backfill existing data as Tenant Zero first. Test all migrations on cloned DB. Keep old scheduler as fallback. | Developer | Instant rollback: revert to pre-migration branch, restore DB backup. Old system is fully operational until explicit cutover. |
| **R5** | **Next.js rewrite scope creep** — 38 templates with embedded business logic; easy to underestimate effort | High | Medium | Time-box frontend work. Prioritise pages by usage frequency (dashboard, inventory list, product detail first). Accept feature parity, not perfection. | Developer | Ship with subset of pages in Next.js, keep remaining pages served by Jinja2 behind `/legacy/` routes. Migrate incrementally. |
| **R6** | **Platform API rate limits under multi-tenancy** — Reverb (120/min), eBay (varies), Shopify (40/s) shared across all tenants | Medium | High | Rate-limit budget sharing in scheduler (T5.6). Stagger sync times across tenants. Implement per-tenant backoff. | Developer | Increase sync intervals for non-premium tenants. Request higher rate limits from platforms (Reverb partnership). |
| **R7** | **Credential encryption key compromise** — Single Fernet key encrypts all tenant credentials | Low | Critical | Key stored in environment variable, not in code. Rotate key annually. Encrypt backup database dumps. | Developer | Key rotation procedure: re-encrypt all credentials with new key. Notify affected tenants to rotate platform API keys. |
| **R8** | **Supabase dependency risk** — Auth system relies on external SaaS | Low | Medium | Supabase is open-source (self-hostable). JWT validation is standard (can switch to any OIDC provider). | Developer | Self-host Supabase or switch to Auth0/Clerk. JWT validation code works with any compliant issuer. |
| **R9** | **Database migration on production** — Adding 20 `tenant_id` columns to tables with data could lock tables | Medium | High | Use `ALTER TABLE ... ADD COLUMN ... DEFAULT` (PostgreSQL 11+ adds columns without table rewrite if default provided). Run during low-traffic window. | Developer | If migration fails: `alembic downgrade` to previous revision. Have `pg_dump` backup ready before migration. |
| **R10** | **Pilot client with unusual data** — Retailer with 2,000+ listings, unusual categories, or edge-case products that break assumptions | Medium | Medium | Pre-screen pilot clients for size and complexity. Start with small retailers (50–200 listings). | Developer | Manual data cleanup for pilot. Add edge-case handling as discovered. |

---

## Section 7: Quality Assurance & Testing Strategy

### Unit Testing (Per Phase)

| Phase | Testing Focus | Target Coverage |
|-------|--------------|----------------|
| 0 | Regression: all existing 369 tests still pass after refactoring | 100% existing tests |
| 1 | ORM model tests: tenant_id present, FK constraints work, RLS policies | 20 new tests |
| 2 | JWT validation: valid/invalid/expired tokens, tenant extraction, dual-auth | 15 new tests |
| 3 | Query scoping: each service method returns only tenant-scoped data | 40+ new tests |
| 4 | CredentialManager: encrypt/decrypt roundtrip, cache invalidation, fallback | 10 new tests |
| 5 | Job queue: enqueue, dequeue, tenant context, rate limiting | 10 new tests |
| 6 | Frontend: component tests (React Testing Library), API integration tests | 30+ new tests |
| 7 | OAuth flows: token exchange, credential storage, validation | 10 new tests |

### Integration Testing Points

1. **After Phase 2:** Login as Tenant Zero → access dashboard → see existing data. Login as new tenant → see empty dashboard.
2. **After Phase 3:** Create product as Tenant A → query as Tenant B → product not visible. Verify via both application queries AND direct SQL with RLS.
3. **After Phase 4:** Platform sync for Tenant A uses Tenant A's credentials. Sync for Tenant B uses Tenant B's credentials. No cross-contamination.
4. **After Phase 5:** Scheduler enqueues jobs for all active tenants. Worker processes them with correct tenant context. No credential mixing.
5. **After Phase 6:** Full user journey in Next.js: login → browse inventory → create product → sync to platform → view report.

### Security Testing Checklist

- [ ] **Tenant isolation (Critical)**
  - [ ] Direct API call with Tenant A token returns only Tenant A data (all endpoints)
  - [ ] JWT with manipulated `tenant_id` claim → rejected (signature verification)
  - [ ] Expired JWT → returns 401
  - [ ] No JWT → returns 401 (no anonymous access)
  - [ ] SQL injection in tenant_id parameter → rejected (UUID validation)
  - [ ] RLS blocks cross-tenant access even with application bug
- [ ] **Credential security**
  - [ ] Encrypted credentials not readable via API (only decrypted server-side)
  - [ ] Credential endpoints require owner role (staff cannot view API keys)
  - [ ] Database backup encryption includes credential columns
- [ ] **OAuth security**
  - [ ] State parameter prevents CSRF in OAuth flows
  - [ ] Redirect URIs are strictly validated
  - [ ] Tokens stored encrypted, never logged
- [ ] **General**
  - [ ] XSS prevention in Next.js (React's default escaping)
  - [ ] CSRF protection on state-changing endpoints
  - [ ] Rate limiting on auth endpoints (login, signup)

### Performance Testing Thresholds

| Metric | Target | Method |
|--------|--------|--------|
| API response time (95th percentile) | < 500ms | Load test with 10 simulated tenants |
| Dashboard load time | < 2s | Lighthouse audit |
| Sync completion (per platform, per tenant) | < 5 minutes | Measure with 200 listings |
| Concurrent syncs (10 tenants) | No failures | Parallel sync execution test |
| Database connection pool | No exhaustion at 20 tenants | Monitor `pg_stat_activity` |
| Memory usage | < 2GB under full load | Monitor RSS during load test |
| Job queue latency | < 30s from enqueue to execution | Measure with arq metrics |

### Staging Environment

- Separate Supabase project (different JWT secret)
- Separate Railway service (different database)
- Seed with 3 test tenants, each with 50–100 test products
- Run all platform syncs in sandbox mode (Reverb sandbox, eBay sandbox, Shopify dev store)

### Pilot Client Acceptance Criteria

- [ ] Client can log in via Supabase (email/password)
- [ ] Client can connect at least 2 platforms
- [ ] Client can import inventory from primary platform
- [ ] Client can view, search, and filter their products
- [ ] Client can create a new listing on secondary platform
- [ ] Sync runs automatically on configured schedule
- [ ] Client cannot see any other tenant's data
- [ ] Client can view sync reports and diagnose issues
- [ ] Client can manage billing (upgrade/downgrade plan)
- [ ] Support tickets are handled within 24 hours

---

## Section 8: Deployment & Rollout Timeline

### Deployment Architecture

```
                    ┌─────────────┐
                    │   Vercel     │
                    │  (Next.js)   │
                    │  app.riff.tools
                    └──────┬──────┘
                           │ API calls (Bearer JWT)
                    ┌──────┴──────┐
                    │   Railway    │
                    │  (FastAPI)   │
                    │  api.riff.tools
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
     ┌────────┴───┐  ┌────┴────┐  ┌────┴────┐
     │  Supabase   │  │ Railway │  │ Upstash │
     │  (Auth +    │  │ Postgres│  │ (Redis) │
     │  optional   │  │         │  │         │
     │  Postgres)  │  │         │  │         │
     └─────────────┘  └─────────┘  └─────────┘
```

### Staging Deployment Milestones

| Week | Milestone | Gate |
|------|-----------|------|
| Week 4 | Phase 0+1 deployed to staging | All tests pass, migration verified on clone |
| Week 7 | Phase 2 deployed to staging | Dual-auth working, Tenant Zero operational |
| Week 10 | Phases 3+4 deployed to staging | Tenant isolation verified in staging |
| Week 12 | Phase 5 deployed to staging | Scheduler running for 2 test tenants |
| Week 16 | Phase 6 deployed to staging (Vercel) | Next.js app functional for all key workflows |
| Week 18 | Phase 7 deployed to staging | Self-service onboarding tested end-to-end |
| Week 19 | All phases deployed to staging | Full system operational in staging |

### Soft Launch Criteria (2–3 Pilot Clients)

**Prerequisites (ALL must be met):**
- [ ] All automated tests pass (400+)
- [ ] Tenant isolation audit passed (T8.1)
- [ ] Security review completed (T8.2)
- [ ] Performance benchmarks met (T8.3)
- [ ] Hanks/Rockers migrated successfully to new system (T8.5)
- [ ] Staging environment stable for 2+ weeks
- [ ] Rollback procedure documented and tested
- [ ] Support process established (email, response SLA)
- [ ] Pilot client agreements signed (beta terms, data processing)

### General Availability Criteria

**Prerequisites (ALL must be met):**
- [ ] Pilot clients operational for 4+ weeks
- [ ] Zero data leakage incidents
- [ ] < 5 support tickets per client per week (trending downward)
- [ ] Pilot client NPS > 7 (Net Promoter Score)
- [ ] Billing system tested with real payments
- [ ] Documentation and knowledge base published
- [ ] Onboarding wizard tested with non-technical user
- [ ] Terms of service and privacy policy published
- [ ] GDPR compliance verified (data processing agreements)

### Rollback Triggers

| Trigger | Action | Timeline |
|---------|--------|----------|
| Any cross-tenant data leakage | Immediate: disable new tenants, investigate, patch | Within 1 hour |
| Auth system failure (> 5 min downtime) | Switch to dual-auth fallback (Basic Auth for Tenant Zero) | Within 30 minutes |
| Database migration failure | `alembic downgrade` to previous revision, restore backup | Within 1 hour |
| Platform sync breaks for > 50% of tenants | Roll back scheduler to old single-tenant version | Within 2 hours |
| Pilot client reports data loss | Restore from backup, investigate root cause | Within 4 hours |

### Communication Plan

| Audience | When | Channel | Content |
|----------|------|---------|---------|
| **Existing client (Hanks)** | Before Phase 1 migration | Email + call | Explain migration, zero downtime plan, dual-auth period |
| **Existing client (Hanks)** | After Phase 2 | Email | New login instructions (Supabase), confirm everything works |
| **Pilot clients** | Before onboarding | Email + video call | Beta terms, expectations, known limitations, support process |
| **Pilot clients** | Weekly during pilot | Email | Status update, known issues, upcoming fixes |
| **Remaining clients** | GA announcement | Email + landing page | Product announcement, pricing, getting started guide |
| **All clients** | Ongoing | Knowledge base | Self-service documentation, FAQ, video tutorials |

---

## Section 9: Documentation & Knowledge Transfer

### Documentation Deliverables

| Document | When Needed | Owner | Priority |
|----------|-------------|-------|----------|
| **API Reference** (OpenAPI/Swagger) | Phase 3 (when routes return JSON) | Auto-generated (FastAPI) | High |
| **Database Schema Guide** (updated with tenant columns) | Phase 1 (after migration) | Developer | High |
| **Authentication Guide** (Supabase setup, JWT flow) | Phase 2 | Developer | High |
| **Tenant Isolation Architecture** (how data is protected) | Phase 3 (for security review) | Developer | Critical |
| **Platform Integration Guide** (per-platform OAuth, sync behaviour) | Phase 4 | Developer | High |
| **Deployment Runbook** (how to deploy, rollback, monitor) | Phase 5 | Developer | High |
| **Onboarding Guide** (for new retailers) | Phase 7 | Developer | High |
| **Admin Operations Guide** (tenant management, troubleshooting) | Phase 7 | Developer | Medium |
| **Knowledge Base / FAQ** (for end users) | Phase 8 (before pilot) | Developer | High |
| **Video Walkthrough** (3–5 min product demo) | Phase 8 (for pilot onboarding) | Developer | Medium |
| **Terms of Service** | Phase 8 (before pilot) | Legal counsel | High |
| **Privacy Policy / DPA** | Phase 8 (before pilot) | Legal counsel | High |
| **Billing & Pricing Page** | Phase 7 | Developer | Medium |

### Client Onboarding Documentation Checklist

- [ ] Getting Started Guide (signup → first sync in 30 minutes)
- [ ] Platform Connection Guides (one per platform: Reverb, eBay, Shopify, V&R)
- [ ] Common Issues & Troubleshooting (FAQ)
- [ ] Sync Schedule Configuration Guide
- [ ] Pricing & Category Mapping Guide
- [ ] Team Management Guide (inviting staff, setting roles)
- [ ] Billing & Subscription Management
- [ ] Contacting Support (email, expected response time)

---

## Section 10: Success Metrics & Acceptance Criteria

### Data Isolation (Critical — Must Pass)

- [ ] **Automated isolation test suite passes** — every tenant-scoped endpoint tested with cross-tenant tokens, zero data leakage
- [ ] **RLS policies active** — PostgreSQL Row-Level Security enabled on all tenant-scoped tables as defence-in-depth
- [ ] **Manual penetration test passes** — 20 critical endpoints manually tested by someone who didn't write the code
- [ ] **No shared state** — in-memory caches, WebSocket connections, and background jobs are all tenant-scoped

### Operational Capacity

- [ ] **20 tenants onboarded and operating independently** — each with their own credentials, sync schedules, and data
- [ ] **Self-service onboarding** — new tenant can go from signup to first sync in < 1 hour without developer intervention
- [ ] **All 5 platforms functional** — Reverb, eBay, Shopify, WooCommerce operational for all tenants; V&R available for premium tier

### Performance SLAs

- [ ] **API response time** — 95th percentile < 500ms under normal load
- [ ] **Sync completion** — < 5 minutes per platform per tenant (200 listings)
- [ ] **Uptime** — 99.5% measured monthly (allows ~3.6 hours/month downtime for maintenance)
- [ ] **Job queue latency** — jobs execute within 30 seconds of scheduled time

### Data Integrity

- [ ] **Zero data loss during migration** — all existing Hanks/Rockers data preserved with Tenant Zero tag
- [ ] **Referential integrity maintained** — all FK relationships valid after tenant_id backfill
- [ ] **Sync accuracy** — < 1% sync event error rate across all tenants

### Security

- [ ] **No plaintext credentials** — all platform API keys encrypted at rest (Fernet)
- [ ] **JWT validation** — expired, malformed, and tampered tokens rejected
- [ ] **Role enforcement** — staff users cannot access owner-level operations (billing, credentials)
- [ ] **Audit trail** — all tenant operations logged in `activity_log` with tenant_id

### Business

- [ ] **Billing active** — Stripe integration collecting payments for subscribed tenants
- [ ] **Support sustainable** — < 5 support tickets per tenant per week
- [ ] **Documentation complete** — knowledge base covers all common workflows

---

## Answers to Specific Questions

### 1. When should the existing client (Hanks) be migrated to the new schema?

**Beginning, as "Tenant Zero."** The very first step in Phase 1 is creating a default tenant record for Hanks and backfilling all existing data with this tenant's UUID. This means:
- Hanks operates on the new schema from day one (with their tenant_id set)
- Dual-auth allows Hanks to continue using Basic Auth while Supabase is being set up
- Hanks is the first "tenant" on the system, serving as continuous validation that the multi-tenant changes don't break existing functionality
- Full migration to Supabase JWT happens in Phase 8 (T8.5), only after all pilot testing is complete

### 2. How will rollback work at each phase if tests fail?

| Phase | Rollback Mechanism |
|-------|-------------------|
| 0 (Cleanup) | `git revert` merge commit — no DB changes |
| 1 (Schema) | `alembic downgrade` drops new columns/tables. Restore from pre-migration `pg_dump` backup if partial corruption |
| 2 (Auth) | Disable Supabase path in middleware, revert `security.py` to Basic Auth. Dual-auth design makes this trivial |
| 3 (Scoping) | Remove `.where(tenant_id == ...)` clauses — queries return all data (unsafe but functional). RLS stays active as safety net |
| 4 (Credentials) | CredentialManager falls back to env vars for Tenant Zero. New tenants cannot function (acceptable during rollback) |
| 5 (Jobs) | Feature flag `USE_NEW_SCHEDULER=false` → old scheduler takes over for Tenant Zero |
| 6 (Frontend) | Next.js runs on separate domain. Jinja2 frontend still served by FastAPI as fallback |
| 7 (Onboarding) | Disable signup. Manual tenant creation by admin only |
| 8 (Pilot) | Individual tenant can be rolled back to standalone RIFF instance (high effort, emergency only) |

### 3. Where are the testing gates that would delay the timeline?

1. **After Phase 1** — Migration must be verified on cloned production DB before production run. If migration fails on clone, Phase 2 is blocked.
2. **After Phase 2** — Dual-auth must work for both existing and new users. If Supabase JWT validation has issues, all subsequent phases are blocked (this is the critical path).
3. **After Phase 3** — Tenant isolation test suite (T3.13) must pass 100%. Any failure here blocks pilot launch and requires investigation. This is the most important gate.
4. **After Phase 7** — eBay OAuth flow (T7.3) depends on eBay Developer approval, which has unpredictable timelines. If delayed, pilot launches without eBay (Reverb + Shopify only).
5. **After Phase 8** — Pilot monitoring period (T8.9) is a mandatory 2-week gate. Cannot proceed to GA until pilot feedback is positive.

### 4. What is the MVP for the first pilot client?

**MVP = Reverb + Shopify + Dashboard + Reports.** Specifically:

| Feature | In MVP | Deferred |
|---------|--------|----------|
| Reverb sync (import, status, price, quantity) | Yes | — |
| Shopify sync (push from Reverb, price, quantity) | Yes | — |
| eBay sync | If eBay OAuth approved | Otherwise deferred |
| V&R sync | No | Premium tier, post-GA |
| WooCommerce sync | Partial (if client needs it) | Full support post-MVP |
| Dashboard | Yes | — |
| Product list/detail/edit | Yes | — |
| Add product | Yes | — |
| Sync reports | Yes | — |
| Sales report | Yes | — |
| Listing health report | Yes | — |
| DHL shipping | No | Post-GA |
| Dropbox image integration | Yes | — |
| Billing (Stripe) | Trial mode | Full billing at GA |

### 5. Who/what handles client onboarding after development?

**Self-service with assisted fallback.** The target flow:

1. **Self-service (80% of onboarding):** Signup → connect platforms via OAuth → import wizard → select plan → subscribe
2. **Assisted (20%):** If platform connection fails, credential validation fails, or import encounters edge cases → support ticket → developer resolves within 24 hours
3. **Post-GA automation:** Onboarding email sequence (day 0: welcome, day 1: connect platforms, day 3: tips & tricks, day 7: check in, day 14: trial ending)

For the first 20 clients, expect ~2 hours of assisted onboarding per client. As the system matures, this drops to ~30 minutes.

---

*This plan should be reviewed and updated at the end of each phase. Estimates are based on AI-assisted development with a single senior developer. Actual timelines may vary based on eBay OAuth approval timing, pilot client availability, and scope decisions.*
