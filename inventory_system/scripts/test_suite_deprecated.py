#!/usr/bin/env python3
"""
DEPRECATED TEST SUITE — March 2026
===================================
These scripts were useful during development but are now superseded by production
code, endpoints, or the scheduler. They are preserved here for reference in case
the underlying logic needs to be re-tested.

| Original File                    | What it does                                              | Why deprecated                                      |
|----------------------------------|-----------------------------------------------------------|-----------------------------------------------------|
| test_ebay_comprehensive.py       | Dry-run eBay listing across product categories            | Covered by production listing routes                |
| test_ebay_conditions.py          | Tests eBay condition ID mapping for all enums             | One-off validation, logic is stable                 |
| test_ebay_listing_data.py        | Creates eBay listing in sandbox, inspects listing_data    | One-off listing_data structure inspection            |
| test_ebay_shipping.py            | Brute-force tests eBay shipping service codes             | Results now hardcoded in ebay_service.py            |
| test_image_transform.py          | Tests Reverb URL transform with 3 sample URLs             | Trivial, should be a unit test if needed            |
| test_inbound_sync.py             | Runs inbound sync in report-only mode                     | Superseded by production scheduler                  |
| test_matcher.py                  | Debugs ProductMatcher for 2 hardcoded product IDs         | One-off debugging, hardcoded IDs                    |
| test_new_listing_dryrun.py       | Dry-run eBay listing for one hardcoded SKU                | One-off business policy validation                  |
| test_shipping_endpoint.py        | Checks shipping profile display_name format               | One-off endpoint response validation                |
| test_stocked_item_sale.py        | Creates mock sale events and processes them                | Writes test data to prod DB — dangerous             |
| test_sync_safe.py                | Skeleton test harness for safe sync testing                | Empty — no actual test logic beyond DB connection   |

WARNING: Some of these scripts hit LIVE APIs (eBay, Reverb, Dropbox) or write to
the production database. Do not run without understanding what they do first.
"""


# ==============================================================================
# ORIGINAL FILE: test_ebay_comprehensive.py
# ==============================================================================

#!/usr/bin/env python3
"""Comprehensive eBay listing test with detailed logging for various product types"""

import os
import sys
import asyncio
from pathlib import Path
import logging

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.ebay_service import EbayService
from app.database import async_session
from app.models.product import Product, ProductCondition
from sqlalchemy import select
from sqlalchemy.orm import selectinload

# Set up comprehensive logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Test scenarios
TEST_SCENARIOS = [
    {
        "name": "Electric Guitar - Solid Body",
        "sku_pattern": "electric.*solid|stratocaster|telecaster|les paul",
        "expected_category": "33034",
        "expected_type": "Electric Guitar"
    },
    {
        "name": "Acoustic Guitar",
        "sku_pattern": "acoustic.*guitar",
        "expected_category": "33021", 
        "expected_type": "Acoustic Guitar"
    },
    {
        "name": "Bass Guitar",
        "sku_pattern": "bass",
        "expected_category": "4713",
        "expected_type": "Bass Guitar"
    },
    {
        "name": "Guitar Amplifier",
        "sku_pattern": "amp|amplifier",
        "expected_category": "38072",
        "expected_amplifier_type": ["Combo", "Head", "Cabinet"]
    },
    {
        "name": "Effects Pedal",
        "sku_pattern": "pedal|effect|distortion|delay",
        "expected_category": "41407",
        "expected_type": "Effects Pedal"
    }
]

