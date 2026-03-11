#!/usr/bin/env python3
"""
Audit Shopify items with 'ended' status locally.

Checks each item against Shopify API and cross-references with orders
to determine actual sale dates.

Usage:
    python scripts/shopify/audit_ended_items.py
    python scripts/shopify/audit_ended_items.py --fix-stale
"""

import asyncio
import argparse
import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from sqlalchemy import text
from app.database import get_session
from app.services.shopify.client import ShopifyGraphQLClient


async def get_ended_items():
    """Get all items with 'ended' status locally for Shopify."""
    async with get_session() as db:
        result = await db.execute(text("""
            SELECT
                p.id,
                p.sku,
                p.title,
                p.quantity,
                pc.status as pc_status,
                sl.status as sl_status,
                sl.shopify_product_id,
                sl.updated_at as sl_updated
            FROM products p
            JOIN platform_common pc ON p.id = pc.product_id AND pc.platform_name = 'shopify'
            JOIN shopify_listings sl ON pc.id = sl.platform_id
            WHERE LOWER(sl.status) = 'ended'
              AND sl.shopify_product_id IS NOT NULL
            ORDER BY sl.updated_at DESC
        """))
        return result.fetchall()


async def get_orders_for_sku(sku: str):
    """Get order info for a SKU from all order tables."""
    async with get_session() as db:
        # Check each table separately to avoid schema issues
        # Shopify orders
        result = await db.execute(text("""
            SELECT 'shopify' as platform, created_at as order_date, order_name as order_ref
            FROM shopify_orders WHERE primary_sku = :sku
            ORDER BY created_at DESC LIMIT 1
        """), {"sku": sku})
        row = result.fetchone()
        if row:
            return row

        # Reverb orders
        result = await db.execute(text("""
            SELECT 'reverb' as platform, created_at as order_date, order_number::text as order_ref
            FROM reverb_orders WHERE sku = :sku
            ORDER BY created_at DESC LIMIT 1
        """), {"sku": sku})
        row = result.fetchone()
        if row:
            return row

        # eBay orders - uses primary_sku
        result = await db.execute(text("""
            SELECT 'ebay' as platform, created_time as order_date, order_id as order_ref
            FROM ebay_orders WHERE primary_sku = :sku
            ORDER BY created_time DESC LIMIT 1
        """), {"sku": sku})
        return result.fetchone()


def check_shopify_status(client, shopify_product_id: str):
    """Check actual status and inventory on Shopify."""
    query = """
    query getProduct($id: ID!) {
        product(id: $id) {
            id
            status
            variants(first: 1) {
                edges {
                    node {
                        inventoryQuantity
                    }
                }
            }
        }
    }
    """

    try:
        result = client._make_request(query, {"id": shopify_product_id}, estimated_cost=1)
        if result and result.get("product"):
            p = result["product"]
            variants = p.get("variants", {}).get("edges", [])
            inv = variants[0]["node"]["inventoryQuantity"] if variants else None
            return p["status"], inv
        return "NOT_FOUND", None
    except Exception as e:
        return "ERROR", str(e)[:30]


