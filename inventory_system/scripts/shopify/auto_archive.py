#!/usr/bin/env python3
"""
Auto-archive Shopify listings for sold/ended products.

BACKGROUND
----------
Shopify doesn't have SOLD or ENDED statuses like other platforms. Products remain
ACTIVE until manually archived. This script automates the archiving process for
products that have been sold/ended for 14+ days.

CRITERIA FOR ARCHIVING
----------------------
A product is archived if ALL of the following are true:
1. Non-inventorised item (quantity <= 1, unique item - not stocked inventory)
2. Shopify listing status is 'ended' (sold internally but still ACTIVE on Shopify)
3. Updated 14+ days ago
4. Has a valid Shopify product ID

WHAT IT DOES
------------
1. Queries database for candidates matching criteria
2. For each candidate:
   - Calls Shopify API to set status to ARCHIVED
   - Updates shopify_listings.status to 'archived'
   - Updates platform_common.status to 'archived'
3. Reports summary

SCHEDULING
----------
This script can be:
- Run manually for testing: python scripts/shopify/auto_archive.py --dry-run --limit 5
- Added to cron/scheduler for weekly runs: python scripts/shopify/auto_archive.py

ARGUMENTS
---------
--dry-run       Show what would be archived without making changes
--limit N       Process only first N items (useful for testing)
--days N        Days since sold/ended before archiving (default: 14)

EXAMPLES
--------
# Dry run - see what would be archived
python scripts/shopify/auto_archive.py --dry-run

# Test with 1 product (dry run)
python scripts/shopify/auto_archive.py --dry-run --limit 1

# Archive first 5 products (live)
python scripts/shopify/auto_archive.py --limit 5

# Archive all eligible products
python scripts/shopify/auto_archive.py

# Use 30 days threshold instead of 14
python scripts/shopify/auto_archive.py --days 30 --dry-run

Created: 2026-01-03
"""

