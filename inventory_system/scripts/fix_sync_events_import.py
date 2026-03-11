#!/usr/bin/env python3
"""
Fix import for sync_events table - handles JSONB properly
"""

import json
import asyncio
import os
import sys
from datetime import datetime

# Add the app directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


async def fix_sync_events(db_url):
    """Import sync_events table with proper JSONB handling"""

    # Ensure it's async
    if not db_url.startswith('postgresql+asyncpg://'):
        db_url = db_url.replace('postgresql://', 'postgresql+asyncpg://', 1)

    engine = create_async_engine(db_url)

    export_dir = 'data_export'
    json_file = os.path.join(export_dir, 'sync_events.json')

    if not os.path.exists(json_file):
        print(f"❌ File {json_file} does not exist!")
        return

    # Load data from JSON
    with open(json_file, 'r') as f:
        data = json.load(f)

    print(f"📦 Importing {len(data)} rows into sync_events...")

    async with engine.begin() as conn:
        # Clear existing data
        await conn.execute(text("DELETE FROM sync_events"))

        # Import data
        for i, row in enumerate(data):
            if i % 10 == 0:
                print(f"  Progress: {i}/{len(data)} rows...")

            # Convert UUID strings
            if 'sync_run_id' in row and isinstance(row['sync_run_id'], str):
                # Keep as string - PostgreSQL will convert
                pass

            # Convert datetime strings
            for dt_field in ['detected_at', 'processed_at']:
                if dt_field in row and row[dt_field] and isinstance(row[dt_field], str):
                    try:
                        row[dt_field] = datetime.fromisoformat(row[dt_field].replace('Z', '+00:00'))
                    except:
                        pass

            # Convert change_data to JSON string
            if 'change_data' in row and isinstance(row['change_data'], dict):
                row['change_data'] = json.dumps(row['change_data'])

            # Build INSERT statement
            columns = list(row.keys())
            placeholders = [f":{col}" for col in columns]

            insert_sql = f"""
                INSERT INTO sync_events ({', '.join(columns)})
                VALUES ({', '.join(placeholders)})
            """

            await conn.execute(text(insert_sql), row)

        # Reset sequence
        if data:
            max_id = max(row['id'] for row in data)
            await conn.execute(text(f"ALTER SEQUENCE sync_events_id_seq RESTART WITH {max_id + 1}"))
            print(f"  ↳ Reset sequence sync_events_id_seq to {max_id + 1}")

    await engine.dispose()
    print(f"✅ Successfully imported {len(data)} rows into sync_events")


if __name__ == "__main__":
    db_url = os.getenv('RAILWAY_DATABASE_URL')
    if not db_url:
        print("Usage: RAILWAY_DATABASE_URL='postgresql://...' python scripts/fix_sync_events_import.py")
        print("Or pass as argument: python scripts/fix_sync_events_import.py 'postgresql://...'")
        if len(sys.argv) > 1:
            db_url = sys.argv[1]
        else:
            sys.exit(1)

    asyncio.run(fix_sync_events(db_url))