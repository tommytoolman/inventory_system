#!/usr/bin/env python3
"""
Test script to archive a single Shopify product
Usage: python scripts/test_shopify_archive.py [platform_id]

Example:
python scripts/test_shopify_archive.py 12069206032724
"""

import asyncio
import sys
import os
from typing import Optional

# Add the project root to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from sqlalchemy import text
from app.database import get_session
from app.core.config import get_settings

class ShopifyArchiveTester:
    
    def __init__(self):
        self.settings = get_settings()
    
    async def test_archive_product(self, product_id: str, sku: str = "TEST") -> bool:
        """Test archiving a single Shopify product using product_id"""
        try:
            print(f"🛍️ SHOPIFY ARCHIVE TEST")
            print(f"Product ID: {product_id}")
            print(f"SKU: {sku}")
            print("=" * 50)
            
            # Create the full Shopify GID
            shopify_product_gid = f"gid://shopify/Product/{product_id}"
            print(f"      🔗 Shopify GID: {shopify_product_gid}")
            
            print(f"      🔌 Connecting to Shopify GraphQL API...")
            
            from app.services.shopify.client import ShopifyGraphQLClient
            shopify_client = ShopifyGraphQLClient()
            
            # Get Shopify product data directly by shopify_product_id
            print(f"      🔍 Looking up Shopify product...")
            
            async with get_session() as db:
                product_query = text("""
                SELECT platform_id, shopify_product_id, handle, status
                FROM shopify_listings 
                WHERE shopify_product_id = :shopify_gid
                """)
                result = await db.execute(product_query, {"shopify_gid": shopify_product_gid})
                shopify_data = result.fetchone()
                
                if not shopify_data:
                    print(f"      ❌ Could not find Shopify product {shopify_product_gid}")
                    return False
                
                platform_id = shopify_data.platform_id
                current_status = shopify_data.status
                handle = shopify_data.handle
                
                print(f"      📦 Found Shopify product:")
                print(f"         Platform ID (internal): {platform_id}")
                print(f"         Handle: {handle}")
                print(f"         Current Status: {current_status}")
            
            # Archive the product
            print(f"      📤 Archiving Shopify product...")
            
            product_updates = {
                "status": "ARCHIVED",
                "inventory": 0,
                "tags": ["sold-on-reverb", "auto-synced-test"]
            }
            
            success = shopify_client.update_complete_product(shopify_product_gid, product_updates)
            
            if success:
                print(f"      ✅ Shopify API call successful!")
                
                # Update local database using the internal platform_id
                async with get_session() as db:
                    update_query = text("""
                    UPDATE shopify_listings 
                    SET status = 'ARCHIVED',
                        updated_at = CURRENT_TIMESTAMP
                    WHERE platform_id = :platform_id
                    """)
                    await db.execute(update_query, {"platform_id": platform_id})
                    await db.commit()
                    print(f"      📝 Updated local Shopify status to 'ARCHIVED'")
                
                return True
            else:
                print(f"      ❌ Shopify API call failed")
                return False
                
        except Exception as e:
            print(f"      ❌ Shopify error: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    
    async def verify_archive_status(self, product_id: str):
        """Check the current status of the product using shopify_product_id"""
        try:
            print(f"\n🔍 VERIFICATION: Checking current status...")
            
            # Create the full Shopify GID
            shopify_gid = f"gid://shopify/Product/{product_id}"
            
            async with get_session() as db:
                verify_query = text("""
                SELECT platform_id, shopify_product_id, handle, status, updated_at
                FROM shopify_listings 
                WHERE shopify_product_id = :shopify_gid
                """)
                result = await db.execute(verify_query, {"shopify_gid": shopify_gid})
                shopify_data = result.fetchone()
                
                if shopify_data:
                    print(f"📊 Current local database status:")
                    print(f"   Platform ID (internal): {shopify_data.platform_id}")
                    print(f"   Shopify GID: {shopify_data.shopify_product_id}")
                    print(f"   Handle: {shopify_data.handle}")
                    print(f"   Status: {shopify_data.status}")
                    print(f"   Updated: {shopify_data.updated_at}")
                else:
                    print(f"❌ No data found for shopify_product_id {shopify_gid}")
                    
        except Exception as e:
            print(f"❌ Error during verification: {e}")

async def main():
    """Test Shopify archiving with command line argument"""
    
    if len(sys.argv) != 2:
        print("Usage: python scripts/test_shopify_archive.py [product_id]")
        print("Example: python scripts/test_shopify_archive.py 12069206032724")
        sys.exit(1)
    
    product_id = sys.argv[1]  # Just the numeric part
    
    tester = ShopifyArchiveTester()
    
    # Show current status first
    await tester.verify_archive_status(product_id)
    
    # Ask for confirmation
    confirm = input(f"\n❓ Archive Shopify product {product_id}? (y/N): ").strip().lower()
    if confirm != 'y':
        print("❌ Operation cancelled")
        return
    
    # Test the archive
    success = await tester.test_archive_product(product_id, sku="REV-90271822")
    
    # Verify the result
    await tester.verify_archive_status(product_id)
    
    if success:
        print(f"\n🎉 Test completed successfully!")
        print(f"✅ Product {product_id} should now be archived on Shopify")
    else:
        print(f"\n⚠️ Test completed with issues")

if __name__ == "__main__":
    asyncio.run(main())