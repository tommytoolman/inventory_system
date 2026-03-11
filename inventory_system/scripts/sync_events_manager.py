#!/usr/bin/env python3
"""
Comprehensive sync events manager for querying, updating, and managing sync events.

Usage examples:
    # Query events
    python scripts/sync_events_manager.py query --platform reverb --status pending
    python scripts/sync_events_manager.py query --change-type new_listing --days 7

    # Update event status
    python scripts/sync_events_manager.py update --id 123 --status pending
    python scripts/sync_events_manager.py update --id 123 --status processed --notes "Manually processed"

    # Bulk operations
    python scripts/sync_events_manager.py delete-all-pending
    python scripts/sync_events_manager.py delete-all-pending --dry-run

    # Reset processed to pending
    python scripts/sync_events_manager.py reset --platform reverb --from-status processed --to-status pending

    # Statistics
    python scripts/sync_events_manager.py stats
    python scripts/sync_events_manager.py stats --platform ebay
"""

import asyncio
import argparse
import sys
from datetime import datetime, timedelta
from typing import Optional, List, Dict
from sqlalchemy import text, select, update, delete, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from tabulate import tabulate
import json

from app.database import async_session
from app.models.sync_event import SyncEvent

class SyncEventsManager:
    def __init__(self):
        self.session = None

    async def query_events(
        self,
        platform: Optional[str] = None,
        status: Optional[str] = None,
        change_type: Optional[str] = None,
        days: Optional[int] = None,
        limit: int = 50
    ) -> List[Dict]:
        """Query sync events with filters"""
        async with async_session() as session:
            query = select(SyncEvent)

            # Build filters
            filters = []
            if platform:
                filters.append(SyncEvent.platform_name == platform)
            if status:
                filters.append(SyncEvent.status == status)
            if change_type:
                filters.append(SyncEvent.change_type == change_type)
            if days:
                cutoff_date = datetime.utcnow() - timedelta(days=days)
                filters.append(SyncEvent.detected_at >= cutoff_date)

            if filters:
                query = query.where(and_(*filters))

            # Order by newest first and limit
            query = query.order_by(SyncEvent.detected_at.desc()).limit(limit)

            result = await session.execute(query)
            events = result.scalars().all()

            return [self._event_to_dict(event) for event in events]

    async def update_event_status(
        self,
        event_id: int,
        new_status: str,
        notes: Optional[str] = None,
        dry_run: bool = False
    ) -> bool:
        """Update a single event's status"""
        async with async_session() as session:
            # First check if event exists
            result = await session.execute(
                select(SyncEvent).where(SyncEvent.id == event_id)
            )
            event = result.scalar_one_or_none()

            if not event:
                print(f"❌ Event {event_id} not found")
                return False

            print(f"\nEvent {event_id}:")
            print(f"  Current status: {event.status}")
            print(f"  New status: {new_status}")
            print(f"  Platform: {event.platform_name}")
            print(f"  Change type: {event.change_type}")
            print(f"  Product ID: {event.product_id}")

            if dry_run:
                print("\n[DRY RUN] Would update this event")
                return True

            # Update the event
            event.status = new_status
            if notes:
                event.notes = notes

            # Update processed_at if changing to processed
            if new_status == 'processed':
                event.processed_at = datetime.utcnow()
            elif new_status == 'pending':
                # Clear processed_at if resetting to pending
                event.processed_at = None

            await session.commit()
            print(f"✅ Updated event {event_id} to status: {new_status}")
            return True

    async def delete_all_pending(self, dry_run: bool = False) -> int:
        """Delete ALL pending sync events"""
        async with async_session() as session:
            # Count pending events first
            count_result = await session.execute(
                select(func.count()).where(SyncEvent.status == 'pending')
            )
            pending_count = count_result.scalar()

            if pending_count == 0:
                print("No pending sync events found")
                return 0

            if dry_run:
                # Show sample of what would be deleted
                sample_result = await session.execute(
                    select(SyncEvent)
                    .where(SyncEvent.status == 'pending')
                    .limit(10)
                )
                sample_events = sample_result.scalars().all()

                print(f"\n[DRY RUN] Would delete {pending_count} pending events")
                print("\nSample of events to be deleted:")
                for event in sample_events:
                    print(f"  - ID: {event.id}, Platform: {event.platform_name}, "
                          f"Type: {event.change_type}, Product: {event.product_id}")

                if pending_count > 10:
                    print(f"  ... and {pending_count - 10} more")

                return pending_count

            # Confirm deletion
            response = input(f"\n⚠️  Delete {pending_count} pending sync events? (yes/no): ")
            if response.lower() != 'yes':
                print("Cancelled")
                return 0

            # Delete pending events
            result = await session.execute(
                delete(SyncEvent).where(SyncEvent.status == 'pending')
            )
            await session.commit()

            print(f"✅ Deleted {result.rowcount} pending sync events")
            return result.rowcount

    async def reset_events(
        self,
        from_status: str,
        to_status: str,
        platform: Optional[str] = None,
        dry_run: bool = False
    ) -> int:
        """Reset events from one status to another"""
        async with async_session() as session:
            # Build query
            query = select(SyncEvent).where(SyncEvent.status == from_status)
            if platform:
                query = query.where(SyncEvent.platform_name == platform)

            # Count affected events
            count_query = select(func.count()).where(SyncEvent.status == from_status)
            if platform:
                count_query = count_query.where(SyncEvent.platform_name == platform)

            count_result = await session.execute(count_query)
            affected_count = count_result.scalar()

            if affected_count == 0:
                print(f"No events found with status '{from_status}'" +
                      (f" for platform '{platform}'" if platform else ""))
                return 0

            if dry_run:
                # Show sample
                sample_result = await session.execute(query.limit(10))
                sample_events = sample_result.scalars().all()

                print(f"\n[DRY RUN] Would reset {affected_count} events from '{from_status}' to '{to_status}'")
                if platform:
                    print(f"Platform: {platform}")

                print("\nSample of events to be reset:")
                for event in sample_events:
                    print(f"  - ID: {event.id}, Type: {event.change_type}, "
                          f"Product: {event.product_id}")

                if affected_count > 10:
                    print(f"  ... and {affected_count - 10} more")

                return affected_count

            # Confirm
            response = input(f"\n⚠️  Reset {affected_count} events from '{from_status}' to '{to_status}'? (yes/no): ")
            if response.lower() != 'yes':
                print("Cancelled")
                return 0

            # Update events
            update_query = (
                update(SyncEvent)
                .where(SyncEvent.status == from_status)
                .values(
                    status=to_status,
                    processed_at=None if to_status == 'pending' else SyncEvent.processed_at
                )
            )
            if platform:
                update_query = update_query.where(SyncEvent.platform_name == platform)

            result = await session.execute(update_query)
            await session.commit()

            print(f"✅ Reset {result.rowcount} events from '{from_status}' to '{to_status}'")
            return result.rowcount

    async def show_stats(self, platform: Optional[str] = None):
        """Show statistics about sync events"""
        async with async_session() as session:
            # Base query
            base_filter = []
            if platform:
                base_filter.append(SyncEvent.platform_name == platform)

            # Total events
            total_query = select(func.count())
            if base_filter:
                total_query = total_query.where(*base_filter)
            total_result = await session.execute(total_query.select_from(SyncEvent))
            total_count = total_result.scalar()

            # By status
            status_query = (
                select(
                    SyncEvent.status,
                    func.count().label('count')
                )
                .group_by(SyncEvent.status)
            )
            if base_filter:
                status_query = status_query.where(*base_filter)

            status_result = await session.execute(status_query)
            status_counts = {row.status: row.count for row in status_result}

            # By platform
            if not platform:
                platform_query = (
                    select(
                        SyncEvent.platform_name,
                        func.count().label('count')
                    )
                    .group_by(SyncEvent.platform_name)
                )
                platform_result = await session.execute(platform_query)
                platform_counts = {row.platform_name: row.count for row in platform_result}

            # By change type
            type_query = (
                select(
                    SyncEvent.change_type,
                    func.count().label('count')
                )
                .group_by(SyncEvent.change_type)
            )
            if base_filter:
                type_query = type_query.where(*base_filter)

            type_result = await session.execute(type_query)
            type_counts = {row.change_type: row.count for row in type_result}

            # Display results
            print("\n=== Sync Events Statistics ===")
            if platform:
                print(f"Platform: {platform}")
            print(f"Total events: {total_count}")

            print("\nBy Status:")
            for status, count in sorted(status_counts.items()):
                print(f"  {status}: {count}")

            if not platform:
                print("\nBy Platform:")
                for plat, count in sorted(platform_counts.items()):
                    print(f"  {plat}: {count}")

            print("\nBy Change Type:")
            for change_type, count in sorted(type_counts.items()):
                print(f"  {change_type}: {count}")

    def _event_to_dict(self, event: SyncEvent) -> Dict:
        """Convert event to dictionary for display"""
        return {
            'id': event.id,
            'platform': event.platform_name,
            'status': event.status,
            'change_type': event.change_type,
            'product_id': event.product_id,
            'external_id': event.external_id,
            'detected_at': event.detected_at.strftime('%Y-%m-%d %H:%M:%S'),
            'notes': event.notes[:50] + '...' if event.notes and len(event.notes) > 50 else event.notes
        }

    def display_events(self, events: List[Dict]):
        """Display events in a nice table format"""
        if not events:
            print("No events found")
            return

        headers = ['ID', 'Platform', 'Status', 'Type', 'Product', 'External ID', 'Detected', 'Notes']
        rows = [
            [
                e['id'],
                e['platform'],
                e['status'],
                e['change_type'],
                e['product_id'] or '-',
                e['external_id'],
                e['detected_at'],
                e['notes'] or '-'
            ]
            for e in events
        ]

        print(f"\nFound {len(events)} events:")
        print(tabulate(rows, headers=headers, tablefmt='grid'))

