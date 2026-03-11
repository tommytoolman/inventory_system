#!/usr/bin/env python
"""
Reconcile VR listings created from Reverb imports.

This script:
1. Downloads VR inventory dataframe
2. Filters for active items (product sold != 'yes')
3. Gets existing VR IDs from database
4. Finds new VR listings (in dataframe but not in DB)
5. Matches them to REV- products using fuzzy matching
6. Updates platform_common and creates vr_listings entries

Run this AFTER batch creating VR listings from Reverb sync.
"""

import asyncio
import logging
import sys
import re
from datetime import datetime
from typing import Dict, List, Optional, Set

import pandas as pd
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.models import Product, PlatformCommon, VRListing
from app.services.vintageandrare.client import VintageAndRareClient
from app.core.config import get_settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def get_active_vr_listings_from_dataframe(client: VintageAndRareClient) -> pd.DataFrame:
    """
    Download VR inventory and filter for active listings.
    Returns DataFrame of active VR listings (where product sold != 'yes')
    """
    logger.info("📥 Downloading VR inventory dataframe...")
    
    # Download all VR listings
    inventory_df = await client.download_inventory_dataframe(save_to_file=True)
    
    if inventory_df is None or inventory_df.empty:
        logger.error("Failed to fetch VR inventory")
        return pd.DataFrame()
    
    logger.info(f"Downloaded {len(inventory_df)} total VR listings")
    
    # Filter for active listings (not sold)
    # The column might be 'product sold' or 'product_sold' depending on source
    sold_col = 'product_sold' if 'product_sold' in inventory_df.columns else 'product sold'
    active_df = inventory_df[inventory_df[sold_col] != 'yes'].copy()
    
    logger.info(f"📊 Found {len(active_df)} active VR listings (not sold)")
    
    return active_df


async def get_existing_vr_ids_from_database(session: AsyncSession) -> Set[str]:
    """
    Get all existing VR listing IDs from the database.
    Returns a set of VR IDs that we already have in vr_listings table.
    """
    logger.info("🔍 Fetching existing VR IDs from database...")
    
    stmt = select(VRListing.vr_listing_id).where(VRListing.vr_listing_id.isnot(None))
    result = await session.execute(stmt)
    existing_ids = {str(row[0]) for row in result if row[0]}
    
    logger.info(f"Found {len(existing_ids)} existing VR listings in database")
    
    return existing_ids


def get_col(df: pd.DataFrame, base_name: str) -> str:
    """Get column name handling both space and underscore variants."""
    underscore = base_name.replace(' ', '_')
    return underscore if underscore in df.columns else base_name


def sanitize_for_json(data: dict) -> dict:
    """Sanitize a dictionary for JSON storage by replacing NaN/inf with None."""
    import math
    sanitized = {}
    for key, value in data.items():
        if pd.isna(value):
            sanitized[key] = None
        elif isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            sanitized[key] = None
        else:
            sanitized[key] = value
    return sanitized


def safe_float(value, default=0.0) -> float:
    """Safely convert a value to float, handling NaN."""
    if pd.isna(value):
        return default
    try:
        result = float(value)
        if pd.isna(result):
            return default
        return result
    except (ValueError, TypeError):
        return default


async def find_new_vr_listings(active_df: pd.DataFrame, existing_ids: Set[str]) -> pd.DataFrame:
    """
    Find VR listings that are in the dataframe but not in the database.
    These are our candidate listings that need to be matched to products.
    """
    # Get VR IDs from dataframe
    id_col = get_col(active_df, 'product id')
    df_ids = set(active_df[id_col].astype(str))
    
    # Find new IDs (in dataframe but not in database)
    new_ids = df_ids - existing_ids
    
    logger.info(f"🆕 Found {len(new_ids)} new VR listings to reconcile")

    # Filter dataframe to only new listings
    new_listings_df = active_df[active_df[id_col].astype(str).isin(new_ids)].copy()
    
    return new_listings_df


