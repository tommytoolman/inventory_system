#!/usr/bin/env python3
"""
Retrofix images for a single product by fetching from Reverb API.

Usage:
    python scripts/retrofix_single_image.py --sku REV-4981589
"""

import asyncio
import argparse
import sys
from pathlib import Path
from datetime import datetime
import logging

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import async_session
from sqlalchemy import select, text
from app.models.product import Product
from app.services.reverb.client import ReverbClient
from app.core.config import get_settings
from app.core.utils import ImageTransformer, ImageQuality

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def fetch_reverb_images(reverb_id: str) -> tuple:
    """Fetch images from Reverb API for a given listing ID."""
    settings = get_settings()
    client = ReverbClient(api_key=settings.REVERB_API_KEY)
    
    try:
        # Fetch listing details from Reverb
        logger.info(f"Fetching Reverb listing {reverb_id}...")
        listing_data = await client.get_listing(reverb_id)
        
        # Extract photos
        photos = listing_data.get('photos', [])
        logger.info(f"Found {len(photos)} photos")
        
        primary_image = None
        additional_images = []
        
        if photos:
            for idx, photo in enumerate(photos):
                links = photo.get('_links', {})
                
                # Try to get the best quality image URL
                image_url = None
                if 'large_crop' in links:
                    image_url = links['large_crop']['href']
                elif 'full' in links:
                    image_url = links['full']['href']
                elif isinstance(photo, str):
                    image_url = photo
                
                if image_url:
                    # Transform to MAX_RES
                    max_res_url = ImageTransformer.transform_reverb_url(image_url, ImageQuality.MAX_RES)
                    
                    if idx == 0:
                        primary_image = max_res_url
                        logger.info(f"  Primary: {primary_image[:80]}...")
                    else:
                        additional_images.append(max_res_url)
                        
        return primary_image, additional_images
        
    except Exception as e:
        logger.error(f"Error fetching Reverb listing {reverb_id}: {e}")
        return None, []


async def fix_single_product(sku: str):
    """Fix images for a single product."""
    async with async_session() as session:
        try:
            # Find the product
            stmt = select(Product).where(Product.sku == sku)
            result = await session.execute(stmt)
            product = result.scalar_one_or_none()
            
            if not product:
                logger.error(f"Product not found: {sku}")
                return False
            
            logger.info(f"\n=== FIXING PRODUCT {product.id} ===")
            logger.info(f"SKU: {product.sku}")
            logger.info(f"Brand/Model: {product.brand} {product.model}")
            logger.info(f"Current Primary Image: {product.primary_image}")
            logger.info(f"Current Additional Images: {len(product.additional_images) if product.additional_images else 0}")
            
            # Extract Reverb ID from SKU
            reverb_id = sku.replace('REV-', '').replace('rev-', '')
            logger.info(f"Reverb ID: {reverb_id}\n")
            
            # Fetch images from Reverb API
            primary_image, additional_images = await fetch_reverb_images(reverb_id)
            
            if primary_image:
                logger.info(f"\n✅ Found images:")
                logger.info(f"  Primary: {primary_image[:80]}...")
                logger.info(f"  Additional: {len(additional_images)} images")
                
                # Update the product
                product.primary_image = primary_image
                product.additional_images = additional_images if additional_images else []
                product.updated_at = datetime.utcnow()
                
                await session.commit()
                logger.info(f"\n💾 Product updated successfully!")
                
                # Verify the update
                await session.refresh(product)
                logger.info(f"\n=== AFTER FIX ===")
                logger.info(f"Primary Image: {product.primary_image[:80]}...")
                logger.info(f"Additional Images: {len(product.additional_images)} images")
                
                return True
            else:
                logger.warning(f"❌ No images found for Reverb listing {reverb_id}")
                return False
                
        except Exception as e:
            logger.error(f"Error: {e}", exc_info=True)
            await session.rollback()
            return False


def main():
    parser = argparse.ArgumentParser(description='Fix images for a single product')
    parser.add_argument('--sku', required=True, help='Product SKU (e.g., REV-4981589)')
    args = parser.parse_args()
    
    success = asyncio.run(fix_single_product(args.sku))
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()