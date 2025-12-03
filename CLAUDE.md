# CLAUDE.md - Important Instructions for Claude AI Assistant

## If making edits to existing functions, classes DO NOT change these names unless there is a compelling reason to. Too often your "helpful" changes break stuff.

## 🚫 NO CO-AUTHOR CREDITS IN COMMITS
Do NOT add co-author credits, "Generated with Claude Code" footers, or any AI attribution to git commits. Keep commit messages clean and professional.

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

## Common Issues & Solutions

1. **VR Download Hanging**: Clean temp files in /tmp before download
2. **Missing Fields**: Run retrofix scripts to populate NULL fields
3. **Column Name Mismatches**: Always check actual schema, never assume
4. **Transaction Issues**: Use commit() not flush() for persistence
5. **NaN in JSON**: Sanitize with pd.isna() before storing in JSONB columns