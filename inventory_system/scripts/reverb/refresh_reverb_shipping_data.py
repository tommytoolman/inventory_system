#!/usr/bin/env python3
"""
Refresh shipping data for all active Reverb listings.

This script fetches fresh data from Reverb API for all active listings 
and updates the platform_specific_data field with complete information,
including shipping profiles.

Usage:
    # Dry run - shows what would be updated
    python scripts/reverb/refresh_reverb_shipping_data.py --dry-run
    
    # Actually update the database
    python scripts/reverb/refresh_reverb_shipping_data.py
    
    # Update specific listings by external ID
    python scripts/reverb/refresh_reverb_shipping_data.py --ids 91672123,91728940
    
    # Update in smaller batches (default is 10)
    python scripts/reverb/refresh_reverb_shipping_data.py --batch-size 5

Background:
    On August 13, 2025, 450 Reverb listings were imported with empty platform_specific_data.
    Starting September 4, 2025, new imports began capturing full API data including shipping profiles.
    This script backfills the missing data for the older listings.
"""

import asyncio
import sys
import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional
import argparse

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent.parent))

from app.services.reverb.client import ReverbClient
from app.core.config import get_settings
from app.database import async_session
from sqlalchemy import select, update, text
from app.models.platform_common import PlatformCommon
from app.models.reverb import ReverbListing

async def get_listings_needing_refresh(session, specific_ids: Optional[List[str]] = None):
    """Get all active Reverb listings with empty platform_specific_data."""
    
    if specific_ids:
        # Get specific listings by external ID
        query = text("""
            SELECT 
                pc.id,
                pc.external_id,
                pc.product_id,
                p.sku,
                pc.platform_specific_data
            FROM platform_common pc
            JOIN products p ON pc.product_id = p.id
            WHERE pc.platform_name = 'reverb'
              AND pc.external_id = ANY(:ids)
            ORDER BY pc.created_at
        """)
        result = await session.execute(query, {"ids": specific_ids})
    else:
        # Get all listings with empty data
        query = text("""
            SELECT 
                pc.id,
                pc.external_id,
                pc.product_id,
                p.sku,
                pc.platform_specific_data
            FROM platform_common pc
            JOIN products p ON pc.product_id = p.id
            WHERE pc.platform_name = 'reverb'
              AND pc.status = 'active'
              AND (pc.platform_specific_data IS NULL OR pc.platform_specific_data::text = '{}')
            ORDER BY pc.created_at
        """)
        result = await session.execute(query)
    
    listings = []
    for row in result:
        listings.append({
            'id': row[0],
            'external_id': row[1],
            'product_id': row[2],
            'sku': row[3],
            'current_data': row[4] or {}
        })
    
    return listings

async def refresh_listing_data(client: ReverbClient, listing_info: Dict, dry_run: bool = False):
    """Fetch fresh data from Reverb API for a single listing."""
    
    try:
        # Fetch detailed listing data
        listing_data = await client.get_listing(listing_info['external_id'])
        
        if not listing_data:
            print(f"  ❌ No data returned for {listing_info['sku']} (ID: {listing_info['external_id']})")
            return None
        
        # Extract key shipping information
        shipping_info = {
            'has_shipping_profile': 'shipping_profile' in listing_data and listing_data['shipping_profile'],
            'shipping_profile_id': listing_data.get('shipping_profile', {}).get('id') if listing_data.get('shipping_profile') else None,
            'shipping_profile_name': listing_data.get('shipping_profile', {}).get('name') if listing_data.get('shipping_profile') else None,
            'has_shipping_rates': 'shipping' in listing_data and 'rates' in listing_data.get('shipping', {})
        }
        
        if dry_run:
            print(f"  ✅ Would update {listing_info['sku']} with shipping profile: {shipping_info['shipping_profile_name']} (ID: {shipping_info['shipping_profile_id']})")
        else:
            print(f"  ✅ Fetched data for {listing_info['sku']} - Profile: {shipping_info['shipping_profile_name']} (ID: {shipping_info['shipping_profile_id']})")
        
        return {
            'platform_common_id': listing_info['id'],
            'external_id': listing_info['external_id'],
            'sku': listing_info['sku'],
            'api_data': listing_data,
            'shipping_info': shipping_info
        }
        
    except Exception as e:
        print(f"  ❌ Error fetching {listing_info['sku']}: {e}")
        return None

