#!/usr/bin/env python3
"""
Retrofix decade field by:
1. Deriving from existing year values
2. Fetching from Reverb API where year field contains decade strings

Usage:
    python scripts/retrofix_decade_field.py [--dry-run]
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


def year_to_decade(year: int) -> int:
    """Convert a year to decade integer (e.g., 1965 -> 1960)"""
    if year:
        decade_start = (year // 10) * 10
        return decade_start
    return None


async def fetch_reverb_decade(reverb_id: str) -> int:
    """Fetch decade from Reverb API for a given listing ID.
    
    Returns:
        int: The decade value (e.g., 1960) or None if not found
    """
    settings = get_settings()
    client = ReverbClient(api_key=settings.REVERB_API_KEY)
    
    try:
        # Fetch listing details from Reverb
        listing_data = await client.get_listing(reverb_id)
        
        # Check the year field first - it might contain decade string
        year_field = listing_data.get('year', None)
        
        # Check if it's a decade string (e.g., "1960s", "1970s")
        if year_field and isinstance(year_field, str) and year_field.endswith('s'):
            # Extract the decade number (e.g., "1960s" -> 1960)
            try:
                decade_num = int(year_field[:-1])  # Remove the 's' and convert to int
                logger.info(f"    Found decade string in year field: {year_field} -> {decade_num}")
                return decade_num
            except ValueError:
                pass
            
        # Try year_min/year_max to derive decade
        year_min = listing_data.get('year_min', None)
        year_max = listing_data.get('year_max', None)
        
        if year_min:
            try:
                year_int = int(year_min) if isinstance(year_min, str) else year_min
                decade = year_to_decade(year_int)
                if decade:
                    logger.info(f"    Derived decade from year_min ({year_min}): {decade}")
                    return decade
            except:
                pass
                
        if year_max:
            try:
                year_int = int(year_max) if isinstance(year_max, str) else year_max
                decade = year_to_decade(year_int)
                if decade:
                    logger.info(f"    Derived decade from year_max ({year_max}): {decade}")
                    return decade
            except:
                pass
        
        return None
        
    except Exception as e:
        logger.error(f"  Error fetching Reverb listing {reverb_id}: {e}")
        return None


async def fix_decade_from_year(session, dry_run=False):
    """Fix decade field for products that have year values."""
    logger.info("=== Fixing Decade from Existing Year Values ===")
    
    # Find products with year but no decade
    query = text('''
        SELECT id, sku, brand, model, year
        FROM products
        WHERE year IS NOT NULL AND decade IS NULL
        ORDER BY id
    ''')
    
    result = await session.execute(query)
    products = result.fetchall()
    
    if not products:
        logger.info("  No products with year but missing decade found")
        return 0
    
    logger.info(f"  Found {len(products)} products with year but missing decade")
    
    fixed_count = 0
    
    for product in products:
        decade = year_to_decade(product.year)
        
        if decade:
            logger.info(f"  {product.sku}: {product.year} → {decade}s")
            
            if not dry_run:
                # Update the product
                stmt = select(Product).where(Product.id == product.id)
                result = await session.execute(stmt)
                product_obj = result.scalar_one()
                
                product_obj.decade = decade
                product_obj.updated_at = datetime.utcnow()
                
            fixed_count += 1
    
    if not dry_run and fixed_count > 0:
        await session.commit()
        logger.info(f"  ✅ Updated {fixed_count} products with decade from year")
    
    return fixed_count


async def fix_decade_from_api(session, dry_run=False):
    """Fix decade field for Reverb products by fetching from API."""
    logger.info("\n=== Fixing Decade from Reverb API ===")
    
    # Find Reverb products without year AND without decade
    query = text('''
        SELECT id, sku, brand, model
        FROM products
        WHERE year IS NULL AND decade IS NULL
        AND (sku LIKE 'REV-%' OR sku LIKE 'rev-%')
        ORDER BY id
    ''')
    
    result = await session.execute(query)
    products = result.fetchall()
    
    if not products:
        logger.info("  No Reverb products missing both year and decade found")
        return 0
    
    logger.info(f"  Found {len(products)} Reverb products missing both year and decade")
    logger.info("  Will process in batches with 1s delay between API calls...")
    
    fixed_count = 0
    commit_frequency = 25
    products_since_commit = 0
    
    for i, product in enumerate(products):
        if i % 10 == 0:
            logger.info(f"\n  Processing batch starting at {i+1}/{len(products)}")
        
        # Extract Reverb ID from SKU
        reverb_id = product.sku.replace('REV-', '').replace('rev-', '')
        
        logger.info(f"    {product.sku}: {product.brand} {product.model or ''}")
        
        # Fetch decade from Reverb API
        decade = await fetch_reverb_decade(reverb_id)
        
        if decade:
            if not dry_run:
                # Update the product
                stmt = select(Product).where(Product.id == product.id)
                result = await session.execute(stmt)
                product_obj = result.scalar_one()
                
                product_obj.decade = decade
                product_obj.updated_at = datetime.utcnow()
                
                logger.info(f"      💾 Set decade to: {decade}s")
            else:
                logger.info(f"      [DRY RUN] Would set decade to: {decade}s")
            
            fixed_count += 1
            products_since_commit += 1
            
            # Commit every 25 products
            if not dry_run and products_since_commit >= commit_frequency:
                await session.commit()
                logger.info(f"  ✅ Committed {products_since_commit} changes to database")
                products_since_commit = 0
        else:
            logger.info(f"      No decade information available")
        
        # Small delay between API calls to be respectful
        await asyncio.sleep(1)
    
    # Commit any remaining changes
    if not dry_run and products_since_commit > 0:
        await session.commit()
        logger.info(f"  ✅ Committed final {products_since_commit} changes to database")
    
    logger.info(f"\n  Fixed {fixed_count}/{len(products)} products from API")
    return fixed_count


async def check_decade_stats(session):
    """Show statistics about decade field completion."""
    logger.info("\n=== Decade Field Statistics ===")
    
    result = await session.execute(
        text('''
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN decade IS NULL THEN 1 ELSE 0 END) as missing,
                SUM(CASE WHEN decade IS NOT NULL THEN 1 ELSE 0 END) as has_decade
            FROM products
        ''')
    )
    stats = result.fetchone()
    
    logger.info(f"  Total products: {stats.total}")
    logger.info(f"  Has decade: {stats.has_decade} ({stats.has_decade/stats.total*100:.1f}%)")
    logger.info(f"  Missing decade: {stats.missing} ({stats.missing/stats.total*100:.1f}%)")
    
    # Check by platform
    result = await session.execute(
        text('''
            SELECT 
                CASE 
                    WHEN sku LIKE 'REV-%' OR sku LIKE 'rev-%' THEN 'Reverb'
                    WHEN sku LIKE 'EBY-%' THEN 'eBay'
                    ELSE 'Other'
                END as platform,
                COUNT(*) as total,
                SUM(CASE WHEN decade IS NULL THEN 1 ELSE 0 END) as missing
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
        else:
            logger.info(f"    {p.platform}: All have decade ✅")


async def main(dry_run=False):
    """Run decade retrofix operations."""
    async with async_session() as session:
        try:
            logger.info("=" * 60)
            logger.info("RETROFIX DECADE FIELD")
            logger.info("=" * 60)
            logger.info(f"Mode: {'DRY RUN' if dry_run else 'LIVE'}")
            logger.info("")
            
            # Show current stats
            await check_decade_stats(session)
            
            total_fixes = 0
            
            # First, fix from existing year values (no API calls needed)
            fixes = await fix_decade_from_year(session, dry_run)
            total_fixes += fixes
            
            # Then, fetch from API for remaining products
            fixes = await fix_decade_from_api(session, dry_run)
            total_fixes += fixes
            
            if not dry_run and total_fixes > 0:
                # Show updated stats
                await check_decade_stats(session)
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
    parser = argparse.ArgumentParser(description='Retrofix decade field from year values and Reverb API')
    parser.add_argument('--dry-run', action='store_true', 
                        help='Show what would be fixed without making changes')
    args = parser.parse_args()
    
    success = asyncio.run(main(dry_run=args.dry_run))
    sys.exit(0 if success else 1)