#!/usr/bin/env python3
"""
Check for any remaining traces of a product in the database.

Usage:
    python scripts/check_product_traces.py --product-id 41
    python scripts/check_product_traces.py --sku REV-90955508
    python scripts/check_product_traces.py --reverb-id 90955508
"""

import asyncio
import argparse
from sqlalchemy import text
from app.database import async_session

async def check_product_traces(product_id: int = None, sku: str = None, reverb_id: str = None):
    """Check all tables for any traces of a product"""

    async with async_session() as session:
        print("\n🔍 Checking for product traces in database...\n")

        traces_found = False

        # Build search conditions
        conditions = []
        if product_id:
            conditions.append(f"Product ID: {product_id}")
        if sku:
            conditions.append(f"SKU: {sku}")
        if reverb_id:
            conditions.append(f"Reverb ID: {reverb_id}")

        print(f"Search criteria: {', '.join(conditions)}")
        print("-" * 60)

        # Check products table
        if product_id or sku:
            query = "SELECT id, sku, brand, model FROM products WHERE "
            if product_id:
                query += f"id = {product_id}"
            elif sku:
                query += f"sku = '{sku}'"

            result = await session.execute(text(query))
            products = result.fetchall()

            if products:
                traces_found = True
                print("\n❌ Found in PRODUCTS table:")
                for p in products:
                    print(f"   ID: {p.id}, SKU: {p.sku}, {p.brand} {p.model}")
            else:
                print("\n✅ No traces in products table")

        # Check platform_common table
        if product_id:
            query = f"""
                SELECT id, platform_name, external_id, status
                FROM platform_common
                WHERE product_id = {product_id}
            """
            result = await session.execute(text(query))
            platform_entries = result.fetchall()

            if platform_entries:
                traces_found = True
                print("\n❌ Found in PLATFORM_COMMON table:")
                for entry in platform_entries:
                    print(f"   ID: {entry.id}, Platform: {entry.platform_name}, External ID: {entry.external_id}, Status: {entry.status}")
            else:
                print("✅ No traces in platform_common table")

        # Check reverb_listings table
        if reverb_id or product_id:
            if reverb_id:
                query = f"SELECT id, platform_id, reverb_listing_id, reverb_state FROM reverb_listings WHERE reverb_listing_id = '{reverb_id}'"
            else:
                query = f"""
                    SELECT rl.id, rl.platform_id, rl.reverb_listing_id, rl.reverb_state
                    FROM reverb_listings rl
                    JOIN platform_common pc ON rl.platform_id = pc.id
                    WHERE pc.product_id = {product_id}
                """

            result = await session.execute(text(query))
            reverb_listings = result.fetchall()

            if reverb_listings:
                traces_found = True
                print("\n❌ Found in REVERB_LISTINGS table:")
                for listing in reverb_listings:
                    print(f"   ID: {listing.id}, Platform ID: {listing.platform_id}, Reverb ID: {listing.reverb_listing_id}, State: {listing.reverb_state}")
            else:
                print("✅ No traces in reverb_listings table")

        # Check sync_events table
        if product_id:
            query = f"""
                SELECT id, platform_name, external_id, change_type, status, created_at
                FROM sync_events
                WHERE product_id = {product_id}
                ORDER BY created_at DESC
                LIMIT 5
            """
            result = await session.execute(text(query))
            sync_events = result.fetchall()

            if sync_events:
                print(f"\n⚠️  Found {len(sync_events)} recent sync events (showing latest 5):")
                for event in sync_events:
                    print(f"   ID: {event.id}, Platform: {event.platform_name}, Type: {event.change_type}, Status: {event.status}, Created: {event.created_at}")
            else:
                print("✅ No traces in sync_events table")

        # Check by external IDs across all platform tables
        if reverb_id:
            # Check ebay_listings
            query = f"""
                SELECT el.id, el.ebay_item_id, pc.product_id
                FROM ebay_listings el
                JOIN platform_common pc ON el.platform_id = pc.id
                JOIN products p ON pc.product_id = p.id
                WHERE p.sku LIKE '%{reverb_id}%'
            """
            result = await session.execute(text(query))
            ebay_related = result.fetchall()

            if ebay_related:
                traces_found = True
                print(f"\n❌ Found related entries in EBAY_LISTINGS:")
                for item in ebay_related:
                    print(f"   eBay Item: {item.ebay_item_id}, Product ID: {item.product_id}")

        # Summary
        print("\n" + "=" * 60)
        if traces_found:
            print("❌ TRACES FOUND - The product still has references in the database")
        else:
            print("✅ ALL CLEAR - No traces of the product found in the database")
        print("=" * 60)

async def main():
    parser = argparse.ArgumentParser(description='Check for product traces in database')
    parser.add_argument('--product-id', type=int, help='Product ID to search for')
    parser.add_argument('--sku', type=str, help='Product SKU to search for')
    parser.add_argument('--reverb-id', type=str, help='Reverb listing ID to search for')

    args = parser.parse_args()

    if not any([args.product_id, args.sku, args.reverb_id]):
        parser.error("At least one search parameter required: --product-id, --sku, or --reverb-id")

    await check_product_traces(args.product_id, args.sku, args.reverb_id)

if __name__ == "__main__":
    asyncio.run(main())