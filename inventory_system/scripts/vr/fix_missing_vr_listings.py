#!/usr/bin/env python3
"""
One-off script to fix missing or incomplete vr_listings entries.
Downloads VR inventory and creates/updates vr_listings for all platform_common entries.

Usage:
    python scripts/vr/fix_missing_vr_listings.py [--dry-run]
"""

import asyncio
import argparse
import sys
from pathlib import Path
from datetime import datetime, timezone
import pandas as pd
import logging

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.database import async_session
from app.core.config import get_settings
from app.services.vintageandrare.client import VintageAndRareClient
from app.models.platform_common import PlatformCommon
from app.models.vr import VRListing
from sqlalchemy import select, and_
from sqlalchemy.orm import selectinload

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def fix_missing_vr_listings(dry_run: bool = False):
    """
    Download VR inventory and create/update missing vr_listings entries.
    
    Args:
        dry_run: If True, only report what would be done without making changes
    """
    settings = get_settings()
    
    async with async_session() as session:
        try:
            # Step 1: Initialize VR client and authenticate
            logger.info("Initializing VR client...")
            client = VintageAndRareClient(
                username=settings.VINTAGE_AND_RARE_USERNAME,
                password=settings.VINTAGE_AND_RARE_PASSWORD
            )
            
            # Clean up any existing temp files
            client.cleanup_temp_files()
            
            if not await client.authenticate():
                logger.error("VR authentication failed")
                return False
            
            # Step 2: Download VR inventory
            logger.info("Downloading VR inventory...")
            inventory_result = await client.download_inventory_dataframe(save_to_file=False)
            
            # Check for timeout
            if isinstance(inventory_result, str) and inventory_result == "RETRY_NEEDED":
                logger.error("VR inventory download timed out")
                return False
            
            if inventory_result is None or (isinstance(inventory_result, pd.DataFrame) and inventory_result.empty):
                logger.error("Failed to download VR inventory or inventory is empty")
                return False
            
            inventory_df = inventory_result
            logger.info(f"Downloaded {len(inventory_df)} VR listings")
            
            # Create lookup dict by VR ID
            vr_inventory = {}
            for _, row in inventory_df.iterrows():
                vr_id = str(row.get('product_id', ''))
                if vr_id:
                    vr_inventory[vr_id] = row
            
            # Step 3: Get all platform_common entries for VR
            logger.info("Fetching platform_common entries for VR...")
            stmt = select(PlatformCommon).where(
                PlatformCommon.platform_name == 'vr'
            ).options(selectinload(PlatformCommon.vr_listing))
            
            result = await session.execute(stmt)
            platform_commons = result.scalars().all()
            logger.info(f"Found {len(platform_commons)} VR platform_common entries")
            
            # Step 4: Check each platform_common for missing/incomplete vr_listings
            created_count = 0
            updated_count = 0
            skipped_count = 0
            
            for pc in platform_commons:
                vr_id = pc.external_id
                
                # Skip if we don't have this VR ID in the inventory
                if vr_id not in vr_inventory:
                    logger.debug(f"VR ID {vr_id} not found in current inventory - skipping")
                    skipped_count += 1
                    continue
                
                vr_row = vr_inventory[vr_id]
                
                # Check if vr_listing exists
                stmt_vr = select(VRListing).where(
                    VRListing.platform_id == pc.id
                )
                result_vr = await session.execute(stmt_vr)
                existing_vr_listing = result_vr.scalar_one_or_none()
                
                if existing_vr_listing:
                    # Check if it needs updating (empty extended_attributes)
                    if not existing_vr_listing.extended_attributes or existing_vr_listing.extended_attributes == {}:
                        logger.info(f"Updating incomplete vr_listing for VR ID {vr_id}")
                        
                        if not dry_run:
                            # Update with full data
                            existing_vr_listing.collective_discount = float(vr_row.get('collective_discount', 0) or 0)
                            # Use product_price for price_notax field (price_notax doesn't exist in CSV)
                            price_val = vr_row.get('product_price', 0)
                            existing_vr_listing.price_notax = float(price_val) if not pd.isna(price_val) else 0.0
                            existing_vr_listing.show_vat = str(vr_row.get('show_vat', '')).lower() == 'yes'
                            existing_vr_listing.in_collective = str(vr_row.get('product_in_collective', '')).lower() == 'yes'
                            existing_vr_listing.in_inventory = str(vr_row.get('product_in_inventory', '')).lower() == 'yes'
                            existing_vr_listing.in_reseller = str(vr_row.get('product_in_reseller', '')).lower() == 'yes'
                            
                            # Parse processing_time
                            processing_time_str = vr_row.get('processing_time', '3 Days')
                            if isinstance(processing_time_str, str):
                                try:
                                    existing_vr_listing.processing_time = int(processing_time_str.split()[0])
                                except:
                                    existing_vr_listing.processing_time = 3
                            else:
                                existing_vr_listing.processing_time = 3
                            
                            existing_vr_listing.last_synced_at = datetime.now(timezone.utc).replace(tzinfo=None)
                            
                            # Sanitize NaN values before storing as JSON
                            row_dict = vr_row.to_dict() if hasattr(vr_row, 'to_dict') else dict(vr_row)
                            sanitized_dict = {}
                            for key, value in row_dict.items():
                                if pd.isna(value):
                                    sanitized_dict[key] = None
                                else:
                                    sanitized_dict[key] = value
                            existing_vr_listing.extended_attributes = sanitized_dict
                        
                        updated_count += 1
                else:
                    # Create new vr_listing
                    logger.info(f"Creating missing vr_listing for VR ID {vr_id}")
                    
                    if not dry_run:
                        # Parse processing_time
                        processing_time_str = vr_row.get('processing_time', '3 Days')
                        if isinstance(processing_time_str, str):
                            try:
                                processing_time_val = int(processing_time_str.split()[0])
                            except:
                                processing_time_val = 3
                        else:
                            processing_time_val = 3
                        
                        # Sanitize NaN values before storing as JSON
                        row_dict = vr_row.to_dict() if hasattr(vr_row, 'to_dict') else dict(vr_row)
                        sanitized_dict = {}
                        for key, value in row_dict.items():
                            if pd.isna(value):
                                sanitized_dict[key] = None
                            else:
                                sanitized_dict[key] = value
                        
                        new_vr_listing = VRListing(
                            platform_id=pc.id,
                            vr_listing_id=vr_id,
                            vr_state='active' if str(vr_row.get('product_sold', '')).lower() != 'yes' else 'sold',
                            inventory_quantity=1,
                            in_collective=str(vr_row.get('product_in_collective', '')).lower() == 'yes',
                            in_inventory=str(vr_row.get('product_in_inventory', '')).lower() == 'yes',
                            in_reseller=str(vr_row.get('product_in_reseller', '')).lower() == 'yes',
                            collective_discount=float(vr_row.get('collective_discount', 0) or 0),
                            price_notax=float(vr_row.get('product_price', 0) or 0) if not pd.isna(vr_row.get('product_price')) else 0.0,
                            show_vat=str(vr_row.get('show_vat', '')).lower() == 'yes',
                            processing_time=processing_time_val,
                            last_synced_at=datetime.now(timezone.utc).replace(tzinfo=None),
                            extended_attributes=sanitized_dict
                        )
                        session.add(new_vr_listing)
                    
                    created_count += 1
            
            # Step 5: Commit changes
            if not dry_run:
                logger.info("Committing changes to database...")
                await session.commit()
                logger.info("Changes committed successfully")
            else:
                logger.info("DRY RUN - No changes made to database")
            
            # Report results
            logger.info("\n" + "="*60)
            logger.info("FIX MISSING VR_LISTINGS COMPLETE")
            logger.info("="*60)
            logger.info(f"Created: {created_count} new vr_listings entries")
            logger.info(f"Updated: {updated_count} incomplete vr_listings entries") 
            logger.info(f"Skipped: {skipped_count} (not in current inventory)")
            logger.info(f"Total processed: {len(platform_commons)} platform_common entries")
            
            return True
            
        except Exception as e:
            logger.error(f"Error fixing VR listings: {e}", exc_info=True)
            return False
        finally:
            # Ensure cleanup
            client.cleanup_temp_files()
            client.cleanup_selenium()


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description='Fix missing or incomplete vr_listings entries')
    parser.add_argument('--dry-run', action='store_true', 
                        help='Show what would be done without making changes')
    args = parser.parse_args()
    
    success = asyncio.run(fix_missing_vr_listings(dry_run=args.dry_run))
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()