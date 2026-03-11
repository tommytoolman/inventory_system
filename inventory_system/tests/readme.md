# Test Suite

*Last updated: 2026-01-03*

## Overview

This is a **minimal smoke test suite** for the Inventory Management System. It provides a safety net for major refactors and dependency upgrades, but is not run as part of daily development.

| Metric | Value |
|--------|-------|
| Total tests | 200 |
| Lines of test code | ~11,100 |
| Collection errors | 0 |

## When to Run Tests

| Scenario | Run tests? |
|----------|------------|
| Day-to-day bug fixes | No |
| Adding a new feature | No (unless it touches core CRUD) |
| Major refactor | **Yes** |
| Upgrading FastAPI/SQLAlchemy | **Yes** |
| Pre-deploy sanity check | **Yes** |

### Quick Command

```bash
# Run all tests (stop on first failure, concise output)
pytest tests/ -x --tb=short

# Collect tests without running (verify nothing is broken)
pytest tests/ --collect-only
```

## Test Structure

```
tests/
├── conftest.py              # Shared fixtures (db_session, test_client, mocks)
├── fixtures/                # Test data fixtures
├── integration/             # End-to-end integration tests
│   └── services/
│       ├── reverb/          # Reverb API integration tests
│       └── vintageandrare/  # V&R integration tests
├── test_routes/             # Route/endpoint tests
│   └── test_inventory_routes.py  # Core inventory CRUD tests (~28 tests)
└── unit/                    # Unit tests
    └── services/
        ├── ebay/            # eBay service tests
        ├── reverb/          # Reverb service tests
        └── vintageandrare/  # V&R service tests
```

## What's Tested

### Route Tests (`test_routes/`)
- Inventory listing with pagination, filtering, search
- Product detail views (found/not found)
- Product creation (success, validation errors, service errors)
- Product update and delete
- SKU generation
- Stock updates
- Shipping profiles
- Dropbox integration
- V&R sync and export

### Unit Tests (`unit/services/`)
- **eBay**: Trading API, client initialization, XML requests
- **Reverb**: Client, importer, service layer
- **V&R**: Client, export service, media handler

### Integration Tests (`integration/`)
- Reverb sandbox/production authentication
- Reverb listing workflows
- V&R client connection and inventory sync

## Fixtures (conftest.py)

| Fixture | Scope | Purpose |
|---------|-------|---------|
| `settings` | session | Test settings with mock API keys |
| `test_engine` | function | Async SQLAlchemy engine with fresh tables |
| `db_session` | function | Async session with automatic rollback |
| `test_client` | function | FastAPI TestClient with overridden deps |
| `mock_ebay_client` | function | Mocked eBay client |
| `mock_reverb_client` | function | Mocked Reverb client |
| `mock_shopify_client` | function | Mocked Shopify client |
| `mock_vintageandrare_client` | function | Mocked V&R client |
| `sample_product_data` | function | Sample product dict |

## Cleanup History

### 2026-01-03: Test Suite Audit & Cleanup

Audited 17,356 lines across 219 tests. Removed broken and stale tests:

**Deleted (broken imports - referenced deleted modules):**
- `test_cli_import_vr.py` - referenced deleted `app.cli` module
- `test_ebay_auth.py` - referenced deleted `TokenStorage` class
- `test_ebay_inventory.py` - referenced deleted `app.services.ebay.inventory` module
- `test_vintageandrare_selenium.py` - referenced deleted `media_handler` module

**Deleted (stale/low value):**
- `test_vr_local_state.py` (4,129 lines) - overly granular, testing internal state
- `test_dhl.py`, `test_fedex.py`, `test_ups.py`, `test_service.py` - empty stub files

**Result:** 200 tests, ~11,100 lines, 0 collection errors

## Notes

- Tests use extensive mocking of external services (eBay, Reverb, V&R APIs)
- Database tests use automatic rollback for isolation
- No CI/CD integration - tests run manually when needed
- Production usage is the primary validation mechanism for this app
