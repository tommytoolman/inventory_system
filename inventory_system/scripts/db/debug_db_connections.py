#!/usr/bin/env python3
"""
Debug which databases we're actually connecting to
"""
import asyncio
import sys
import os
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

async def test_all_connections():
    """Test all possible database connections"""
    
    print("🔍 DATABASE CONNECTION DIAGNOSTIC")
    print("=" * 60)
    
    # Test different connection methods
    connections_to_test = {
        "Direct inventory": "postgresql+asyncpg://inventory_user:Playboy2023!@localhost/inventory",
        "Direct inventory_test": "postgresql+asyncpg://inventory_user:Playboy2023!@localhost/inventory_test",
        "conftest.py test_db": "postgresql+asyncpg://test_user:test_pass@localhost/test_db"
    }
    
    for name, url in connections_to_test.items():
        try:
            print(f"\n📊 Testing: {name}")
            print(f"   URL: {url}")
            
            engine = create_async_engine(url)
            async with engine.connect() as conn:
                # Check database name
                result = await conn.execute(text('SELECT current_database()'))
                current_db = result.scalar()
                print(f"   ✅ Connected to: {current_db}")
                
                # Check product count
                try:
                    result = await conn.execute(text('SELECT COUNT(*) FROM products'))
                    count = result.scalar()
                    print(f"   📦 Products: {count}")
                except Exception as e:
                    print(f"   ❌ No products table: {e}")
                
            await engine.dispose()
            
        except Exception as e:
            print(f"   ❌ Connection failed: {e}")
    
    # Test using your app's get_settings
    print(f"\n📊 Testing your app's get_settings():")
    try:
        from app.core.config import get_settings
        from app.database import get_session
        
        settings = get_settings()
        print(f"   Settings URL: {settings.DATABASE_URL}")
        
        async with get_session() as db:
            result = await db.execute(text('SELECT current_database()'))
            current_db = result.scalar()
            print(f"   ✅ App connects to: {current_db}")
            
            result = await db.execute(text('SELECT COUNT(*) FROM products'))
            count = result.scalar()
            print(f"   📦 Products via app: {count}")
            
    except Exception as e:
        print(f"   ❌ App connection failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_all_connections())
