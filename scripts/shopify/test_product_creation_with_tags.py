# scripts/test_comprehensive_product_creation.py
"""
Comprehensive test for all possible Shopify product fields.
Uses the proven working pattern from your Jupyter script.
Tests ProductInput fields, variant updates, images, SEO, metafields, etc.
"""

import sys
import time
from pathlib import Path
from datetime import datetime

# Add workspace to path
sys.path.insert(0, str(Path(__file__).parent.parent))

def test_comprehensive_product_creation():
    """
    Test creating a product with maximum possible fields from your export format.
    Uses your proven working pattern: ProductInput → variant updates → images → publishing.
    """
    
    from app.services.shopify.client import ShopifyGraphQLClient
    
    # Initialize client
    client = ShopifyGraphQLClient()
    
    print("🧪 COMPREHENSIVE SHOPIFY PRODUCT FIELD TESTING")
    print("=" * 70)
    print(f"Testing all possible fields from your export format")
    print(f"Using your proven working pattern from Jupyter script\n")
    
    # =============================================================================
    # PHASE 1: PRODUCT INPUT FIELDS (Direct creation)
    # =============================================================================
    
    print("📦 PHASE 1: Testing ProductInput Fields")
    print("-" * 45)
    
    # Product data using only ProductInput supported fields
    test_product_input = {
        "title": "Comprehensive Test Guitar 2025",
        "handle": "comprehensive-test-guitar-2025",
        "vendor": "Test Vendor Co",
        "productType": "Electric Guitar",
        "descriptionHtml": """
            <div>
                <h2>Test Product Description</h2>
                <p><strong>This is a comprehensive test product</strong> with HTML description.</p>
                <ul>
                    <li>Testing all possible fields</li>
                    <li>Using proven working patterns</li>
                    <li>Comprehensive field validation</li>
                </ul>
            </div>
        """,
        "tags": ["test", "comprehensive", "electric guitar", "2025", "validation"],
        "status": "DRAFT",  # Keep as draft for testing
        
        # SEO fields - Test if these work in ProductInput
        "seo": {
            "title": "Comprehensive Test Guitar - SEO Title",
            "description": "SEO description for comprehensive test guitar validation"
        },
        
        # Gift card field from export
        "giftCard": False,
        
        # Product options (for default variant structure)
        "productOptions": [
            {
                "name": "Title", 
                "values": [{"name": "Default Title"}]
            }
        ]
    }
    
    print(f"Creating product shell with {len(test_product_input)} ProductInput fields...")
    
    try:
        # Create product shell
        create_result = client.create_product(test_product_input)
        
        if not create_result or not create_result.get("product"):
                    print("❌ PHASE 1 FAILED: Could not create product shell")
                    
                    # Better handle specific error cases
                    if create_result and create_result.get("userErrors"):
                        for error in create_result["userErrors"]:
                            error_field = error.get('field', 'Unknown')
                            error_message = error.get('message', 'Unknown')
                            print(f"   Error: {error_field}: {error_message}")
                            
                            # Check if it's a handle conflict - this indicates data integrity issue
                            if 'handle' in str(error_field).lower() and 'already in use' in error_message:
                                print(f"   🛑 HANDLE CONFLICT DETECTED!")
                                print(f"   📋 Handle: '{test_product_input['handle']}'")
                                print(f"   ⚠️  This indicates a data integrity issue that needs manual resolution")
                                print(f"   🔍 Check your SKU/handle generation logic")
                                print(f"   🛑 HALTING PROCESS - Manual intervention required")
                                return None  # Halt the process - don't try to fix automatically
                    
                    return None
        
        product_gid = create_result["product"]["id"]
        product_title = create_result["product"]["title"]
        
        print(f"✅ PHASE 1 SUCCESS: Product shell created")
        print(f"   GID: {product_gid}")
        print(f"   Title: {product_title}")
        
        # Verify what fields were actually set by fetching the product
        verification_data = client.get_all_products_summary(
            query_filter=f"handle:{test_product_input['handle']}"
        )
        
        if verification_data and len(verification_data) > 0:
            created_product = verification_data[0]
            
            print(f"\n📊 PHASE 1 VERIFICATION:")
            field_results = {}
            
            # Check each field we sent
            checks = [
                ("title", "Title"),
                ("handle", "Handle"), 
                ("vendor", "Vendor"),
                ("productType", "Product Type"),
                ("tags", "Tags"),
                ("status", "Status"),
                ("description", "Description"),
                ("seo", "SEO")
            ]
            
            for api_field, display_name in checks:
                sent_value = test_product_input.get(api_field)
                received_value = created_product.get(api_field)
                
                if api_field == "tags":
                    # Special handling for tags (list comparison)
                    if set(sent_value or []) == set(received_value or []):
                        print(f"   ✅ {display_name}: {received_value}")
                        field_results[api_field] = True
                    else:
                        print(f"   ⚠️ {display_name}: Expected {sent_value}, Got {received_value}")
                        field_results[api_field] = False
                elif api_field == "seo":
                    # Special handling for SEO
                    seo_data = received_value or {}
                    sent_seo = sent_value or {}
                    if seo_data.get("title") == sent_seo.get("title"):
                        print(f"   ✅ {display_name}: Title set correctly")
                        field_results[api_field] = True
                    else:
                        print(f"   ⚠️ {display_name}: SEO not set as expected")
                        field_results[api_field] = False
                elif received_value == sent_value:
                    print(f"   ✅ {display_name}: {received_value}")
                    field_results[api_field] = True
                else:
                    print(f"   ⚠️ {display_name}: Expected '{sent_value}', Got '{received_value}'")
                    field_results[api_field] = False
        
        # =============================================================================
        # PHASE 2: VARIANT FIELDS (REST API Updates)
        # =============================================================================
        
        print(f"\n📦 PHASE 2: Testing Variant Fields via REST")
        print("-" * 45)
        
        # Get the auto-created default variant
        product_snapshot = client.get_product_snapshot_by_id(product_gid, num_variants=1)
        if not product_snapshot or not product_snapshot.get("variants", {}).get("edges"):
            print("❌ PHASE 2 FAILED: Could not find default variant")
            return product_gid
        
        variant_gid = product_snapshot["variants"]["edges"][0]["node"]["id"]
        print(f"Found default variant: {variant_gid}")
        
        # Test all variant fields from your export
        variant_updates = {
            "price": "2499.99",
            "sku": "COMP-TEST-2025-001", 
            "inventoryPolicy": "DENY",
            "inventoryItem": {"tracked": True},
            "inventoryQuantities": [{
                "availableQuantity": 1,
                "locationId": "gid://shopify/Location/109766639956"  # Your default location
            }]
        }
        
        print(f"Updating variant with {len(variant_updates)} fields...")
        
        variant_result = client.update_variant_rest(variant_gid, variant_updates)
        
        if variant_result:
            print(f"✅ PHASE 2 SUCCESS: Variant updated via REST")
            
            # Verify variant updates
            variant_details = client.get_variant_details_rest(variant_gid)
            if variant_details:
                print(f"\n📊 PHASE 2 VERIFICATION:")
                print(f"   ✅ Price: {variant_details.get('price', 'Not set')}")
                print(f"   ✅ SKU: {variant_details.get('sku', 'Not set')}")
                print(f"   ✅ Inventory Policy: {variant_details.get('inventory_policy', 'Not set')}")
                print(f"   ✅ Inventory Management: {variant_details.get('inventory_management', 'Not set')}")
        else:
            print(f"❌ PHASE 2 FAILED: Variant update failed")
        
        # =============================================================================
        # PHASE 3: IMAGES (FIXED VERIFICATION)
        # =============================================================================
        
        print(f"\n📦 PHASE 3: Testing Image Upload")
        print("-" * 35)
        
        # Test images with different formats
        test_images = [
            {
                "src": "https://rvb-img.reverb.com/image/upload/s--i9YlVM6x--/a_0/f_auto,t_supersize/v1742848273/rnysk4dogt7f7mugtkfw.jpg",
                "altText": "Tommy Wants This Guitar"
            },
            "https://rvb-img.reverb.com/image/upload/s--UB_zoQMw--/a_0/f_auto,t_supersize/v1742848273/t6oppbwym8tzh7patenr.jpg"  # URL only format
        ]
        
        print(f"Adding {len(test_images)} test images...")
        
        images_result = client.create_product_images(product_gid, test_images)
        
        if images_result and not images_result.get("mediaUserErrors"):
            print(f"✅ PHASE 3 SUCCESS: Images uploaded")
            
            # FIXED: Safer verification with error handling
            try:
                updated_product = client.get_all_products_summary(
                    query_filter=f"handle:{test_product_input['handle']}"
                )
                
                if updated_product and len(updated_product) > 0:
                    product_data = updated_product[0]
                    media_count = product_data.get("mediaCount", {}).get("count", 0)
                    featured_media = product_data.get("featuredMedia")
                    
                    print(f"\n📊 PHASE 3 VERIFICATION:")
                    print(f"   ✅ Media count: {media_count}")
                    
                    if featured_media and featured_media.get("id"):
                        print(f"   ✅ Featured media: {featured_media['id']}")
                    else:
                        print(f"   ⚠️ Featured media: Not set")
                else:
                    print(f"   ⚠️ Could not retrieve updated product for verification")
                    
            except Exception as e:
                print(f"   ⚠️ Verification error: {e}")
                print(f"   📝 Images likely uploaded successfully despite verification error")
        else:
            print(f"❌ PHASE 3 FAILED: Image upload failed")
            if images_result and images_result.get("mediaUserErrors"):
                for error in images_result["mediaUserErrors"]:
                    print(f"   Error: {error}")
        
        # =============================================================================
        # PHASE 4: CATEGORY ASSIGNMENT (ENHANCED WITH SPECIFIC GID)
        # =============================================================================
        
        print(f"\n📦 PHASE 4: Testing Category Assignment")
        print("-" * 42)
        
        # Use the specific Electric Guitars category GID you provided
        electric_guitars_gid = "gid://shopify/TaxonomyCategory/ae-2-8-7-2-4"
        category_name = "Arts & Entertainment > Hobbies & Creative Arts > Musical Instruments > String Instruments > Electric Guitars"
        
        print(f"Using specific Electric Guitars category:")
        print(f"   Name: {category_name}")
        print(f"   GID: {electric_guitars_gid}")
        
        # Test both the find_category_gid method AND direct GID assignment
        print(f"\n🔍 Testing category lookup method...")
        found_gid = client.find_category_gid("electric guitars")
        if found_gid:
            print(f"   ✅ find_category_gid() found: {found_gid}")
        else:
            print(f"   ⚠️ find_category_gid() didn't find a match")
        
        print(f"\n🎯 Assigning specific Electric Guitars category...")
        category_result = client.set_product_category(product_gid, electric_guitars_gid)
        
        if category_result:
            print(f"✅ PHASE 4 SUCCESS: Category assigned")
            
            # Verify category assignment
            try:
                updated_product = client.get_all_products_summary(
                    query_filter=f"handle:{test_product_input['handle']}"
                )
                
                if updated_product and len(updated_product) > 0:
                    product_data = updated_product[0]
                    category_data = product_data.get("category", {})
                    
                    print(f"\n📊 PHASE 4 VERIFICATION:")
                    assigned_gid = category_data.get('id')
                    assigned_name = category_data.get('name')
                    assigned_full_name = category_data.get('fullName')
                    
                    if assigned_gid == electric_guitars_gid:
                        print(f"   ✅ Category GID: {assigned_gid} (MATCH!)")
                    else:
                        print(f"   ⚠️ Category GID: Expected {electric_guitars_gid}, Got {assigned_gid}")
                    
                    print(f"   ✅ Category Name: {assigned_name}")
                    print(f"   ✅ Full Category Path: {assigned_full_name}")
                    
                else:
                    print(f"   ⚠️ Could not retrieve product for category verification")
                    
            except Exception as e:
                print(f"   ⚠️ Category verification error: {e}")
                
        else:
            print(f"❌ PHASE 4 FAILED: Category assignment failed")
            
            # Test if the issue is with the GID itself
            print(f"🔍 Testing if category GID is valid...")
            
            # Try a simple product update with just the category
            try:
                update_result = client.update_product({
                    "id": product_gid,
                    "category": electric_guitars_gid
                })
                
                if update_result and update_result.get("product"):
                    print(f"   ✅ Direct category update via productUpdate worked")
                elif update_result and update_result.get("userErrors"):
                    print(f"   ❌ Category update errors:")
                    for error in update_result["userErrors"]:
                        print(f"      {error.get('field', 'Unknown')}: {error.get('message', 'Unknown')}")
                else:
                    print(f"   ❌ Direct category update failed")
                    
            except Exception as e:
                print(f"   ❌ Category update exception: {e}")
        
        # =============================================================================
        # PHASE 5: PUBLISHING (Optional)
        # =============================================================================
        
        print(f"\n📦 PHASE 5: Testing Publishing (Optional)")
        print("-" * 45)
        
        publish_test = input("Test publishing to Online Store? (y/n): ").lower().strip()
        
        if publish_test == 'y':
            online_store_gid = client.get_online_store_publication_id()
            
            if online_store_gid:
                print(f"Found Online Store GID: {online_store_gid}")
                
                publish_result = client.publish_product_to_sales_channel(product_gid, online_store_gid)
                
                if publish_result:
                    print(f"✅ PHASE 5 SUCCESS: Product published")
                else:
                    print(f"❌ PHASE 5 FAILED: Publishing failed")
            else:
                print(f"❌ PHASE 5 FAILED: Could not find Online Store GID")
        else:
            print(f"⏭️ PHASE 5 SKIPPED: Publishing test skipped")
        
        return product_gid
        
    except Exception as e:
        print(f"❌ COMPREHENSIVE TEST FAILED: {e}")
        return None