async def update_database_records(session, updates: List[Dict]):
    """Update platform_common and reverb_listings with fresh data."""
    
    updated_count = 0
    
    for update_data in updates:
        if not update_data:
            continue
        
        try:
            # Update platform_common with full API data
            stmt = (
                update(PlatformCommon)
                .where(PlatformCommon.id == update_data['platform_common_id'])
                .values(
                    platform_specific_data=update_data['api_data'],
                    updated_at=datetime.utcnow()
                )
            )
            await session.execute(stmt)
            
            # Also update reverb_listings shipping_profile_id if we have the data
            if update_data['shipping_info']['shipping_profile_id']:
                reverb_stmt = (
                    update(ReverbListing)
                    .where(ReverbListing.platform_id == update_data['platform_common_id'])
                    .values(
                        shipping_profile_id=update_data['shipping_info']['shipping_profile_id'],
                        updated_at=datetime.utcnow()
                    )
                )
                await session.execute(reverb_stmt)
            
            updated_count += 1
            
        except Exception as e:
            print(f"  ❌ Error updating {update_data['sku']}: {e}")
    
    if updated_count > 0:
        await session.commit()
        print(f"\n✅ Updated {updated_count} records in database")
    
    return updated_count

async def main(dry_run: bool = False, batch_size: int = 10, specific_ids: Optional[List[str]] = None):
    """Main function to refresh Reverb shipping data."""
    
    settings = get_settings()
    client = ReverbClient(api_key=settings.REVERB_API_KEY)
    
    async with async_session() as session:
        # Get listings needing refresh
        print("🔍 Fetching listings that need data refresh...")
        listings = await get_listings_needing_refresh(session, specific_ids)
        
        if not listings:
            print("✅ No listings need refreshing!")
            return
        
        print(f"📦 Found {len(listings)} listings needing refresh")
        
        if dry_run:
            print("\n🔄 DRY RUN MODE - No changes will be made\n")
        
        # Process in batches
        total_updated = 0
        for i in range(0, len(listings), batch_size):
            batch = listings[i:i+batch_size]
            batch_num = (i // batch_size) + 1
            total_batches = (len(listings) + batch_size - 1) // batch_size
            
            print(f"\n📦 Processing batch {batch_num}/{total_batches} ({len(batch)} listings)...")
            
            # Fetch data for this batch
            updates = []
            for listing in batch:
                update_data = await refresh_listing_data(client, listing, dry_run)
                if update_data:
                    updates.append(update_data)
                
                # Small delay to avoid rate limiting
                await asyncio.sleep(0.5)
            
            # Update database if not dry run
            if not dry_run and updates:
                batch_updated = await update_database_records(session, updates)
                total_updated += batch_updated
            elif dry_run:
                total_updated += len(updates)
        
        # Final summary
        print("\n" + "=" * 60)
        print(f"📊 SUMMARY:")
        print(f"   Total listings checked: {len(listings)}")
        if dry_run:
            print(f"   Would update: {total_updated} listings")
        else:
            print(f"   Successfully updated: {total_updated} listings")
            
            # Show current state
            query = text("""
                SELECT 
                    COUNT(*) as total,
                    COUNT(CASE WHEN platform_specific_data::text != '{}' THEN 1 END) as with_data,
                    COUNT(CASE WHEN platform_specific_data->'shipping_profile' IS NOT NULL THEN 1 END) as with_shipping
                FROM platform_common 
                WHERE platform_name = 'reverb' AND status = 'active'
            """)
            result = await session.execute(query)
            row = result.fetchone()
            print(f"\n   Current state of active listings:")
            print(f"   - Total: {row[0]}")
            print(f"   - With data: {row[1]}")
            print(f"   - With shipping profile: {row[2]}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Refresh Reverb shipping data")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be updated without making changes")
    parser.add_argument("--batch-size", type=int, default=10, help="Number of listings to process at once")
    parser.add_argument("--ids", type=str, help="Comma-separated list of external IDs to update")
    
    args = parser.parse_args()
    
    specific_ids = None
    if args.ids:
        specific_ids = [id.strip() for id in args.ids.split(",")]
    
    asyncio.run(main(
        dry_run=args.dry_run, 
        batch_size=args.batch_size,
        specific_ids=specific_ids
    ))