async def test_product_category(product: Product, scenario: dict):
    """Test a single product against expected category mapping"""
    logger.info(f"\n{'='*80}")
    logger.info(f"TESTING: {scenario['name']}")
    logger.info(f"Product: {product.sku} - {product.title}")
    logger.info(f"{'='*80}")
    
    async with async_session() as db:
        # Initialize eBay service
        from app.core.config import Settings
        settings = Settings()
        ebay_service = EbayService(db, settings)
        
        # Test with minimal enriched data to trigger fallback logic
        enriched_data = {
            "categories": [],  # Empty to test string mapping
            "shipping": {
                "rates": [
                    {"region_code": "GB", "rate": {"amount": "50.00"}},
                    {"region_code": "US", "rate": {"amount": "150.00"}}
                ]
            }
        }
        
        # Dry run the listing creation
        result = await ebay_service.create_listing_from_product(
            product=product,
            reverb_api_data=enriched_data,
            use_shipping_profile=True,
            shipping_profile_id='252277357017',
            payment_profile_id='252544577017',
            return_profile_id='252277356017',
            dry_run=True
        )
        
        if result.get("status") == "dry_run":
            item_data = result.get('item_data', {})
            
            # Check category mapping
            actual_category = item_data.get('CategoryID')
            logger.info(f"\n--- CATEGORY VALIDATION ---")
            logger.info(f"Expected Category: {scenario['expected_category']}")
            logger.info(f"Actual Category: {actual_category}")
            logger.info(f"PASS: {actual_category == scenario['expected_category']}")
            
            # Check ItemSpecifics
            item_specifics = item_data.get('ItemSpecifics', {})
            logger.info(f"\n--- ITEM SPECIFICS ---")
            for key, value in sorted(item_specifics.items()):
                logger.info(f"  {key}: {value}")
            
            # Validate Type or Amplifier Type
            if 'expected_type' in scenario:
                actual_type = item_specifics.get('Type')
                logger.info(f"\n--- TYPE VALIDATION ---")
                logger.info(f"Expected Type: {scenario['expected_type']}")
                logger.info(f"Actual Type: {actual_type}")
                logger.info(f"PASS: {actual_type == scenario['expected_type']}")
            
            if 'expected_amplifier_type' in scenario:
                actual_amp_type = item_specifics.get('Amplifier Type')
                logger.info(f"\n--- AMPLIFIER TYPE VALIDATION ---")
                logger.info(f"Expected Types: {scenario['expected_amplifier_type']}")
                logger.info(f"Actual Type: {actual_amp_type}")
                logger.info(f"PASS: {actual_amp_type in scenario['expected_amplifier_type']}")
            
            # Check condition mapping
            logger.info(f"\n--- CONDITION MAPPING ---")
            logger.info(f"Product Condition: {product.condition}")
            logger.info(f"eBay ConditionID: {item_data.get('ConditionID')}")
            logger.info(f"Condition in ItemSpecifics: {item_specifics.get('Condition')}")
            
            # Check quantity handling for stocked items
            logger.info(f"\n--- INVENTORY HANDLING ---")
            logger.info(f"Is Stocked Item: {product.is_stocked_item}")
            logger.info(f"Product Quantity: {product.quantity}")
            logger.info(f"Listing Quantity: {item_data.get('Quantity')}")
            
            return True
        else:
            logger.error(f"Failed to create listing: {result}")
            return False

async def find_test_products():
    """Find products matching our test scenarios"""
    async with async_session() as db:
        test_products = {}
        
        for scenario in TEST_SCENARIOS:
            # Try to find a product matching this scenario
            query = select(Product).where(
                Product.title.ilike(f"%{scenario['sku_pattern'].split('|')[0]}%")
            ).limit(1)
            
            result = await db.execute(query)
            product = result.scalar_one_or_none()
            
            if product:
                test_products[scenario['name']] = (product, scenario)
                logger.info(f"Found product for {scenario['name']}: {product.sku}")
            else:
                logger.warning(f"No product found for scenario: {scenario['name']}")
        
        return test_products

async def test_stocked_items():
    """Test stocked item handling"""
    logger.info(f"\n{'='*80}")
    logger.info("TESTING STOCKED ITEMS")
    logger.info(f"{'='*80}")
    
    async with async_session() as db:
        # Find a stocked item
        query = select(Product).where(
            Product.is_stocked_item == True,
            Product.quantity > 1
        ).limit(1)
        
        result = await db.execute(query)
        stocked_product = result.scalar_one_or_none()
        
        if stocked_product:
            logger.info(f"Found stocked item: {stocked_product.sku}")
            logger.info(f"  Title: {stocked_product.title}")
            logger.info(f"  Quantity: {stocked_product.quantity}")
            
            # Test listing creation
            from app.core.config import Settings
            settings = Settings()
            ebay_service = EbayService(db, settings)
            
            result = await ebay_service.create_listing_from_product(
                product=stocked_product,
                reverb_api_data={"categories": []},
                use_shipping_profile=True,
                shipping_profile_id='252277357017',
                dry_run=True
            )
            
            if result.get("status") == "dry_run":
                item_data = result.get('item_data', {})
                logger.info(f"  Listing Quantity: {item_data.get('Quantity')}")
                logger.info(f"  Expected: {stocked_product.quantity}")
                logger.info(f"  PASS: {int(item_data.get('Quantity', 0)) == stocked_product.quantity}")
        else:
            logger.warning("No stocked items found in database")

async def main():
    logger.info("Starting comprehensive eBay testing...")
    
    # Test 1: Category and Type mapping
    test_products = await find_test_products()
    
    success_count = 0
    for name, (product, scenario) in test_products.items():
        success = await test_product_category(product, scenario)
        if success:
            success_count += 1
    
    logger.info(f"\n{'='*80}")
    logger.info(f"CATEGORY TESTS: {success_count}/{len(test_products)} passed")
    logger.info(f"{'='*80}")
    
    # Test 2: Stocked items
    await test_stocked_items()
    
    logger.info("\nTesting complete!")

if __name__ == "__main__":
    asyncio.run(main())

# ==============================================================================
# ORIGINAL FILE: test_ebay_conditions.py
# ==============================================================================

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

# ==============================================================================
# ORIGINAL FILE: test_ebay_listing_data.py
# ==============================================================================

