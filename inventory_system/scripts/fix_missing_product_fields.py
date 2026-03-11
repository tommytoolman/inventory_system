#!/usr/bin/env python
"""
Fix missing year, finish, and category fields for existing REV- products.
Fetches data from Reverb API and updates the products.
"""

import asyncio
import logging
import re
from sqlalchemy import select, update
from app.database import async_session
from app.models import Product
from app.services.reverb.client import ReverbClient
from app.core.config import get_settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def fix_product_fields(session, product, reverb_data):
    """Update a product with missing fields from Reverb data."""
    
    # Extract year (convert "1940s" to 1940)
    year_str = reverb_data.get('year', '')
    year = None
    if year_str:
        year_match = re.search(r'(\d{4})', str(year_str))
        if year_match:
            year = int(year_match.group(1))
    
    # Extract finish
    finish = reverb_data.get('finish', '')
    
    # Extract category from categories array
    category = None
    categories = reverb_data.get('categories', [])
    if categories and len(categories) > 0:
        category = categories[0].get('full_name', '')
    
    # Update the product
    updates = {}
    if year and not product.year:
        updates['year'] = year
        logger.info(f"  Setting year: {year_str} -> {year}")
    
    if finish and not product.finish:
        updates['finish'] = finish
        logger.info(f"  Setting finish: {finish}")
    
    if category and not product.category:
        updates['category'] = category
        logger.info(f"  Setting category: {category}")
    
    if updates:
        stmt = update(Product).where(Product.id == product.id).values(**updates)
        await session.execute(stmt)
        return True
    
    return False


async def main():
    """Fix missing fields for all REV- products."""
    
    settings = get_settings()
    
    async with async_session() as session:
        # Get all REV- products with missing fields
        stmt = select(Product).where(
            Product.sku.like('REV-%')
        ).where(
            (Product.year.is_(None)) | 
            (Product.finish.is_(None)) | 
            (Product.category.is_(None))
        )
        
        result = await session.execute(stmt)
        products = result.scalars().all()
        
        logger.info(f"Found {len(products)} REV- products with missing fields")
        
        if not products:
            logger.info("No products need fixing")
            return
        
        # Initialize Reverb client
        reverb_client = ReverbClient(
            api_key=settings.REVERB_API_KEY,
            use_sandbox=settings.REVERB_USE_SANDBOX
        )
        
        fixed_count = 0
        
        for product in products:
            # Extract Reverb ID from SKU (REV-12345 -> 12345)
            reverb_id = product.sku.replace('REV-', '')
            
            logger.info(f"\nProcessing {product.sku} (ID: {product.id})")
            logger.info(f"  Current - Year: {product.year}, Finish: {product.finish}, Category: {product.category}")
            
            try:
                # Fetch Reverb data
                reverb_data = await reverb_client.get_listing_details(reverb_id)
                
                if reverb_data:
                    # Update the product
                    if await fix_product_fields(session, product, reverb_data):
                        fixed_count += 1
                else:
                    logger.warning(f"  Could not fetch Reverb data for {reverb_id}")
                    
            except Exception as e:
                logger.error(f"  Error processing {product.sku}: {e}")
                continue
        
        # Commit all changes
        await session.commit()
        
        logger.info(f"\n{'='*60}")
        logger.info(f"COMPLETE: Fixed {fixed_count} products")
        logger.info(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())