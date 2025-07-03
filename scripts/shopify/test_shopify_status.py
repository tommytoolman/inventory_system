#!/usr/bin/env python3
"""
Test script to update Shopify product status to ARCHIVED
Usage: python scripts/shopify/test_shopify_status.py [product_id]
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from sqlalchemy import text
from app.database import get_session
from app.core.config import get_settings

class ShopifyStatusTester:
    
    def __init__(self):
        self.settings = get_settings()
    
    async def test_status_update(self, product_id: str) -> bool:
        """Test updating status to ARCHIVED only"""
        try:
            print(f"📋 SHOPIFY STATUS UPDATE TEST")
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
                print(f"      📊 Current local status: {data.status}")
            
            # ONLY update status - no inventory change
            print(f"      📤 Setting status to ARCHIVED...")
            
            # Use direct GraphQL mutation for precise control
            mutation = """
            mutation productUpdate($input: ProductInput!) {
              productUpdate(input: $input) {
                product {
                  id
                  status
                  title
                  updatedAt
                }
                userErrors {
                  field
                  message
                }
              }
            }
            """
            
            variables = {
                "input": {
                    "id": shopify_product_gid,
                    "status": "ARCHIVED"
                }
            }
            
            result = shopify_client._make_request(mutation, variables, estimated_cost=10)
            print(f"      📊 GraphQL result: {result}")
            
            if result and result.get("productUpdate"):
                product_data = result["productUpdate"].get("product", {})
                user_errors = result["productUpdate"].get("userErrors", [])
                
                if user_errors:
                    print(f"      ❌ GraphQL errors: {user_errors}")
                    return False
                elif product_data.get("status") == "ARCHIVED":
                    print(f"      ✅ Status successfully changed to ARCHIVED")
                    return True
                else:
                    print(f"      ⚠️  Status in response: {product_data.get('status')} - verifying...")
                    # Continue to verification step below
            else:
                print(f"      ❌ Status update failed - no product data returned")
                return False
                
        except Exception as e:
            print(f"      ❌ Error: {e}")
            import traceback
            traceback.print_exc()
            return False

    async def verify_status(self, product_id: str) -> dict:
        """Read-only check of actual product status"""
        try:
            print(f"\n🔍 VERIFICATION: Checking actual product status...")
            
            shopify_product_gid = f"gid://shopify/Product/{product_id}"
            
            from app.services.shopify.client import ShopifyGraphQLClient
            shopify_client = ShopifyGraphQLClient()
            
            # Simple, reliable GraphQL query for product status
            status_query = """
            query getProductStatus($id: ID!) {
              product(id: $id) {
                id
                title
                status
                updatedAt
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
            
            variables = {"id": shopify_product_gid}
            result = shopify_client._make_request(status_query, variables, estimated_cost=5)
            
            if result and result.get("product"):
                product = result["product"]
                print(f"📊 Product: {product.get('title')}")
                print(f"📊 Product Status: {product.get('status')}")
                print(f"📊 Updated At: {product.get('updatedAt')}")
                
                # Get variant info if available
                if product.get("variants", {}).get("edges"):
                    variant = product["variants"]["edges"][0]["node"]
                    print(f"📊 Variant SKU: {variant.get('sku')}")
                    print(f"📊 Inventory Quantity: {variant.get('inventoryQuantity')}")
                
                return {
                    "product_status": product.get('status'),
                    "title": product.get('title'),
                    "updated_at": product.get('updatedAt'),
                    "variant_sku": variant.get('sku') if product.get("variants", {}).get("edges") else None,
                    "inventory_quantity": variant.get('inventoryQuantity') if product.get("variants", {}).get("edges") else None
                }
            else:
                print(f"❌ Could not retrieve product data")
                return {}
                
        except Exception as e:
            print(f"❌ Verification error: {e}")
            return {}

async def main():
    if len(sys.argv) != 2:
        print("Usage: python scripts/shopify/test_shopify_status.py [product_id]")
        sys.exit(1)
    
    product_id = sys.argv[1]
    tester = ShopifyStatusTester()
    
    # Check current status BEFORE update
    print(f"🔍 BEFORE UPDATE:")
    before_data = await tester.verify_status(product_id)
    
    # Run the status update
    print(f"\n🧪 Testing status update ONLY (no inventory change)")
    success = await tester.test_status_update(product_id)
    
    # Check status AFTER update
    print(f"\n🔍 AFTER UPDATE:")
    after_data = await tester.verify_status(product_id)
    
    # Compare results
    if before_data and after_data:
        print(f"\n📊 COMPARISON:")
        print(f"   Status Before: {before_data.get('product_status', 'N/A')}")
        print(f"   Status After:  {after_data.get('product_status', 'N/A')}")
        print(f"   Updated At Before: {before_data.get('updated_at', 'N/A')}")
        print(f"   Updated At After:  {after_data.get('updated_at', 'N/A')}")
        
        # Check if status actually changed
        status_changed = before_data.get('product_status') != after_data.get('product_status')
        print(f"   Status Changed: {'✅ YES' if status_changed else '❌ NO'}")
    
    print(f"\n{'✅ SUCCESS' if success else '❌ FAILED'}: Status test")

if __name__ == '__main__':
    asyncio.run(main())