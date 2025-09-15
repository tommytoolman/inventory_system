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