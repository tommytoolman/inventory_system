#!/usr/bin/env python3
"""
Test script to update Shopify product inventory to 0
Usage: python scripts/shopify/test_shopify_inventory.py [product_id]
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from sqlalchemy import text
from app.database import get_session
from app.core.config import get_settings

class ShopifyInventoryTester:
    
    def __init__(self):
        self.settings = get_settings()
    
    async def test_inventory_update(self, product_id: str) -> bool:
        """Test updating inventory to 0 only"""
        try:
            print(f"📦 SHOPIFY INVENTORY UPDATE TEST")
            print(f"Product ID: {product_id}")
            print("=" * 50)
            
            shopify_product_gid = f"gid://shopify/Product/{product_id}"
            print(f"      🔗 Shopify GID: {shopify_product_gid}")
            
            from app.services.shopify.client import ShopifyGraphQLClient
            shopify_client = ShopifyGraphQLClient()
            
            # Get current product info
            async with get_session() as db:
                query = text("""
                SELECT platform_id, shopify_product_id, handle, status
                FROM shopify_listings 
                WHERE shopify_product_id = :shopify_gid
                """)
                result = await db.execute(query, {"shopify_gid": shopify_product_gid})
                data = result.fetchone()
                
                if not data:
                    print(f"      ❌ Product not found")
                    return False
                
                print(f"      📦 Found: {data.handle}")
                print(f"      📊 Current status: {data.status}")
            
            # ONLY update inventory - no status change
            print(f"      📤 Setting inventory to 0...")
            
            inventory_updates = {
                "inventory": 0,
                "tags": ["inventory-test", f"updated-{int(asyncio.get_event_loop().time())}"]
            }
            
            result = shopify_client.update_complete_product(shopify_product_gid, inventory_updates)
            
            if result:
                print(f"      ✅ Inventory update completed")
                return True
            else:
                print(f"      ❌ Inventory update failed")
                return False
                
        except Exception as e:
            print(f"      ❌ Error: {e}")
            import traceback
            traceback.print_exc()
            return False

    async def verify_inventory_status(self, product_id: str) -> dict:
        """Read-only check of actual inventory status"""
        try:
            print(f"\n🔍 VERIFICATION: Checking actual inventory status...")
            
            shopify_product_gid = f"gid://shopify/Product/{product_id}"
            
            from app.services.shopify.client import ShopifyGraphQLClient
            shopify_client = ShopifyGraphQLClient()
            
            # CORRECT GraphQL query using actual Shopify API fields
            inventory_query = """
            query getProductInventory($id: ID!) {
            product(id: $id) {
                id
                title
                status
                variants(first: 10) {
                edges {
                    node {
                    id
                    sku
                    price
                    inventoryQuantity
                    inventoryPolicy
                    inventoryItem {
                        id
                        tracked
                        inventoryLevels(first: 10) {
                        edges {
                            node {
                            id
                            quantities(names: "available") {
                                quantity
                                name
                            }
                            location {
                                id
                                name
                            }
                            }
                        }
                        }
                    }
                    }
                }
                }
            }
            }
            """
            
            variables = {"id": shopify_product_gid}
            result = shopify_client._make_request(inventory_query, variables, estimated_cost=15)
            
            if result and result.get("product"):
                product = result["product"]
                print(f"📊 Product: {product.get('title')}")
                print(f"📊 Product Status: {product.get('status')}")
                
                if product.get("variants", {}).get("edges"):
                    for variant_edge in product["variants"]["edges"]:
                        variant = variant_edge["node"]
                        
                        print(f"\n🔧 Variant Details:")
                        print(f"   SKU: {variant.get('sku')}")
                        print(f"   Price: £{variant.get('price')}")
                        print(f"   Inventory Quantity: {variant.get('inventoryQuantity')}")
                        print(f"   Inventory Policy: {variant.get('inventoryPolicy')}")
                        
                        inventory_item = variant.get("inventoryItem", {})
                        print(f"   Inventory Tracked: {inventory_item.get('tracked')}")
                        
                        if inventory_item.get("inventoryLevels", {}).get("edges"):
                            print(f"   📍 Location Inventory:")
                            for level_edge in inventory_item["inventoryLevels"]["edges"]:
                                level = level_edge["node"]
                                location = level.get("location", {})
                                quantities = level.get("quantities", [])
                                
                                available_qty = None
                                for qty in quantities:
                                    if qty.get("name") == "available":
                                        available_qty = qty.get("quantity")
                                        break
                                
                                print(f"      {location.get('name', 'Unknown')}: {available_qty} available")
                        
                        # Return summary data
                        return {
                            "product_status": product.get('status'),
                            "variant_id": variant.get('id'),
                            "sku": variant.get('sku'),
                            "inventory_quantity": variant.get('inventoryQuantity'),
                            "inventory_policy": variant.get('inventoryPolicy'),
                            "inventory_tracked": inventory_item.get('tracked'),
                            "locations": [
                                {
                                    "name": level["node"]["location"]["name"],
                                    "available": next(
                                        (qty["quantity"] for qty in level["node"].get("quantities", []) 
                                        if qty.get("name") == "available"), 
                                        None
                                    )
                                }
                                for level in inventory_item.get("inventoryLevels", {}).get("edges", [])
                            ]
                        }
                else:
                    print(f"❌ No variants found")
                    return {}
            else:
                print(f"❌ Could not retrieve product data")
                return {}
                
        except Exception as e:
            print(f"❌ Verification error: {e}")
            return {}

async def main():
    if len(sys.argv) != 2:
        print("Usage: python scripts/shopify/test_shopify_inventory.py [product_id]")
        sys.exit(1)
    
    product_id = sys.argv[1]
    tester = ShopifyInventoryTester()
    
    # Check current status BEFORE update
    print(f"🔍 BEFORE UPDATE:")
    before_data = await tester.verify_inventory_status(product_id)
    
    # Run the inventory update
    print(f"\n🧪 Testing inventory update ONLY (no status change)")
    success = await tester.test_inventory_update(product_id)
    
    # Check status AFTER update
    print(f"\n🔍 AFTER UPDATE:")
    after_data = await tester.verify_inventory_status(product_id)
    
    # Compare results
    if before_data and after_data:
        print(f"\n📊 COMPARISON:")
        print(f"   Inventory Before: {before_data.get('inventory_quantity', 'N/A')}")
        print(f"   Inventory After:  {after_data.get('inventory_quantity', 'N/A')}")
        
        if before_data.get('locations') and after_data.get('locations'):
            for i, (before_loc, after_loc) in enumerate(zip(before_data['locations'], after_data['locations'])):
                print(f"   Location {before_loc['name']}:")
                print(f"      Before: {before_loc['available']} → After: {after_loc['available']}")
    
    print(f"\n{'✅ SUCCESS' if success else '❌ FAILED'}: Inventory test")

if __name__ == '__main__':
    asyncio.run(main())