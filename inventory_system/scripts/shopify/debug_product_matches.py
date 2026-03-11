#!/usr/bin/env python3
"""
Debug script to check REAL Reverb<->Shopify product matching data
"""

import asyncio
import sys
from pathlib import Path
from sqlalchemy import text

sys.path.append(str(Path(__file__).parent.parent))
from app.database import async_session

async def debug_real_products():
    """Debug what products we actually have in platform-specific tables"""
    print("🔍 Debugging REAL Product Data (from platform tables)")
    print("=" * 60)
    
    async with async_session() as db:
        
        # Check sample Reverb products with actual data
        print("📋 Sample Reverb products (from reverb_listings):")
        reverb_query = text("""
            SELECT 
                p.id, 
                p.sku, 
                rl.reverb_listing_id,
                rl.list_price,
                rl.reverb_state,
                p.title as product_title,
                p.brand,
                p.model
            FROM products p
            JOIN platform_common pc ON p.id = pc.product_id
            JOIN reverb_listings rl ON pc.id = rl.platform_id
            WHERE pc.platform_name = 'reverb'
            LIMIT 5
        """)
        result = await db.execute(reverb_query)
        reverb_products = result.fetchall()
        
        for product in reverb_products:
            print(f"  ID: {product.id}")
            print(f"    SKU: {product.sku}")
            print(f"    Reverb Listing ID: {product.reverb_listing_id}")
            print(f"    Price: £{product.list_price}")
            print(f"    State: {product.reverb_state}")
            print(f"    Product Title: {product.product_title}")
            print(f"    Brand: {product.brand}")
            print()
        
        # Check sample Shopify products with actual data
        print("📋 Sample Shopify products (from shopify_listings):")
        shopify_query = text("""
            SELECT 
                p.id, 
                p.sku, 
                sl.shopify_product_id,
                sl.price,
                sl.status,
                sl.title as shopify_title,
                sl.handle,
                p.title as product_title,
                p.brand,
                p.model
            FROM products p
            JOIN platform_common pc ON p.id = pc.product_id
            JOIN shopify_listings sl ON pc.id = sl.platform_id
            WHERE pc.platform_name = 'shopify'

        """)
        result = await db.execute(shopify_query)
        shopify_products = result.fetchall()
        
        for product in shopify_products:
            print(f"  ID: {product.id}")
            print(f"    SKU: {product.sku}")
            print(f"    Shopify Product ID: {product.shopify_product_id}")
            print(f"    Price: £{product.price}")
            print(f"    Status: {product.status}")
            print(f"    Shopify Title: {product.shopify_title}")
            print(f"    Handle: {product.handle}")
            print(f"    Product Title: {product.product_title}")
            print()
        
        # Check if we have perfect matches (same product_id with different platforms)
        print("🎯 Checking for SAME product with different platforms:")
        same_product_query = text("""
            SELECT 
                p.id as product_id,
                p.sku,
                COUNT(DISTINCT pc.platform_name) as platform_count,
                STRING_AGG(DISTINCT pc.platform_name, ', ') as platforms
            FROM products p
            JOIN platform_common pc ON p.id = pc.product_id
            WHERE pc.platform_name IN ('reverb', 'shopify')
            GROUP BY p.id, p.sku
            HAVING COUNT(DISTINCT pc.platform_name) > 1

        """)
        result = await db.execute(same_product_query)
        same_products = result.fetchall()
        
        if same_products:
            print(f"  Found {len(same_products)} products that exist on BOTH platforms:")
            for product in same_products:
                print(f"    Product ID: {product.product_id}, SKU: {product.sku}")
                print(f"      Platforms: {product.platforms}")
                print()
        else:
            print("  ❌ No products found that exist on BOTH platforms!")
            print("  This means each product_id is unique to one platform")
        
        # Check the relationship structure
        print("📊 Platform relationship analysis:")
        relationship_query = text("""
            SELECT 
                pc.platform_name,
                COUNT(DISTINCT p.id) as unique_products,
                COUNT(DISTINCT p.sku) as unique_skus,
                COUNT(*) as total_platform_records
            FROM products p
            JOIN platform_common pc ON p.id = pc.product_id
            WHERE pc.platform_name IN ('reverb', 'shopify')
            GROUP BY pc.platform_name
        """)
        result = await db.execute(relationship_query)
        relationships = result.fetchall()
        
        for rel in relationships:
            print(f"  {rel.platform_name}:")
            print(f"    Unique products: {rel.unique_products}")
            print(f"    Unique SKUs: {rel.unique_skus}")
            print(f"    Platform records: {rel.total_platform_records}")

async def main():
    try:
        await debug_real_products()
    except Exception as e:
        print(f"\n💥 Error: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())