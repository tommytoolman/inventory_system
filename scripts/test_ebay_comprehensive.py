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