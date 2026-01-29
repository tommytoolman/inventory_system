# RIFF - Realtime Inventory Fast Flow

A comprehensive multi-platform inventory management system for music gear retailers. RIFF syncs product listings, orders, and inventory across four e-commerce platforms from a single unified interface.

## Overview

RIFF serves as the single source of truth for guitar and music equipment inventory, automatically syncing data across:
- **Reverb** (primary marketplace)
- **eBay** (secondary marketplace)
- **Shopify** (e-commerce storefront)
- **Vintage & Rare** (specialized platform)

## Core Features

### Multi-Platform Synchronization
- **Push Sync**: Price/quantity changes trigger immediate API calls to all platforms
- **Pull Sync**: Hourly automated sync detects external changes
- **Conflict Resolution**: Timestamp-based logic ensures data consistency

### Order Processing
- Unified order view across all platforms
- Automatic inventory decrements on sale
- DHL shipping label integration
- Order tracking and fulfillment workflow

### Inventory Management
- Create products once, publish to multiple platforms
- Bulk operations and CSV export
- Image management with Dropbox integration
- Automatic image health checking and repair

### Analytics & Reporting
- Sync event tracking and monitoring
- Inventory reconciliation reports
- Sales analytics across platforms
- Failed sync detection and alerting

## Tech Stack

**Backend**: FastAPI (Python 3.12), SQLAlchemy (async), PostgreSQL
**Frontend**: Jinja2 Templates, TailwindCSS, Vanilla JavaScript
**Infrastructure**: Railway (hosting), Chrome Service (Selenium for V&R)
**Integrations**: Reverb REST API, eBay Trading API (XML), Shopify GraphQL, DHL Express API, Dropbox API

## Getting Started

### Prerequisites
- Python 3.12+
- PostgreSQL 14+
- Git version control

### Installation

1. Clone the repository:
```bash
git clone https://github.com/tommytoolman/inventory_system.git
cd inventory_system
```

2. Set up virtual environment:
```bash
python3.12 -m venv venv
source venv/bin/activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Configure environment:
```bash
cp .env.example .env
# Edit .env with your database URL and API credentials
```

5. Run migrations:
```bash
alembic upgrade head
```

6. Start development server:
```bash
uvicorn app.main:app --reload --port 8000
```

7. Visit http://localhost:8000

## Project Structure

```
app/
├── core/               # Configuration and utilities
├── models/             # SQLAlchemy database models
├── routes/             # FastAPI route handlers
├── services/           # Platform-specific business logic
│   ├── reverb_service.py
│   ├── ebay_service.py
│   ├── shopify_service.py
│   └── vr_service.py
├── templates/          # Jinja2 HTML templates
└── static/             # CSS, JS, images

scripts/                # Automation and maintenance scripts
docs/                   # Technical documentation
```

## Database Schema

**Core Tables**:
- `products` - Central inventory (single source of truth)
- `platform_common` - Links products to platform-specific listings
- `reverb_listings`, `ebay_listings`, `shopify_listings`, `vr_listings` - Platform-specific data
- `sync_events` - Tracks all synchronization operations
- `reverb_orders`, `ebay_orders`, `shopify_orders` - Order data per platform

## Background Jobs

Automated tasks run via cron scheduler:
- **Hourly Sync** (`*/60 * * * *`) - Pull changes from all platforms
- **Daily Stats** (`0 2 * * *`) - Generate analytics aggregations
- **Weekly Archive** (`0 3 * * 0`) - Clean up ended Shopify listings
- **Nightly Images** (`0 2 * * *`) - Check and repair broken image URLs

## Key Documentation

- **`docs/RIFF_Developer_Onboarding.pdf`** - Comprehensive technical onboarding guide
- **`CLAUDE.md`** - Important development instructions and patterns
- **`docs/todo.md`** - Current priorities and completed work
- **`docs/api/`** - Platform integration details and architecture

## Development Workflow

1. Create feature branch from `main`
2. Make changes and test locally
3. Commit with descriptive messages
4. Push branch and open pull request
5. Wait for code review and approval
6. Merge to `main` (deploys to Railway production)

## Important Notes

- **Never use conda** - Always use the project's venv
- **Check database schema before queries** - Verify column names (see CLAUDE.md)
- **Test with dry-run flags** - Most scripts support `--dry-run`
- **Async database sessions** - Use `async with get_session()` pattern

## Platform-Specific Notes

**Reverb**: Primary data source, REST API, OAuth2
**eBay**: XML Trading API, complex category mapping, shipping profiles required
**Shopify**: GraphQL API, inventory location-based quantities
**Vintage & Rare**: Selenium browser automation, no official API

## Support

For questions or issues:
- Check `CLAUDE.md` for common patterns and gotchas
- Review `docs/RIFF_Developer_Onboarding.pdf` for comprehensive technical details
- Ask Tom or Codex

## License

Proprietary - All rights reserved