async def main():
    parser = argparse.ArgumentParser(description='Manage sync events')
    subparsers = parser.add_subparsers(dest='command', help='Command to run')

    # Query command
    query_parser = subparsers.add_parser('query', help='Query sync events')
    query_parser.add_argument('--platform', choices=['reverb', 'ebay', 'shopify', 'vr'])
    query_parser.add_argument('--status', choices=['pending', 'processed', 'error', 'partial'])
    query_parser.add_argument('--change-type', choices=['new_listing', 'price_change', 'status_change', 'removed_listing'])
    query_parser.add_argument('--days', type=int, help='Events from last N days')
    query_parser.add_argument('--limit', type=int, default=50, help='Max results (default: 50)')

    # Update command
    update_parser = subparsers.add_parser('update', help='Update event status')
    update_parser.add_argument('--id', type=int, required=True, help='Event ID')
    update_parser.add_argument('--status', required=True, choices=['pending', 'processed', 'error', 'partial'])
    update_parser.add_argument('--notes', help='Add notes to the event')
    update_parser.add_argument('--dry-run', action='store_true')

    # Delete all pending command
    delete_parser = subparsers.add_parser('delete-all-pending', help='Delete ALL pending events')
    delete_parser.add_argument('--dry-run', action='store_true')

    # Reset command
    reset_parser = subparsers.add_parser('reset', help='Reset events from one status to another')
    reset_parser.add_argument('--from-status', required=True, choices=['processed', 'error', 'partial'])
    reset_parser.add_argument('--to-status', required=True, choices=['pending', 'processed', 'error'])
    reset_parser.add_argument('--platform', choices=['reverb', 'ebay', 'shopify', 'vr'])
    reset_parser.add_argument('--dry-run', action='store_true')

    # Stats command
    stats_parser = subparsers.add_parser('stats', help='Show statistics')
    stats_parser.add_argument('--platform', choices=['reverb', 'ebay', 'shopify', 'vr'])

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    manager = SyncEventsManager()

    if args.command == 'query':
        events = await manager.query_events(
            platform=args.platform,
            status=args.status,
            change_type=args.change_type,
            days=args.days,
            limit=args.limit
        )
        manager.display_events(events)

    elif args.command == 'update':
        await manager.update_event_status(
            event_id=args.id,
            new_status=args.status,
            notes=args.notes,
            dry_run=args.dry_run
        )

    elif args.command == 'delete-all-pending':
        await manager.delete_all_pending(dry_run=args.dry_run)

    elif args.command == 'reset':
        await manager.reset_events(
            from_status=args.from_status,
            to_status=args.to_status,
            platform=args.platform,
            dry_run=args.dry_run
        )

    elif args.command == 'stats':
        await manager.show_stats(platform=args.platform)

if __name__ == "__main__":
    asyncio.run(main())