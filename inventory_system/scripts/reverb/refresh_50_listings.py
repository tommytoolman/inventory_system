#!/usr/bin/env python3
"""
Refresh 50 Reverb listings with shipping data.
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

async def refresh_50_listings():
    """Refresh data for 50 listings."""
    
    settings = get_settings()
    client = ReverbClient(api_key=settings.REVERB_API_KEY)
    
    async with async_session() as session:
        # Get 50 listings that need refresh
        query = text("""
            SELECT 
                pc.id,
                pc.external_id,
                p.sku
            FROM platform_common pc
            JOIN products p ON pc.product_id = p.id
            WHERE pc.platform_name = 'reverb'
              AND pc.status = 'active'
              AND (pc.platform_specific_data IS NULL OR pc.platform_specific_data::text = '{}')
            ORDER BY pc.created_at
            LIMIT 50
        """)
        result = await session.execute(query)
        listings = result.fetchall()
        
        print(f"📦 Refreshing {len(listings)} listings...\n")
        
        updated_count = 0
        profiles_found = {}
        
        for i, (pc_id, external_id, sku) in enumerate(listings, 1):
            try:
                # Progress indicator
                if i % 10 == 1:
                    print(f"\n📦 Batch {(i-1)//10 + 1}/5 (listings {i}-{min(i+9, len(listings))}):")
                
                # Fetch listing data
                listing_data = await client.get_listing(external_id)
                
                # Extract shipping profile
                shipping_profile = listing_data.get('shipping_profile', {})
                profile_id = shipping_profile.get('id') if shipping_profile else None
                profile_name = shipping_profile.get('name') if shipping_profile else None
                
                if profile_id:
                    profiles_found[profile_id] = profile_name
                    print(f"  ✅ {sku}: {profile_name} (ID: {profile_id})")
                else:
                    print(f"  ⚠️  {sku}: No shipping profile")
                
                # Update platform_common
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
                
                # Small delay to avoid rate limiting
                await asyncio.sleep(0.3)
                
            except Exception as e:
                print(f"  ❌ {sku}: Error - {e}")
        
        # Commit all updates
        await session.commit()
        
        # Summary
        print("\n" + "=" * 60)
        print(f"📊 SUMMARY:")
        print(f"   Updated: {updated_count}/{len(listings)} listings")
        print(f"\n   Shipping Profiles Found:")
        for pid, pname in profiles_found.items():
            print(f"   - {pname} (ID: {pid})")
        
        # Check new totals
        stats_query = text("""
            SELECT 
                COUNT(*) as total,
                COUNT(CASE WHEN platform_specific_data::text != '{}' THEN 1 END) as with_data,
                COUNT(CASE WHEN platform_specific_data->'shipping_profile' IS NOT NULL THEN 1 END) as with_shipping
            FROM platform_common 
            WHERE platform_name = 'reverb' AND status = 'active'
        """)
        stats = await session.execute(stats_query)
        row = stats.fetchone()
        
        print(f"\n   Database Status:")
        print(f"   - Total active: {row[0]}")
        print(f"   - With data: {row[1]} ({row[1]*100//row[0]}%)")
        print(f"   - With shipping: {row[2]} ({row[2]*100//row[0]}%)")
        print(f"   - Still need refresh: {row[0] - row[1]}")

if __name__ == "__main__":
    asyncio.run(refresh_50_listings())