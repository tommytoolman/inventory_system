#!/usr/bin/env python3
"""
Retrofix missing product images by fetching from Reverb API.
Uses the same method as the sync process.

Usage:
    python scripts/retrofix_missing_images.py [--dry-run] [--limit N]
"""

import asyncio
import argparse
import sys
from pathlib import Path
from datetime import datetime
import logging
import json

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
    """Fetch images from Reverb API for a given listing ID.
    
    Returns:
        tuple: (primary_image_url, additional_images_list)
    """
    settings = get_settings()
    client = ReverbClient(api_key=settings.REVERB_API_KEY)
    
    try:
        # Fetch listing details from Reverb
        logger.info(f"  Fetching Reverb listing {reverb_id}...")
        listing_data = await client.get_listing(reverb_id)
        
        # Extract photos (same logic as process_sync_event.py)
        photos = listing_data.get('photos', [])
        logger.info(f"  Found {len(photos)} photos")
        
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
                    # Transform to MAX_RES using the same transformer as sync
                    max_res_url = ImageTransformer.transform_reverb_url(image_url, ImageQuality.MAX_RES)
                    
                    if idx == 0:
                        primary_image = max_res_url
                        logger.info(f"    Primary: {primary_image[:80]}...")
                    else:
                        additional_images.append(max_res_url)
                        
        return primary_image, additional_images
        
    except Exception as e:
        logger.error(f"  Error fetching Reverb listing {reverb_id}: {e}")
        return None, []


async def fix_reverb_products(session, dry_run=False, limit=None):
    """Fix missing images for Reverb products by fetching from API."""
    logger.info("=== Fixing Reverb Product Images ===")
    
    # Find Reverb products with missing images
    query = text('''
        SELECT id, sku, brand, model
        FROM products
        WHERE primary_image IS NULL
        AND (sku LIKE 'REV-%' OR sku LIKE 'rev-%')
        ORDER BY id
    ''')
    
    if limit:
        query = text(f'{query.text} LIMIT {limit}')
    
    result = await session.execute(query)
    products = result.fetchall()
    
    if not products:
        logger.info("  No Reverb products with missing images found")
        return 0
    
    logger.info(f"  Found {len(products)} Reverb products with missing images")
    
    fixed_count = 0
    for product in products:
        # Extract Reverb ID from SKU
        reverb_id = product.sku.replace('REV-', '').replace('rev-', '')
        
        logger.info(f"\nProcessing Product {product.id}: {product.sku}")
        logger.info(f"  {product.brand} {product.model}")
        logger.info(f"  Reverb ID: {reverb_id}")
        
        # Fetch images from Reverb API
        primary_image, additional_images = await fetch_reverb_images(reverb_id)
        
        if primary_image:
            logger.info(f"  ✅ Found images - Primary + {len(additional_images)} additional")
            
            if not dry_run:
                # Update the product
                stmt = select(Product).where(Product.id == product.id)
                result = await session.execute(stmt)
                product_obj = result.scalar_one()
                
                product_obj.primary_image = primary_image
                product_obj.additional_images = additional_images if additional_images else []
                product_obj.updated_at = datetime.utcnow()
                
                logger.info(f"  💾 Updated product {product.id}")
            
            fixed_count += 1
        else:
            logger.warning(f"  ❌ No images found for Reverb listing {reverb_id}")
    
    logger.info(f"\n  Fixed {fixed_count}/{len(products)} products")
    return fixed_count


async def fix_ebay_products(session, dry_run=False, limit=None):
    """Fix missing images for eBay products."""
    logger.info("\n=== eBay Products ===")
    
    # Find eBay products with missing images
    query = text('''
        SELECT id, sku, brand, model
        FROM products
        WHERE primary_image IS NULL
        AND sku LIKE 'EBY-%'
        ORDER BY id
    ''')
    
    if limit:
        query = text(f'{query.text} LIMIT {limit}')
    
    result = await session.execute(query)
    products = result.fetchall()
    
    if not products:
        logger.info("  No eBay products with missing images found")
        return 0
    
    logger.info(f"  Found {len(products)} eBay products with missing images")
    logger.info("  ⚠️  eBay image fetching not implemented yet - would need eBay API integration")
    logger.info("  Consider using scripts/ebay/get_item_details.py to fetch these manually")
    
    for product in products:
        ebay_id = product.sku.replace('EBY-', '')
        logger.info(f"    - {product.sku}: {product.brand} {product.model} (eBay ID: {ebay_id})")
    
    return 0


