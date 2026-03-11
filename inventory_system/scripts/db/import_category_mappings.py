#!/usr/bin/env python3
"""
Import category mappings from JSON file into platform_category_mappings table

Usage:
    python scripts/db/import_category_mappings.py
"""
import asyncio
import json
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sqlalchemy import text
from app.database import async_session


async def import_category_mappings():
    """Import category mappings from JSON file to database"""
    
    # Load JSON file
    json_file = Path("data/platform_category_mappings.json")
    if not json_file.exists():
        print(f"❌ JSON file not found: {json_file}")
        return
    
    with open(json_file, 'r') as f:
        data = json.load(f)
    
    print(f"📊 Loaded {len(data['mappings'])} mappings from JSON file")
    print(f"   Source: {data['metadata']['source_file']}")
    print(f"   Date: {data['metadata']['extracted_date']}")
    
    async with async_session() as db:
        try:
            # Check if table exists
            check_query = text("""
                SELECT COUNT(*) FROM information_schema.tables 
                WHERE table_name = 'platform_category_mappings'
            """)
            result = await db.execute(check_query)
            if result.scalar() == 0:
                print("❌ Table 'platform_category_mappings' does not exist!")
                print("   Please create it first with:")
                print("   CREATE TABLE platform_category_mappings (")
                print("       id SERIAL PRIMARY KEY,")
                print("       source_platform VARCHAR(50),")
                print("       source_category_id VARCHAR(100),")
                print("       source_category_name TEXT,")
                print("       target_platform VARCHAR(50),")
                print("       target_category_id VARCHAR(100),")
                print("       target_category_name TEXT,")
                print("       item_count INTEGER,")
                print("       created_at TIMESTAMP DEFAULT NOW()")
                print("   );")
                return
            
            # Clear existing mappings for reverb->ebay
            delete_query = text("""
                DELETE FROM platform_category_mappings 
                WHERE source_platform = 'reverb' AND target_platform = 'ebay'
            """)
            result = await db.execute(delete_query)
            print(f"🗑️  Cleared {result.rowcount} existing reverb->ebay mappings")
            
            # Insert new mappings
            insert_query = text("""
                INSERT INTO platform_category_mappings (
                    source_platform, 
                    source_category_id, 
                    source_category_name,
                    target_platform, 
                    target_category_id, 
                    target_category_name,
                    item_count
                ) VALUES (
                    :source_platform, 
                    :source_category_id, 
                    :source_category_name,
                    :target_platform, 
                    :target_category_id, 
                    :target_category_name,
                    :item_count
                )
            """)
            
            # Insert all mappings
            for mapping in data['mappings']:
                await db.execute(insert_query, {
                    'source_platform': mapping['source_platform'],
                    'source_category_id': mapping['source_category_id'],
                    'source_category_name': mapping.get('source_category_name', ''),
                    'target_platform': mapping['target_platform'],
                    'target_category_id': mapping['target_category_id'],
                    'target_category_name': mapping.get('target_category_name', ''),
                    'item_count': mapping.get('item_count', 0)
                })
            
            await db.commit()
            print(f"✅ Successfully imported {len(data['mappings'])} category mappings")
            
            # Verify the import
            count_query = text("""
                SELECT COUNT(*) FROM platform_category_mappings 
                WHERE source_platform = 'reverb' AND target_platform = 'ebay'
            """)
            result = await db.execute(count_query)
            count = result.scalar()
            print(f"📊 Verified: {count} mappings now in database")
            
            # Show sample mappings
            sample_query = text("""
                SELECT source_category_name, target_category_name, item_count
                FROM platform_category_mappings 
                WHERE source_platform = 'reverb' AND target_platform = 'ebay'
                AND item_count > 100
                ORDER BY item_count DESC
                LIMIT 5
            """)
            result = await db.execute(sample_query)
            samples = result.fetchall()
            
            if samples:
                print("\n📋 Top 5 mappings by item count:")
                for sample in samples:
                    print(f"   {sample.source_category_name} → {sample.target_category_name} ({sample.item_count} items)")
            
        except Exception as e:
            print(f"❌ Error importing mappings: {e}")
            await db.rollback()
            raise


if __name__ == "__main__":
    asyncio.run(import_category_mappings())