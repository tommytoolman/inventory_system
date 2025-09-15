#!/usr/bin/env python3
"""
Import all category mappings from JSON files into the enhanced platform_category_mappings table

This script imports:
1. eBay mappings from data/platform_category_mappings.json
2. Shopify mappings from app/services/category_mappings/reverb_to_shopify.json  
3. VR mappings from data/vr_category_mappings.json

Usage:
    python scripts/db/import_all_category_mappings.py
"""

import asyncio
import json
import sys
from pathlib import Path
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sqlalchemy import text
from app.database import async_session


async def clear_existing_mappings(db, platform=None):
    """Clear existing mappings for a platform or all"""
    if platform:
        query = text("DELETE FROM platform_category_mappings WHERE target_platform = :platform")
        result = await db.execute(query, {"platform": platform})
    else:
        query = text("DELETE FROM platform_category_mappings")
        result = await db.execute(query)
    
    await db.commit()
    return result.rowcount


async def import_ebay_mappings(db):
    """Import eBay category mappings"""
    print("\n📦 Importing eBay mappings...")
    
    json_file = Path("data/platform_category_mappings.json")
    if not json_file.exists():
        print(f"  ❌ File not found: {json_file}")
        return 0
    
    with open(json_file, 'r') as f:
        data = json.load(f)
    
    # Handle the new JSON structure with metadata and mappings array
    mappings = data.get("mappings", [])
    
    count = 0
    for mapping in mappings:
        query = text("""
            INSERT INTO platform_category_mappings (
                source_platform,
                source_category_id,
                source_category_name,
                target_platform,
                target_category_id,
                target_category_name,
                item_count,
                is_verified,
                confidence_score
            ) VALUES (
                :source_platform,
                :source_category_id,
                :source_category_name,
                :target_platform,
                :target_category_id,
                :target_category_name,
                :item_count,
                :is_verified,
                :confidence_score
            )
            ON CONFLICT (source_platform, source_category_id, target_platform) 
            DO UPDATE SET
                target_category_id = EXCLUDED.target_category_id,
                target_category_name = EXCLUDED.target_category_name,
                item_count = EXCLUDED.item_count,
                updated_at = NOW()
        """)
        
        await db.execute(query, {
            "source_platform": mapping.get("source_platform", "reverb"),
            "source_category_id": mapping.get("source_category_id", ""),
            "source_category_name": mapping.get("source_category_name", ""),
            "target_platform": mapping.get("target_platform", "ebay"),
            "target_category_id": mapping.get("target_category_id", ""),
            "target_category_name": mapping.get("target_category_name", ""),
            "item_count": mapping.get("item_count", 0),
            "is_verified": True,  # These are production mappings
            "confidence_score": 1.0
        })
        count += 1
    
    await db.commit()
    print(f"  ✅ Imported {count} eBay mappings")
    return count


async def import_shopify_mappings(db):
    """Import Shopify category mappings"""
    print("\n🛍️ Importing Shopify mappings...")
    
    json_file = Path("app/services/category_mappings/reverb_to_shopify.json")
    if not json_file.exists():
        print(f"  ❌ File not found: {json_file}")
        return 0
    
    with open(json_file, 'r') as f:
        data = json.load(f)
    
    mappings = data.get("mappings", {})
    count = 0
    
    for reverb_uuid, mapping in mappings.items():
        # Extract category name from the full Shopify category path
        shopify_category = mapping.get("shopify_category", "")
        category_parts = shopify_category.split(" > ")
        source_name = category_parts[-1] if category_parts else ""
        
        query = text("""
            INSERT INTO platform_category_mappings (
                source_platform,
                source_category_id,
                source_category_name,
                target_platform,
                target_category_name,
                shopify_gid,
                merchant_type,
                is_verified,
                confidence_score
            ) VALUES (
                :source_platform,
                :source_category_id,
                :source_category_name,
                :target_platform,
                :target_category_name,
                :shopify_gid,
                :merchant_type,
                :is_verified,
                :confidence_score
            )
            ON CONFLICT (source_platform, source_category_id, target_platform) 
            DO UPDATE SET
                shopify_gid = EXCLUDED.shopify_gid,
                merchant_type = EXCLUDED.merchant_type,
                target_category_name = EXCLUDED.target_category_name,
                updated_at = NOW()
        """)
        
        await db.execute(query, {
            "source_platform": "reverb",
            "source_category_id": reverb_uuid,
            "source_category_name": source_name,
            "target_platform": "shopify",
            "target_category_name": shopify_category,
            "shopify_gid": mapping.get("shopify_gid", ""),
            "merchant_type": mapping.get("merchant_type", ""),
            "is_verified": True,
            "confidence_score": 1.0
        })
        count += 1
    
    await db.commit()
    print(f"  ✅ Imported {count} Shopify mappings")
    return count


