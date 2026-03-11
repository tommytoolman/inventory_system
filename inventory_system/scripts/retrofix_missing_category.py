#!/usr/bin/env python3
"""
Retrofix missing category field by fetching from Reverb API.

Usage:
    python scripts/retrofix_missing_category.py [--dry-run]
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

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def fetch_reverb_category(reverb_id: str) -> tuple:
    """Fetch category from Reverb API for a given listing ID.
    
    Returns:
        tuple: (category_name, category_path) or (None, None) if not found
    """
    settings = get_settings()
    client = ReverbClient(api_key=settings.REVERB_API_KEY)
    
    try:
        # Fetch listing details from Reverb
        listing_data = await client.get_listing(reverb_id)
        
        # Extract categories - Reverb has a categories array
        categories = listing_data.get('categories', [])
        
        if categories:
            # Get the most specific (deepest) category
            category = categories[-1] if categories else None
            
            if category:
                # Category might have 'name' and 'full_name' fields
                category_name = category.get('name', category.get('full_name', None))
                
                # Build the full path from all categories
                category_path = ' > '.join([c.get('name', '') for c in categories if c.get('name')])
                
                if category_name:
                    logger.info(f"    Found category: {category_name}")
                    logger.info(f"    Full path: {category_path}")
                    return category_name, category_path
        
        # Alternative: check if there's a simple 'category' field
        simple_category = listing_data.get('category', None)
        if simple_category:
            logger.info(f"    Found category: {simple_category}")
            return simple_category, simple_category
            
        return None, None
        
    except Exception as e:
        logger.error(f"  Error fetching Reverb listing {reverb_id}: {e}")
        return None, None


async def fix_missing_categories(session, dry_run=False):
    """Fix missing categories for Reverb products by fetching from API."""
    logger.info("=== Fixing Missing Category Field ===")
    
    # Find Reverb products with missing category
    query = text('''
        SELECT id, sku, brand, model, year
        FROM products
        WHERE category IS NULL
        AND (sku LIKE 'REV-%' OR sku LIKE 'rev-%')
        ORDER BY id
    ''')
    
    result = await session.execute(query)
    products = result.fetchall()
    
    if not products:
        logger.info("  No Reverb products with missing category found")
        return 0
    
    logger.info(f"  Found {len(products)} Reverb products with missing category")
    
    fixed_count = 0
    
    for product in products:
        # Extract Reverb ID from SKU
        reverb_id = product.sku.replace('REV-', '').replace('rev-', '')
        
        logger.info(f"\n  Product {product.id}: {product.sku}")
        logger.info(f"    {product.brand} {product.model} {product.year or ''}")
        
        # Fetch category from Reverb API
        category_name, category_path = await fetch_reverb_category(reverb_id)
        
        if category_name:
            if not dry_run:
                # Update the product
                stmt = select(Product).where(Product.id == product.id)
                result = await session.execute(stmt)
                product_obj = result.scalar_one()
                
                # Use the most specific category name
                product_obj.category = category_name
                product_obj.updated_at = datetime.utcnow()
                
                logger.info(f"    💾 Updated category to: {category_name}")
            else:
                logger.info(f"    [DRY RUN] Would set category to: {category_name}")
            
            fixed_count += 1
        else:
            logger.info(f"    No category field in API response")
        
        # Small delay between API calls to be respectful
        await asyncio.sleep(1)
    
    # Commit all changes at once
    if not dry_run and fixed_count > 0:
        await session.commit()
        logger.info(f"\n  ✅ Committed {fixed_count} changes to database")
    
    logger.info(f"\n  Fixed {fixed_count}/{len(products)} products")
    return fixed_count


async def check_category_stats(session):
    """Show statistics about category field completion."""
    logger.info("\n=== Category Field Statistics ===")
    
    result = await session.execute(
        text('''
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN category IS NULL THEN 1 ELSE 0 END) as missing,
                SUM(CASE WHEN category IS NOT NULL THEN 1 ELSE 0 END) as has_category
            FROM products
        ''')
    )
    stats = result.fetchone()
    
    logger.info(f"  Total products: {stats.total}")
    logger.info(f"  Has category: {stats.has_category} ({stats.has_category/stats.total*100:.1f}%)")
    logger.info(f"  Missing category: {stats.missing} ({stats.missing/stats.total*100:.1f}%)")
    
    # Show which products are still missing
    result = await session.execute(
        text('''
            SELECT id, sku, brand, model
            FROM products
            WHERE category IS NULL
            ORDER BY sku
        ''')
    )
    missing = result.fetchall()
    
    if missing:
        logger.info("\n  Products still missing category:")
        for p in missing:
            logger.info(f"    {p.sku}: {p.brand} {p.model}")


async def main(dry_run=False):
    """Run category retrofix operations."""
    async with async_session() as session:
        try:
            logger.info("=" * 60)
            logger.info("RETROFIX MISSING CATEGORY FIELD")
            logger.info("=" * 60)
            logger.info(f"Mode: {'DRY RUN' if dry_run else 'LIVE'}")
            logger.info("")
            
            # Show current stats
            await check_category_stats(session)
            
            # Fix missing categories
            total_fixes = await fix_missing_categories(session, dry_run)
            
            if not dry_run and total_fixes > 0:
                # Show updated stats
                await check_category_stats(session)
            elif dry_run:
                logger.info("\n🔍 DRY RUN - No changes made")
            
            logger.info("")
            logger.info("=" * 60)
            logger.info(f"TOTAL FIXES: {total_fixes}")
            logger.info("=" * 60)
            
            return True
            
        except Exception as e:
            logger.error(f"Error during retrofix: {e}", exc_info=True)
            if not dry_run:
                await session.rollback()
            return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Retrofix missing category field from Reverb API')
    parser.add_argument('--dry-run', action='store_true', 
                        help='Show what would be fixed without making changes')
    args = parser.parse_args()
    
    success = asyncio.run(main(dry_run=args.dry_run))
    sys.exit(0 if success else 1)