#!/usr/bin/env python3
"""
Sync stocked item orders from Reverb.

Imports orders from Reverb API and upserts to reverb_orders table.
Order processing is handled by OrderSaleProcessor in the scheduler.

Usage:
    python scripts/reverb/sync_stocked_orders.py [--dry-run]
"""

import argparse
import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent.parent))

from sqlalchemy import select
from app.database import async_session
from app.services.reverb.client import ReverbClient
from app.models.reverb_order import ReverbOrder
from app.core.config import get_settings

# Import the SAME upsert function used by the scheduler
from scripts.reverb.get_reverb_sold_orders import upsert_orders


async def fetch_orders_smart(client, db, per_page=50, max_pages=10):
    """
    Fetch orders from Reverb API, stopping early if we've caught up.

    Strategy:
    - Fetch page 1 first
    - Check how many orders are NEW (not in DB)
    - If all 50 are new → we might have missed some, fetch more pages
    - If some are existing → we've overlapped with previous sync, done

    Returns list of orders to upsert.
    """
    print(f"    Fetching page 1...")

    # Fetch just page 1 first
    page1_orders = await client.get_all_sold_orders(per_page=per_page, max_pages=1)

    if not page1_orders:
        print(f"    No orders returned")
        return []

    # Check how many are new (not in DB)
    # Use 'uuid' field - same as get_reverb_sold_orders.py upsert_orders()
    order_uuids = [o.get('uuid') or o.get('order_number') for o in page1_orders]
    order_uuids = [str(u).strip() for u in order_uuids if u]

    existing_stmt = select(ReverbOrder.order_uuid).where(ReverbOrder.order_uuid.in_(order_uuids))
    existing_result = await db.execute(existing_stmt)
    existing_uuids = {row[0] for row in existing_result.fetchall()}

    new_count = len([u for u in order_uuids if u not in existing_uuids])
    existing_count = len(order_uuids) - new_count

    print(f"    Page 1: {len(page1_orders)} orders ({new_count} new, {existing_count} existing)")

    # If we found existing orders, we've caught up - just return page 1
    if existing_count > 0:
        print(f"    Found existing orders - caught up with 1 page")
        return page1_orders

    # All orders on page 1 are new - we might have missed some, fetch more
    print(f"    All {new_count} orders are new - fetching more pages to catch up...")
    all_orders = await client.get_all_sold_orders(per_page=per_page, max_pages=max_pages)
    print(f"    Fetched {len(all_orders)} total orders across up to {max_pages} pages")

    return all_orders


async def main():
    parser = argparse.ArgumentParser(description="Sync stocked item orders from Reverb")
    parser.add_argument("--dry-run", action="store_true", help="Just show what would be created")

    args = parser.parse_args()

    print("=" * 60)
    print("REVERB STOCKED ORDERS SYNC")
    print("=" * 60)

    settings = get_settings()
    sync_run_id = uuid.uuid4()

    async with async_session() as db:
        # Step 1: Import orders from Reverb - smart fetch that stops when caught up
        print("\n[1/2] Importing orders from Reverb...")
        if not args.dry_run:
            client = ReverbClient(api_key=settings.REVERB_API_KEY)

            # Smart fetch - stops when we find existing orders
            orders = await fetch_orders_smart(client, db, per_page=50, max_pages=10)

            if orders:
                summary = await upsert_orders(db, orders)
                print(f"  Total fetched: {len(orders)}")
                print(f"  Inserted: {summary.get('inserted', 0)}")
                print(f"  Updated: {summary.get('updated', 0)}")
                print(f"  Errors: {summary.get('errors', 0)}")
                await db.commit()
            else:
                print("  No orders returned from API")
        else:
            print("  [DRY RUN] Would import orders from Reverb API")

    print("\n" + "=" * 60)
    print("DONE")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
