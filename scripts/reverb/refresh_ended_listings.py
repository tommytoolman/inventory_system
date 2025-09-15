#!/usr/bin/env python3
"""
Refresh ended Reverb listings with shipping data.
"""

import asyncio
import sys
from pathlib import Path
from datetime import datetime

sys.path.append(str(Path(__file__).parent.parent.parent))

from app.services.reverb.client import ReverbClient
from app.core.config import get_settings
from app.database import async_session
from sqlalchemy import text, update
from app.models.platform_common import PlatformCommon
from app.models.reverb import ReverbListing

async def refresh_ended_listings():
    """Refresh data for ended listings."""
    
    settings = get_settings()
    client = ReverbClient(api_key=settings.REVERB_API_KEY)
    
    async with async_session() as session:
        # Get all ended listings that need refresh
        query = text("""
            SELECT 
                pc.id,
                pc.external_id,
                p.sku,
                pc.status
            FROM platform_common pc
            JOIN products p ON pc.product_id = p.id
            WHERE pc.platform_name = 'reverb'
              AND pc.status = 'ended'
              AND (pc.platform_specific_data IS NULL OR pc.platform_specific_data::text = '{}')
            ORDER BY pc.created_at
        """)
        result = await session.execute(query)
        listings = result.fetchall()
        
        print(f"📦 Refreshing {len(listings)} ended listings...\n")
        
        updated_count = 0
        error_count = 0
        profiles_found = {}
        
        for i, (pc_id, external_id, sku, status) in enumerate(listings, 1):
            try:
                print(f"{i}/{len(listings)}: {sku} (Status: {status})")
                
                # Fetch listing data - ended listings might return limited data
                listing_data = await client.get_listing(external_id)
                
                if listing_data:
                    # Extract shipping profile if available
                    shipping_profile = listing_data.get('shipping_profile', {})
                    profile_id = shipping_profile.get('id') if shipping_profile else None
                    profile_name = shipping_profile.get('name') if shipping_profile else None
                    
                    if profile_id:
                        profiles_found[profile_id] = profile_name
                        print(f"  ✅ Found shipping profile: {profile_name} (ID: {profile_id})")
                    else:
                        print(f"  ⚠️  No shipping profile in response")
                    
                    # Update platform_common with whatever data we got
                    stmt = (
                        update(PlatformCommon)
                        .where(PlatformCommon.id == pc_id)
                        .values(
                            platform_specific_data=listing_data,
                            updated_at=datetime.utcnow()
                        )
                    )
                    await session.execute(stmt)
                    
                    # Update reverb_listings if we have shipping profile
                    if profile_id:
                        reverb_stmt = (
                            update(ReverbListing)
                            .where(ReverbListing.platform_id == pc_id)
                            .values(
                                shipping_profile_id=profile_id,
                                updated_at=datetime.utcnow()
                            )
                        )
                        await session.execute(reverb_stmt)
                    
                    updated_count += 1
                else:
                    print(f"  ❌ No data returned (listing may be deleted)")
                    error_count += 1
                
                # Small delay to avoid rate limiting
                await asyncio.sleep(0.3)
                
            except Exception as e:
                error_count += 1
                print(f"  ❌ Error: {e}")
        
        # Commit all updates
        await session.commit()
        
        # Summary
        print("\n" + "=" * 60)
        print(f"📊 SUMMARY:")
        print(f"   Total ended listings: {len(listings)}")
        print(f"   Successfully updated: {updated_count}")
        if error_count > 0:
            print(f"   Errors/No data: {error_count}")
        
        if profiles_found:
            print(f"\n   Shipping Profiles Found:")
            for pid, pname in sorted(profiles_found.items(), key=lambda x: x[1]):
                print(f"   - {pname} (ID: {pid})")
        
        # Check final totals for ALL reverb listings
        stats_query = text("""
            SELECT 
                status,
                COUNT(*) as total,
                COUNT(CASE WHEN platform_specific_data::text != '{}' THEN 1 END) as with_data,
                COUNT(CASE WHEN platform_specific_data->'shipping_profile' IS NOT NULL THEN 1 END) as with_shipping
            FROM platform_common 
            WHERE platform_name = 'reverb'
            GROUP BY status
            ORDER BY status
        """)
        stats = await session.execute(stats_query)
        
        print(f"\n   Database Status by Status:")
        for row in stats:
            status, total, with_data, with_shipping = row
            print(f"   {status.upper()}:")
            print(f"     - Total: {total}")
            print(f"     - With data: {with_data} ({with_data*100//total if total > 0 else 0}%)")
            print(f"     - With shipping: {with_shipping} ({with_shipping*100//total if total > 0 else 0}%)")
        
        # Overall totals
        total_query = text("""
            SELECT 
                COUNT(*) as total,
                COUNT(CASE WHEN platform_specific_data::text != '{}' THEN 1 END) as with_data,
                COUNT(CASE WHEN platform_specific_data->'shipping_profile' IS NOT NULL THEN 1 END) as with_shipping
            FROM platform_common 
            WHERE platform_name = 'reverb'
        """)
        total_stats = await session.execute(total_query)
        total_row = total_stats.fetchone()
        
        print(f"\n   🎯 OVERALL TOTALS:")
        print(f"   - Total Reverb listings: {total_row[0]}")
        print(f"   - With data: {total_row[1]} ({total_row[1]*100//total_row[0]}%)")
        print(f"   - With shipping: {total_row[2]} ({total_row[2]*100//total_row[0]}%)")

if __name__ == "__main__":
    asyncio.run(refresh_ended_listings())