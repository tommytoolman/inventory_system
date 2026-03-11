#!/usr/bin/env python3
"""
Drop and recreate the shipping_profiles table with new structure.

This script:
1. Drops the existing shipping_profiles table
2. Recreates it with the new structure including reverb_profile_id and ebay_profile_id
3. Imports Reverb shipping profiles

Usage:
    python scripts/shipping/recreate_shipping_profiles_table.py
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent.parent))

from sqlalchemy import text
from app.database import async_session, engine
from app.models.shipping import ShippingProfile

async def drop_and_recreate_table():
    """Drop and recreate the shipping_profiles table."""
    
    async with engine.begin() as conn:
        print("🗑️  Dropping existing shipping_profiles table...")
        await conn.execute(text("DROP TABLE IF EXISTS shipping_profiles CASCADE"))
        print("✅ Table dropped")
        
        print("\n📦 Creating new shipping_profiles table...")
        await conn.execute(text("""
            CREATE TABLE shipping_profiles (
                id SERIAL PRIMARY KEY,
                reverb_profile_id VARCHAR,
                ebay_profile_id VARCHAR,
                name VARCHAR NOT NULL,
                description VARCHAR,
                is_default BOOLEAN DEFAULT FALSE,
                package_type VARCHAR,
                weight FLOAT,
                dimensions JSONB,
                carriers JSONB,
                options JSONB,
                rates JSONB,
                created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT (timezone('utc', now())),
                updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT (timezone('utc', now()))
            )
        """))
        
        # Add index on reverb_profile_id
        await conn.execute(text(
            "CREATE INDEX ix_shipping_profiles_reverb_profile_id ON shipping_profiles(reverb_profile_id)"
        ))
        
        print("✅ Table created with new structure")

async def main():
    """Main execution function."""
    print("=" * 60)
    print("RECREATE SHIPPING PROFILES TABLE")
    print("=" * 60)
    
    # Drop and recreate table
    await drop_and_recreate_table()
    
    print("\n" + "=" * 60)
    print("TABLE RECREATION COMPLETE")
    print("=" * 60)
    print("\n✅ Next step: Run import_reverb_shipping_profiles.py to populate with data")
    print("   python scripts/shipping/import_reverb_shipping_profiles.py")

if __name__ == "__main__":
    asyncio.run(main())