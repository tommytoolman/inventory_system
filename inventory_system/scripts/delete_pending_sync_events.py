#!/usr/bin/env python3
"""
Delete ONLY pending sync events from the database.
This will not touch processed, failed, or any other status events.

Usage:
    python scripts/delete_pending_sync_events.py
    python scripts/delete_pending_sync_events.py --dry-run
"""

import asyncio
import argparse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, func
from app.database import async_session
from app.models.sync_event import SyncEvent

async def delete_pending_events(dry_run: bool = False):
    """Delete only pending sync events"""
    async with async_session() as session:
        # First, count pending events
        count_stmt = select(func.count()).where(SyncEvent.status == 'pending')
        result = await session.execute(count_stmt)
        pending_count = result.scalar()

        print(f"Found {pending_count} pending sync events")

        if pending_count == 0:
            print("No pending sync events to delete")
            return

        if dry_run:
            # Show a sample of what would be deleted
            sample_stmt = select(SyncEvent).where(
                SyncEvent.status == 'pending'
            ).limit(10)
            sample_result = await session.execute(sample_stmt)
            sample_events = sample_result.scalars().all()

            print("\nSample of events that would be deleted:")
            for event in sample_events:
                print(f"  - ID: {event.id}, Platform: {event.platform_name}, "
                      f"Type: {event.change_type}, Product: {event.product_id}")

            if pending_count > 10:
                print(f"  ... and {pending_count - 10} more")

            print(f"\n[DRY RUN] Would delete {pending_count} pending sync events")
        else:
            # Confirm before deleting
            response = input(f"\nAre you sure you want to delete {pending_count} pending sync events? (yes/no): ")
            if response.lower() != 'yes':
                print("Cancelled")
                return

            # Delete pending events
            delete_stmt = delete(SyncEvent).where(SyncEvent.status == 'pending')
            result = await session.execute(delete_stmt)
            await session.commit()

            print(f"✅ Successfully deleted {result.rowcount} pending sync events")

async def main():
    parser = argparse.ArgumentParser(description='Delete pending sync events')
    parser.add_argument('--dry-run', action='store_true',
                       help='Show what would be deleted without actually deleting')

    args = parser.parse_args()

    await delete_pending_events(dry_run=args.dry_run)

if __name__ == "__main__":
    asyncio.run(main())