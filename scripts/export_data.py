#!/usr/bin/env python3
"""
Export data from local database to JSON files for migration
"""

import json
import asyncio
import os
import sys
from datetime import datetime, date
from decimal import Decimal
from uuid import UUID

# Add the app directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from app.core.config import get_settings


class DateTimeEncoder(json.JSONEncoder):
    """Custom JSON encoder for datetime objects"""
    def default(self, obj):
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        elif isinstance(obj, Decimal):
            return float(obj)
        elif isinstance(obj, UUID):
            return str(obj)
        return super().default(obj)


async def export_data():
    """Export all data from local database"""

    settings = get_settings()
    db_url = str(settings.DATABASE_URL)

    # Ensure it's async
    if not db_url.startswith('postgresql+asyncpg://'):
        db_url = db_url.replace('postgresql://', 'postgresql+asyncpg://', 1)

    engine = create_async_engine(db_url)

    # Tables to export in dependency order
    tables_to_export = [
        # Independent tables first
        'shipping_profiles',
        'users',
        'activity_log',
        'category_mappings',
        'csv_import_logs',
        'platform_category_mappings',
        'platform_policies',
        'platform_status_mappings',
        'reverb_categories',
        'vr_accepted_brands',
        'webhook_events',

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
    os.makedirs(export_dir, exist_ok=True)

    exported_counts = {}

    async with engine.begin() as conn:
        for table in tables_to_export:
            try:
                # Check if table exists
                check_result = await conn.execute(text(f"""
                    SELECT EXISTS (
                        SELECT 1 FROM information_schema.tables
                        WHERE table_schema = 'public'
                        AND table_name = '{table}'
                    )
                """))

                if not check_result.scalar():
                    print(f"⚠️  Table {table} does not exist, skipping...")
                    continue

                # Export table data
                result = await conn.execute(text(f"SELECT * FROM {table}"))
                rows = result.fetchall()

                # Convert rows to dictionaries
                data = []
                for row in rows:
                    data.append(dict(row._mapping))

                # Save to JSON file
                output_file = os.path.join(export_dir, f"{table}.json")
                with open(output_file, 'w') as f:
                    json.dump(data, f, cls=DateTimeEncoder, indent=2)

                exported_counts[table] = len(data)
                print(f"✅ Exported {len(data)} rows from {table}")

            except Exception as e:
                print(f"❌ Error exporting {table}: {e}")

    await engine.dispose()

    # Save export metadata
    metadata = {
        'export_date': datetime.now().isoformat(),
        'table_counts': exported_counts,
        'total_rows': sum(exported_counts.values())
    }

    with open(os.path.join(export_dir, 'export_metadata.json'), 'w') as f:
        json.dump(metadata, f, indent=2)

    print(f"\n📦 Export complete! Total rows exported: {metadata['total_rows']}")
    print(f"📁 Data saved to: {export_dir}/")


if __name__ == "__main__":
    print("🚀 Starting data export from local database...")
    asyncio.run(export_data())