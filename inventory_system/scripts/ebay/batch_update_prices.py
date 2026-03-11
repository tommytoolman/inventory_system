#!/usr/bin/env python3
"""
Batch update eBay listing prices from enriched xlsx.

This script uses the ReviseFixedPriceItem API which ONLY updates the price field.
It does NOT touch: title, description, images, item specifics, shipping, etc.

IMPORTANT: The script marks items as complete in the SOURCE xlsx file after each
successful update. This allows incremental batch updates - run with --limit 10,
then run again to process the next batch.

Columns added to xlsx:
    - update_status: 'success', 'failed', or empty (pending)
    - updated_at: timestamp when the update was applied

Usage:
    # Dry run (show what would be updated + progress stats)
    python scripts/ebay/batch_update_prices.py --dry-run

    # Update first 10 items only (marks them complete, next run skips them)
    python scripts/ebay/batch_update_prices.py --limit 10

    # Continue updating next batch (previous successes are skipped)
    python scripts/ebay/batch_update_prices.py --limit 10

    # Retry only items that previously failed
    python scripts/ebay/batch_update_prices.py --retry-failed

    # Full run
    python scripts/ebay/batch_update_prices.py

    # Specify different input file
    python scripts/ebay/batch_update_prices.py --input scripts/ebay/output/custom_prices.xlsx
"""

import argparse
import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
load_dotenv()

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.services.ebay.trading import EbayTradingLegacyAPI


def save_progress(df: pd.DataFrame, file_path: str):
    """Save the dataframe back to xlsx, preserving progress."""
    df.to_excel(file_path, index=False)


