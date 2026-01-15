# CLAUDE.md - Important Instructions for Claude AI Assistant

## If making edits to existing functions, classes DO NOT change these names unless there is a compelling reason to. Too often your "helpful" changes break stuff.

## 🚫 NO CO-AUTHOR CREDITS IN COMMITS
Do NOT add co-author credits, "Generated with Claude Code" footers, or any AI attribution to git commits. Keep commit messages clean and professional.

## 🛑 ALWAYS ASK BEFORE PUSHING TO PRODUCTION
**NEVER run `git push` without explicit user confirmation.**
- Commits are fine to make locally after changes
- But ALWAYS ask "Ready to push to production?" and wait for confirmation before pushing
- This prevents untested code from reaching Railway/production
- User must explicitly say "yes", "push it", "go ahead" or similar before you push

## 🚫 NEVER USE CONDA - CRITICAL
**NEVER EVER install packages using conda. DO NOT suggest conda commands. DO NOT use conda environments.**
- Always use the project's virtual environment: `source venv/bin/activate`
- Install packages with pip only: `pip install package_name`
- If you see `/opt/miniconda3/` in error paths, remind user to activate venv first
- Conda is a nightmare - avoid at all costs

## Critical Reminders

### 🔴 ALWAYS CHECK DATABASE SCHEMA BEFORE QUERIES
**This is the #1 source of errors and retries!**

Before writing ANY SQL or ORM queries:
1. **ALWAYS** check the actual table schema first using:
   ```python
   SELECT column_name, data_type, is_nullable
   FROM information_schema.columns
   WHERE table_name = 'your_table_name'
   ORDER BY ordinal_position
   ```

2. **NEVER ASSUME** column names - verify them first
3. **NEVER ASSUME** relationships - check foreign keys and joins
4. Common mistakes to avoid:
   - Using `photos` instead of `primary_image` and `additional_images` 
   - Assuming `reverb_id` exists in products (use SKU instead: REV-{reverb_id})
   - Using wrong column names in joins

### Database Schema Quick Reference

#### Products Table
- `id`: integer (PK)
- `sku`: varchar (format: REV-{id}, EBY-{id}, VR-{id}, SHOP-{id})
- `primary_image`: varchar (URL)
- `additional_images`: jsonb (array of URLs)
- `brand`: varchar
- `model`: varchar
- `base_price`: float
- `quantity`: integer
- `category`: varchar
- `processing_time`: integer (days)

#### Platform Common Table
- Links products to platform-specific tables
- `product_id`: FK to products.id
- `platform_name`: 'reverb', 'ebay', 'shopify', 'vr'
- `external_id`: The platform's ID for the item