#!/usr/bin/env python3
"""Test creating an eBay listing and verify the listing_data structure"""

import os
import sys
import asyncio
import json
from pathlib import Path
from datetime import datetime

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.ebay_service import EbayService
from app.database import async_session
from app.models.product import Product
from app.models.platform_common import PlatformCommon
from app.models.ebay import EbayListing
from sqlalchemy import select
from sqlalchemy.orm import selectinload
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_listing_data_structure():
    """Test creating a listing and verify the listing_data structure."""
    
    async with async_session() as db:
        # Find a product without an eBay listing
        result = await db.execute(
            select(Product)
            .outerjoin(PlatformCommon, 
                (PlatformCommon.product_id == Product.id) & 
                (PlatformCommon.platform_name == 'ebay')
            )
            .where(PlatformCommon.id == None)
            .limit(1)
        )
        product = result.scalar_one_or_none()
        
        if not product:
            logger.error("No products found without eBay listings")
            return
            
        logger.info(f"Testing with product: {product.sku} - {product.title}")
        
        # Initialize eBay service
        from app.core.config import Settings
        settings = Settings()
        ebay_service = EbayService(db, settings)
        
        # Create enriched data
        enriched_data = {
            "title": f"TEST - {product.title}",
            "description": product.description or "Test listing",
            "price": {"amount": "99999", "currency": "GBP"},
            "condition": {"value": product.condition} if product.condition else None,
            "categories": [],
            "photos": [],
            "shipping": {
                "rates": [
                    {"region_code": "GB", "rate": {"amount": "50.00"}},
                    {"region_code": "US", "rate": {"amount": "150.00"}}
                ]
            }
        }
        
        # Add images
        if product.primary_image:
            enriched_data["photos"].append({"url": product.primary_image})
            
        # First do a dry run
        logger.info("Performing dry run...")
        dry_run_result = await ebay_service.create_listing_from_product(
            product=product,
            reverb_api_data=enriched_data,
            use_shipping_profile=True,
            shipping_profile_id='252277357017',
            payment_profile_id='252544577017',
            return_profile_id='252277356017',
            dry_run=True
        )
        
        if dry_run_result.get("status") != "dry_run":
            logger.error(f"Dry run failed: {dry_run_result}")
            return
            
        logger.info("Dry run successful! Now creating actual listing in SANDBOX...")
        
        # Create actual listing in SANDBOX
        result = await ebay_service.create_listing_from_product(
            product=product,
            reverb_api_data=enriched_data,
            use_shipping_profile=True,
            shipping_profile_id='252277357017',
            payment_profile_id='252544577017',
            return_profile_id='252277356017',
            sandbox=True  # Use sandbox for testing
        )
        
        if result.get("status") == "success":
            ebay_item_id = result.get("external_id")
            logger.info(f"✅ Successfully created eBay listing: {ebay_item_id}")
            
            # Now fetch and examine the listing_data
            pc_result = await db.execute(
                select(PlatformCommon)
                .options(selectinload(PlatformCommon.ebay_listing))
                .where(
                    (PlatformCommon.product_id == product.id) & 
                    (PlatformCommon.platform_name == 'ebay') &
                    (PlatformCommon.external_id == ebay_item_id)
                )
            )
            platform_common = pc_result.scalar_one_or_none()
            
            if platform_common and platform_common.ebay_listing:
                ebay_listing = platform_common.ebay_listing
                
                logger.info("\n=== LISTING DATA STRUCTURE ===")
                logger.info(f"listing_data type: {type(ebay_listing.listing_data)}")
                logger.info(f"listing_data keys: {list(ebay_listing.listing_data.keys())}")
                
                # Check for the presence of 'Raw' key like in older listings
                if 'Raw' in ebay_listing.listing_data:
                    logger.info("✅ Contains 'Raw' key like older listings")
                    logger.info(f"Raw keys: {list(ebay_listing.listing_data['Raw'].keys())}")
                    
                    if 'Item' in ebay_listing.listing_data['Raw']:
                        item_keys = list(ebay_listing.listing_data['Raw']['Item'].keys())
                        logger.info(f"Item keys: {item_keys[:10]}... (showing first 10)")
                        logger.info(f"Total Item keys: {len(item_keys)}")
                else:
                    logger.warning("❌ Missing 'Raw' key - structure differs from older listings")
                    
                # Show a sample of the structure
                logger.info("\nSample of listing_data structure:")
                logger.info(json.dumps(ebay_listing.listing_data, indent=2)[:1000] + "...")
                
                # Compare with expected old structure
                logger.info("\n=== COMPARISON WITH OLD STRUCTURE ===")
                expected_keys = ['Raw', 'created_via', 'sandbox', 'site', 'listing_type', 'listing_duration']
                for key in expected_keys:
                    if key in ebay_listing.listing_data:
                        logger.info(f"✅ Has key: {key}")
                    else:
                        logger.info(f"❌ Missing key: {key}")
                        
            else:
                logger.error("Could not find ebay_listing entry")
                
        else:
            logger.error(f"❌ Failed to create listing: {result}")

