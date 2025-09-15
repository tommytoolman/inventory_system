#!/usr/bin/env python3
"""
Comprehensive retrofix script for missing fields in database.
Fixes category, quantity, processing_time, and other missing fields.

Usage:
    python scripts/retrofix_missing_fields.py [--dry-run]
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
from sqlalchemy import select, update, and_
from app.models.product import Product
from app.models.vr import VRListing

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def fix_missing_categories(session, dry_run=False):
    """Fix missing categories based on brand/model analysis."""
    logger.info("=== Fixing Missing Categories ===")
    
    # Manual category assignments based on brand/model
    category_fixes = [
        # Product 495: Fender Stratocaster
        {
            'id': 495,
            'sku': 'REV-91978553',
            'category': 'Electric Guitars / Solid Body'
        }
    ]
    
    fixed_count = 0
    for fix in category_fixes:
        stmt = select(Product).where(Product.id == fix['id'])
        result = await session.execute(stmt)
        product = result.scalar_one_or_none()
        
        if product and product.category is None:
            logger.info(f"  Fixing category for {fix['sku']}: {fix['category']}")
            if not dry_run:
                product.category = fix['category']
                product.updated_at = datetime.utcnow()
            fixed_count += 1
    
    logger.info(f"  Fixed {fixed_count} categories")
    return fixed_count


async def fix_missing_quantities(session, dry_run=False):
    """Fix missing quantities - all vintage items should have quantity=1."""
    logger.info("=== Fixing Missing Quantities ===")
    
    # Find all products with NULL quantity
    stmt = select(Product).where(
        and_(
            Product.quantity.is_(None),
            Product.is_stocked_item == False  # Only fix non-stocked items
        )
    )
    result = await session.execute(stmt)
    products = result.scalars().all()
    
    fixed_count = 0
    for product in products:
        logger.info(f"  Setting quantity=1 for {product.sku}")
        if not dry_run:
            product.quantity = 1
            product.updated_at = datetime.utcnow()
        fixed_count += 1
    
    logger.info(f"  Fixed {fixed_count} quantities")
    return fixed_count


async def fix_processing_times(session, dry_run=False):
    """Fix missing processing times in products table."""
    logger.info("=== Fixing Product Processing Times ===")
    
    # Set default processing time to 3 days for all NULL values
    stmt = select(Product).where(Product.processing_time.is_(None))
    result = await session.execute(stmt)
    products = result.scalars().all()
    
    fixed_count = 0
    for product in products:
        if not dry_run:
            product.processing_time = 3  # Default 3 days
            product.updated_at = datetime.utcnow()
        fixed_count += 1
    
    logger.info(f"  Set processing_time=3 for {fixed_count} products")
    return fixed_count


async def fix_vr_processing_times(session, dry_run=False):
    """Fix missing processing times in vr_listings by parsing extended_attributes."""
    logger.info("=== Fixing VR Listing Processing Times ===")
    
    # Find VR listings with NULL processing_time but data in extended_attributes
    stmt = select(VRListing).where(
        and_(
            VRListing.processing_time.is_(None),
            VRListing.extended_attributes.isnot(None)
        )
    )
    result = await session.execute(stmt)
    vr_listings = result.scalars().all()
    
    fixed_count = 0
    for listing in vr_listings:
        # Try to extract processing_time from extended_attributes
        if listing.extended_attributes and 'processing_time' in listing.extended_attributes:
            csv_time = listing.extended_attributes.get('processing_time', '')
            
            # Parse the time string (e.g., "3 Days" -> 3, "1 Weeks" -> 7)
            if isinstance(csv_time, str):
                if 'Days' in csv_time or 'days' in csv_time:
                    try:
                        days = int(csv_time.split()[0])
                        logger.info(f"  Setting processing_time={days} for VR listing {listing.vr_listing_id}")
                        if not dry_run:
                            listing.processing_time = days
                            listing.updated_at = datetime.utcnow()
                        fixed_count += 1
                    except (ValueError, IndexError):
                        pass
                elif 'Week' in csv_time or 'week' in csv_time:
                    try:
                        weeks = int(csv_time.split()[0])
                        days = weeks * 7
                        logger.info(f"  Setting processing_time={days} for VR listing {listing.vr_listing_id}")
                        if not dry_run:
                            listing.processing_time = days
                            listing.updated_at = datetime.utcnow()
                        fixed_count += 1
                    except (ValueError, IndexError):
                        pass
    
    # For any still NULL, default to 3
    stmt = select(VRListing).where(VRListing.processing_time.is_(None))
    result = await session.execute(stmt)
    remaining = result.scalars().all()
    
    for listing in remaining:
        logger.info(f"  Setting default processing_time=3 for VR listing {listing.vr_listing_id}")
        if not dry_run:
            listing.processing_time = 3
            listing.updated_at = datetime.utcnow()
        fixed_count += 1
    
    logger.info(f"  Fixed {fixed_count} VR processing times")
    return fixed_count


async def fix_boolean_fields(session, dry_run=False):
    """Fix NULL boolean fields with sensible defaults."""
    logger.info("=== Fixing Boolean Fields ===")
    
    # Boolean fields that should default to False
    boolean_defaults = {
        'is_sold': False,
        'in_collective': False, 
        'in_inventory': True,  # Default to true for active items
        'in_reseller': False,
        'free_shipping': False,
        'buy_now': True,  # Default to true for immediate purchase
        'show_vat': True,  # UK business, show VAT
        'local_pickup': False,
        'available_for_shipment': True  # Default to true for active items
    }
    
    fixed_count = 0
    for field_name, default_value in boolean_defaults.items():
        stmt = f"UPDATE products SET {field_name} = %s WHERE {field_name} IS NULL"
        
        if not dry_run:
            # Using raw SQL for efficiency
            from sqlalchemy import text
            update_stmt = text(f"UPDATE products SET {field_name} = :value, updated_at = NOW() WHERE {field_name} IS NULL")
            result = await session.execute(update_stmt, {'value': default_value})
            count = result.rowcount
            if count > 0:
                logger.info(f"  Set {field_name}={default_value} for {count} products")
                fixed_count += count
    
    logger.info(f"  Fixed {fixed_count} boolean fields total")
    return fixed_count


async def main(dry_run=False):
    """Run all retrofix operations."""
    async with async_session() as session:
        try:
            logger.info("=" * 60)
            logger.info("RETROFIX MISSING FIELDS")
            logger.info("=" * 60)
            logger.info(f"Mode: {'DRY RUN' if dry_run else 'LIVE'}")
            logger.info("")
            
            total_fixes = 0
            
            # Run all fixes
            total_fixes += await fix_missing_categories(session, dry_run)
            total_fixes += await fix_missing_quantities(session, dry_run)
            total_fixes += await fix_processing_times(session, dry_run)
            total_fixes += await fix_vr_processing_times(session, dry_run)
            total_fixes += await fix_boolean_fields(session, dry_run)
            
            if not dry_run:
                logger.info("\nCommitting changes...")
                await session.commit()
                logger.info("✅ All changes committed successfully")
            else:
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
    parser = argparse.ArgumentParser(description='Retrofix missing fields in database')
    parser.add_argument('--dry-run', action='store_true', 
                        help='Show what would be fixed without making changes')
    args = parser.parse_args()
    
    success = asyncio.run(main(dry_run=args.dry_run))
    sys.exit(0 if success else 1)