def update_item_status(df: pd.DataFrame, item_id: str, status: str, file_path: str):
    """Update status for a specific item and save to file."""
    # Find the row by ItemID and update status
    mask = df['ItemID'].astype(str) == str(item_id)
    df.loc[mask, 'update_status'] = status
    df.loc[mask, 'updated_at'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Save immediately
    save_progress(df, file_path)


async def batch_update_prices(
    input_file: str,
    dry_run: bool = True,
    limit: int = None,
    delay: float = 1.0,
    retry_failed: bool = False,
):
    """
    Batch update eBay prices from xlsx file.

    Uses price_override if set, otherwise calculated_new_price.
    Only updates items where the new price differs from current price.
    """

    # Read the xlsx
    print(f"📖 Reading {input_file}...")
    df = pd.read_excel(input_file)
    print(f"   Loaded {len(df)} listings")

    # Ensure status columns exist
    if 'update_status' not in df.columns:
        df['update_status'] = ''
    if 'updated_at' not in df.columns:
        df['updated_at'] = ''

    # Count already processed
    already_done = df[df['update_status'] == 'success']
    if len(already_done) > 0:
        print(f"   {len(already_done)} already completed (will be skipped)")

    # Determine which price to use for each row
    # Priority: price_override > calculated_new_price
    df['target_price'] = df.apply(
        lambda row: row['price_override'] if pd.notna(row.get('price_override')) and row['price_override'] > 0
        else row['calculated_new_price'],
        axis=1
    )

    # Filter to only items that need updating:
    # - Price changed from current
    # - Not already successfully updated
    if retry_failed:
        # Only retry previously failed items
        df['needs_update'] = (
            df['target_price'].notna() &
            (df['target_price'] > 0) &
            (df['update_status'] == 'failed')
        )
        print(f"   RETRY MODE: Only processing previously failed items")
    else:
        df['needs_update'] = (
            df['target_price'].notna() &
            (df['target_price'] > 0) &
            (df['target_price'] != df['current_ebay_price']) &
            (df['update_status'] != 'success')  # Skip already completed
        )

    to_update = df[df['needs_update']].copy()
    print(f"   {len(to_update)} items need price updates")

    if len(to_update) == 0:
        print("✅ No items need updating!")
        return

    # Apply limit if specified
    if limit:
        to_update = to_update.head(limit)
        print(f"   Limited to first {limit} items")

    # Show summary
    print(f"\n📊 Price Update Summary:")
    print(f"   Items to update: {len(to_update)}")
    print(f"   Current total: £{to_update['current_ebay_price'].sum():,.0f}")
    print(f"   New total: £{to_update['target_price'].sum():,.0f}")
    print(f"   Total increase: £{(to_update['target_price'] - to_update['current_ebay_price']).sum():,.0f}")

    if dry_run:
        # Show overall progress
        total_success = len(df[df['update_status'] == 'success'])
        total_failed = len(df[df['update_status'] == 'failed'])
        total_pending = len(to_update)

        print(f"\n📊 CURRENT PROGRESS")
        print(f"   Total items: {len(df)}")
        print(f"   ✅ Completed: {total_success}")
        print(f"   ❌ Failed: {total_failed}")
        print(f"   ⏳ Pending: {total_pending}")

        print(f"\n🔍 DRY RUN - Would update these {len(to_update)} items:")
        for idx, row in to_update.head(20).iterrows():
            title = row['Title'][:40] if pd.notna(row.get('Title')) else 'N/A'
            status_note = " (retry)" if row.get('update_status') == 'failed' else ""
            print(f"   {row['ItemID']}: £{row['current_ebay_price']:,.0f} → £{row['target_price']:,.0f} ({title}...){status_note}")
        if len(to_update) > 20:
            print(f"   ... and {len(to_update) - 20} more")
        print("\n⚠️  Run without --dry-run to actually update eBay listings")
        return

    # Confirm before proceeding
    confirm = input(f"\n⚠️  About to update {len(to_update)} eBay listings. Continue? (y/N): ")
    if confirm.lower() != 'y':
        print("❌ Cancelled")
        return

    # Initialize eBay API
    api = EbayTradingLegacyAPI(sandbox=False)

    # Connect to DB for local updates
    database_url = os.environ.get("DATABASE_URL")
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    engine = create_async_engine(database_url)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # Results tracking
    results = {
        "success": [],
        "failed": [],
        "skipped": [],
    }

    # Process each item
    print(f"\n🔄 Starting price updates...")

    for idx, row in to_update.iterrows():
        item_id = str(int(row['ItemID']))
        old_price = row['current_ebay_price']
        new_price = row['target_price']
        title = row['Title'][:40] if pd.notna(row.get('Title')) else 'N/A'

        print(f"\n[{len(results['success']) + len(results['failed']) + 1}/{len(to_update)}] {item_id}")
        print(f"   {title}...")
        print(f"   £{old_price:,.0f} → £{new_price:,.0f}")

        try:
            # Call eBay API to revise price
            response = await api.revise_listing_price(item_id, float(new_price))

            # Check response
            ack = response.get('Ack', '')

            if ack in ['Success', 'Warning']:
                print(f"   ✅ eBay updated successfully")

                # Update local database
                async with async_session() as session:
                    await session.execute(
                        text("""
                            UPDATE ebay_listings
                            SET price = :new_price, updated_at = NOW()
                            WHERE ebay_item_id = :item_id
                        """),
                        {"new_price": float(new_price), "item_id": item_id}
                    )
                    await session.commit()
                print(f"   ✅ Local DB updated")

                # Mark as complete in source xlsx
                update_item_status(df, item_id, 'success', input_file)
                print(f"   ✅ Marked complete in xlsx")

                results["success"].append({
                    "item_id": item_id,
                    "old_price": old_price,
                    "new_price": new_price,
                    "title": title,
                })
            else:
                # Handle errors
                errors = response.get('Errors', [])
                if not isinstance(errors, list):
                    errors = [errors]
                error_msg = "; ".join([e.get('LongMessage', 'Unknown') for e in errors])
                print(f"   ❌ eBay error: {error_msg}")

                # Mark as failed in source xlsx
                update_item_status(df, item_id, 'failed', input_file)

                results["failed"].append({
                    "item_id": item_id,
                    "old_price": old_price,
                    "new_price": new_price,
                    "title": title,
                    "error": error_msg,
                })

        except Exception as e:
            print(f"   ❌ Exception: {str(e)}")

            # Mark as failed in source xlsx
            update_item_status(df, item_id, 'failed', input_file)

            results["failed"].append({
                "item_id": item_id,
                "old_price": old_price,
                "new_price": new_price,
                "title": title,
                "error": str(e),
            })

        # Delay between requests
        await asyncio.sleep(delay)

    await engine.dispose()

    # Final summary
    print(f"\n" + "=" * 60)
    print("📊 FINAL RESULTS (this run)")
    print("=" * 60)
    print(f"✅ Successful: {len(results['success'])}")
    print(f"❌ Failed: {len(results['failed'])}")

    # Re-read the file to get overall stats
    df_final = pd.read_excel(input_file)
    total_success = len(df_final[df_final['update_status'] == 'success'])
    total_failed = len(df_final[df_final['update_status'] == 'failed'])
    total_pending = len(df_final) - total_success - total_failed

    print(f"\n📊 OVERALL PROGRESS")
    print(f"   Total items: {len(df_final)}")
    print(f"   ✅ Completed: {total_success}")
    print(f"   ❌ Failed: {total_failed}")
    print(f"   ⏳ Pending: {total_pending}")

    if results['failed']:
        print(f"\n❌ Failed items (this run):")
        for item in results['failed']:
            print(f"   {item['item_id']}: {item['error']}")

    # Save results to file
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    results_file = f"scripts/ebay/output/price_update_results_{timestamp}.xlsx"

    results_df = pd.DataFrame(results['success'] + results['failed'])
    if not results_df.empty:
        results_df['status'] = ['success'] * len(results['success']) + ['failed'] * len(results['failed'])
        results_df.to_excel(results_file, index=False)
        print(f"\n📁 Results saved to: {results_file}")


async def main():
    parser = argparse.ArgumentParser(description='Batch update eBay listing prices')
    parser.add_argument('--input', '-i',
                        default='scripts/ebay/output/ebay_pricing_enriched_20251216_140043.xlsx',
                        help='Input xlsx file with pricing data')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would be updated without making changes')
    parser.add_argument('--limit', '-n', type=int,
                        help='Limit to first N items')
    parser.add_argument('--delay', '-d', type=float, default=1.0,
                        help='Delay between API calls in seconds (default: 1.0)')
    parser.add_argument('--retry-failed', action='store_true',
                        help='Only retry items that previously failed')

    args = parser.parse_args()

    await batch_update_prices(
        input_file=args.input,
        dry_run=args.dry_run,
        limit=args.limit,
        delay=args.delay,
        retry_failed=args.retry_failed,
    )


if __name__ == "__main__":
    asyncio.run(main())
