# Realtime Inventory Forms Feed System

A comprehensive multi-platform inventory management system that syncs product listings across eBay, Reverb, Vintage & Rare, and your own website.

## Overview

This application allows music gear sellers to manage their inventory through a unified interface, with seamless synchronization across multiple online marketplaces. It handles everything from product creation to platform-specific listing management, image handling, and sales tracking.

## Features

- **Unified Product Management**: Create, edit, and track products from a single interface
- **Multi-Platform Sync**: Publish listings to eBay, Reverb, Vintage & Rare, and your own website
- **Media Management**: 
  - Upload images directly or use URLs
  - Seamless Dropbox integration for image management
  - Support for video content (YouTube)
- **Advanced Filtering**: Sort and filter your inventory by brand, category, price, etc.
- **Platform-Specific Customization**: Configure platform-specific attributes for optimal listing performance
- **Real-time Status Tracking**: Monitor the sync status of your listings across all platforms
- **CSV Export**: Export your inventory data for use in other tools
- **Sales Tracking**: Track sales and performance metrics across platforms

## Tech Stack

- **Backend**: FastAPI (Python 3.10+)
- **Database**: PostgreSQL with SQLAlchemy ORM (async)
- **Frontend**: Jinja2 Templates, TailwindCSS, JavaScript
- **Deployment**: Docker support (containerized deployment)

## Architecture

The system follows a modular architecture:

```
app/
├── core/               # Core configuration and utilities
├── database.py         # Database configuration
├── dependencies.py     # FastAPI dependencies
├── integrations/       # Platform integration modules
├── models/             # Database models
├── routes/             # API routes
├── schemas/            # Pydantic schemas for validation
├── services/           # Business logic services
├── static/             # Static assets
└── templates/          # Jinja2 templates
```

## Platform Integrations

### eBay
- Create and publish listings to eBay
- Sync inventory and pricing
- Manage eBay-specific attributes and categories

### Reverb
- Create and maintain Reverb listings
- Support for Reverb-specific pricing and inventory features
- Category and attribute mapping

### Vintage & Rare
- Custom V&R listing creation with headless browser automation
- Support for V&R's unique selling features (Dealer's Collective, etc.)
- Media and description formatting

### Shopify
- Publish products to your own custom website
- SEO optimization for listings
- Custom layouts and templates

## Media Management

- **Local Storage**: Upload and store images directly
- **URL References**: Reference external image URLs
- **Dropbox Integration**: Browse and select images from your Dropbox account
- **Video Integration**: Add YouTube videos to your listings

## Database Schema

The database schema is designed to handle both common and platform-specific attributes:

- `products`: Core product information
- `platform_common`: Shared attributes across platforms
- `platform_specific`: Platform-specific listing tables (ebay_listings, reverb_listings, etc.)
- `sales`: Sales tracking information

## Getting Started

### Prerequisites

- Python 3.10+
- PostgreSQL
- Dropbox API credentials (optional)
- eBay API credentials (optional)
- Reverb API credentials (optional)

### Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/inventory-management.git
cd inventory-management
```

2. Create a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Set up environment variables:
```bash
cp .env.example .env
# Edit .env with your configuration
```

5. Run database migrations:
```bash
alembic upgrade head
```

6. Start the development server:
```bash
uvicorn app.main:app --reload
```

7. Visit http://localhost:8000 in your browser

## Configuration

Key configuration options in the `.env` file:

```
# Database
DATABASE_URL=postgresql+asyncpg://user:password@localhost/dbname

# Security
SECRET_KEY=your-secure-secret-key
WEBHOOK_SECRET=your-webhook-secret

# eBay API
EBAY_API_KEY=your-ebay-api-key
EBAY_API_SECRET=your-ebay-api-secret
EBAY_SANDBOX_MODE=True

# Reverb API
REVERB_API_KEY=your-reverb-api-key

# VintageAndRare
VINTAGE_AND_RARE_USERNAME=your-username
VINTAGE_AND_RARE_PASSWORD=your-password

