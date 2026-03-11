#!/usr/bin/env python3
"""
Script to find mismatches between platform_common and platform-specific listings tables

Usage:
    python scripts/check_platform_mismatches.py
    python scripts/check_platform_mismatches.py --platform reverb
    python scripts/check_platform_mismatches.py --show-all

Shows records where platform_common.status doesn't match the status in the
platform-specific table (reverb_listings, ebay_listings, vr_listings, shopify_listings).

Platform mapping:
- reverb: reverb_listings.reverb_state
- ebay: ebay_listings.listing_status
- vr: vr_listings.vr_state
- shopify: shopify_listings.status
"""

import asyncio
import argparse
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from dotenv import load_dotenv
import os
from datetime import datetime

# Load environment variables from .env file
load_dotenv()

async def check_mismatches(platform_filter=None, show_all=False):
    """
    Check for status mismatches between platform_common and platform-specific tables.

    Args:
        platform_filter: Optional platform name to filter by ('reverb', 'ebay', 'vr', 'shopify')
        show_all: If True, shows all records including matches
    """
    db_url = os.getenv('DATABASE_URL')
    if not db_url:
        print("ERROR: DATABASE_URL environment variable not set")
        return

    # Convert to async URL
    if db_url.startswith('postgresql://'):
        db_url = db_url.replace('postgresql://', 'postgresql+asyncpg://', 1)

    # Show which database we're connecting to (masked)
    host_part = db_url.split('@')[1].split('/')[0] if '@' in db_url else 'unknown'
    print(f"Connecting to database at: {host_part}")

    engine = create_async_engine(db_url)

    # Build the query with CASE statements for each platform
    query = """
        WITH platform_statuses AS (
            SELECT
                pc.id,
                pc.product_id,
                pc.platform_name,
                pc.external_id,
                pc.status,
                pc.listing_url,
                pc.created_at,
                CASE
                    WHEN pc.platform_name = 'reverb' THEN rl.reverb_state
                    WHEN pc.platform_name = 'ebay' THEN el.listing_status
                    WHEN pc.platform_name = 'vr' THEN vl.vr_state
                    WHEN pc.platform_name = 'shopify' THEN sl.status
                    ELSE NULL
                END as platform_table_status,
                CASE
                    WHEN pc.platform_name = 'reverb' AND rl.id IS NULL THEN 'Missing in reverb_listings'
                    WHEN pc.platform_name = 'ebay' AND el.id IS NULL THEN 'Missing in ebay_listings'
                    WHEN pc.platform_name = 'vr' AND vl.id IS NULL THEN 'Missing in vr_listings'
                    WHEN pc.platform_name = 'shopify' AND sl.id IS NULL THEN 'Missing in shopify_listings'
                    ELSE NULL
                END as missing_note
            FROM platform_common pc
            LEFT JOIN reverb_listings rl ON pc.platform_name = 'reverb' AND pc.id = rl.platform_id
            LEFT JOIN ebay_listings el ON pc.platform_name = 'ebay' AND pc.id = el.platform_id
            LEFT JOIN vr_listings vl ON pc.platform_name = 'vr' AND pc.id = vl.platform_id
            LEFT JOIN shopify_listings sl ON pc.platform_name = 'shopify' AND pc.id = sl.platform_id
    """

    # Add platform filter if provided
    if platform_filter:
        query += f"\n            WHERE pc.platform_name = :platform_filter"

    query += """
        )
        SELECT *
        FROM platform_statuses
    """

    # Filter for mismatches unless showing all
    if not show_all:
        if platform_filter:
            query += "\n        WHERE (status != platform_table_status OR platform_table_status IS NULL)"
        else:
            query += "\n        WHERE (status != platform_table_status OR platform_table_status IS NULL)"

    query += "\n        ORDER BY platform_name, created_at DESC"

    async with engine.connect() as conn:
        params = {"platform_filter": platform_filter} if platform_filter else {}
        result = await conn.execute(text(query), params)

        rows = result.fetchall()

        if not rows:
            print("\n✅ No mismatches found!")
            if not show_all:
                print("   (Use --show-all to see all records)")
            await engine.dispose()
            return

        # Group by platform for better display
        platforms = {}
        for row in rows:
            platform = row[2]  # platform_name
            if platform not in platforms:
                platforms[platform] = []
            platforms[platform].append(row)

        total_mismatches = 0
        total_missing = 0

        for platform, platform_rows in platforms.items():
            mismatches = [r for r in platform_rows if r[4] != r[7] and r[7] is not None]
            missing = [r for r in platform_rows if r[7] is None]

            total_mismatches += len(mismatches)
            total_missing += len(missing)

            print(f"\n{'='*80}")
            print(f"PLATFORM: {platform.upper()}")
            print(f"Total records: {len(platform_rows)}")
            if not show_all:
                print(f"Status mismatches: {len(mismatches)}")
                print(f"Missing in platform table: {len(missing)}")
            print(f"{'='*80}")

            for row in platform_rows:
                # Only show if mismatch/missing or show_all is True
                if show_all or row[4] != row[7] or row[7] is None:
                    print(f"\nID: {row[0]} | Product: {row[1]} | External ID: {row[3]}")
                    print(f"  Platform Common Status: {row[4]}")
                    print(f"  Platform Table Status:  {row[7] if row[7] is not None else 'MISSING'}")
                    if row[8]:  # missing_note
                        print(f"  ⚠️  {row[8]}")
                    print(f"  Listing URL: {row[5] or 'N/A'}")
                    print(f"  Created: {row[6]}")

                    # Highlight mismatches
                    if row[4] != row[7] and row[7] is not None:
                        print(f"  ❌ MISMATCH: {row[4]} != {row[7]}")

        # Summary
        print(f"\n{'='*80}")
        print("SUMMARY")
        print(f"{'='*80}")
        print(f"Total records checked: {len(rows)}")
        if not show_all:
            print(f"Total status mismatches: {total_mismatches}")
            print(f"Total missing in platform tables: {total_missing}")
            print(f"Total issues: {total_mismatches + total_missing}")

    await engine.dispose()

async def main():
    """Main function to parse arguments and run the check."""
    parser = argparse.ArgumentParser(
        description='Check for mismatches between platform_common and platform-specific tables'
    )
    parser.add_argument(
        '--platform',
        choices=['reverb', 'ebay', 'vr', 'shopify'],
        help='Filter by specific platform'
    )
    parser.add_argument(
        '--show-all',
        action='store_true',
        help='Show all records, not just mismatches'
    )

    args = parser.parse_args()

    await check_mismatches(
        platform_filter=args.platform,
        show_all=args.show_all
    )

if __name__ == '__main__':
    asyncio.run(main())