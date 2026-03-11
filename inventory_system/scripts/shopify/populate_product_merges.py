#!/usr/bin/env python3
"""
Populate missing product_merges data for Reverb<->Shopify matches
Matches the exact schema of existing product_merges records
"""

import asyncio
import sys
import json
from pathlib import Path
from datetime import datetime
from sqlalchemy import text

# Add the parent directory to the path so we can import app modules
sys.path.append(str(Path(__file__).parent.parent))

from app.database import async_session

async def populate_reverb_shopify_matches():
    """Create missing product_merges entries for Reverb<->Shopify pairs"""
    print("🔧 Populating Reverb<->Shopify match records...")
    print("📋 Using existing schema: kept_product_id, merged_product_id, merged_product_data, merged_at, merged_by, reason")
    
    async with async_session() as db:
        # Find Reverb products that have corresponding Shopify products by SKU
        query = text("""
            WITH reverb_products AS (
                SELECT p.*, pc.platform_name
                FROM products p
                JOIN platform_common pc ON p.id = pc.product_id
                WHERE pc.platform_name = 'reverb'
            ),
            shopify_products AS (
                SELECT p.*, pc.platform_name
                FROM products p
                JOIN platform_common pc ON p.id = pc.product_id
                WHERE pc.platform_name = 'shopify'
            )
            SELECT 
                r.id as reverb_product_id,
                s.id as shopify_product_id,
                r.sku,
                r.title as reverb_title,
                s.title as shopify_title,
                row_to_json(r.*) as reverb_data
            FROM reverb_products r
            JOIN shopify_products s ON r.sku = s.sku
            WHERE NOT EXISTS (
                SELECT 1 FROM product_merges pm 
                WHERE pm.kept_product_id IN (r.id, s.id) 
                   OR pm.merged_product_id IN (r.id, s.id)
            )
            ORDER BY r.sku
            LIMIT 50  -- Start with 50 to test
        """)
        
        result = await db.execute(query)
        matches = result.fetchall()
        
        print(f"📋 Found {len(matches)} Reverb<->Shopify pairs to match")
        
        if len(matches) == 0:
            print("✅ No missing matches found - data is already correct!")
            return
        
        # Show a few examples
        print("\n📋 Sample matches to create:")
        for i, match in enumerate(matches[:3]):
            print(f"  {i+1}. SKU: {match.sku}")
            print(f"     Reverb: {match.reverb_title}")
            print(f"     Shopify: {match.shopify_title}")
        
        if len(matches) > 3:
            print(f"  ... and {len(matches) - 3} more")
        
        # Confirm before proceeding
        response = input(f"\n❓ Create {len(matches)} product_merges records? (y/N): ")
        if response.lower() != 'y':
            print("❌ Cancelled by user")
            return
        
        # Create the matches using the EXACT schema from your existing data
        current_time = datetime.now()
        created_count = 0
        
        for match in matches:
            reverb_id = match.reverb_product_id
            shopify_id = match.shopify_product_id
            sku = match.sku
            reverb_data = match.reverb_data
            
            try:
                # Insert merge record matching your exact schema
                # kept_product_id = Shopify (the "main" product)
                # merged_product_id = Reverb (the "merged" product)  
                # merged_product_data = JSON of the Reverb product data
                merge_insert = text("""
                    INSERT INTO product_merges (
                        kept_product_id, 
                        merged_product_id,
                        merged_product_data,
                        merged_at,
                        merged_by,
                        reason
                    ) VALUES (
                        :kept_id,
                        :merged_id, 
                        :merged_data,
                        :merged_at,
                        :merged_by,
                        :reason
                    )
                """)
                
                await db.execute(merge_insert, {
                    "kept_id": shopify_id,  # Keep Shopify product
                    "merged_id": reverb_id,  # Merge Reverb product
                    "merged_data": json.dumps(reverb_data),  # JSON string of Reverb data
                    "merged_at": current_time,
                    "merged_by": "reverb_shopify_import_backfill",  # Clear source identifier
                    "reason": "Reverb to Shopify import synchronization"  # Clear reason
                })
                
                created_count += 1
                
                if created_count % 10 == 0:
                    print(f"  📝 Created {created_count}/{len(matches)} matches...")
                
            except Exception as e:
                print(f"❌ Error matching SKU {sku}: {str(e)}")
                continue
        
        await db.commit()
        print(f"\n🎉 Successfully created {created_count} product matches!")
        
        # Show the result
        await verify_results(db)

async def verify_results(db):
    """Verify the results match expectations"""
    print("\n🔍 Verifying results...")
    
    # Check total merge count
    count_query = text("SELECT COUNT(*) as total FROM product_merges")
    result = await db.execute(count_query)
    total_count = result.fetchone().total
    print(f"📊 Total product_merges records: {total_count}")
    
    # Check by source
    source_query = text("""
        SELECT merged_by, COUNT(*) as count
        FROM product_merges 
        GROUP BY merged_by 
        ORDER BY count DESC
    """)
    result = await db.execute(source_query)
    sources = result.fetchall()
    
    print("📊 Merge records by source:")
    for source in sources:
        print(f"  {source.merged_by}: {source.count}")
    
    # Check platform status
    platform_query = text("""
        SELECT 
            pc.platform_name,
            COUNT(*) as total_products,
            COUNT(pm.kept_product_id) + COUNT(pm.merged_product_id) as in_merges
        FROM products p
        JOIN platform_common pc ON p.id = pc.product_id
        LEFT JOIN product_merges pm ON (p.id = pm.kept_product_id OR p.id = pm.merged_product_id)
        GROUP BY pc.platform_name
        ORDER BY pc.platform_name
    """)
    
    result = await db.execute(platform_query)
    platforms = result.fetchall()
    
    print("\n📊 Platform matching status:")
    for platform in platforms:
        percentage = (platform.in_merges / platform.total_products * 100) if platform.total_products > 0 else 0
        print(f"  {platform.platform_name}: {platform.in_merges}/{platform.total_products} ({percentage:.1f}% matched)")

async def main():
    """Main function"""
    print("🔧 Reverb<->Shopify Product Merge Populator")
    print("=" * 50)
    print("📋 Schema: kept_product_id | merged_product_id | merged_product_data | merged_at | merged_by | reason")
    print("📋 Logic: Shopify (kept) ← Reverb (merged)")
    print()
    
    try:
        await populate_reverb_shopify_matches()
        print("\n✅ Population complete!")
        print("🌐 Your matching interface should now show correct statistics")
        
    except Exception as e:
        print(f"\n💥 Error: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())