import asyncio
import argparse
import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from sqlalchemy import text
from app.database import get_session
from app.core.config import get_settings
from app.services.shopify.client import ShopifyGraphQLClient
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class ShopifyAutoArchiver:

    def __init__(self, dry_run: bool = False, days_threshold: int = 14):
        self.settings = get_settings()
        self.dry_run = dry_run
        self.days_threshold = days_threshold
        self.shopify_client = ShopifyGraphQLClient()
        self.archived_count = 0
        self.skipped_count = 0
        self.error_count = 0

    async def get_archive_candidates(self, limit: int = None) -> list:
        """Get products eligible for archiving.

        Criteria:
        - Non-inventorised (quantity <= 1, unique items)
        - Shopify listing status is 'ended' (sold internally but not yet archived)
        - Has a valid Shopify product ID
        - Updated 14+ days ago
        """
        cutoff_date = datetime.now() - timedelta(days=self.days_threshold)

        async with get_session() as db:
            query = text("""
                SELECT
                    p.id as product_id,
                    p.sku,
                    p.title,
                    p.quantity,
                    p.updated_at as product_updated_at,
                    pc.id as platform_common_id,
                    pc.status as platform_status,
                    pc.updated_at as platform_updated_at,
                    sl.id as shopify_listing_id,
                    sl.shopify_product_id,
                    sl.handle,
                    sl.status as shopify_status
                FROM products p
                JOIN platform_common pc ON p.id = pc.product_id AND pc.platform_name = 'shopify'
                JOIN shopify_listings sl ON pc.id = sl.platform_id
                WHERE
                    -- Non-inventorised: quantity should be 0 or 1 (unique items that sold)
                    p.quantity <= 1
                    -- Shopify listing is 'ended' (sold but not yet archived on Shopify)
                    AND LOWER(sl.status) = 'ended'
                    -- Has a valid Shopify product ID
                    AND sl.shopify_product_id IS NOT NULL
                    -- Updated more than X days ago
                    AND sl.updated_at < :cutoff_date
                ORDER BY sl.updated_at ASC
            """ + (f" LIMIT {limit}" if limit else ""))

            result = await db.execute(query, {"cutoff_date": cutoff_date})
            return result.fetchall()

    def archive_on_shopify(self, shopify_product_id: str) -> bool:
        """Call Shopify API to set product status to ARCHIVED."""
        if self.dry_run:
            return True

        try:
            # Use the existing update_product method
            result = self.shopify_client.update_product({
                "id": shopify_product_id,
                "status": "ARCHIVED"
            })
            return result is not None
        except Exception as e:
            logger.error(f"Shopify API error archiving {shopify_product_id}: {e}")
            return False

    async def update_local_status(self, platform_common_id: int, shopify_listing_id: int) -> bool:
        """Update local database status to archived."""
        if self.dry_run:
            return True

        try:
            async with get_session() as db:
                # Update platform_common
                await db.execute(
                    text("""
                        UPDATE platform_common
                        SET status = 'archived', updated_at = CURRENT_TIMESTAMP
                        WHERE id = :id
                    """),
                    {"id": platform_common_id}
                )

                # Update shopify_listings
                await db.execute(
                    text("""
                        UPDATE shopify_listings
                        SET status = 'archived', updated_at = CURRENT_TIMESTAMP
                        WHERE id = :id
                    """),
                    {"id": shopify_listing_id}
                )

                await db.commit()
                return True
        except Exception as e:
            logger.error(f"Database error updating status: {e}")
            return False

    async def run(self, limit: int = None):
        """Main execution."""
        print("=" * 60)
        print("SHOPIFY AUTO-ARCHIVE")
        print("=" * 60)

        if self.dry_run:
            print("🔍 DRY RUN MODE - No changes will be made\n")
        else:
            print("⚠️  LIVE MODE - Will archive products on Shopify\n")

        print(f"📅 Threshold: {self.days_threshold} days since sold/ended")
        cutoff_date = datetime.now() - timedelta(days=self.days_threshold)
        print(f"📅 Cutoff date: {cutoff_date.strftime('%Y-%m-%d')}\n")

        # Get candidates
        candidates = await self.get_archive_candidates(limit)
        print(f"Found {len(candidates)} products eligible for archiving\n")

        if not candidates:
            print("No products to archive.")
            return

        for row in candidates:
            print(f"📦 {row.sku}: {row.title[:50]}...")
            print(f"   Shopify ID: {row.shopify_product_id}")
            print(f"   Platform status: {row.platform_status} | Shopify status: {row.shopify_status}")
            print(f"   Last updated: {row.platform_updated_at}")

            # Archive on Shopify
            if self.archive_on_shopify(row.shopify_product_id):
                # Update local database
                if await self.update_local_status(row.platform_common_id, row.shopify_listing_id):
                    if self.dry_run:
                        print(f"   ✅ Would archive (dry run)")
                    else:
                        print(f"   ✅ Archived successfully")
                    self.archived_count += 1
                else:
                    print(f"   ❌ Shopify archived but local DB update failed")
                    self.error_count += 1
            else:
                print(f"   ❌ Failed to archive on Shopify")
                self.error_count += 1

            print()

        # Summary
        print("=" * 60)
        print("SUMMARY")
        print("=" * 60)
        print(f"Archived: {self.archived_count}")
        print(f"Skipped:  {self.skipped_count}")
        print(f"Errors:   {self.error_count}")

        if self.dry_run and self.archived_count > 0:
            print(f"\nRun without --dry-run to archive {self.archived_count} products")


async def run_auto_archive(dry_run: bool = False, limit: int = None, days: int = 14):
    """Entry point for scheduler integration."""
    archiver = ShopifyAutoArchiver(dry_run=dry_run, days_threshold=days)
    await archiver.run(limit=limit)
    return {
        "archived": archiver.archived_count,
        "skipped": archiver.skipped_count,
        "errors": archiver.error_count
    }


async def main():
    parser = argparse.ArgumentParser(description="Auto-archive Shopify listings for sold/ended products")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be archived without making changes")
    parser.add_argument("--limit", type=int, help="Limit number of products to process")
    parser.add_argument("--days", type=int, default=14, help="Days since sold/ended before archiving (default: 14)")

    args = parser.parse_args()

    archiver = ShopifyAutoArchiver(dry_run=args.dry_run, days_threshold=args.days)
    await archiver.run(limit=args.limit)


if __name__ == "__main__":
    asyncio.run(main())
