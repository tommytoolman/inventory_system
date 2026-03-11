#!/usr/bin/env python3
"""
Test script to mark a Shopify product as sold (reduce inventory + update local DB)
Usage: python scripts/shopify/test_sync_shopify_sold.py [external_id]

Example:
python scripts/shopify/test_sync_shopify_sold.py 12069206032724
"""

import asyncio
import sys
import os
from typing import Optional

# Add the project root to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from sqlalchemy import text
from app.database import get_session
from app.core.config import get_settings

class ShopifySoldTester:
    
    def __init__(self):
        self.settings = get_settings()
    
    async def test_mark_as_sold(self, external_id: str) -> bool:
        """Test the complete mark as sold workflow"""
        try:
            print(f"🛍️ SHOPIFY MARK AS SOLD TEST")
            print(f"External ID: {external_id}")
            print("=" * 50)
            
            from app.services.shopify.client import ShopifyGraphQLClient
            shopify_client = ShopifyGraphQLClient()
            
            # Step 1: Get Shopify product info from database
            print(f"      🔍 Looking up Shopify product for external_id {external_id}...")
            
            async with get_session() as db:
                product_query = text("""
                SELECT 
                    sl.platform_id,
                    sl.shopify_product_id,
                    sl.handle,
                    sl.status as local_status,
                    pc.external_id
                FROM shopify_listings sl
                JOIN platform_common pc ON sl.platform_id = pc.id
                WHERE pc.external_id = :external_id 
                AND pc.platform_name = 'shopify'
                """)
                result = await db.execute(product_query, {"external_id": external_id})
                shopify_data = result.fetchone()
                
                if not shopify_data:
                    print(f"      ❌ Could not find Shopify product for external_id {external_id}")
                    return False
                
                platform_id = shopify_data.platform_id
                shopify_product_gid = shopify_data.shopify_product_id
                handle = shopify_data.handle
                local_status = shopify_data.local_status
                
                print(f"      📦 Found Shopify product:")
                print(f"         Platform ID (internal): {platform_id}")
                print(f"         Shopify GID: {shopify_product_gid}")
                print(f"         Handle: {handle}")
                print(f"         Local Status: {local_status}")
            
            # Step 2: Mark as sold via inventory reduction
            print(f"      📤 Marking product as sold (reducing inventory by 1)...")
            
            result = await shopify_client.mark_product_as_sold(shopify_product_gid, reduce_by=1)
            
            if result.get("success"):
                print(f"      ✅ Shopify API call successful!")
                print(f"      📊 New quantity: {result.get('new_quantity')}")
                print(f"      📊 Product status: {result.get('status')} (remains active)")
                
                # Step 3: Update local database only if Shopify API succeeded
                print(f"      📝 Updating local database...")
                async with get_session() as db:
                    # Update shopify_listings table
                    shopify_update_query = text("""
                    UPDATE shopify_listings 
                    SET status = 'SOLD_OUT',
                        updated_at = CURRENT_TIMESTAMP
                    WHERE platform_id = :platform_id
                    """)
                    await db.execute(shopify_update_query, {"platform_id": platform_id})
                    
                    # Update platform_common table
                    platform_update_query = text("""
                    UPDATE platform_common 
                    SET status = 'SOLD',
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = :platform_id
                    """)
                    await db.execute(platform_update_query, {"platform_id": platform_id})
                    
                    await db.commit()
                    print(f"      ✅ Updated shopify_listings status to 'SOLD_OUT'")
                    print(f"      ✅ Updated platform_common status to 'SOLD'")
                
                return True
            else:
                error_msg = result.get("error", "Unknown error")
                step = result.get("step", "unknown")
                print(f"      ❌ Shopify mark as sold failed at step '{step}': {error_msg}")
                return False
                
        except Exception as e:
            print(f"      ❌ Error: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    async def verify_sold_status(self, external_id: str):
        """Verify the current status after marking as sold"""
        try:
            print(f"\n🔍 VERIFICATION: Checking final status...")
            
            # Check local database
            async with get_session() as db:
                verify_query = text("""
                SELECT 
                    sl.platform_id,
                    sl.shopify_product_id,
                    sl.handle,
                    sl.status as local_status,
                    sl.updated_at,
                    pc.external_id
                FROM shopify_listings sl
                JOIN platform_common pc ON sl.platform_id = pc.id
                WHERE pc.external_id = :external_id 
                AND pc.platform_name = 'shopify'
                """)
                result = await db.execute(verify_query, {"external_id": external_id})
                shopify_data = result.fetchone()
                
                if shopify_data:
                    print(f"📊 Local Database Status:")
                    print(f"   External ID: {shopify_data.external_id}")
                    print(f"   Platform ID: {shopify_data.platform_id}")
                    print(f"   Handle: {shopify_data.handle}")
                    print(f"   Local Status: {shopify_data.local_status}")
                    print(f"   Updated: {shopify_data.updated_at}")
                    
                    # Check Shopify API status
                    print(f"\n📊 Shopify API Status:")
                    from app.services.shopify.client import ShopifyGraphQLClient
                    shopify_client = ShopifyGraphQLClient()
                    
                    shopify_product_gid = shopify_data.shopify_product_id
                    
                    verify_query = """
                    query getProductStatus($id: ID!) {
                      product(id: $id) {
                        id
                        title
                        status
                        variants(first: 1) {
                          edges {
                            node {
                              id
                              sku
                              inventoryQuantity
                            }
                          }
                        }
                      }
                    }
                    """
                    
                    api_result = shopify_client._make_request(verify_query, {"id": shopify_product_gid}, estimated_cost=5)
                    
                    if api_result and api_result.get("product"):
                        product = api_result["product"]
                        print(f"   Product Status: {product.get('status')}")
                        
                        if product.get("variants", {}).get("edges"):
                            variant = product["variants"]["edges"][0]["node"]
                            print(f"   Variant SKU: {variant.get('sku')}")
                            print(f"   Inventory Quantity: {variant.get('inventoryQuantity')}")
                            
                            # Determine if sold out
                            inventory_qty = variant.get('inventoryQuantity', 0)
                            is_sold_out = inventory_qty <= 0
                            print(f"   Sold Out: {'✅ YES' if is_sold_out else '❌ NO'}")
                else:
                    print(f"❌ No data found for external_id {external_id}")
                    
        except Exception as e:
            print(f"❌ Error during verification: {e}")

async def main():
    """Test Shopify mark as sold with command line argument"""
    
    if len(sys.argv) != 2:
        print("Usage: python scripts/shopify/test_sync_shopify_sold.py [external_id]")
        print("Example: python scripts/shopify/test_sync_shopify_sold.py 12069206032724")
        sys.exit(1)
    
    external_id = sys.argv[1]  # Shopify product ID
    
    tester = ShopifySoldTester()
    
    # Show current status first
    await tester.verify_sold_status(external_id)
    
    # Ask for confirmation
    confirm = input(f"\n❓ Mark Shopify product {external_id} as sold? (y/N): ").strip().lower()
    if confirm != 'y':
        print("❌ Operation cancelled")
        return
    
    # Test the mark as sold workflow
    success = await tester.test_mark_as_sold(external_id)
    
    # Verify the result
    await tester.verify_sold_status(external_id)
    
    if success:
        print(f"\n🎉 Test completed successfully!")
        print(f"✅ Product {external_id} marked as sold on Shopify")
        print(f"✅ Local database updated to SOLD_OUT")
    else:
        print(f"\n⚠️ Test completed with issues")

if __name__ == "__main__":
    asyncio.run(main())