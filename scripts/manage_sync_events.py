#!/usr/bin/env python3
"""
Script to manage sync_events on Railway database

Usage:
    # For Railway (uses sync_events table)
    python scripts/manage_sync_events.py list --railway --platform ebay --status error
    python scripts/manage_sync_events.py delete --railway --id 12345

    # For local (uses sync_event table)
    python scripts/manage_sync_events.py list --platform ebay --status error
    python scripts/manage_sync_events.py delete --id 12345
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

# Global variable for table name
TABLE_NAME = "sync_events"  # default to plural (Railway uses this)

async def get_engine(use_railway=False):
    global TABLE_NAME

    if use_railway:
        # Try to get Railway-specific URL
        db_url = os.getenv('RAILWAY_DATABASE_URL') or os.getenv('DATABASE_URL')
        TABLE_NAME = "sync_events"  # Railway uses plural
    else:
        db_url = os.getenv('DATABASE_URL')
        # Don't override TABLE_NAME here - it's already set to sync_events by default

    if not db_url:
        print("ERROR: DATABASE_URL environment variable not set")
        print("Export your Railway DATABASE_URL first:")
        print("export DATABASE_URL='postgresql://...'")
        print("Or set RAILWAY_DATABASE_URL in your .env file")
        sys.exit(1)

    # Convert to async URL
    if db_url.startswith('postgresql://'):
        db_url = db_url.replace('postgresql://', 'postgresql+asyncpg://', 1)

    # Show which database we're connecting to (masked)
    host_part = db_url.split('@')[1].split('/')[0] if '@' in db_url else 'unknown'
    print(f"Connecting to database at: {host_part}")

    return create_async_engine(db_url)

async def list_sync_events(platform=None, status=None, product_id=None, limit=50, use_railway=False):
    """List sync events with optional filters"""
    engine = await get_engine(use_railway)

    conditions = []
    params = {}

    if platform:
        conditions.append("platform = :platform")
        params["platform"] = platform
    if status:
        conditions.append("status = :status")
        params["status"] = status
    if product_id:
        conditions.append("product_id = :product_id")
        params["product_id"] = product_id

    where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""

    query = f"""
        SELECT id, product_id, platform, status, created_at,
               error_details, sync_type
        FROM {TABLE_NAME}
        {where_clause}
        ORDER BY created_at DESC
        LIMIT :limit
    """

    async with engine.connect() as conn:
        result = await conn.execute(text(query), {**params, "limit": limit})

        events = []
        for row in result:
            events.append({
                "id": row[0],
                "product_id": row[1],
                "platform": row[2],
                "status": row[3],
                "created_at": row[4],
                "error_details": row[5],
                "sync_type": row[6]
            })

        print(f"\nFound {len(events)} sync events")
        print("-" * 80)

        for event in events:
            print(f"ID: {event['id']} | Product: {event['product_id']} | "
                  f"Platform: {event['platform']} | Status: {event['status']} | "
                  f"Type: {event['sync_type'] or 'N/A'}")
            print(f"Created: {event['created_at']}")
            if event['error_details']:
                print(f"Error: {event['error_details'][:100]}...")
            print("-" * 80)

    await engine.dispose()
    return events

async def delete_by_id(event_id, use_railway=False):
    """Delete a specific sync event by ID"""
    engine = await get_engine(use_railway)

    async with engine.connect() as conn:
        # First check if it exists
        check_result = await conn.execute(
            text(f"SELECT id, product_id, platform, status FROM {TABLE_NAME} WHERE id = :id"),
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
            text(f"DELETE FROM {TABLE_NAME} WHERE id = :id"),
            {"id": event_id}
        )
        await conn.commit()
        print(f"✓ Deleted sync event {event_id}")

    await engine.dispose()

async def delete_by_criteria(platform=None, status=None, product_id=None, use_railway=False):
    """Delete sync events matching criteria"""
    engine = await get_engine(use_railway)

    conditions = []
    params = {}

    if platform:
        conditions.append("platform = :platform")
        params["platform"] = platform
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
            text(f"SELECT COUNT(*) FROM {TABLE_NAME} {where_clause}"),
            params
        )
        count = count_result.scalar()

        if count == 0:
            print("No sync events found matching criteria")
            await engine.dispose()
            return

        print(f"\nFound {count} sync events matching criteria:")
        print(f"  Platform: {platform or 'any'}")
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
            text(f"DELETE FROM {TABLE_NAME} {where_clause}"),
            params
        )
        await conn.commit()
        print(f"✓ Deleted {result.rowcount} sync events")

    await engine.dispose()

async def main():
    parser = argparse.ArgumentParser(description='Manage sync_events on Railway or local database')
    parser.add_argument('--railway', action='store_true', help='Use Railway database (sync_events table) instead of local (sync_event table)')
    subparsers = parser.add_subparsers(dest='command', help='Command to run')

    # List command
    list_parser = subparsers.add_parser('list', help='List sync events')
    list_parser.add_argument('--platform', help='Filter by platform (ebay, reverb, shopify, vr)')
    list_parser.add_argument('--status', help='Filter by status (pending, completed, error, partial)')
    list_parser.add_argument('--product-id', type=int, help='Filter by product ID')
    list_parser.add_argument('--limit', type=int, default=50, help='Limit results (default: 50)')

    # Delete command
    delete_parser = subparsers.add_parser('delete', help='Delete sync events')
    delete_parser.add_argument('--id', type=int, help='Delete specific sync event by ID')
    delete_parser.add_argument('--platform', help='Delete by platform')
    delete_parser.add_argument('--status', help='Delete by status')
    delete_parser.add_argument('--product-id', type=int, help='Delete by product ID')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    if args.command == 'list':
        await list_sync_events(
            platform=args.platform,
            status=args.status,
            product_id=args.product_id,
            limit=args.limit,
            use_railway=args.railway
        )

    elif args.command == 'delete':
        if args.id:
            await delete_by_id(args.id, use_railway=args.railway)
        else:
            await delete_by_criteria(
                platform=args.platform,
                status=args.status,
                product_id=args.product_id,
                use_railway=args.railway
            )

if __name__ == '__main__':
    asyncio.run(main())