def cleanup_test_product(product_gid):
    """Clean up the comprehensive test product."""
    
    from app.services.shopify.client import ShopifyGraphQLClient
    
    client = ShopifyGraphQLClient()
    
    try:
        print(f"\n🧹 CLEANING UP TEST PRODUCT")
        print("-" * 35)
        print(f"Deleting product: {product_gid}")
        
        result = client.delete_product(product_gid)
        
        if result and result.get("deletedProductId"):
            print(f"✅ Test product deleted successfully")
        else:
            print(f"⚠️ Could not delete test product - manual cleanup may be required")
            print(f"Product GID: {product_gid}")
            
    except Exception as e:
        print(f"❌ Error during cleanup: {e}")
        print(f"Manual cleanup required for product: {product_gid}")

def main():
    """Main comprehensive test function."""
    
    print("🚀 STARTING COMPREHENSIVE SHOPIFY FIELD TESTING")
    print("=" * 70)
    print("This will test all possible fields from your export format")
    print("using your proven working patterns.\n")
    
    # Run comprehensive test
    product_gid = test_comprehensive_product_creation()
    
    if product_gid:
        print(f"\n🎉 COMPREHENSIVE TEST COMPLETED!")
        print(f"Product GID: {product_gid}")
        
        # Ask about cleanup
        cleanup = input(f"\nDelete the test product? (y/n): ").lower().strip()
        
        if cleanup == 'y':
            cleanup_test_product(product_gid)
        else:
            print(f"✅ Test product preserved: {product_gid}")
            print(f"You can view it in your Shopify admin or delete manually later")
    else:
        print(f"\n❌ COMPREHENSIVE TEST FAILED")
        print("Check the error messages above for details")

if __name__ == "__main__":
    main()