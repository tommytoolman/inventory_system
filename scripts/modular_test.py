#!/usr/bin/env python3
"""
Simple modular database testing - switch in/out easily
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

class DatabaseSwitcher:
    """Simple database switcher"""
    
    def __init__(self):
        self.PROD_URL = "postgresql+asyncpg://inventory_user:Playboy2023!@localhost/inventory"
        self.TEST_URL = "postgresql+asyncpg://inventory_user:Playboy2023!@localhost/inventory_test"
        
    async def get_session(self, use_test=True):
        """Get a database session - test or production"""
        url = self.TEST_URL if use_test else self.PROD_URL
        engine = create_async_engine(url)
        SessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        return SessionLocal(), engine
    
    async def verify_connection(self, session):
        """Verify which database we're connected to"""
        result = await session.execute(text('SELECT current_database()'))
        return result.scalar()

async def test_sync_operations():
    """Your sync operations with easy database switching"""
    
    db_switcher = DatabaseSwitcher()
    
    print("🧪 MODULAR DATABASE TESTING")
    print("=" * 50)
    
    # === USE TEST DATABASE ===
    print("📊 Switching to TEST database...")
    test_session, test_engine = await db_switcher.get_session(use_test=True)
    
    async with test_session as db:
        current_db = await db_switcher.verify_connection(db)
        print(f"✅ Connected to: {current_db}")
        
        if current_db != 'inventory_test':
            print("❌ ERROR: Not on test database!")
            return
        
        # === YOUR SYNC OPERATIONS HERE ===
        print("\n🔄 Running sync operations on TEST database...")
        
        # Take before snapshot
        before_counts = await take_snapshot(db)
        print("📊 BEFORE:")
        for table, count in before_counts.items():
            print(f"   {table}: {count}")
        
        # ADD YOUR SYNC OPERATIONS HERE
        print("   🎸 Testing your sync operations...")
        
        # Example: Import your actual sync services
        # from app.services.reverb.importer import ReverbImporter
        # importer = ReverbImporter(db)
        # result = await importer.import_all_listings()
        # print(f"   Reverb import: {result}")
        
        # Example: Test eBay sync
        # from app.services.ebay.ebay_service import EbayService
        # ebay_service = EbayService(db, mock_settings)
        # result = await ebay_service.sync_inventory()
        # print(f"   eBay sync: {result}")
        
        await db.commit()
        
        # Take after snapshot
        after_counts = await take_snapshot(db)
        print("\n📊 AFTER:")
        for table, count in after_counts.items():
            change = after_counts[table] - before_counts[table]
            symbol = "+" if change > 0 else ""
            print(f"   {table}: {count} ({symbol}{change})")
        
        print("\n✅ Test operations completed!")
        print("💡 Your production database is untouched")
    
    await test_engine.dispose()
    
    # === SWITCH BACK TO PRODUCTION (if needed) ===
    print("\n📊 Switching back to PRODUCTION database...")
    prod_session, prod_engine = await db_switcher.get_session(use_test=False)
    
    async with prod_session as db:
        current_db = await db_switcher.verify_connection(db)
        print(f"✅ Back on: {current_db}")
        
        # You can run production operations here if needed
        # But typically you'd just verify the connection
        
    await prod_engine.dispose()
    print("🎉 Database switching test completed!")

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