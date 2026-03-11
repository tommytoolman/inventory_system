#!/usr/bin/env python3
"""
Retrospective fix to reconcile a single VR listing that failed during initial creation.

Usage:
    python scripts/vr/fix_single_vr_listing.py --sku REV-91978742
"""

import asyncio
import argparse
import sys
from pathlib import Path
from datetime import datetime, timezone
import logging

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.database import async_session
from app.core.config import get_settings
from app.services.vintageandrare.client import VintageAndRareClient
from app.models.product import Product
from app.models.platform_common import PlatformCommon
from app.models.vr import VRListing
from sqlalchemy import select
from scripts.process_sync_event import reconcile_vr_listing_for_product

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def fix_single_vr_listing(sku: str):
    """
    Fix a single missing VR listing by running reconciliation.
    
    Args:
        sku: The product SKU to reconcile (e.g., REV-91978742)
    """
    async with async_session() as session:
        try:
            # Step 1: Find the product
            logger.info(f"Looking for product with SKU: {sku}")
            stmt = select(Product).where(Product.sku == sku)
            result = await session.execute(stmt)
            product = result.scalar_one_or_none()
            
            if not product:
                logger.error(f"Product not found with SKU: {sku}")
                return False
            
            logger.info(f"Found product: ID={product.id}, {product.brand} {product.model}")
            
            # Step 2: Check platform_common for VR
            stmt = select(PlatformCommon).where(
                PlatformCommon.product_id == product.id,
                PlatformCommon.platform_name == 'vr'
            )
            result = await session.execute(stmt)
            vr_platform = result.scalar_one_or_none()
            
            if not vr_platform:
                logger.error("No VR platform_common entry found for this product")
                return False
            
            logger.info(f"Found VR platform_common: ID={vr_platform.id}, external_id={vr_platform.external_id}")
            
            # Step 3: Check if vr_listings already exists
            stmt = select(VRListing).where(VRListing.platform_id == vr_platform.id)
            result = await session.execute(stmt)
            existing_vr_listing = result.scalar_one_or_none()
            
            if existing_vr_listing:
                logger.info(f"VR listing already exists: ID={existing_vr_listing.id}, vr_listing_id={existing_vr_listing.vr_listing_id}")
                return True
            
            logger.info("VR listing missing - attempting reconciliation...")
            
            # Step 4: Run reconciliation
            success = await reconcile_vr_listing_for_product(session, product)
            
            if success:
                logger.info("✅ Reconciliation successful!")
                
                # Verify the vr_listing was created
                stmt = select(VRListing).where(VRListing.platform_id == vr_platform.id)
                result = await session.execute(stmt)
                new_vr_listing = result.scalar_one_or_none()
                
                if new_vr_listing:
                    logger.info(f"✅ VR listing created: ID={new_vr_listing.id}, vr_listing_id={new_vr_listing.vr_listing_id}")
                    
                    # Also update the sync_events status if needed
                    from app.models.sync_event import SyncEvent
                    stmt = select(SyncEvent).where(
                        SyncEvent.external_id == sku.replace('REV-', ''),
                        SyncEvent.platform_name == 'reverb',
                        SyncEvent.status == 'processed'
                    )
                    result = await session.execute(stmt)
                    sync_event = result.scalar_one_or_none()
                    
                    if sync_event:
                        # Update to partial since VR reconciliation was needed
                        logger.info(f"Updating sync_event {sync_event.id} status from 'processed' to 'partial' (retrospective fix)")
                        sync_event.status = 'partial'
                        sync_event.notes = sync_event.notes or {}
                        if isinstance(sync_event.notes, str):
                            import json
                            sync_event.notes = json.loads(sync_event.notes)
                        sync_event.notes['retrospective_fix'] = f"VR reconciliation completed on {datetime.now(timezone.utc).isoformat()}"
                        import json
                        sync_event.notes = json.dumps(sync_event.notes)
                    
                    await session.commit()
                    return True
                else:
                    logger.error("Reconciliation reported success but no VR listing found")
                    return False
            else:
                logger.error("❌ Reconciliation failed")
                return False
                
        except Exception as e:
            logger.error(f"Error during fix: {e}", exc_info=True)
            return False


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description='Fix a single missing VR listing')
    parser.add_argument('--sku', required=True, help='Product SKU (e.g., REV-91978742)')
    args = parser.parse_args()
    
    success = asyncio.run(fix_single_vr_listing(args.sku))
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()