async def main():
    await test_listing_data_structure()

if __name__ == "__main__":
    asyncio.run(main())

# ==============================================================================
# ORIGINAL FILE: test_ebay_shipping.py
# ==============================================================================

#!/usr/bin/env python3
"""Test eBay shipping service codes to find valid ones."""

import os
import sys
import asyncio
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.ebay_service import EbayService
from app.database import async_session
import json

async def test_ebay_shipping():
    """Test different eBay shipping service codes."""
    
    async with async_session() as db:
        ebay_service = EbayService(db)
        
        # Test data
        test_item = {
            "Item": {
                "Title": "Test Guitar Listing",
                "Description": "This is a test listing",
                "PrimaryCategory": {"CategoryID": "33034"},  # Electric Guitars
                "StartPrice": "100.00",
                "ConditionID": "3000",  # Used
                "Country": "GB",
                "Currency": "GBP",
                "DispatchTimeMax": "3",
                "ListingDuration": "GTC",
                "ListingType": "FixedPriceItem",
                "PaymentMethods": "PayPal",
                "PayPalEmailAddress": os.getenv("PAYPAL_EMAIL", "test@example.com"),
                "PostalCode": "SW1A 1AA",
                "Quantity": "1",
                "ReturnPolicy": {
                    "ReturnsAcceptedOption": "ReturnsAccepted",
                    "RefundOption": "MoneyBack",
                    "ReturnsWithinOption": "Days_14",
                    "ShippingCostPaidByOption": "Buyer"
                },
                "Site": "UK",
                "SKU": "TEST-SHIPPING-001"
            }
        }
        
        print("Testing eBay Shipping Service Codes:\n" + "="*50)
        
        # Test different UK domestic services
        domestic_services = [
            # Currently used
            "UK_OtherCourier24",
            
            # Common alternatives
            "UK_RoyalMailFirstClassStandard",
            "UK_RoyalMailSecondClassStandard", 
            "UK_RoyalMailTracked24",
            "UK_RoyalMailTracked48",
            "UK_Parcelforce24",
            "UK_Parcelforce48",
            "UK_OtherCourier",
            "UK_OtherCourier3Days",
            "UK_SellersStandardRate",
            "UK_CollectInPerson",
            
            # Economy services
            "UK_EconomyShippingFromOutside",
            "UK_StandardShippingFromOutside",
            "UK_ExpeditedShippingFromOutside",
            
            # Other potential services
            "UK_myHermesDoorToDoorService",
            "UK_CollectDropAtStoreDeliveryToDoor"
        ]
        
        print("\n1. Testing DOMESTIC Services:\n" + "-"*40)
        valid_domestic = []
        
        for service_code in domestic_services:
            test_item_copy = json.loads(json.dumps(test_item))  # Deep copy
            test_item_copy["Item"]["ShippingDetails"] = {
                "ShippingType": "Flat",
                "ShippingServiceOptions": {
                    "ShippingServicePriority": "1",
                    "ShippingService": service_code,
                    "ShippingServiceCost": "10.00"
                }
            }
            
            try:
                response = await ebay_service.trading_api.verify_add_item(test_item_copy["Item"])
                print(f"  ✓ {service_code}")
                valid_domestic.append(service_code)
            except Exception as e:
                error_msg = str(e)
                if "ShippingService" in error_msg or "Invalid shipping service" in error_msg:
                    print(f"  ✗ {service_code} - INVALID")
                else:
                    # Check for other errors that might indicate format issues
                    if "Input data" in error_msg:
                        print(f"  ⚠ {service_code} - Format issue: {error_msg[:100]}")
                    else:
                        print(f"  ? {service_code} - Other: {error_msg[:80]}")
        
        # Test international services
        international_services = [
            # Currently used
            "UK_InternationalStandard",
            
            # Common alternatives
            "UK_RoyalMailInternationalStandard",
            "UK_RoyalMailInternationalTracked",
            "UK_RoyalMailInternationalSignedFor",
            "UK_ParcelForceInternationalStandard",
            "UK_ParcelForceInternationalEconomy", 
            "UK_ParcelForceInternationalExpress",
            "UK_OtherCourierOrDeliveryInternational",
            
            # Generic international
            "InternationalPriorityShipping",
            "StandardInternational",
            "ExpeditedInternational",
            "OtherInternational"
        ]
        
        print("\n2. Testing INTERNATIONAL Services:\n" + "-"*40)
        valid_international = []
        
        for service_code in international_services:
            test_item_copy = json.loads(json.dumps(test_item))  # Deep copy
            test_item_copy["Item"]["ShippingDetails"] = {
                "ShippingType": "Flat",
                "ShippingServiceOptions": {
                    "ShippingServicePriority": "1",
                    "ShippingService": "UK_RoyalMailFirstClassStandard",  # Valid domestic
                    "ShippingServiceCost": "10.00"
                },
                "InternationalShippingServiceOption": {
                    "ShippingServicePriority": "1", 
                    "ShippingService": service_code,
                    "ShippingServiceCost": "25.00",
                    "ShipToLocation": "Worldwide"
                }
            }
            
            try:
                response = await ebay_service.trading_api.verify_add_item(test_item_copy["Item"])
                print(f"  ✓ {service_code}")
                valid_international.append(service_code)
            except Exception as e:
                error_msg = str(e)
                if "ShippingService" in error_msg or "Invalid shipping service" in error_msg:
                    print(f"  ✗ {service_code} - INVALID")
                else:
                    if "Input data" in error_msg:
                        print(f"  ⚠ {service_code} - Format issue: {error_msg[:100]}")
                    else:
                        print(f"  ? {service_code} - Other: {error_msg[:80]}")
        
        # Test the exact format from _map_reverb_shipping_to_ebay
        print("\n3. Testing EXACT Format from ebay_service.py:\n" + "-"*40)
        
        # This is how the current code structures it
        test_item_copy = json.loads(json.dumps(test_item))
        test_item_copy["Item"]["ShippingDetails"] = {
            "ShippingType": "Flat",
            "ShippingServiceOptions": [
                {
                    "ShippingServicePriority": "1",
                    "ShippingService": "UK_OtherCourier24",
                    "ShippingServiceCost": "10.00"
                }
            ],
            "InternationalShippingServiceOption": [
                {
                    "ShippingServicePriority": "1",
                    "ShippingService": "UK_InternationalStandard",
                    "ShippingServiceCost": "25.00",
                    "ShipToLocation": "Worldwide"
                }
            ]
        }
        
        print("Testing with array format (current implementation):")
        try:
            response = ebay_service.client.execute('VerifyAddItem', test_item_copy)
            print("  ✓ Array format works!")
        except Exception as e:
            print(f"  ✗ Array format failed: {str(e)[:150]}")
        
        # Summary
        print("\n" + "="*50)
        print("SUMMARY:")
        print("="*50)
        if valid_domestic:
            print(f"\nValid DOMESTIC services ({len(valid_domestic)}):")
            for svc in valid_domestic:
                print(f"  • {svc}")
        
        if valid_international:
            print(f"\nValid INTERNATIONAL services ({len(valid_international)}):")
            for svc in valid_international:
                print(f"  • {svc}")

