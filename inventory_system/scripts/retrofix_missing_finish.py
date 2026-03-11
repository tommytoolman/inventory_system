#!/usr/bin/env python3
"""
Retrofix missing finish field by fetching from Reverb API.

Usage:
    python scripts/retrofix_missing_finish.py [--dry-run] [--limit N]
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


async def fetch_reverb_finish(reverb_id: str) -> str:
    """Fetch finish from Reverb API for a given listing ID.
    
    Returns:
        str: The finish value or None if not found
    """
    settings = get_settings()
    client = ReverbClient(api_key=settings.REVERB_API_KEY)
    
    try:
        # Fetch listing details from Reverb
        listing_data = await client.get_listing(reverb_id)
        
        # Extract finish
        finish = listing_data.get('finish', None)
        
        if finish:
            logger.info(f"    Found finish: {finish}")
        
        return finish
        
    except Exception as e:
        logger.error(f"  Error fetching Reverb listing {reverb_id}: {e}")
        return None


async def fix_missing_finish(session, dry_run=False, limit=None):
    """Fix missing finish for Reverb products by fetching from API."""
    logger.info("=== Fixing Missing Finish Field ===")
    
    # Find Reverb products with missing finish
    query = text('''
        SELECT id, sku, brand, model, year
        FROM products
        WHERE finish IS NULL
        AND (sku LIKE 'REV-%' OR sku LIKE 'rev-%')
        ORDER BY id
    ''')
    
    if limit:
        query = text(f'{query.text} LIMIT {limit}')
    
    result = await session.execute(query)
    products = result.fetchall()
    
    if not products:
        logger.info("  No Reverb products with missing finish found")
        return 0
    
    logger.info(f"  Found {len(products)} Reverb products with missing finish")
    
    fixed_count = 0
    batch_size = 10  # Process in batches to avoid too many API calls
    commit_frequency = 25  # Commit every 25 products
    products_since_commit = 0
    
    for i in range(0, len(products), batch_size):
        batch = products[i:i+batch_size]
        logger.info(f"\nProcessing batch {i//batch_size + 1} ({len(batch)} products)")
        
        for product in batch:
            # Extract Reverb ID from SKU
            reverb_id = product.sku.replace('REV-', '').replace('rev-', '')
            
            logger.info(f"\n  Product {product.id}: {product.sku}")
            logger.info(f"    {product.brand} {product.model} {product.year or ''}")
            
            # Fetch finish from Reverb API
            finish = await fetch_reverb_finish(reverb_id)
            
            if finish:
                if not dry_run:
                    # Update the product
                    stmt = select(Product).where(Product.id == product.id)
                    result = await session.execute(stmt)
                    product_obj = result.scalar_one()
                    
                    product_obj.finish = finish
                    product_obj.updated_at = datetime.utcnow()
                    
                    logger.info(f"    💾 Updated finish to: {finish}")
                else:
                    logger.info(f"    [DRY RUN] Would set finish to: {finish}")
                
                fixed_count += 1
                products_since_commit += 1
                
                # Commit every 25 products
                if not dry_run and products_since_commit >= commit_frequency:
                    await session.commit()
                    logger.info(f"  ✅ Committed {products_since_commit} changes to database")
                    products_since_commit = 0
            else:
                logger.info(f"    No finish field in API response")
            
            # Small delay between API calls to be respectful
            await asyncio.sleep(1)
        
        # Small delay between batches to be nice to the API
        if i + batch_size < len(products):
            await asyncio.sleep(1)
    
    # Commit any remaining changes
    if not dry_run and products_since_commit > 0:
        await session.commit()
        logger.info(f"  ✅ Committed final {products_since_commit} changes to database")
    
    logger.info(f"\n  Fixed {fixed_count}/{len(products)} products")
    return fixed_count


async def check_finish_stats(session):
    """Show statistics about finish field completion."""
    logger.info("\n=== Finish Field Statistics ===")
    
    result = await session.execute(
        text('''
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN finish IS NULL THEN 1 ELSE 0 END) as missing,
                SUM(CASE WHEN finish IS NOT NULL THEN 1 ELSE 0 END) as has_finish
            FROM products
        ''')
    )
    stats = result.fetchone()
    
    logger.info(f"  Total products: {stats.total}")
    logger.info(f"  Has finish: {stats.has_finish} ({stats.has_finish/stats.total*100:.1f}%)")
    logger.info(f"  Missing finish: {stats.missing} ({stats.missing/stats.total*100:.1f}%)")
    
    # Check by platform
    result = await session.execute(
        text('''
            SELECT 
                CASE 
                    WHEN sku LIKE 'REV-%' OR sku LIKE 'rev-%' THEN 'Reverb'
                    WHEN sku LIKE 'EBY-%' THEN 'eBay'
                    WHEN sku LIKE 'VR-%' THEN 'VintageAndRare'
                    WHEN sku LIKE 'SHOP-%' THEN 'Shopify'
                    ELSE 'Other'
                END as platform,
                COUNT(*) as total,
                SUM(CASE WHEN finish IS NULL THEN 1 ELSE 0 END) as missing
            FROM products
            GROUP BY platform
            ORDER BY platform
        ''')
    )
    platforms = result.fetchall()
    
    logger.info("\n  By platform:")
    for p in platforms:
        if p.missing > 0:
            logger.info(f"    {p.platform}: {p.missing}/{p.total} missing ({p.missing/p.total*100:.1f}%)")


async def main(dry_run=False, limit=None):
    """Run finish retrofix operations."""
    async with async_session() as session:
        try:
            logger.info("=" * 60)
            logger.info("RETROFIX MISSING FINISH FIELD")
            logger.info("=" * 60)
            logger.info(f"Mode: {'DRY RUN' if dry_run else 'LIVE'}")
            if limit:
                logger.info(f"Limit: {limit} products")
            logger.info("")
            
            # Show current stats
            await check_finish_stats(session)
            
            # Fix missing finish (commits are handled inside the function every 25 products)
            total_fixes = await fix_missing_finish(session, dry_run, limit)
            
            if not dry_run and total_fixes > 0:
                # Show updated stats
                await check_finish_stats(session)
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
    parser = argparse.ArgumentParser(description='Retrofix missing finish field from Reverb API')
    parser.add_argument('--dry-run', action='store_true', 
                        help='Show what would be fixed without making changes')
    parser.add_argument('--limit', type=int, default=None,
                        help='Limit number of products to process')
    args = parser.parse_args()
    
    success = asyncio.run(main(dry_run=args.dry_run, limit=args.limit))
    sys.exit(0 if success else 1)