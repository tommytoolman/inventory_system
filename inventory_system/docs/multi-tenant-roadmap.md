# Multi-Tenant SaaS Roadmap

*Created: 2026-01-06*

This document outlines the path from single-tenant inventory system (Hanks/Rockers Guitars) to a multi-customer SaaS product serving the music retail vertical.

---

## Current State Assessment

### What We Have
- **Core sync engine**: Reverb, eBay, Shopify, Vintage & Rare integration
- **Order processing**: Cross-platform quantity propagation on sales
- **Background scheduler**: Hourly syncs, daily stats, weekly maintenance jobs
- **Reporting suite**: Reconciliation, engagement stats, listing health
- **Product management**: Multi-platform listing creation, editing, image handling
- **Solid foundation**: 200 clean tests, PostgreSQL, FastAPI, async throughout

### What's Working Well
- Reverb as primary source of truth with fan-out to other platforms
- Stocked vs non-stocked item handling
- Platform-specific field mapping (conditions, categories, shipping profiles)
- Email notifications on sales
- Activity logging and sync event tracking

### Gaps for Production Readiness (Single Tenant)
See `todo.md` for current priorities:
- Sync event automation (reduce manual intervention)
- User sync recovery tools (self-service diagnostics)
- Admin settings UI (reduce support dependency)
- DHL integration completion

---

## Target Market

### Primary Persona
**Independent music gear retailers** who:
- List primarily on Reverb (their comfort zone)
- Want to expand to eBay/Shopify without double-entry
- Have 50-500 active listings
- Currently use spreadsheets or nothing for cross-platform management
- Struggle with inventory sync when items sell

### Market Size Indicators
- Reverb has 10M+ listings, thousands of professional sellers
- eBay Musical Instruments category is massive
- No dominant solution for Reverb-first multi-platform sync
- Existing tools (Sellbrite, ChannelAdvisor) are generic, expensive, poor Reverb support

### Why We Win
- **Built for music retail**: Category mappings, condition handling, spec fields designed for guitars/amps/pedals
- **Reverb-native**: Most tools treat Reverb as afterthought; we treat it as primary
- **Right-sized**: Not enterprise bloatware, not a toy
- **Real-world tested**: Built solving actual problems for a working shop

---

## Technical Requirements for Multi-Tenancy

### Tier 1: Database Isolation
Current schema assumes single tenant. Options:

**Option A: Schema-per-tenant (PostgreSQL schemas)**
- Each customer gets own schema within same database
- Pros: Strong isolation, easy backup/restore per tenant, familiar SQL
- Cons: Schema migrations must run per-tenant, connection pooling complexity
- Best for: 10-100 customers

**Option B: Row-level tenancy (tenant_id column)**
- Add `tenant_id` to all tables, filter all queries
- Pros: Single schema, simpler migrations, easier cross-tenant reporting
- Cons: Risk of data leaks if filter missed, harder to extract single tenant
- Best for: 100+ customers, need for cross-tenant analytics

**Option C: Database-per-tenant**
- Completely separate PostgreSQL instances
- Pros: Maximum isolation, easy to offer dedicated hosting tier
- Cons: Operational overhead, expensive at scale
- Best for: Enterprise tier customers

**Recommendation**: Start with **Option A (schema-per-tenant)** for balance of isolation and manageability. Migrate to Option B if scaling past 50+ tenants.

### Tier 2: Application Changes

#### Authentication & Authorization
- Current: Single admin password
- Needed:
  - User accounts with email/password or OAuth
  - Tenant membership (user belongs to one or more tenants)
  - Roles within tenant (owner, staff, read-only)
  - Session management with tenant context

#### Request Context
- Every request must carry tenant context
- Middleware to set tenant from authenticated user
- All database queries scoped to current tenant
- Background jobs must specify tenant

#### API Credentials per Tenant
- Current: Single set of platform API keys in environment
- Needed:
  - Encrypted storage of API credentials per tenant
  - OAuth flows for Reverb, eBay, Shopify onboarding
  - Credential refresh handling per tenant
  - Graceful degradation when credentials expire

#### Background Jobs
- Current: Single scheduler for single tenant
- Needed:
  - Job queue with tenant isolation (e.g., separate Celery queues or tenant-tagged jobs)
  - Fair scheduling across tenants
  - Per-tenant job configuration (sync frequency, enabled platforms)

### Tier 3: Infrastructure

#### Hosting Strategy
**Option A: Shared infrastructure**
- Single Railway/Heroku deployment
- All tenants share compute, separate by data
- Pros: Economical, simple ops
- Cons: Noisy neighbor risk, harder to offer SLAs

**Option B: Tenant clusters**
- Group tenants onto shared infrastructure tiers
- Premium tier gets dedicated resources
- Pros: Balance of efficiency and isolation
- Cons: More complex deployment

**Option C: Dedicated instances**
- Each customer gets own deployment
- Pros: Maximum isolation, customisation possible
- Cons: High ops overhead, expensive

**Recommendation**: Start **Option A** with monitoring. Offer **Option C** as enterprise tier.

#### Secrets Management
- Move from environment variables to proper secrets manager
- AWS Secrets Manager, HashiCorp Vault, or Railway's native secrets
- Per-tenant credential encryption