async def get_unmatched_rev_products(session: AsyncSession) -> List[Dict]:
    """
    Get REV- products that have VR platform_common but either:
    1. No vr_listings entry at all, OR
    2. vr_listings entry with vr_listing_id = NULL
    These are products we created VR listings for but don't have the VR ID yet.
    """
    logger.info("🔍 Finding REV- products with VR platform but no valid vr_listing_id...")

    from sqlalchemy import or_

    # Query for products with REV- SKU and VR platform_common but missing vr_listing_id
    stmt = select(Product, PlatformCommon, VRListing).join(
        PlatformCommon, Product.id == PlatformCommon.product_id
    ).outerjoin(
        VRListing, PlatformCommon.id == VRListing.platform_id
    ).where(
        and_(
            Product.sku.like('REV-%'),
            PlatformCommon.platform_name == 'vr',
            or_(
                VRListing.id.is_(None),  # No vr_listings entry
                VRListing.vr_listing_id.is_(None)  # Has entry but no ID resolved
            )
        )
    )

    result = await session.execute(stmt)
    unmatched = []

    for product, platform_common, vr_listing in result:
        unmatched.append({
            'product': product,
            'platform_common': platform_common,
            'vr_listing': vr_listing,  # May be None or have null vr_listing_id
            'sku': product.sku,
            'brand': product.brand or '',
            'model': product.model or '',
            'year': product.year,
            'finish': product.finish or '',
            'price': product.base_price or product.price,
            'description': product.description or ''
        })

    logger.info(f"Found {len(unmatched)} REV- products needing VR ID reconciliation")

    return unmatched


def match_vr_listing_to_product(vr_row: pd.Series, unmatched_products: List[Dict]) -> Optional[Dict]:
    """
    Match a VR listing from the dataframe to one of our unmatched REV- products.
    Uses fuzzy matching on brand, model, year, finish, price, and description.
    """
    # Handle both space and underscore column names
    def get_val(base_name: str, default=''):
        underscore = base_name.replace(' ', '_')
        return vr_row.get(underscore, vr_row.get(base_name, default))

    vr_brand = str(get_val('brand name', '')).lower().strip()
    vr_model = str(get_val('product model name', '')).lower().strip()
    vr_year = str(get_val('product year', '')).strip()
    vr_finish = str(get_val('product finish', '')).lower().strip()
    vr_price = float(get_val('product price', 0) or 0)
    vr_description = str(get_val('product description', '')).lower()
    
    logger.debug(f"Attempting to match VR listing: {vr_brand} {vr_model} {vr_year} £{vr_price}")
    
    best_match = None
    best_score = 0
    
    for product_data in unmatched_products:
        score = 0
        
        # Brand match (required)
        if vr_brand and product_data['brand'].lower() == vr_brand:
            score += 30
        else:
            continue  # Skip if brand doesn't match
        
        # Model match (heavily weighted)
        if vr_model and product_data['model'].lower() == vr_model:
            score += 30
        
        # Year match
        if vr_year and product_data['year']:
            if str(product_data['year']) == vr_year:
                score += 15
            elif vr_year.endswith('s') and str(product_data['year']).startswith(vr_year[:3]):
                # e.g., "1960s" matches 1965
                score += 10
        
        # Finish match
        if vr_finish and product_data['finish'].lower() == vr_finish:
            score += 10
        
        # Price match (within 5% tolerance)
        if vr_price > 0 and product_data['price']:
            price_ratio = abs(vr_price - product_data['price']) / max(vr_price, product_data['price'])
            if price_ratio < 0.05:  # Within 5%
                score += 15
            elif price_ratio < 0.10:  # Within 10%
                score += 10
        
        # Check for SKU in description (strong indicator)
        if product_data['sku'] in vr_description:
            score += 20
            logger.info(f"  Found SKU {product_data['sku']} in VR description!")
        
        # If this is the best match so far
        if score > best_score and score >= 50:  # Minimum threshold
            best_score = score
            best_match = product_data
    
    if best_match:
        vr_id = vr_row.get('product_id', vr_row.get('product id', '?'))
        logger.info(f"  ✅ Matched VR {vr_id} to {best_match['sku']} (score: {best_score})")
    else:
        vr_id = vr_row.get('product_id', vr_row.get('product id', '?'))
        logger.debug(f"  ❌ No match found for VR {vr_id}")
    
    return best_match


