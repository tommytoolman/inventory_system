#!/usr/bin/env python3
"""
Safe sync testing using test database clone
"""
import asyncio
import sys
import os
from pathlib import Path
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Use test environment BEFORE importing anything
os.environ['ENV_FILE'] = '.env.test'

# IMPORTANT: Clear any existing settings cache
from app.core.config import get_settings, clear_settings_cache
clear_settings_cache()

# Now import other modules
from app.database import get_session
from sqlalchemy import text

async def test_sync_operations():
    """Run your sync operations against the test database"""
    
    print("🧪 SAFE SYNC TESTING ON TEST DATABASE")
    print("=" * 60)
    
    # Verify we're using the correct environment
    settings = get_settings()
    print(f"📊 Database URL: {settings.DATABASE_URL}")
    
    if 'inventory_test' not in settings.DATABASE_URL:
        print("❌ ERROR: Not using test database!")
        print(f"Expected: ...inventory_test, Got: {settings.DATABASE_URL}")
        return
    
    # Test actual connection
    async with get_session() as db:
        result = await db.execute(text('SELECT current_database()'))
        current_db = result.scalar()
        print(f"📊 Connected to: {current_db}")
        
        if current_db != 'inventory_test':
            print("❌ ERROR: Connected to wrong database!")
            return
    
    print("✅ Successfully connected to test database!")
    
    # Rest of your sync operations...

if __name__ == "__main__":
    asyncio.run(test_sync_operations())