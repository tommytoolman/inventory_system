#!/usr/bin/env python3
"""Test eBay condition mappings for all possible product conditions."""

import os
import sys
import asyncio
from pathlib import Path
from typing import Dict, Optional

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.ebay_service import EbayService
from app.database import async_session
from app.models.product import Product
from app.core.enums import ProductCondition
from sqlalchemy import select
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Expected eBay condition mappings for musical instruments
# Note: eBay limits musical instrument conditions to New, Used, and For parts
EXPECTED_MAPPINGS_MUSICAL = {
    ProductCondition.NEW: "1000",        # New
    ProductCondition.EXCELLENT: "3000",  # Used (best for excellent vintage items)
    ProductCondition.VERYGOOD: "3000",   # Used
    ProductCondition.GOOD: "3000",       # Used
    ProductCondition.FAIR: "3000",       # Used
    ProductCondition.POOR: "7000",       # For parts or not working
}

# Expected eBay condition mappings for other categories
EXPECTED_MAPPINGS_OTHER = {
    ProductCondition.NEW: "1000",        # New
    ProductCondition.EXCELLENT: "2000",  # Manufacturer refurbished / Excellent
    ProductCondition.VERYGOOD: "3000",   # Used
    ProductCondition.GOOD: "4000",       # Good
    ProductCondition.FAIR: "5000",       # Acceptable
    ProductCondition.POOR: "7000",       # For parts or not working
}

async def test_condition_mapping(ebay_service: EbayService, condition: ProductCondition, 
                               category_id: str = None) -> Dict:
    """Test a single condition mapping."""
    result = {
        "condition": condition.value,
        "category_id": category_id,
        "mapped_id": None,
        "display_name": None,
        "success": False,
        "error": None
    }
    
    try:
        # Test the mapping
        mapped_id = ebay_service._get_ebay_condition_id(condition, category_id)
        display_name = ebay_service._get_ebay_condition_display_name(mapped_id)
        
        result["mapped_id"] = mapped_id
        result["display_name"] = display_name
        result["success"] = True
        
        # Check if mapping is as expected
        # Need to check if it's a musical instrument category
        musical_categories = [
            "33034", "33021", "4713", "38072", "41407", "180012", "47067", 
            "10181", "180013", "180014", "180015", "619", "181162", "3858",
            "35023", "181220", "159948", "181219"
        ]
        
        if category_id in musical_categories or category_id is None:
            expected = EXPECTED_MAPPINGS_MUSICAL.get(condition)
        else:
            expected = EXPECTED_MAPPINGS_OTHER.get(condition)
            
        if mapped_id != expected:
            result["error"] = f"Expected {expected}, got {mapped_id}"
            
    except Exception as e:
        result["error"] = str(e)
        
    return result

async def test_with_real_product(ebay_service: EbayService, product: Product, 
                               test_condition: Optional[ProductCondition] = None) -> Dict:
    """Test creating a listing with a real product."""
    
    # Override condition if specified
    original_condition = product.condition
    if test_condition:
        product.condition = test_condition
    
    try:
        # Create enriched data from product
        enriched_data = {
            "title": f"TEST LISTING - {product.display_title}",
            "description": product.description or "Test listing",
            "price": {"amount": "99999", "currency": "GBP"},
            "condition": {"value": product.condition} if product.condition else None,
            "categories": [],  # Empty to test string mapping fallback
            "photos": [],
            "shipping": {
                "rates": [
                    {"region_code": "GB", "rate": {"amount": "60.00"}},
                    {"region_code": "US", "rate": {"amount": "200.00"}}
                ]
            }
        }
        
        # Add images
        if product.primary_image:
            enriched_data["photos"].append({"url": product.primary_image})
            
        # Try to create listing (dry run)
        result = await ebay_service.create_listing_from_product(
            product=product,
            reverb_api_data=enriched_data,
            use_shipping_profile=True,
            shipping_profile_id='252277357017',
            payment_profile_id='252544577017',
            return_profile_id='252277356017',
            dry_run=True
        )
        
        return result
        
    finally:
        # Restore original condition
        product.condition = original_condition

async def main():
    """Run all condition mapping tests."""
    
    async with async_session() as db:
        # Initialize eBay service
        from app.core.config import Settings
        settings = Settings()
        ebay_service = EbayService(db, settings)
        
        print("=" * 80)
        print("EBAY CONDITION MAPPING TESTS")
        print("=" * 80)
        
        # Test 1: Test all condition mappings for musical instruments
        print("\n1. Testing Musical Instruments Category (4713 - Bass Guitars):")
        print("-" * 50)
        
        for condition in ProductCondition:
            result = await test_condition_mapping(ebay_service, condition, "4713")
            status = "✅" if result["success"] and not result["error"] else "❌"
            print(f"{status} {result['condition']:<12} → {result['mapped_id']} ({result['display_name']})")
            if result["error"]:
                print(f"   ERROR: {result['error']}")
        
        # Test 2: Test when category_id is None (defaults to musical instrument)
        print("\n2. Testing with No Category (defaults to musical instrument):")
        print("-" * 50)
        
        for condition in ProductCondition:
            result = await test_condition_mapping(ebay_service, condition, None)
            status = "✅" if result["success"] and not result["error"] else "❌"
            print(f"{status} {result['condition']:<12} → {result['mapped_id']} ({result['display_name']})")
            if result["error"]:
                print(f"   ERROR: {result['error']}")
        
        # Test 3: Test all condition mappings for another category
        print("\n3. Testing Other Category (e.g., Electronics - 58058):")
        print("-" * 50)
        
        for condition in ProductCondition:
            result = await test_condition_mapping(ebay_service, condition, "58058")
            status = "✅" if result["success"] and not result["error"] else "❌"
            print(f"{status} {result['condition']:<12} → {result['mapped_id']} ({result['display_name']})")
            if result["error"]:
                print(f"   ERROR: {result['error']}")
        
        # Test 4: Test with real product
        print("\n4. Testing with Real Product:")
        print("-" * 50)
        
        # Find a test product
        test_sku = 'REV-91978762'  # The Zemaitis
        result = await db.execute(
            select(Product)
            .where(Product.sku == test_sku)
        )
        product = result.scalar_one_or_none()
        
        if product:
            print(f"Found product: {product.sku} - {product.display_title}")
            print(f"Original condition: {product.condition}")
            
            # Test with original condition
            listing_result = await test_with_real_product(ebay_service, product)
            
            if listing_result.get("status") == "dry_run":
                item_data = listing_result.get('item_data', {})
                print(f"✅ Dry run successful!")
                print(f"   ConditionID: {item_data.get('ConditionID', 'N/A')}")
                print(f"   Category: {item_data.get('CategoryID', 'N/A')}")
                
                # Show ItemSpecifics related to condition
                item_specifics = item_data.get('ItemSpecifics', {})
                if 'Condition' in item_specifics:
                    print(f"   ItemSpecific 'Condition': {item_specifics['Condition']}")
            else:
                print(f"❌ Test failed: {listing_result.get('error') or listing_result.get('message')}")
        else:
            print(f"❌ Product {test_sku} not found")
        
        # Test 5: Verify condition display names
        print("\n5. Testing Condition Display Names:")
        print("-" * 50)
        
        condition_ids = ["1000", "3000", "4000", "5000", "6000", "7000"]
        for cond_id in condition_ids:
            display_name = ebay_service._get_ebay_condition_display_name(cond_id)
            print(f"ConditionID {cond_id} → {display_name}")
        
        print("\n" + "=" * 80)
        print("TEST COMPLETE")
        print("=" * 80)

if __name__ == "__main__":
    asyncio.run(main())