# Dropbox
DROPBOX_ACCESS_TOKEN=your-dropbox-access-token
DROPBOX_REFRESH_TOKEN=your-dropbox-refresh-token
```

## Development

### Adding New Features

1. Update relevant models in `app/models/`
2. Create or update Pydantic schemas in `app/schemas/`
3. Add service methods in `app/services/`
4. Update routes in `app/routes/`
5. Add UI templates in `app/templates/`

### Database Migrations

Generate migrations after model changes:

```bash
alembic revision --autogenerate -m "Description of changes"
```

Apply migrations:

```bash
alembic upgrade head
```

## Deployment

### Docker Deployment

1. Build the Docker image:
```bash
docker build -t inventory-system .
```

2. Run the container:
```bash
docker run -p 8000:8000 --env-file .env inventory-system
```

### Production Considerations

- Use a production ASGI server (e.g., Gunicorn with Uvicorn workers)
- Set up proper database connection pooling
- Configure CORS appropriately
- Set up proper logging
- Use a reverse proxy (Nginx, etc.)

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Acknowledgements

- FastAPI framework
- SQLAlchemy ORM
- Pydantic validation
- TailwindCSS for UI components
- Jinja2 templating engine




🎯 Core System Purpose:

The inventory management system is the "Single Source of Truth" for guitar inventory, serving as:

1. Central Hub - Manages all guitar/kit inventory in one place
2. Multi-Platform Publisher - Can create/update/delete listings across 4 ecommerce sites
3. Sync Manager - Keeps all platforms in sync with central inventory
4. External Change Handler - Detects and manages listings created outside the system

🔄 Two-Way Data Flow:
  Outbound (System → Platforms):
- Create new listings on eBay, Reverb, V&R, Shopify from central inventory
- Update existing listings when inventory changes
- Delete/end listings when items are sold or removed
- Inbound (Platforms → System):

- Detect new listings created directly on platforms (outside system)
- Import those external listings into central inventory
- Sync status changes (sold, ended, etc.) back to central system

🤔 Questions to Clarify:
Conflict Resolution: When someone creates a listing externally that might duplicate an existing inventory item, how should the system handle this?

Primary Platform: Is there a hierarchy of platforms (e.g., if the same item is listed on multiple platforms, which one "wins" for status updates)?

Inventory Sync: When an item sells on one platform, should it automatically be removed/ended on all other platforms?

1. External Listing Handling:
Import → Create new SKU in products table
Link → Create corresponding platform_common and [platform]_listings records
Display → Item detail page shows "synced with 1 platform" + option to list on others
Report → Generate flagging report for manual review/action
2. Platform Hierarchy (At Launch):
Shopify (Primary when launched)
Reverb
Vintage & Rare
eBay
But any platform can sell first and becomes the "winner"

3. Cross-Platform Sync Strategy:
Frequency: 2x daily status checks across all platforms
Rule: First platform to sell wins
Action: Automatically end/remove listings on all other platforms
Logic: Timestamp-based conflict resolution
🎯 System Flow Example:
Item sells on eBay at 10:30 AM
Next sync cycle (12:00 PM) detects the sale
System automatically ends listings on Reverb, V&R, and Shopify
Central inventory marked as SOLD with eBay as winning platform
🚀 Ready for Next Steps:
I understand the complete two-way sync architecture. What would you like to tackle now?

Are we looking at:

Building the external listing detection/import system?
Creating the cross-platform sync mechanism?
Setting up the conflict resolution logic?
Building the flagging reports?


app/integrations/
├── base.py             🗃️ ARCHIVE - PlatformInterface abstraction (unused)
├── setup.py            🗃️ ARCHIVE - Platform registration system (unused)
└── platforms/          🗃️ ARCHIVE - All stub implementations
    ├── ebay.py         🗃️ ARCHIVE - Empty stub
    ├── reverb.py       🗃️ ARCHIVE - Empty stub
    ├── shopify.py      🗃️ ARCHIVE - Empty stub
    └── vintageandrare/ 🗃️ ARCHIVE - Empty stubs