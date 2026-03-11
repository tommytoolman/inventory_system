#!/usr/bin/env python3
"""
Import a single table from JSON files to Railway database
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


async def import_single_table(table_name, db_url):
    """Import a single table to Railway database"""

    # Ensure it's async
    if not db_url.startswith('postgresql+asyncpg://'):
        db_url = db_url.replace('postgresql://', 'postgresql+asyncpg://', 1)

    engine = create_async_engine(db_url)

    export_dir = 'data_export'
    json_file = os.path.join(export_dir, f"{table_name}.json")

    if not os.path.exists(json_file):
        print(f"❌ File {json_file} does not exist!")
        return

    # Load data from JSON
    with open(json_file, 'r') as f:
        data = json.load(f)

    if not data:
        print(f"⚠️  No data to import for {table_name}")
        return

    print(f"📦 Importing {len(data)} rows into {table_name}...")

    async with engine.begin() as conn:
        # Get table schema to identify JSONB columns
        schema_result = await conn.execute(text(f"""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_name = '{table_name}'
            AND table_schema = 'public'
        """))
        schema = {row[0]: row[1] for row in schema_result}

        # Clear existing data
        await conn.execute(text(f"DELETE FROM {table_name}"))

        # Import data row by row with progress
        for i, row in enumerate(data):
            if i % 100 == 0:
                print(f"  Progress: {i}/{len(data)} rows...")

            # Process columns
            for key, value in row.items():
                if key in schema:
                    # Convert datetime strings
                    if isinstance(value, str) and ('T' in value and ':' in value):
                        try:
                            row[key] = datetime.fromisoformat(value.replace('Z', '+00:00'))
                        except:
                            pass
                    # Convert dicts/lists to JSON strings for JSONB columns
                    elif schema[key] == 'jsonb' and isinstance(value, (dict, list)):
                        row[key] = json.dumps(value)

            # Build INSERT statement
            columns = list(row.keys())
            placeholders = [f":{col}" for col in columns]

            insert_sql = f"""
                INSERT INTO {table_name} ({', '.join(columns)})
                VALUES ({', '.join(placeholders)})
            """

            await conn.execute(text(insert_sql), row)

        # Reset sequence if needed
        if 'id' in data[0]:
            max_id = max(row['id'] for row in data)
            sequence_name = f"{table_name}_id_seq"

            # Check if sequence exists
            seq_check = await conn.execute(text(f"""
                SELECT EXISTS (
                    SELECT 1 FROM pg_sequences
                    WHERE schemaname = 'public'
                    AND sequencename = '{sequence_name}'
                )
            """))

            if seq_check.scalar():
                await conn.execute(text(f"ALTER SEQUENCE {sequence_name} RESTART WITH {max_id + 1}"))
                print(f"  ↳ Reset sequence {sequence_name} to {max_id + 1}")

    await engine.dispose()
    print(f"✅ Successfully imported {len(data)} rows into {table_name}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python scripts/import_single_table.py <table_name> <db_url>")
        print("\nExample tables to import:")
        print("  - products")
        print("  - shipping_profiles")
        print("  - reverb_listings")
        sys.exit(1)

    table_name = sys.argv[1]
    db_url = sys.argv[2]

    asyncio.run(import_single_table(table_name, db_url))