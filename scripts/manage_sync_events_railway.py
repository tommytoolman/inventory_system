#!/usr/bin/env python3
"""
Script to manage sync_events on Railway database (different schema)

Usage:
    python scripts/manage_sync_events_railway.py list
    python scripts/manage_sync_events_railway.py delete --id 12345
"""

import asyncio
import argparse
import os
import sys
from datetime import datetime
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

async def get_engine():
    db_url = os.getenv('DATABASE_URL')
    if not db_url:
        print("ERROR: DATABASE_URL environment variable not set")
        sys.exit(1)

    # Convert to async URL
    if db_url.startswith('postgresql://'):
        db_url = db_url.replace('postgresql://', 'postgresql+asyncpg://', 1)

    # Show which database we're connecting to (masked)
    host_part = db_url.split('@')[1].split('/')[0] if '@' in db_url else 'unknown'
    print(f"Connecting to database at: {host_part}")

    return create_async_engine(db_url)

async def list_sync_events(platform_name=None, status=None, product_id=None, limit=50):
    """List sync events with optional filters"""
    engine = await get_engine()

    conditions = []
    params = {}

    if platform_name:
        conditions.append("platform_name = :platform_name")
        params["platform_name"] = platform_name
    if status:
        conditions.append("status = :status")
        params["status"] = status
    if product_id:
        conditions.append("product_id = :product_id")
        params["product_id"] = product_id

    where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""

    query = f"""
        SELECT id, product_id, platform_name, status, detected_at,
               external_id, change_type, notes
        FROM sync_events
        {where_clause}
        ORDER BY detected_at DESC
        LIMIT :limit
    """

    async with engine.connect() as conn:
        result = await conn.execute(text(query), {**params, "limit": limit})

        events = []
        for row in result:
            events.append({
                "id": row[0],
                "product_id": row[1],
                "platform_name": row[2],
                "status": row[3],
                "detected_at": row[4],
                "external_id": row[5],
                "change_type": row[6],
                "notes": row[7]
            })

        print(f"\nFound {len(events)} sync events")
        print("-" * 80)

        for event in events:
            print(f"ID: {event['id']} | Product: {event['product_id']} | "
                  f"Platform: {event['platform_name']} | Status: {event['status']} | "
                  f"Type: {event['change_type'] or 'N/A'}")
            print(f"External ID: {event['external_id'] or 'N/A'}")
            print(f"Detected: {event['detected_at']}")
            if event['notes']:
                print(f"Notes: {event['notes'][:100]}...")
            print("-" * 80)

    await engine.dispose()
    return events

async def delete_by_id(event_id):
    """Delete a specific sync event by ID"""
    engine = await get_engine()

    async with engine.connect() as conn:
        # First check if it exists
        check_result = await conn.execute(
            text("SELECT id, product_id, platform_name, status FROM sync_events WHERE id = :id"),
            {"id": event_id}
        )
        row = check_result.first()

        if not row:
            print(f"No sync event found with ID {event_id}")
            await engine.dispose()
            return

        print(f"Found event: ID={row[0]}, Product={row[1]}, Platform={row[2]}, Status={row[3]}")

        # Confirm deletion
        confirm = input("Delete this event? (y/N): ")
        if confirm.lower() != 'y':
            print("Deletion cancelled")
            await engine.dispose()
            return

        # Delete
        await conn.execute(
            text("DELETE FROM sync_events WHERE id = :id"),
            {"id": event_id}
        )
        await conn.commit()
        print(f"✓ Deleted sync event {event_id}")

    await engine.dispose()

async def delete_by_criteria(platform_name=None, status=None, product_id=None):
    """Delete sync events matching criteria"""
    engine = await get_engine()

    conditions = []
    params = {}

    if platform_name:
        conditions.append("platform_name = :platform_name")
        params["platform_name"] = platform_name
    if status:
        conditions.append("status = :status")
        params["status"] = status
    if product_id:
        conditions.append("product_id = :product_id")
        params["product_id"] = product_id

    if not conditions:
        print("ERROR: At least one filter criterion required for bulk delete")
        await engine.dispose()
        return

    where_clause = " WHERE " + " AND ".join(conditions)

    async with engine.connect() as conn:
        # Count how many will be deleted
        count_result = await conn.execute(
            text(f"SELECT COUNT(*) FROM sync_events {where_clause}"),
            params
        )
        count = count_result.scalar()

        if count == 0:
            print("No sync events found matching criteria")
            await engine.dispose()
            return

        print(f"\nFound {count} sync events matching criteria:")
        print(f"  Platform: {platform_name or 'any'}")
        print(f"  Status: {status or 'any'}")
        print(f"  Product ID: {product_id or 'any'}")

        # Safety check for large deletions
        if count > 20:
            print(f"\n⚠️  WARNING: This will delete {count} events!")

        confirm = input(f"\nDelete {count} events? (y/N): ")
        if confirm.lower() != 'y':
            print("Deletion cancelled")
            await engine.dispose()
            return

        # Delete
        result = await conn.execute(
            text(f"DELETE FROM sync_events {where_clause}"),
            params
        )
        await conn.commit()
        print(f"✓ Deleted {result.rowcount} sync events")

    await engine.dispose()

async def main():
    parser = argparse.ArgumentParser(description='Manage sync_events on Railway')
    subparsers = parser.add_subparsers(dest='command', help='Command to run')

    # List command
    list_parser = subparsers.add_parser('list', help='List sync events')
    list_parser.add_argument('--platform', dest='platform_name', help='Filter by platform name')
    list_parser.add_argument('--status', help='Filter by status')
    list_parser.add_argument('--product-id', type=int, help='Filter by product ID')
    list_parser.add_argument('--limit', type=int, default=50, help='Limit results (default: 50)')

    # Delete command
    delete_parser = subparsers.add_parser('delete', help='Delete sync events')
    delete_parser.add_argument('--id', type=int, help='Delete specific sync event by ID')
    delete_parser.add_argument('--platform', dest='platform_name', help='Delete by platform name')
    delete_parser.add_argument('--status', help='Delete by status')
    delete_parser.add_argument('--product-id', type=int, help='Delete by product ID')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    if args.command == 'list':
        await list_sync_events(
            platform_name=args.platform_name,
            status=args.status,
            product_id=args.product_id,
            limit=args.limit
        )

    elif args.command == 'delete':
        if args.id:
            await delete_by_id(args.id)
        else:
            await delete_by_criteria(
                platform_name=args.platform_name,
                status=args.status,
                product_id=args.product_id
            )

if __name__ == '__main__':
    asyncio.run(main())