async def reconcile_vr_listings(session: AsyncSession, username: str, password: str, dry_run: bool = False):
    """Main reconciliation process."""
    
    stats = {
        "vr_total": 0,
        "vr_active": 0,
        "vr_new": 0,
        "products_needing_match": 0,
        "matched": 0,
        "vr_listings_created": 0,
        "platform_common_updated": 0,
        "errors": 0
    }
    
    try:
        # Initialize VR client
        client = VintageAndRareClient(username, password)
        
        # Authenticate
        logger.info("🔐 Authenticating with V&R...")
        if not await client.authenticate():
            logger.error("V&R authentication failed")
            return {"error": "Authentication failed"}
        
        # Step 1: Get active VR listings from dataframe
        active_df = await get_active_vr_listings_from_dataframe(client)
        stats["vr_total"] = len(await client.download_inventory_dataframe(save_to_file=False))
        stats["vr_active"] = len(active_df)
        
        if active_df.empty:
            logger.info("No active VR listings found")
            return stats
        
        # Step 2: Get existing VR IDs from database
        existing_ids = await get_existing_vr_ids_from_database(session)
        
        # Step 3: Find new VR listings
        new_vr_df = await find_new_vr_listings(active_df, existing_ids)
        stats["vr_new"] = len(new_vr_df)
        
        if new_vr_df.empty:
            logger.info("No new VR listings to reconcile")
            return stats
        
        # Step 4: Get unmatched REV- products
        unmatched_products = await get_unmatched_rev_products(session)
        stats["products_needing_match"] = len(unmatched_products)
        
        if not unmatched_products:
            logger.info("No REV- products need VR reconciliation")
            return stats
        
        logger.info(f"🔄 Attempting to match {len(new_vr_df)} VR listings to {len(unmatched_products)} products...")
        
        # Step 5: Match each new VR listing to a product
        # Helper for column access
        def get_v(row, base_name, default=''):
            underscore = base_name.replace(' ', '_')
            return row.get(underscore, row.get(base_name, default))

        for idx, vr_row in new_vr_df.iterrows():
            try:
                vr_id = str(get_v(vr_row, 'product id'))
                # Handle NaN in external_link - pandas returns float NaN
                raw_url = get_v(vr_row, 'external link', '')
                if pd.isna(raw_url) or not raw_url:
                    vr_url = f"https://www.vintageandrare.com/product/{vr_id}"
                else:
                    vr_url = str(raw_url)

                logger.info(f"\n🔍 Processing VR listing {vr_id}: {get_v(vr_row, 'brand name')} {get_v(vr_row, 'product model name')}")
                
                # Try to match to a product
                match = match_vr_listing_to_product(vr_row, unmatched_products)
                
                if not match:
                    continue
                
                stats["matched"] += 1

                product = match['product']
                platform_common = match['platform_common']
                existing_vr_listing = match.get('vr_listing')

                # Update platform_common with real VR ID and URL
                logger.info(f"  Updating platform_common {platform_common.id}: external_id {platform_common.external_id} → {vr_id}")

                if not dry_run:
                    platform_common.external_id = vr_id
                    platform_common.listing_url = vr_url
                    stats["platform_common_updated"] += 1

                    # Sanitize extended attributes for JSON storage
                    extended_attrs = sanitize_for_json(vr_row.to_dict())

                    # Safe parsing of processing time
                    proc_time_raw = get_v(vr_row, 'processing time', '3')
                    try:
                        proc_time = int(str(proc_time_raw).split()[0]) if proc_time_raw and not pd.isna(proc_time_raw) else 3
                    except (ValueError, AttributeError):
                        proc_time = 3

                    if existing_vr_listing:
                        # Update existing VRListing entry
                        existing_vr_listing.vr_listing_id = vr_id
                        existing_vr_listing.vr_state = 'active'
                        existing_vr_listing.in_collective = get_v(vr_row, 'product in collective', '') == 'yes'
                        existing_vr_listing.in_inventory = get_v(vr_row, 'product in inventory', '') == 'yes'
                        existing_vr_listing.in_reseller = get_v(vr_row, 'product in reseller', '') == 'yes'
                        existing_vr_listing.collective_discount = safe_float(get_v(vr_row, 'collective discount', 0), 0.0)
                        existing_vr_listing.price_notax = safe_float(get_v(vr_row, 'product price notax', 0), 0.0)
                        existing_vr_listing.show_vat = get_v(vr_row, 'show vat', '') == 'yes'
                        existing_vr_listing.processing_time = proc_time
                        existing_vr_listing.extended_attributes = extended_attrs
                        stats["vr_listings_updated"] = stats.get("vr_listings_updated", 0) + 1
                        logger.info(f"  ✅ Updated vr_listings entry {existing_vr_listing.id} with VR ID {vr_id}")
                    else:
                        # Create new vr_listings entry
                        vr_listing = VRListing(
                            platform_id=platform_common.id,
                            vr_listing_id=vr_id,
                            vr_state='active',
                            inventory_quantity=1,
                            in_collective=get_v(vr_row, 'product in collective', '') == 'yes',
                            in_inventory=get_v(vr_row, 'product in inventory', '') == 'yes',
                            in_reseller=get_v(vr_row, 'product in reseller', '') == 'yes',
                            collective_discount=safe_float(get_v(vr_row, 'collective discount', 0), 0.0),
                            price_notax=safe_float(get_v(vr_row, 'product price notax', 0), 0.0),
                            show_vat=get_v(vr_row, 'show vat', '') == 'yes',
                            processing_time=proc_time,
                            extended_attributes=extended_attrs
                        )
                        session.add(vr_listing)
                        stats["vr_listings_created"] += 1
                        logger.info(f"  ✅ Created vr_listings entry for {vr_id}")
                
                # Remove from unmatched list so we don't match it again
                unmatched_products.remove(match)
                
            except Exception as e:
                logger.error(f"Error processing VR listing {vr_row.get('product id')}: {e}")
                stats["errors"] += 1
                continue
        
        if not dry_run:
            await session.commit()
            logger.info("💾 Changes committed to database")
        else:
            logger.info("🔍 DRY RUN - no changes made")
        
    except Exception as e:
        logger.error(f"Reconciliation failed: {e}", exc_info=True)
        if not dry_run:
            await session.rollback()
        raise
    
    return stats


