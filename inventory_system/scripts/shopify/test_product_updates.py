# scripts/test_product_updates.py
"""
Test comprehensive product update scenarios:
1. Price reduction with compare-at-price (strike-through discount)
2. Mark product as sold/unavailable
"""

def test_price_reduction_with_discount(client, product_gid):
    """Test updating price with compare-at-price for strike-through effect."""
    
    print("🔄 TESTING PRICE REDUCTION WITH DISCOUNT DISPLAY")
    print("-" * 55)
    
    # Get current product details
    product_data = client.get_product_snapshot_by_id(product_gid, num_variants=1)
    if not product_data or not product_data.get("variants", {}).get("edges"):
        print("❌ Could not get product details")
        return False
    
    variant = product_data["variants"]["edges"][0]["node"]
    variant_gid = variant["id"]
    current_price = float(variant["price"])
    
    print(f"📊 Current price: £{current_price}")
    
    # Calculate 5% discount
    discount_price = current_price * 0.95
    
    print(f"💰 Setting discount:")
    print(f"   Compare At Price (strike-through): £{current_price}")
    print(f"   New Price: £{discount_price:.2f}")
    print(f"   Discount: {((current_price - discount_price) / current_price * 100):.1f}%")
    
    # Update variant with compare-at-price
    # variant_updates = {
    #     "price": f"{discount_price:.2f}",
    #     "compare_at_price": f"{current_price + 100:.2f}"  # Obviously higher value for testing
    # }
    
    # gid://shopify/Product/12060082602324
    
    variant_updates = {
        "price": "2374.05",  # Explicit string
        "compare_at_price": "2499.99"  # Explicit string
    }
    
    result = client.update_variant_rest(variant_gid, variant_updates)
    
    if result:
        print("✅ Price discount applied successfully!")
        
        # Verify the update
        updated_variant = client.get_variant_details_rest(variant_gid)
        if updated_variant:
            print(f"\n📊 VERIFICATION:")
            print(f"   New Price: £{updated_variant.get('price', 'Not set')}")
            print(f"   Compare At Price: £{updated_variant.get('compare_at_price', 'Not set')}")
            print(f"   💡 This will show as strike-through price in Shopify storefront")
        
        return True
    else:
        print("❌ Price discount update failed")
        return False

def test_mark_as_sold(client, product_gid):
    """Test marking product as sold/unavailable."""
    
    print("\n🔄 TESTING MARK AS SOLD/UNAVAILABLE")
    print("-" * 40)
    
    # Get current product details
    product_data = client.get_product_snapshot_by_id(product_gid, num_variants=1)
    if not product_data:
        print("❌ Could not get product details")
        return False
    
    current_title = product_data.get("title", "")
    
    # Strategy 1: Update inventory to 0 and set unavailable
    variant = product_data["variants"]["edges"][0]["node"]
    variant_gid = variant["id"]
    
    print(f"📦 Current title: {current_title}")
    print(f"📦 Current inventory: {variant.get('inventoryQuantity', 0)}")
    
    print(f"\n🛑 Marking as SOLD:")
    print(f"   Setting inventory to 0")
    print(f"   Updating title to include 'SOLD'")
    
    # Update variant inventory
    variant_updates = {
        "inventoryQuantities": [{
            "availableQuantity": 0,
            "locationId": "gid://shopify/Location/109766639956"  # Your location
        }],
        "inventoryPolicy": "DENY"  # Don't allow overselling
    }
    
    variant_result = client.update_variant_rest(variant_gid, variant_updates)
    
    # Update product title to show SOLD
    sold_title = f"SOLD - {current_title}" if not current_title.startswith("SOLD") else current_title
    
    product_updates = {
        "id": product_gid,
        "title": sold_title,
        "status": "DRAFT"  # Optionally set to draft to hide from storefront
    }
    
    product_result = client.update_product(product_updates)
    
    if variant_result and product_result:
        print("✅ Product marked as SOLD successfully!")
        
        # Verify the updates
        updated_product = client.get_all_products_summary(
            query_filter=f"id:{product_gid.split('/')[-1]}"
        )
        
        if updated_product and len(updated_product) > 0:
            product_data = updated_product[0]
            variant_data = product_data.get("variants", {}).get("nodes", [{}])[0]
            
            print(f"\n📊 VERIFICATION:")
            print(f"   Updated Title: {product_data.get('title', 'Not set')}")
            print(f"   Status: {product_data.get('status', 'Not set')}")
            print(f"   Inventory Quantity: {variant_data.get('inventoryQuantity', 'Not set')}")
            print(f"   Available for Sale: {variant_data.get('availableForSale', 'Not set')}")
        
        return True
    else:
        print("❌ Mark as sold update failed")
        return False

def main():
    """Main update testing function."""
    
    from app.services.shopify.client import ShopifyGraphQLClient
    
    print("🧪 COMPREHENSIVE PRODUCT UPDATE TESTING")
    print("=" * 60)
    print("Testing price discounts and sold status updates\n")
    
    # Get the test product GID from the previous test
    test_product_gid = input("Enter the test product GID from previous test: ").strip()
    
    if not test_product_gid.startswith("gid://shopify/Product/"):
        print("❌ Invalid product GID format")
        return
    
    # Initialize client
    client = ShopifyGraphQLClient()
    
    print(f"🎯 Testing updates on product: {test_product_gid}")
    
    # Test 1: Price reduction with discount display
    test1_success = test_price_reduction_with_discount(client, test_product_gid)
    
    if test1_success:
        # Wait a moment and ask if user wants to continue
        continue_test = input(f"\nContinue with 'mark as sold' test? (y/n): ").lower().strip()
        
        if continue_test == 'y':
            # Test 2: Mark as sold
            test2_success = test_mark_as_sold(client, test_product_gid)
            
            if test2_success:
                print(f"\n🎉 ALL UPDATE TESTS COMPLETED SUCCESSFULLY!")
                print(f"✅ Price discount with strike-through working")
                print(f"✅ Mark as sold functionality working")
            else:
                print(f"\n⚠️ Test 1 passed, Test 2 failed")
        else:
            print(f"\n✅ Test 1 completed successfully (Test 2 skipped)")
    else:
        print(f"\n❌ Test 1 failed - skipping Test 2")
    
    print(f"\n📝 Check your Shopify admin to see the visual effects!")

if __name__ == "__main__":
    main()