#### Monitoring & Alerting
- Per-tenant health dashboards
- Alerting on sync failures per tenant
- Usage metrics for billing

---

## Onboarding Flow

### Step 1: Account Creation
- Email/password registration
- Email verification
- Create first tenant (shop name)

### Step 2: Platform Connections
- **Reverb**: OAuth flow → store access token
- **eBay**: OAuth flow → store refresh token (already have this working)
- **Shopify**: App installation flow → store access token
- **V&R**: Username/password (no OAuth available)

### Step 3: Initial Import
- Choose primary platform (usually Reverb)
- Import all active listings
- Map to internal product model
- Preview before committing

### Step 4: Cross-Platform Setup
- Enable secondary platforms
- Configure category mappings
- Set pricing rules (e.g., Shopify = Reverb - 5%)
- Configure shipping profiles

### Step 5: Go Live
- Enable sync scheduler
- Set notification preferences
- Training/documentation links

---

## Pricing Model Options

### Option A: Per-Listing Fee
- £0.05-0.10 per active listing per month
- Pros: Scales with value delivered
- Cons: Unpredictable revenue, incentivises fewer listings

### Option B: Tiered Subscription
| Tier | Listings | Platforms | Price/month |
|------|----------|-----------|-------------|
| Starter | Up to 100 | 2 | £29 |
| Growth | Up to 300 | 3 | £59 |
| Pro | Up to 500 | 4 | £99 |
| Enterprise | Unlimited | 4 + support | £199+ |

- Pros: Predictable revenue, clear upgrade path
- Cons: Must enforce limits

### Option C: Platform-Based
- Base fee + per-platform add-on
- £19 base + £15 per additional platform
- Pros: Pay for what you use
- Cons: Complex pricing page

**Recommendation**: Start with **Option B (tiered subscription)**. Simple to explain, predictable for both sides.

---

## Go-to-Market Strategy

### Phase 1: Private Beta (0-10 customers)
- Hand-picked Reverb sellers (reach out via forums, Reddit r/Gear4Sale)
- Free or heavily discounted
- High-touch onboarding
- Gather feedback, find bugs
- Build case studies

### Phase 2: Public Beta (10-50 customers)
- Launch landing page
- Content marketing: "How to sync Reverb to eBay without losing your mind"
- Reverb seller community engagement
- Discounted pricing, no long-term contracts
- Refine onboarding based on Phase 1

### Phase 3: General Availability
- Full pricing
- Self-service onboarding
- Knowledge base and support ticketing
- Consider Reverb partnership/marketplace listing

### Marketing Channels
- **Reverb forums and groups**: Where sellers hang out
- **Reddit**: r/Gear4Sale, r/Guitar, r/Bass
- **YouTube**: Tutorials for music gear sellers
- **SEO**: "Reverb eBay sync", "multi-platform guitar inventory"
- **Trade shows**: NAMM, music retail conferences

---

## Development Phases

### Phase A: Complete Single-Tenant Polish
*Prerequisites before multi-tenant work*
- [ ] Sync event automation complete
- [ ] User recovery tools functional
- [ ] Admin settings UI done
- [ ] DHL integration tested
- [ ] 30 days stable in production

### Phase B: Multi-Tenant Foundation
*Estimated effort: 4-6 weeks*
- [ ] Schema-per-tenant database architecture
- [ ] User authentication system (consider Auth0/Clerk for speed)
- [ ] Tenant context middleware
- [ ] Credential storage per tenant
- [ ] Tenant-scoped background jobs

### Phase C: Onboarding & Self-Service
*Estimated effort: 3-4 weeks*
- [ ] OAuth flows for Reverb, eBay, Shopify
- [ ] Initial import wizard
- [ ] Platform connection management UI
- [ ] Self-service billing (Stripe integration)

### Phase D: Beta Launch
*Estimated effort: 2-3 weeks*
- [ ] Landing page and marketing site
- [ ] Documentation and knowledge base
- [ ] Support ticketing integration
- [ ] Monitoring and alerting per tenant

---

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Platform API changes | High | Monitor changelogs, abstract API layers, quick response process |
| Credential security breach | Critical | Encryption at rest, audit logging, regular security review |
| Noisy neighbor (one tenant overloads system) | Medium | Rate limiting, resource quotas, monitoring |
| Support burden too high | Medium | Invest in self-service tools, documentation, community |
| Platform ToS issues | High | Legal review of reselling API access, stay compliant |

---

## Success Metrics

### Product Metrics
- Time to first successful sync (target: < 1 hour from signup)
- Sync error rate (target: < 1%)
- Customer churn (target: < 5% monthly)

### Business Metrics
- Monthly Recurring Revenue (MRR)
- Customer Acquisition Cost (CAC)
- Lifetime Value (LTV)
- LTV:CAC ratio (target: > 3:1)

---

## Next Steps

1. **Complete single-tenant polish** - Focus on `todo.md` high-priority items
2. **Document current architecture** - Update `docs/api/architecture.md`
3. **Validate market interest** - Informal conversations with Reverb sellers
4. **Technical spike** - Prototype schema-per-tenant in a branch
5. **Business planning** - Pricing, legal entity, terms of service

---

## References

- `todo.md` - Current development priorities
- `docs/api/architecture.md` - System architecture (needs update)
- `docs/api/platform_integration.md` - Platform-specific behaviours
