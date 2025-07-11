#!/usr/bin/env python3
"""
Direct connection to inventory_test database
"""
import asyncio
import sys
import os
from pathlib import Path
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text

# Direct database URL for inventory_test
TEST_DATABASE_URL = "postgresql+asyncpg://inventory_user:Playboy2023!@localhost/inventory_test"

async def test_sync_operations():
    """Run sync operations directly on inventory_test"""
    
    print("🧪 DIRECT SYNC TESTING ON INVENTORY_TEST DATABASE")
    print("=" * 60)
    print(f"📊 Database URL: {TEST_DATABASE_URL}")
    
    # Create engine and session
    engine = create_async_engine(TEST_DATABASE_URL)
    TestSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with TestSessionLocal() as db:
        # Verify connection
        result = await db.execute(text('SELECT current_database()'))
        current_db = result.scalar()
        print(f"📊 Connected to: {current_db}")
        
        if current_db != 'inventory_test':
            print("❌ ERROR: Connected to wrong database!")
            return
        
        print("✅ Successfully connected to test database!")
        print(f"📦 Production backup: backups/pre_sync_test_20250704_105958.sql")
        
        # Take before snapshot
        before_counts = await take_snapshot(db)
        print(f"\n📊 BEFORE SYNC:")
        for table, count in before_counts.items():
            print(f"   {table}: {count}")
        
        # YOUR SYNC OPERATIONS GO HERE
        print(f"\n🔄 RUNNING SYNC OPERATIONS...")
        
        try:
            print("   🎸 Testing sync operations...")
            
            # ADD YOUR ACTUAL SYNC CALLS HERE
            # Example:
            # from app.services.reverb.importer import ReverbImporter
            # importer = ReverbImporter(db)
            # result = await importer.import_all_listings()
            # print(f"      Result: {result}")
            
            await db.commit()
            print(f"   ✅ All sync operations completed!")
            
            # Take after snapshot
            after_counts = await take_snapshot(db)
            print(f"\n📊 AFTER SYNC:")
            for table, count in after_counts.items():
                change = after_counts[table] - before_counts[table]
                symbol = "+" if change > 0 else ""
                print(f"   {table}: {count} ({symbol}{change})")
            
            print(f"\n🎉 SYNC TEST COMPLETED SUCCESSFULLY!")
            
        except Exception as e:
            print(f"❌ Error during sync: {e}")
            import traceback
            traceback.print_exc()
            await db.rollback()
    
    await engine.dispose()

async def take_snapshot(db):
    """Take database snapshot"""
    queries = {
        'products': "SELECT COUNT(*) FROM products",
        'platform_common': "SELECT COUNT(*) FROM platform_common", 
        'reverb_listings': "SELECT COUNT(*) FROM reverb_listings",
        'shopify_listings': "SELECT COUNT(*) FROM shopify_listings",
        'ebay_listings': "SELECT COUNT(*) FROM ebay_listings"
    }
    
    snapshot = {}
    for table, query in queries.items():
        try:
            result = await db.execute(text(query))
            snapshot[table] = result.scalar()
        except Exception:
            snapshot[table] = 0
    
    return snapshot

if __name__ == "__main__":
    asyncio.run(test_sync_operations())
