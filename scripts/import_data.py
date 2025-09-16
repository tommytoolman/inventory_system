#!/usr/bin/env python3
"""
Import data from JSON files to Railway database
"""

import json
import asyncio
import os
import sys
from datetime import datetime
from decimal import Decimal

# Add the app directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from app.core.config import get_settings


async def import_data(railway_db_url=None):
    """Import all data to Railway database"""

    settings = get_settings()

    # Use provided URL or get from environment
    if railway_db_url:
        db_url = railway_db_url
    else:
        db_url = os.getenv('RAILWAY_DATABASE_URL') or str(settings.DATABASE_URL)

    # Ensure it's async
    if not db_url.startswith('postgresql+asyncpg://'):
        db_url = db_url.replace('postgresql://', 'postgresql+asyncpg://', 1)

    engine = create_async_engine(db_url)

    # Tables to import in dependency order
    tables_to_import = [
        # Independent tables first
        'shipping_profiles',
        'activity_log',
        'category_mappings',
        'csv_import_logs',
        'platform_category_mappings',
        'platform_policies',
        'platform_status_mappings',
        'reverb_categories',
        'vr_accepted_brands',

        # Products and related
        'products',
        'product_mappings',
        'product_merges',

        # Platform tables
        'platform_common',
        'reverb_listings',
        'ebay_listings',
        'shopify_listings',
        'vr_listings',

        # Category mappings (depend on reverb_categories)
        'ebay_category_mappings',
        'shopify_category_mappings',
        'vr_category_mappings',

        # Sales and orders
        'sales',
        'orders',
        'shipments',

        # Sync tracking
        'sync_events',
        'sync_stats'
    ]

    export_dir = 'data_export'
    imported_counts = {}

    async with engine.begin() as conn:
        # First, disable all foreign key constraints temporarily
        await conn.execute(text("SET session_replication_role = 'replica';"))

        for table in tables_to_import:
            json_file = os.path.join(export_dir, f"{table}.json")

            if not os.path.exists(json_file):
                print(f"⚠️  File {json_file} does not exist, skipping...")
                continue

            try:
                # Load data from JSON
                with open(json_file, 'r') as f:
                    data = json.load(f)

                if not data:
                    print(f"⚠️  No data to import for {table}")
                    continue

                # Clear existing data in table
                await conn.execute(text(f"TRUNCATE TABLE {table} CASCADE"))

                # Get table schema to identify JSONB columns
                schema_result = await conn.execute(text(f"""
                    SELECT column_name, data_type
                    FROM information_schema.columns
                    WHERE table_name = '{table}'
                    AND table_schema = 'public'
                """))
                schema = {row[0]: row[1] for row in schema_result}

                # Process all rows first
                processed_rows = []
                for i, row in enumerate(data):
                    # Show progress for large datasets
                    if len(data) > 100 and i % 100 == 0:
                        print(f"  Processing row {i}/{len(data)}...")

                    # Process each column based on its type
                    for key, value in row.items():
                        if key in schema:
                            # Convert datetime strings back to datetime objects
                            if isinstance(value, str) and ('T' in value and ':' in value):
                                try:
                                    row[key] = datetime.fromisoformat(value.replace('Z', '+00:00'))
                                except:
                                    pass
                            # Convert dicts/lists to JSON strings for JSONB columns
                            elif schema[key] == 'jsonb' and isinstance(value, (dict, list)):
                                row[key] = json.dumps(value)

                    processed_rows.append(row)

                # Batch insert for better performance
                if processed_rows:
                    columns = list(processed_rows[0].keys())

                    # Use batch insert
                    for i in range(0, len(processed_rows), 100):
                        batch = processed_rows[i:i+100]
                        if len(data) > 100:
                            print(f"  Inserting batch {i//100 + 1}/{(len(processed_rows) + 99)//100}...")

                        for row in batch:
                            placeholders = [f":{col}" for col in columns]
                            insert_sql = f"""
                                INSERT INTO {table} ({', '.join(columns)})
                                VALUES ({', '.join(placeholders)})
                            """
                            await conn.execute(text(insert_sql), row)

                imported_counts[table] = len(data)
                print(f"✅ Imported {len(data)} rows into {table}")

                # Reset sequences if table has an id column
                if 'id' in data[0]:
                    max_id = max(row['id'] for row in data)
                    sequence_name = f"{table}_id_seq"

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

            except Exception as e:
                print(f"❌ Error importing {table}: {e}")

        # Re-enable foreign key constraints
        await conn.execute(text("SET session_replication_role = 'origin';"))

    await engine.dispose()

    # Save import metadata
    metadata = {
        'import_date': datetime.now().isoformat(),
        'table_counts': imported_counts,
        'total_rows': sum(imported_counts.values())
    }

    print(f"\n📦 Import complete! Total rows imported: {metadata['total_rows']}")
    return metadata


async def verify_import(railway_db_url=None):
    """Verify the import by counting rows in each table"""

    settings = get_settings()

    # Use provided URL or get from environment
    if railway_db_url:
        db_url = railway_db_url
    else:
        db_url = os.getenv('RAILWAY_DATABASE_URL') or str(settings.DATABASE_URL)

    # Ensure it's async
    if not db_url.startswith('postgresql+asyncpg://'):
        db_url = db_url.replace('postgresql://', 'postgresql+asyncpg://', 1)

    engine = create_async_engine(db_url)

    print("\n🔍 Verifying imported data...")

    async with engine.begin() as conn:
        # Get all tables
        result = await conn.execute(text("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
            AND table_type = 'BASE TABLE'
            AND table_name != 'alembic_version'
            ORDER BY table_name
        """))

        tables = result.fetchall()

        for (table_name,) in tables:
            count_result = await conn.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
            count = count_result.scalar()
            if count > 0:
                print(f"  {table_name}: {count} rows")

    await engine.dispose()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Import data to Railway database')
    parser.add_argument('--db-url', help='Railway database URL (or set RAILWAY_DATABASE_URL env var)')
    parser.add_argument('--verify-only', action='store_true', help='Only verify existing data, don\'t import')

    args = parser.parse_args()

    if args.verify_only:
        print("🔍 Running verification only...")
        asyncio.run(verify_import(args.db_url))
    else:
        print("🚀 Starting data import to Railway database...")
        asyncio.run(import_data(args.db_url))
        asyncio.run(verify_import(args.db_url))