async def import_vr_mappings(db):
    """Import VR category mappings"""
    print("\n🎸 Importing V&R mappings...")
    
    json_file = Path("data/vr_category_mappings.json")
    if not json_file.exists():
        print(f"  ❌ File not found: {json_file}")
        return 0
    
    with open(json_file, 'r') as f:
        data = json.load(f)
    
    mappings = data.get("mappings", {})
    count = 0
    
    for reverb_uuid, mapping in mappings.items():
        query = text("""
            INSERT INTO platform_category_mappings (
                source_platform,
                source_category_id,
                source_category_name,
                target_platform,
                vr_category_id,
                vr_subcategory_id,
                vr_sub_subcategory_id,
                vr_sub_sub_subcategory_id,
                is_verified,
                confidence_score
            ) VALUES (
                :source_platform,
                :source_category_id,
                :source_category_name,
                :target_platform,
                :vr_category_id,
                :vr_subcategory_id,
                :vr_sub_subcategory_id,
                :vr_sub_sub_subcategory_id,
                :is_verified,
                :confidence_score
            )
            ON CONFLICT (source_platform, source_category_id, target_platform) 
            DO UPDATE SET
                vr_category_id = EXCLUDED.vr_category_id,
                vr_subcategory_id = EXCLUDED.vr_subcategory_id,
                vr_sub_subcategory_id = EXCLUDED.vr_sub_subcategory_id,
                vr_sub_sub_subcategory_id = EXCLUDED.vr_sub_sub_subcategory_id,
                source_category_name = EXCLUDED.source_category_name,
                updated_at = NOW()
        """)
        
        await db.execute(query, {
            "source_platform": "reverb",
            "source_category_id": reverb_uuid,
            "source_category_name": mapping.get("full_name", ""),
            "target_platform": "vintageandrare",
            "vr_category_id": mapping.get("category_id"),
            "vr_subcategory_id": mapping.get("subcategory_id") if mapping.get("subcategory_id") != "" else None,
            "vr_sub_subcategory_id": mapping.get("sub_subcategory_id"),
            "vr_sub_sub_subcategory_id": mapping.get("sub_sub_subcategory_id"),
            "is_verified": True,
            "confidence_score": 1.0
        })
        count += 1
    
    await db.commit()
    print(f"  ✅ Imported {count} V&R mappings")
    return count


async def verify_import(db):
    """Verify the import by showing counts per platform"""
    print("\n📊 Verifying import...")
    
    query = text("""
        SELECT 
            target_platform,
            COUNT(*) as count,
            COUNT(DISTINCT source_category_id) as unique_categories
        FROM platform_category_mappings
        GROUP BY target_platform
        ORDER BY target_platform
    """)
    
    result = await db.execute(query)
    rows = result.fetchall()
    
    print("\n  Platform Counts:")
    print("  " + "-" * 40)
    total = 0
    for row in rows:
        print(f"  {row.target_platform:20s}: {row.count:4d} mappings")
        total += row.count
    print("  " + "-" * 40)
    print(f"  {'TOTAL':20s}: {total:4d} mappings")
    
    # Show sample mappings
    print("\n  Sample mappings:")
    for platform in ['ebay', 'shopify', 'vintageandrare']:
        query = text("""
            SELECT source_category_name, 
                   COALESCE(target_category_name, merchant_type, 
                           'VR: ' || vr_category_id || '/' || vr_subcategory_id) as target
            FROM platform_category_mappings
            WHERE target_platform = :platform
            AND source_category_name IS NOT NULL
            LIMIT 2
        """)
        result = await db.execute(query, {"platform": platform})
        samples = result.fetchall()
        
        print(f"\n  {platform}:")
        for sample in samples:
            print(f"    {sample.source_category_name[:30]:30s} → {sample.target[:40]}")


async def main():
    """Main import function"""
    print("=" * 60)
    print("Category Mappings Import Tool")
    print("=" * 60)
    
    async with async_session() as db:
        # First check if table exists
        query = text("""
            SELECT COUNT(*) 
            FROM information_schema.tables 
            WHERE table_name = 'platform_category_mappings'
        """)
        result = await db.execute(query)
        exists = result.scalar() > 0
        
        if not exists:
            print("❌ Table 'platform_category_mappings' does not exist!")
            print("Please run the SQL script to create the table first.")
            return
        
        # Check existing data
        query = text("SELECT COUNT(*) FROM platform_category_mappings")
        result = await db.execute(query)
        existing_count = result.scalar()
        
        if existing_count > 0:
            print(f"⚠️  Found {existing_count} existing mappings in the table")
            response = input("Do you want to clear existing data? (y/n): ")
            if response.lower() == 'y':
                deleted = await clear_existing_mappings(db)
                print(f"  Deleted {deleted} existing mappings")
        
        # Import from each source
        ebay_count = await import_ebay_mappings(db)
        shopify_count = await import_shopify_mappings(db)
        vr_count = await import_vr_mappings(db)
        
        # Verify the import
        await verify_import(db)
        
        print("\n✅ Import complete!")
        print(f"   Total mappings imported: {ebay_count + shopify_count + vr_count}")


if __name__ == "__main__":
    asyncio.run(main())