#### Reverb Listings Table
- Does NOT store images (they're in products table)
- `platform_id`: FK to platform_common.id
- `reverb_listing_id`: varchar
- Extended data in `extended_attributes`: jsonb

#### VR Listings Table
- `platform_id`: FK to platform_common.id
- `vr_listing_id`: varchar
- `processing_time`: integer (can be parsed from extended_attributes)
- `price_notax`: float (from CSV product_price column)

### Testing Commands

Always run these when working on sync/import features:

```bash
# Dry run first
python scripts/your_script.py --dry-run

# Check specific product
python -c "
from app.database import async_session
from sqlalchemy import text
import asyncio

async def check():
    async with async_session() as session:
        result = await session.execute(text('SELECT * FROM products WHERE sku = :sku'), {'sku': 'REV-123'})
        print(result.fetchone())
        
asyncio.run(check())
"
```

### Common Patterns

#### 🔴 Async Database Sessions - CRITICAL PATTERN
**NEVER use `Depends(get_session)` in route functions!** This codebase uses async context managers.

```python
# WRONG - Will cause 'AsyncGeneratorContextManager' has no attribute 'execute'
async def my_route(db: AsyncSession = Depends(get_session)):
    result = await db.execute(...)  # ERROR!

# CORRECT - Use async with context manager
async def my_route(request: Request):
    async with get_session() as db:
        result = await db.execute(...)  # Works!
        # ALL code using db must be inside this block
```

**All code that uses the `db` session MUST be inside the `async with` block.** If you close the block early, subsequent code will fail.

#### Extract Reverb ID from SKU
```python
# SKU format is REV-{reverb_id}
reverb_id = sku.replace('REV-', '').replace('rev-', '')
```

#### Image URL Transformation
```python
from app.core.utils import ImageTransformer, ImageQuality
max_res_url = ImageTransformer.transform_reverb_url(image_url, ImageQuality.MAX_RES)
```

### Currency
- Always use **£** (British Pounds) not $ for display
- Database stores raw numbers without currency symbols
- Format as: `£{price:,.0f}` for display

### Processing Time
- Stored as integer days in database
- Parse from CSV: "3 Days" → 3, "1 Weeks" → 7
- Default to 3 days if missing

## Project Context

This is an inventory management system that syncs products across multiple platforms:
- **Reverb**: Primary marketplace (SKU: REV-{id})
- **eBay**: Secondary marketplace (SKU: EBY-{id})
- **Shopify**: E-commerce platform (SKU: SHOP-{id})
- **VR (Vintage & Rare)**: Specialized platform (SKU: VR-{id})

The sync flow is typically:
1. Import from Reverb (primary source)
2. Create product in local database
3. Sync to other platforms (eBay, Shopify, VR)
4. Track sync status in sync_events table

## Key Documentation

- **`docs/todo.md`** - Current development priorities and completed work
- **`docs/multi-tenant-roadmap.md`** - Future SaaS product roadmap (multi-customer architecture, onboarding, pricing)
- **`docs/dhl-integration.md`** - DHL shipping label integration details
- **`docs/api/`** - Architecture, models, and platform integration docs

## Common Issues & Solutions

1. **VR Download Hanging**: Clean temp files in /tmp before download
2. **Missing Fields**: Run retrofix scripts to populate NULL fields
3. **Column Name Mismatches**: Always check actual schema, never assume
4. **Transaction Issues**: Use commit() not flush() for persistence
5. **NaN in JSON**: Sanitize with pd.isna() before storing in JSONB columns

### 🔴 Reverb API: LISTINGS vs ORDERS - CRITICAL DISTINCTION

**These are TWO COMPLETELY DIFFERENT APIs that return different data:**

| API Endpoint | Method | Returns | Use For |
|-------------|--------|---------|---------|
| `/my/listings` | `get_all_listings_detailed(state="sold")` | **Listing objects** (product info, no buyer data) | Syncing listing status/data |
| `/my/orders/selling/all` | `get_all_sold_orders()` | **Order objects** (buyer, payment, shipping) | Processing sales & inventory |

**NEVER use `get_all_listings_detailed(state="sold")` to import orders!**

- Listings don't have: `order_number`, `order_uuid`, `buyer_name`, `total_amount`, shipping info
- Orders have all this data and are what we need for `reverb_orders` table

**Correct Pattern (see `scripts/run_sync_scheduler.py`):**
```python
# CORRECT - for fetching order data
client = ReverbClient(api_key=settings.REVERB_API_KEY)
orders = await client.get_all_sold_orders()  # Uses /my/orders/selling/all

# WRONG - this returns listings, NOT orders
orders = await client.get_all_listings_detailed(state="sold")  # Uses /my/listings
```

**Order Processing Flow:**
1. Scheduler's `fetch_reverb_orders()` → `get_all_sold_orders()` → upserts to `reverb_orders`
2. `OrderSaleProcessor.process_unprocessed_orders()` → handles inventory decrements
3. For stocked items: `create_sync_events_for_stocked_orders()` → creates `order_sale` sync_events

### 🔴 eBay Listing Creation - TWO ROUTES

**Both routes ultimately call `ebay_service.create_listing_from_product()` but differ in how they're triggered:**

#### Route 1: Multi-Platform Create via add.html
**Endpoint:** `POST /inventory/add` → `add_product()`
**Location:** `app/routes/inventory.py:3674-3720`

```
User fills add.html form with platform checkboxes
    ↓
add_product() parses form, creates Product
    ↓
If "ebay" in platforms_to_sync:
    ↓
Builds enriched_data from form fields (category, images, etc.)
    ↓
ebay_service.create_listing_from_product(
    product=product,
    reverb_api_data=enriched_data,  ← Built from form
    use_shipping_profile=True,
    **ebay_policies
)
```

#### Route 2: Single Platform via details.html "List on eBay" button
**Endpoint:** `POST /inventory/product/{id}/list_on/ebay` → `handle_create_platform_listing_from_detail()`
**Location:** `app/routes/inventory.py:2630-2744`

```
User clicks "List on eBay" button on product detail page
    ↓
Fetches existing Reverb listing to get category UUID (if REV- SKU)
    ↓
Builds enriched_data with Reverb category UUID
    ↓
ebay_service.create_listing_from_product(
    product=product,
    reverb_api_data=enriched_data,  ← Contains Reverb UUID for category mapping
    use_shipping_profile=True,
    **policies
)
```

#### Common Service Method
**Location:** `app/services/ebay_service.py:1624-1920` → `create_listing_from_product()`

Both routes converge here. This method:
1. Maps category via UUID (`_get_ebay_category_from_reverb_uuid`) or string fallback
2. Maps condition via `_get_ebay_condition_id()`
3. Builds item specifics via `_build_item_specifics()`
4. Calls `trading_api.add_fixed_price_item()`

**Available Dynamic APIs (for validation):**
- `trading_api.get_category_features(category_id)` → Returns `ValidConditions` list
- `client.get_category_aspects(category_id)` → Returns required Item Specifics