async def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Reconcile VR listings with REV- products")
    parser.add_argument("--username", help="V&R username (or use env var)")
    parser.add_argument("--password", help="V&R password (or use env var)")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without committing")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable debug logging")
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Get credentials from args or environment
    settings = get_settings()
    username = args.username or settings.VINTAGE_AND_RARE_USERNAME
    password = args.password or settings.VINTAGE_AND_RARE_PASSWORD
    
    if not username or not password:
        logger.error("V&R credentials required (use --username/--password or set env vars)")
        sys.exit(1)
    
    
    async with async_session() as session:
        try:
            stats = await reconcile_vr_listings(
                session, 
                username, 
                password,
                dry_run=args.dry_run
            )
            
            logger.info("\n" + "="*60)
            logger.info("VR RECONCILIATION COMPLETE")
            logger.info("="*60)
            logger.info(f"VR Inventory Total: {stats.get('vr_total', 0)}")
            logger.info(f"VR Active Listings: {stats.get('vr_active', 0)}")
            logger.info(f"New VR Listings: {stats.get('vr_new', 0)}")
            logger.info(f"Products Needing Match: {stats.get('products_needing_match', 0)}")
            logger.info(f"Successfully Matched: {stats.get('matched', 0)}")
            logger.info(f"VR Listings Created: {stats.get('vr_listings_created', 0)}")
            logger.info(f"VR Listings Updated: {stats.get('vr_listings_updated', 0)}")
            logger.info(f"Platform Common Updated: {stats.get('platform_common_updated', 0)}")
            logger.info(f"Errors: {stats.get('errors', 0)}")
            
            if args.dry_run:
                logger.info("\n⚠️  DRY RUN - No changes were made to the database")
            
        except Exception as e:
            logger.error(f"Reconciliation failed: {e}")
            sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())