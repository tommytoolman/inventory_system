"""
Enrich eBay listings with product data and calculate new pricing.

New eBay T&Cs require 10% markup over base price, rounded to sensible endings:
- Endings: 49, 99, 499, 999 (whichever is next highest)
"""

import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

load_dotenv()


def round_to_sensible_price(target: float) -> int:
    """
    Round a price UP to the nearest sensible ending: 49, 99, 499, 999.

    Examples:
        658.9 -> 699
        1098.9 -> 1099
        540 -> 549
        4500 -> 4999
        10050 -> 10499
    """
    if target <= 0:
        return 0

    target = int(target)  # Start with integer

    # Define sensible endings in order
    endings = [49, 99, 499, 999]

    # Get the base (thousands, hundreds, etc.)
    # For each ending, calculate what the price would be
    candidates = []

    for ending in endings:
        if ending < 100:
            # For 49, 99 - these repeat every 100
            base = (target // 100) * 100
            candidate = base + ending
            if candidate < target:
                candidate += 100
            candidates.append(candidate)
        else:
            # For 499, 999 - these repeat every 1000
            base = (target // 1000) * 1000
            candidate = base + ending
            if candidate < target:
                candidate += 1000
            candidates.append(candidate)

    # Return the smallest candidate that's >= target
    valid_candidates = [c for c in candidates if c >= target]
    return min(valid_candidates) if valid_candidates else max(candidates)


def calculate_new_ebay_price(base_price: float) -> int:
    """Calculate new eBay price: base * 1.10, rounded to sensible ending."""
    if pd.isna(base_price) or base_price <= 0:
        return 0
    target = base_price * 1.10
    return round_to_sensible_price(target)


async def get_product_data_by_sku(session: AsyncSession, skus: list) -> dict:
    """Fetch product data for given SKUs."""
    if not skus:
        return {}

    # Clean SKUs - remove NaN
    clean_skus = [s for s in skus if pd.notna(s) and s]
    if not clean_skus:
        return {}

    query = text("""
        SELECT
            p.id as product_id,
            p.sku,
            p.brand,
            p.model,
            p.finish as colour,
            p.year,
            p.base_price,
            p.title,
            p.category
        FROM products p
        WHERE p.sku = ANY(:skus)
    """)

    result = await session.execute(query, {"skus": clean_skus})
    rows = result.fetchall()

    # Return dict keyed by SKU
    return {row.sku: dict(row._mapping) for row in rows}


async def get_product_data_by_ebay_id(session: AsyncSession, ebay_ids: list) -> dict:
    """Fetch product data for eBay item IDs (for items without SKU)."""
    if not ebay_ids:
        return {}

    # Convert to strings
    clean_ids = [str(int(i)) for i in ebay_ids if pd.notna(i)]
    if not clean_ids:
        return {}

    query = text("""
        SELECT
            p.id as product_id,
            p.sku,
            p.brand,
            p.model,
            p.finish as colour,
            p.year,
            p.base_price,
            p.title,
            p.category,
            el.ebay_item_id
        FROM products p
        JOIN platform_common pc ON p.id = pc.product_id
        JOIN ebay_listings el ON pc.id = el.platform_id
        WHERE el.ebay_item_id = ANY(:ebay_ids)
        AND pc.platform_name = 'ebay'
    """)

    result = await session.execute(query, {"ebay_ids": clean_ids})
    rows = result.fetchall()

    # Return dict keyed by eBay item ID
    return {row.ebay_item_id: dict(row._mapping) for row in rows}


async def enrich_ebay_listings(input_file: str, output_file: str):
    """Main enrichment function."""

    # Read the xlsx
    print(f"Reading {input_file}...")
    df = pd.read_excel(input_file)
    print(f"Loaded {len(df)} listings")

    # Connect to database
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL not set")

    # Convert to async URL if needed
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    engine = create_async_engine(database_url)
    async_session_maker = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session_maker() as session:
        # Get product data by SKU
        skus = df['SKU'].dropna().unique().tolist()
        print(f"Looking up {len(skus)} unique SKUs...")
        sku_data = await get_product_data_by_sku(session, skus)
        print(f"Found {len(sku_data)} products by SKU")

        # Get product data by eBay ID for items without SKU
        no_sku_mask = df['SKU'].isna()
        ebay_ids_without_sku = df.loc[no_sku_mask, 'ItemID'].unique().tolist()
        print(f"Looking up {len(ebay_ids_without_sku)} items without SKU by eBay ID...")
        ebay_id_data = await get_product_data_by_ebay_id(session, ebay_ids_without_sku)
        print(f"Found {len(ebay_id_data)} products by eBay ID")

    await engine.dispose()

    # Enrich the dataframe
    print("Enriching data...")

    # Initialize new columns
    df['db_product_id'] = None
    df['db_sku'] = None
    df['db_brand'] = None
    df['db_model'] = None
    df['db_colour'] = None
    df['db_year'] = None
    df['db_base_price'] = None
    df['db_title'] = None
    df['db_category'] = None
    df['calculated_new_price'] = None
    df['price_override'] = None  # For manual overrides

    matched_count = 0

    for idx, row in df.iterrows():
        product_data = None

        # Try SKU first
        if pd.notna(row['SKU']) and row['SKU'] in sku_data:
            product_data = sku_data[row['SKU']]
        # Then try eBay ID
        elif str(int(row['ItemID'])) in ebay_id_data:
            product_data = ebay_id_data[str(int(row['ItemID']))]

        if product_data:
            matched_count += 1
            df.at[idx, 'db_product_id'] = product_data['product_id']
            df.at[idx, 'db_sku'] = product_data['sku']
            df.at[idx, 'db_brand'] = product_data['brand']
            df.at[idx, 'db_model'] = product_data['model']
            df.at[idx, 'db_colour'] = product_data['colour']
            df.at[idx, 'db_year'] = product_data['year']
            df.at[idx, 'db_base_price'] = product_data['base_price']
            df.at[idx, 'db_title'] = product_data['title']
            df.at[idx, 'db_category'] = product_data['category']

            # Calculate new price
            if product_data['base_price']:
                new_price = calculate_new_ebay_price(product_data['base_price'])
                df.at[idx, 'calculated_new_price'] = new_price

    print(f"Matched {matched_count} of {len(df)} listings to products")

    # Select and reorder columns for output
    output_cols = [
        'ItemID',
        'db_product_id',
        'db_sku',
        'SKU',
        'Title',
        'db_brand',
        'brand',
        'db_model',
        'model',
        'db_colour',
        'color',
        'db_year',
        'year',
        'db_category',
        'primary_category_name',
        'db_base_price',
        'price',
        'calculated_new_price',
        'price_override',
        'condition_display_name',
        'listing_url',
    ]

    # Only include columns that exist
    output_cols = [c for c in output_cols if c in df.columns]

    output_df = df[output_cols].copy()

    # Rename columns for clarity
    output_df = output_df.rename(columns={
        'db_product_id': 'product_id',
        'db_sku': 'sku_db',
        'SKU': 'sku_ebay',
        'db_brand': 'brand_db',
        'brand': 'brand_ebay',
        'db_model': 'model_db',
        'model': 'model_ebay',
        'db_colour': 'colour_db',
        'color': 'colour_ebay',
        'db_year': 'year_db',
        'year': 'year_ebay',
        'db_category': 'category_db',
        'primary_category_name': 'category_ebay',
        'db_base_price': 'base_price',
        'price': 'current_ebay_price',
    })

    # Add price difference column
    output_df['price_change'] = output_df['calculated_new_price'] - output_df['current_ebay_price']

    # Sort by price change descending (biggest increases first)
    output_df = output_df.sort_values('price_change', ascending=False, na_position='last')

    # Save to xlsx
    print(f"Saving to {output_file}...")
    output_df.to_excel(output_file, index=False)

    # Print summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    print(f"Total listings: {len(df)}")
    print(f"Matched to products: {matched_count}")
    print(f"Unmatched: {len(df) - matched_count}")

    # Price stats for matched items
    matched_df = output_df[output_df['base_price'].notna()]
    if len(matched_df) > 0:
        print(f"\nPrice changes for {len(matched_df)} items with base price:")
        print(f"  Current total: £{matched_df['current_ebay_price'].sum():,.0f}")
        print(f"  New total: £{matched_df['calculated_new_price'].sum():,.0f}")
        print(f"  Total increase: £{matched_df['price_change'].sum():,.0f}")

        # Show some examples
        print("\nSample price changes:")
        sample = matched_df.head(10)[['Title', 'base_price', 'current_ebay_price', 'calculated_new_price', 'price_change']]
        for _, r in sample.iterrows():
            title = r['Title'][:40] if pd.notna(r['Title']) else 'N/A'
            print(f"  {title}... £{r['base_price']:,.0f} base → £{r['current_ebay_price']:,.0f} current → £{r['calculated_new_price']:,.0f} new (change: £{r['price_change']:+,.0f})")


if __name__ == "__main__":
    input_file = "scripts/ebay/output/ebay_listings_active_flat_20251216_131122.xlsx"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = f"scripts/ebay/output/ebay_pricing_enriched_{timestamp}.xlsx"

    asyncio.run(enrich_ebay_listings(input_file, output_file))
    print(f"\nOutput saved to: {output_file}")