async def main():
    await test_ebay_shipping()

if __name__ == "__main__":
    asyncio.run(main())

# ==============================================================================
# ORIGINAL FILE: test_image_transform.py
# ==============================================================================

#!/usr/bin/env python3
"""Test image transformation logic"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.utils import ImageTransformer, ImageQuality

# Test URLs
test_urls = [
    "https://rvb-img.reverb.com/image/upload/s--u94pKSb---/f_auto,t_large/v1756373398/a5s7yex1zki69hqmi7tc.jpg",
    "https://rvb-img.reverb.com/image/upload/s--k5jtQgjw--/a_0/f_auto,t_large/v1748246175/image.jpg",
    "https://rvb-img.reverb.com/image/upload/a_0/f_auto,t_large/v1748246175/image.jpg"
]

print("Testing ImageTransformer.transform_reverb_url with MAX_RES:\n")

for url in test_urls:
    max_res = ImageTransformer.transform_reverb_url(url, ImageQuality.MAX_RES)
    print(f"Original: {url}")
    print(f"MAX_RES:  {max_res}")
    print(f"Expected: https://rvb-img.reverb.com/image/upload/v{url.split('/v')[1]}")
    print("-" * 80)

# ==============================================================================
# ORIGINAL FILE: test_inbound_sync.py
# ==============================================================================

# scripts/test_inbound_sync.py
import asyncio
from app.database import get_session
from app.services.sync_services import InboundSyncScheduler

async def test_sync():
    async with get_session() as db:
        scheduler = InboundSyncScheduler(db, report_only=True)
        
        # Test single platform
        report = await scheduler.run_platform_sync("reverb")
        scheduler.print_sync_report(report)
        
        # Test all platforms
        # reports = await scheduler.run_all_platforms_sync()
        # for platform, report in reports.items():
        #     scheduler.print_sync_report(report)

if __name__ == "__main__":
    asyncio.run(test_sync())

# ==============================================================================
# ORIGINAL FILE: test_matcher.py
# ==============================================================================

# Update your test_matcher.py to focus on the known match
import asyncio
from app.database import async_session
from scripts.product_matcher import ProductMatcher
from sqlalchemy import text

async def debug_specific_burns_match():
    async with async_session() as session:
        matcher = ProductMatcher(session)
        
        # Get the specific products we know should match
        products_by_platform = await matcher._get_products_by_platform("ACTIVE")
        
        reverb_products = products_by_platform.get('reverb', [])
        shopify_products = products_by_platform.get('shopify', [])
        
        # Find our specific Burns products
        target_reverb = None
        target_shopify = None
        
        for product in reverb_products:
            if product['id'] == 4163:  # Our known Reverb Burns
                target_reverb = product
                break
                
        for product in shopify_products:
            if product['id'] == 7854:  # Our known Shopify Burns  
                target_shopify = product
                break
        
        if target_reverb and target_shopify:
            print("Found our target products:")
            print(f"Reverb: ID={target_reverb['id']}, SKU={target_reverb['sku']}")
            print(f"  Brand: '{target_reverb['brand']}'")
            print(f"  Title: '{target_reverb['title']}'") 
            print(f"  Price: {target_reverb['price']}")
            
            print(f"Shopify: ID={target_shopify['id']}, SKU={target_shopify['sku']}")
            print(f"  Brand: '{target_shopify['brand']}'")
            print(f"  Title: '{target_shopify['title']}'")
            print(f"  Price: {target_shopify['price']}")
            
            # Test each step of the matching process
            print("\\n--- Matching Debug ---")
            
            # 1. Brand normalization
            brand1 = matcher.normalize_brand(target_reverb['brand'])
            brand2 = matcher.normalize_brand(target_shopify['brand'])
            print(f"1. Brand normalization:")
            print(f"   Reverb: '{target_reverb['brand']}' → '{brand1}'")
            print(f"   Shopify: '{target_shopify['brand']}' → '{brand2}'")
            print(f"   Brands match: {brand1 == brand2}")
            
            # 2. Year extraction
            year1 = matcher._extract_year_from_title(target_reverb['title'])
            year2 = matcher._extract_year_from_title(target_shopify['title'])
            print(f"\\n2. Year extraction:")
            print(f"   Reverb title: '{target_reverb['title']}' → Year: {year1}")
            print(f"   Shopify title: '{target_shopify['title']}' → Year: {year2}")
            print(f"   Years match: {year1 == year2}")
            
            # 3. Price comparison
            price1 = target_reverb['price']
            price2 = target_shopify['price']
            if price1 and price2:
                price_diff = abs(price1 - price2)
                price_diff_pct = (price_diff / max(price1, price2)) * 100
                print(f"\\n3. Price comparison:")
                print(f"   Reverb: £{price1}")
                print(f"   Shopify: £{price2}")
                print(f"   Difference: £{price_diff} ({price_diff_pct:.1f}%)")
            
            # 4. Full confidence calculation
            confidence = matcher._calculate_match_confidence(target_reverb, target_shopify)
            print(f"\\n4. Final confidence: {confidence:.1f}%")
            
            # 5. Check if they would be in the same brand group for filtering
            reverb_brand_key = target_reverb.get('brand', '').lower()
            shopify_brand_key = target_shopify.get('brand', '').lower()
            print(f"\\n5. Brand filtering check:")
            print(f"   Reverb brand key: '{reverb_brand_key}'")
            print(f"   Shopify brand key: '{shopify_brand_key}'")
            print(f"   Would be grouped together: {reverb_brand_key == shopify_brand_key}")
            
        else:
            print("Could not find target products!")
            print(f"Target Reverb found: {target_reverb is not None}")
            print(f"Target Shopify found: {target_shopify is not None}")

# Add this to test_matcher.py
async def check_actual_titles():
    async with async_session() as session:
        # Get the actual product titles from the database
        query = text('''
            SELECT p.id, p.sku, p.brand, p.model, p.title, p.year
            FROM products p
            WHERE p.id IN (4163, 7854)
            ORDER BY p.id
        ''')
        
        result = await session.execute(query)
        rows = result.fetchall()
        
        print("Actual product data:")
        for row in rows:
            print(f'  ID: {row.id}, SKU: {row.sku}')
            print(f'    Brand: "{row.brand}", Model: "{row.model}"')
            print(f'    Title: "{row.title}"')
            print(f'    Year: {row.year}')
            print()

if __name__ == "__main__":
    asyncio.run(check_actual_titles())

#     asyncio.run(debug_specific_burns_match())

# ==============================================================================
# ORIGINAL FILE: test_new_listing_dryrun.py
# ==============================================================================

#!/usr/bin/env python3
"""Test eBay listing creation in dry-run mode"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import async_session
from app.services.ebay_service import EbayService
from app.models.product import Product
from sqlalchemy import select
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def test_ebay_dry_run():
    """Test creating eBay listing with our updated Business Policy implementation."""
    async with async_session() as db:
        # Find product REV-91978762 that was failing
        result = await db.execute(
            select(Product).where(Product.sku == 'REV-91978762')
        )
        product = result.scalar_one_or_none()
        
        if not product:
            logger.error("Product REV-91978762 not found")
            return
            
        logger.info(f"Testing with product: {product.sku} - {product.title}")
        logger.info(f"  Price: £{product.base_price}")
        logger.info(f"  Condition: {product.condition}")
        
        # Create minimal enriched data
        enriched_data = {
            "title": f"NOT FOR SALE - TEST {product.title}",
            "description": product.description or "High quality musical instrument",
            "price": {"amount": "66666", "currency": "GBP"},
            "condition": {"value": product.condition} if product.condition else None,
            "categories": [{"uuid": "solid-body"}],  # Default category
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
        if product.additional_images:
            for img in product.additional_images[:5]:  # Limit to 5 additional
                enriched_data["photos"].append({"url": img})
                
        # Initialize service
        from app.core.config import Settings
        settings = Settings()
        ebay_service = EbayService(db, settings)
        
        # Test with Business Policies (the defaults we set in inventory.py)
        logger.info("\n=== Testing with Business Policies ===")
        result = await ebay_service.create_listing_from_product(
            product=product,
            reverb_api_data=enriched_data,
            use_shipping_profile=True,
            shipping_profile_id='252277357017',
            payment_profile_id='252544577017', 
            return_profile_id='252277356017',
            dry_run=True
        )
        
        if result.get("status") == "dry_run":
            logger.info("✅ DRY RUN SUCCESS with Business Policies!")
            item_data = result.get('item_data', {})
            logger.info(f"   Would create listing with title: {item_data.get('Title', 'N/A')}")
            logger.info(f"   Category: {item_data.get('CategoryID', 'N/A')}")
            logger.info(f"   Condition: {item_data.get('ConditionID', 'N/A')}")
            logger.info(f"   Price: £{item_data.get('Price', 'N/A')}")
            logger.info(f"   Using Business Policies: Yes")
            profiles = item_data.get('SellerProfiles', {})
            logger.info(f"   Shipping Profile: {profiles.get('SellerShippingProfile', {}).get('ShippingProfileID', 'N/A')}")
        elif result.get("status") == "error":
            logger.error(f"❌ FAILED: {result.get('error', 'Unknown error')}")
            logger.error(f"   Full result: {result}")
        else:
            logger.info(f"Result status: {result.get('status')}")
            logger.info(f"Full result: {result}")

async def main():
    await test_ebay_dry_run()

if __name__ == "__main__":
    asyncio.run(main())


# ==============================================================================
# ORIGINAL FILE: test_shipping_endpoint.py
# ==============================================================================

#!/usr/bin/env python3
"""
Test the shipping profiles endpoint to verify display_name is returned.
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from sqlalchemy import select
from app.database import async_session
from app.models.shipping import ShippingProfile

async def test_endpoint_logic():
    """Test the same logic as the endpoint."""
    
    async with async_session() as session:
        profiles = await session.execute(select(ShippingProfile).order_by(ShippingProfile.name))
        result = profiles.scalars().all()
        
        # Simulate the endpoint response
        response = [
            {
                "id": profile.id,
                "reverb_profile_id": profile.reverb_profile_id,
                "ebay_profile_id": profile.ebay_profile_id,
                "name": profile.name,
                "display_name": f"{profile.name} ({profile.reverb_profile_id})" if profile.reverb_profile_id else profile.name,
                "description": profile.description,
                "package_type": profile.package_type,
                "dimensions": profile.dimensions,
                "weight": profile.weight,
                "carriers": profile.carriers,
                "options": profile.options,
                "rates": profile.rates,
                "is_default": profile.is_default
            }
            for profile in result
        ]
        
        print("Sample API Response (first 3 profiles):")
        print("=" * 60)
        for profile in response[:3]:
            print(f"ID: {profile['id']}")
            print(f"Name: {profile['name']}")
            print(f"Reverb ID: {profile['reverb_profile_id']}")
            print(f"Display Name: {profile['display_name']}")
            print("-" * 40)

if __name__ == "__main__":
    asyncio.run(test_endpoint_logic())

# ==============================================================================
# ORIGINAL FILE: test_stocked_item_sale.py
# ==============================================================================

#!/usr/bin/env python3
"""Test stocked item sale handling"""

import os
import sys
import asyncio
from pathlib import Path
from datetime import datetime

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import async_session
from app.models.product import Product, ProductStatus
from app.models.sync_event import SyncEvent, SyncEventType
from app.services.sync_services import SyncService
from sqlalchemy import select
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_stocked_item_sale():
    """Test that stocked items have quantity decremented instead of being marked as sold"""
    
    async with async_session() as db:
        # Find a stocked item with quantity > 1
        result = await db.execute(
            select(Product)
            .where(
                Product.is_stocked_item == True,
                Product.quantity > 1,
                Product.status == ProductStatus.ACTIVE
            )
            .limit(1)
        )
        product = result.scalar_one_or_none()
        
        if not product:
            logger.error("No active stocked items with quantity > 1 found")
            # Create a test stocked item
            product = Product(
                sku="TEST-STOCKED-001",
                title="Test Stocked Item",
                brand="Test Brand",
                model="Test Model",
                base_price=100.0,
                is_stocked_item=True,
                quantity=5,
                status=ProductStatus.ACTIVE
            )
            db.add(product)
            await db.commit()
            await db.refresh(product)
            logger.info(f"Created test stocked product: {product.sku} with quantity {product.quantity}")
        else:
            logger.info(f"Found stocked product: {product.sku} with quantity {product.quantity}")
        
        # Create a mock sale event
        sale_event = SyncEvent(
            platform_name='reverb',
            external_id='TEST-123',
            event_type=SyncEventType.STATUS_CHANGE,
            product_id=product.id,
            change_data={'old': 'live', 'new': 'sold'},
            created_at=datetime.utcnow()
        )
        db.add(sale_event)
        await db.commit()
        
        # Test the sync service
        sync_service = SyncService(db)
        
        # Process the sale event (dry run first)
        logger.info("\n=== DRY RUN TEST ===")
        initial_quantity = product.quantity
        initial_status = product.status
        
        report = await sync_service.process_pending_events(dry_run=True)
        logger.info(f"Dry run report: {report}")
        
        # Refresh to check nothing changed in dry run
        await db.refresh(product)
        assert product.quantity == initial_quantity, "Quantity should not change in dry run"
        assert product.status == initial_status, "Status should not change in dry run"
        
        # Now do actual processing
        logger.info("\n=== ACTUAL PROCESSING ===")
        report = await sync_service.process_pending_events(dry_run=False)
        logger.info(f"Processing report: {report}")
        
        # Refresh and check the results
        await db.refresh(product)
        logger.info(f"\nAfter processing:")
        logger.info(f"  Initial quantity: {initial_quantity}")
        logger.info(f"  New quantity: {product.quantity}")
        logger.info(f"  Status: {product.status}")
        
        # Verify behavior
        if initial_quantity > 1:
            assert product.quantity == initial_quantity - 1, f"Quantity should decrement by 1, but went from {initial_quantity} to {product.quantity}"
            assert product.status == ProductStatus.ACTIVE, f"Status should remain ACTIVE when quantity > 0, but is {product.status}"
            logger.info("✅ SUCCESS: Stocked item quantity decremented correctly!")
        
        # Test multiple sales until quantity reaches 0
        logger.info("\n=== TESTING MULTIPLE SALES ===")
        while product.quantity > 0:
            # Create another sale event
            sale_event = SyncEvent(
                platform_name='reverb',
                external_id=f'TEST-{product.quantity}',
                event_type=SyncEventType.STATUS_CHANGE,
                product_id=product.id,
                change_data={'old': 'live', 'new': 'sold'},
                created_at=datetime.utcnow()
            )
            db.add(sale_event)
            await db.commit()
            
            # Process
            await sync_service.process_pending_events(dry_run=False)
            await db.refresh(product)
            logger.info(f"After sale: Quantity = {product.quantity}, Status = {product.status}")
        
        # Final check - should be SOLD when quantity reaches 0
        assert product.quantity == 0, "Quantity should be 0"
        assert product.status == ProductStatus.SOLD, f"Status should be SOLD when quantity reaches 0, but is {product.status}"
        logger.info("✅ SUCCESS: Product marked as SOLD when quantity reached 0!")

async def main():
    await test_stocked_item_sale()

if __name__ == "__main__":
    asyncio.run(main())

# ==============================================================================
# ORIGINAL FILE: test_sync_safe.py
# ==============================================================================

#!/usr/bin/env python3
"""
Safe sync testing using test database clone
"""
import asyncio
import sys
import os
from pathlib import Path
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Use test environment BEFORE importing anything
os.environ['ENV_FILE'] = '.env.test'

# IMPORTANT: Clear any existing settings cache
from app.core.config import get_settings, clear_settings_cache
clear_settings_cache()

# Now import other modules
from app.database import get_session
from sqlalchemy import text

async def test_sync_operations():
    """Run your sync operations against the test database"""
    
    print("🧪 SAFE SYNC TESTING ON TEST DATABASE")
    print("=" * 60)
    
    # Verify we're using the correct environment
    settings = get_settings()
    print(f"📊 Database URL: {settings.DATABASE_URL}")
    
    if 'inventory_test' not in settings.DATABASE_URL:
        print("❌ ERROR: Not using test database!")
        print(f"Expected: ...inventory_test, Got: {settings.DATABASE_URL}")
        return
    
    # Test actual connection
    async with get_session() as db:
        result = await db.execute(text('SELECT current_database()'))
        current_db = result.scalar()
        print(f"📊 Connected to: {current_db}")
        
        if current_db != 'inventory_test':
            print("❌ ERROR: Connected to wrong database!")
            return
    
    print("✅ Successfully connected to test database!")
    
    # Rest of your sync operations...

if __name__ == "__main__":
    asyncio.run(test_sync_operations())
