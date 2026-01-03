#!/usr/bin/env python3
"""
Check for discrepancies between local archived status and Shopify actual status.

This script identifies products that are marked as 'archived' locally but are
still ACTIVE on Shopify - these are legacy data issues that need fixing.

Usage:
    python scripts/shopify/check_archive_discrepancies.py
    python scripts/shopify/check_archive_discrepancies.py --limit 10
    python scripts/shopify/check_archive_discrepancies.py --fix --dry-run
    python scripts/shopify/check_archive_discrepancies.py --fix --limit 5
"""

import asyncio
import argparse
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from sqlalchemy import text
from app.database import get_session
from app.services.shopify.client import ShopifyGraphQLClient


async def get_archived_listings(limit: int = None):
    """Get all products marked as archived locally with Shopify IDs."""
    async with get_session() as db:
        query = text("""
            SELECT
                p.id as product_id,
                p.sku,
                p.title,
                pc.id as platform_common_id,
                sl.id as shopify_listing_id,
                sl.shopify_product_id
            FROM products p
            JOIN platform_common pc ON p.id = pc.product_id AND pc.platform_name = 'shopify'
            JOIN shopify_listings sl ON pc.id = sl.platform_id
            WHERE LOWER(sl.status) = 'archived'
              AND sl.shopify_product_id IS NOT NULL
            ORDER BY p.id
        """ + (f" LIMIT {limit}" if limit else ""))

        result = await db.execute(query)
        return result.fetchall()


def check_shopify_status(client, shopify_product_id: str) -> str:
    """Check actual status on Shopify."""
    query = """
    query getProductStatus($id: ID!) {
        product(id: $id) {
            id
            status
        }
    }
    """

    try:
        result = client._make_request(query, {"id": shopify_product_id}, estimated_cost=1)
        if result and result.get("product"):
            return result["product"]["status"]
        return "NOT_FOUND"
    except Exception as e:
        return f"ERROR: {e}"


def archive_on_shopify(client, shopify_product_id: str) -> bool:
    """Archive product on Shopify."""
    try:
        result = client.update_product({
            "id": shopify_product_id,
            "status": "ARCHIVED"
        })
        return result is not None
    except Exception as e:
        print(f"      Error: {e}")
        return False


async def main():
    parser = argparse.ArgumentParser(description="Check/fix archive discrepancies between local DB and Shopify")
    parser.add_argument("--limit", type=int, help="Limit number of products to check")
    parser.add_argument("--fix", action="store_true", help="Fix discrepancies by archiving on Shopify")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be fixed without making changes")

    args = parser.parse_args()

    print("=" * 70)
    print("SHOPIFY ARCHIVE DISCREPANCY CHECK")
    print("=" * 70)

    if args.fix:
        if args.dry_run:
            print("MODE: FIX (DRY RUN) - Will show what would be archived\n")
        else:
            print("MODE: FIX (LIVE) - Will archive on Shopify\n")
    else:
        print("MODE: CHECK ONLY - Identifying discrepancies\n")

    client = ShopifyGraphQLClient()

    # Get archived listings from local DB
    listings = await get_archived_listings(args.limit)
    print(f"Found {len(listings)} products marked as archived locally\n")

    active_on_shopify = []
    already_archived = []
    not_found = []
    errors = []

    for row in listings:
        print(f"Product ID {row.product_id}: {row.sku}")
        print(f"  Title: {row.title[:50]}...")

        status = check_shopify_status(client, row.shopify_product_id)
        print(f"  Shopify Status: {status}")

        if status == "ACTIVE":
            active_on_shopify.append(row)
            print(f"  -> MISMATCH: Local=archived, Shopify=ACTIVE")

            if args.fix:
                if args.dry_run:
                    print(f"  -> Would archive on Shopify (dry run)")
                else:
                    if archive_on_shopify(client, row.shopify_product_id):
                        print(f"  -> FIXED: Archived on Shopify")
                    else:
                        print(f"  -> FAILED to archive on Shopify")
                        errors.append(row)

        elif status == "ARCHIVED":
            already_archived.append(row)
            print(f"  -> OK: Already archived on Shopify")
        elif status == "NOT_FOUND":
            not_found.append(row)
            print(f"  -> Product not found on Shopify")
        else:
            errors.append(row)
            print(f"  -> Error checking status")

        print()

    # Summary
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Total checked:         {len(listings)}")
    print(f"Already archived:      {len(already_archived)}")
    print(f"Still ACTIVE (need fix): {len(active_on_shopify)}")
    print(f"Not found on Shopify:  {len(not_found)}")
    print(f"Errors:                {len(errors)}")

    if active_on_shopify and not args.fix:
        print(f"\nTo fix these discrepancies, run:")
        print(f"  python scripts/shopify/check_archive_discrepancies.py --fix --dry-run")
        print(f"  python scripts/shopify/check_archive_discrepancies.py --fix")


if __name__ == "__main__":
    asyncio.run(main())