async def main():
    parser = argparse.ArgumentParser(description="Audit Shopify ended items")
    parser.add_argument("--fix-stale", action="store_true",
                        help="Archive items that are 14+ days old with no recent orders")
    args = parser.parse_args()

    cutoff = datetime.now() - timedelta(days=14)

    print("=" * 110)
    print("SHOPIFY ENDED ITEMS AUDIT")
    print("=" * 110)
    print(f"14-day cutoff: {cutoff.strftime('%Y-%m-%d')}")
    print()

    client = ShopifyGraphQLClient()
    items = await get_ended_items()

    print(f"Found {len(items)} items with 'ended' status locally\n")
    print(f"{'ID':>4} | {'SKU':<18} | {'Shopify':<8} | {'Inv':>3} | {'Updated':<10} | {'Order Date':<10} | Status")
    print("-" * 110)

    categories = {
        "sold_recent": [],      # Has order < 14 days - correct
        "sold_stale": [],       # Has order >= 14 days - should archive
        "no_order_recent": [],  # No order, updated < 14 days
        "no_order_stale": [],   # No order, updated >= 14 days - should archive
        "already_archived": [], # Already archived on Shopify
        "error": []
    }

    for item in items:
        shopify_status, inv = check_shopify_status(client, item.shopify_product_id)
        order = await get_orders_for_sku(item.sku)

        updated_str = item.sl_updated.strftime('%Y-%m-%d') if item.sl_updated else 'N/A'

        if order:
            order_date = order.order_date
            order_str = order_date.strftime('%Y-%m-%d') if order_date else 'N/A'
            is_stale = order_date < cutoff if order_date else True
            if is_stale:
                status = "STALE (14+d)"
                categories["sold_stale"].append(item)
            else:
                status = "OK (recent)"
                categories["sold_recent"].append(item)
        else:
            order_str = "NO ORDER"
            is_stale = item.sl_updated < cutoff if item.sl_updated else True
            if is_stale:
                status = "STALE (no order)"
                categories["no_order_stale"].append(item)
            else:
                status = "recent (no order)"
                categories["no_order_recent"].append(item)

        if shopify_status == "ARCHIVED":
            status = "ARCHIVED on Shopify"
            categories["already_archived"].append(item)
        elif shopify_status == "ERROR":
            categories["error"].append(item)

        inv_str = str(inv) if inv is not None else "?"
        print(f"{item.id:4d} | {item.sku:<18} | {shopify_status:<8} | {inv_str:>3} | {updated_str:<10} | {order_str:<10} | {status}")

    # Summary
    print()
    print("=" * 110)
    print("SUMMARY")
    print("=" * 110)
    print(f"Sold recently (< 14 days):    {len(categories['sold_recent']):3d} - OK, keep as ended")
    print(f"Sold stale (>= 14 days):      {len(categories['sold_stale']):3d} - Should archive")
    print(f"No order, recent:             {len(categories['no_order_recent']):3d} - Investigate")
    print(f"No order, stale:              {len(categories['no_order_stale']):3d} - Should archive")
    print(f"Already archived on Shopify:  {len(categories['already_archived']):3d}")
    print(f"Errors:                       {len(categories['error']):3d}")

    stale_count = len(categories['sold_stale']) + len(categories['no_order_stale'])
    if stale_count > 0 and not args.fix_stale:
        print(f"\nTo archive the {stale_count} stale items, run:")
        print("  python scripts/shopify/audit_ended_items.py --fix-stale")

    # Fix stale items if requested
    if args.fix_stale and stale_count > 0:
        print(f"\n{'=' * 110}")
        print("ARCHIVING STALE ITEMS")
        print("=" * 110)

        to_archive = categories['sold_stale'] + categories['no_order_stale']
        archived = 0
        failed = 0

        for item in to_archive:
            print(f"Archiving {item.sku}...", end=" ")
            try:
                # Archive on Shopify
                result = client.update_product({
                    "id": item.shopify_product_id,
                    "status": "ARCHIVED"
                })
                if result:
                    # Update local database
                    await update_local_status(item.sku)
                    print("OK")
                    archived += 1
                else:
                    print("FAILED (API)")
                    failed += 1
            except Exception as e:
                print(f"ERROR: {e}")
                failed += 1

        print(f"\nArchived: {archived}, Failed: {failed}")


async def update_local_status(sku: str):
    """Update local database status to archived."""
    async with get_session() as db:
        await db.execute(text("""
            UPDATE shopify_listings sl
            SET status = 'archived', updated_at = CURRENT_TIMESTAMP
            FROM platform_common pc
            JOIN products p ON pc.product_id = p.id
            WHERE sl.platform_id = pc.id
              AND pc.platform_name = 'shopify'
              AND p.sku = :sku
        """), {"sku": sku})

        await db.execute(text("""
            UPDATE platform_common pc
            SET status = 'archived', updated_at = CURRENT_TIMESTAMP
            FROM products p
            WHERE pc.product_id = p.id
              AND pc.platform_name = 'shopify'
              AND p.sku = :sku
        """), {"sku": sku})

        await db.commit()


if __name__ == "__main__":
    asyncio.run(main())