async def enrich_additional_images(session, dry_run=False, limit=None):
    """Enrich products that have empty additional_images arrays."""
    logger.info("\n=== Enriching Empty Additional Images ===")
    
    # Find products with empty additional_images that could be enriched
    query = text('''
        SELECT id, sku, brand, model, primary_image
        FROM products
        WHERE additional_images = '[]'::jsonb
        AND primary_image IS NOT NULL
        AND (sku LIKE 'REV-%' OR sku LIKE 'rev-%')
        ORDER BY id
    ''')
    
    if limit:
        query = text(f'{query.text} LIMIT {limit}')
    
    result = await session.execute(query)
    products = result.fetchall()
    
    if not products:
        logger.info("  No products with empty additional_images found")
        return 0
    
    logger.info(f"  Found {len(products)} products with empty additional_images")
    
    enriched_count = 0
    for product in products:
        reverb_id = product.sku.replace('REV-', '').replace('rev-', '')
        
        logger.info(f"\nProcessing Product {product.id}: {product.sku}")
        
        # Fetch images from Reverb API
        primary_image, additional_images = await fetch_reverb_images(reverb_id)
        
        if additional_images:
            logger.info(f"  ✅ Found {len(additional_images)} additional images")
            
            if not dry_run:
                # Update only additional_images
                stmt = select(Product).where(Product.id == product.id)
                result = await session.execute(stmt)
                product_obj = result.scalar_one()
                
                product_obj.additional_images = additional_images
                product_obj.updated_at = datetime.utcnow()
                
                logger.info(f"  💾 Updated additional images for product {product.id}")
            
            enriched_count += 1
        else:
            logger.info(f"  No additional images found")
    
    logger.info(f"\n  Enriched {enriched_count}/{len(products)} products")
    return enriched_count


async def main(dry_run=False, limit=None):
    """Run image retrofix operations."""
    async with async_session() as session:
        try:
            logger.info("=" * 60)
            logger.info("RETROFIX MISSING IMAGES")
            logger.info("=" * 60)
            logger.info(f"Mode: {'DRY RUN' if dry_run else 'LIVE'}")
            if limit:
                logger.info(f"Limit: {limit} products per category")
            logger.info("")
            
            total_fixes = 0
            
            # Fix Reverb products
            total_fixes += await fix_reverb_products(session, dry_run, limit)
            
            # Report on eBay products (not fixed yet)
            await fix_ebay_products(session, dry_run, limit)
            
            # Enrich products with empty additional_images
            total_fixes += await enrich_additional_images(session, dry_run, limit)
            
            if not dry_run:
                logger.info("\nCommitting changes...")
                await session.commit()
                logger.info("✅ All changes committed successfully")
            else:
                logger.info("\n🔍 DRY RUN - No changes made")
            
            logger.info("")
            logger.info("=" * 60)
            logger.info(f"TOTAL FIXES/ENRICHMENTS: {total_fixes}")
            logger.info("=" * 60)
            
            return True
            
        except Exception as e:
            logger.error(f"Error during retrofix: {e}", exc_info=True)
            if not dry_run:
                await session.rollback()
            return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Retrofix missing product images from Reverb API')
    parser.add_argument('--dry-run', action='store_true', 
                        help='Show what would be fixed without making changes')
    parser.add_argument('--limit', type=int, default=None,
                        help='Limit number of products to process per category')
    args = parser.parse_args()
    
    success = asyncio.run(main(dry_run=args.dry_run, limit=args.limit))
    sys.exit(0 if success else 1)