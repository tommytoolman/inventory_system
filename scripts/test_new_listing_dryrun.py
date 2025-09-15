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
