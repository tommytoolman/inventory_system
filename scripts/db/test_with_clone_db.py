#!/usr/bin/env python3
"""
Test script that directly uses the test database
"""
import asyncio
import sys
import os
from pathlib import Path
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import and monkey-patch the database URL
from app.core.config import Settings
from app.database import get_session
from sqlalchemy import text

# Create a test-specific settings class that FORCES the test database
class TestSettings(Settings):
    DATABASE_URL: str = "postgresql+asyncpg://inventory_user:Playboy2023!@localhost/inventory_test"

# Monkey-patch the get_settings function
from app.core import config
config.get_settings = lambda: TestSettings()

async def test_sync_operations():
    """Run your sync operations against the test database"""
    
    print("🧪 SAFE SYNC TESTING ON TEST DATABASE")
    print("=" * 60)
    
    # Verify we're using the test database
    settings = TestSettings()
    print(f"📊 Database URL: {settings.DATABASE_URL}")
    
    # Test actual connection
    async with get_session() as db:
        result = await db.execute(text('SELECT current_database()'))
        current_db = result.scalar()
        print(f"📊 Connected to: {current_db}")
        
        if current_db != 'inventory_test':
            print("❌ ERROR: Connected to wrong database!")
            return
    
    print("✅ Successfully connected to test database!")
    print(f"📦 Production backup: backups/pre_sync_test_20250704_105958.sql")
    print(f"🕐 Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Take before snapshot
    before_counts = await take_snapshot()
    print(f"\n📊 BEFORE SYNC:")
    for table, count in before_counts.items():
        print(f"   {table}: {count}")
    
    # YOUR SYNC OPERATIONS GO HERE
    print(f"\n🔄 RUNNING SYNC OPERATIONS...")
    
    try:
        # Example: Test your sync operations
        print("   🎸 Testing sync operations...")
        
        # ADD YOUR ACTUAL SYNC CALLS HERE
        # from app.services.reverb.importer import ReverbImporter
        # async with get_session() as db:
        #     importer = ReverbImporter(db)
        #     result = await importer.import_all_listings()
        #     print(f"      Result: {result}")
        
        print(f"   ✅ All sync operations completed!")
        
        # Take after snapshot
        after_counts = await take_snapshot()
        print(f"\n📊 AFTER SYNC:")
        for table, count in after_counts.items():
            change = after_counts[table] - before_counts[table]
            symbol = "+" if change > 0 else ""
            print(f"   {table}: {count} ({symbol}{change})")
        
        print(f"\n🎉 SYNC TEST COMPLETED SUCCESSFULLY!")
        print(f"💡 Your production database is completely safe")
        print(f"🚀 If results look good, run against production")
        
    except Exception as e:
        print(f"❌ Error during sync: {e}")
        import traceback
        traceback.print_exc()

async def take_snapshot():
    """Take database snapshot"""
    queries = {
        'products': "SELECT COUNT(*) FROM products",
        'platform_common': "SELECT COUNT(*) FROM platform_common", 
        'reverb_listings': "SELECT COUNT(*) FROM reverb_listings",
        'shopify_listings': "SELECT COUNT(*) FROM shopify_listings",
        'ebay_listings': "SELECT COUNT(*) FROM ebay_listings"
    }
    
    snapshot = {}
    async with get_session() as db:
        for table, query in queries.items():
            result = await db.execute(text(query))
            snapshot[table] = result.scalar()
    
    return snapshot

if __name__ == "__main__":
    asyncio.run(test_sync_operations())
