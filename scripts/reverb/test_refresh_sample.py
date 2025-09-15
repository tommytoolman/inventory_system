#!/usr/bin/env python3
"""
Test refresh on a small sample of listings to verify it works.
"""

import asyncio
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent.parent))

from app.services.reverb.client import ReverbClient
from app.core.config import get_settings
from app.database import async_session
from sqlalchemy import text

async def test_sample():
    """Test refreshing data for just 3 listings."""
    
    settings = get_settings()
    client = ReverbClient(api_key=settings.REVERB_API_KEY)
    
    async with async_session() as session:
        # Get 3 sample listings
        query = text("""
            SELECT 
                pc.external_id,
                p.sku
            FROM platform_common pc
            JOIN products p ON pc.product_id = p.id
            WHERE pc.platform_name = 'reverb'
              AND pc.status = 'active'
              AND (pc.platform_specific_data IS NULL OR pc.platform_specific_data::text = '{}')
            LIMIT 3
        """)
        result = await session.execute(query)
        
        print("🔍 Testing data refresh for 3 sample listings:\n")
        
        for row in result:
            external_id, sku = row
            print(f"📦 Fetching {sku} (ID: {external_id})...")
            
            try:
                # Fetch listing data
                listing_data = await client.get_listing(external_id)
                
                # Check what we got
                has_shipping = 'shipping_profile' in listing_data
                profile_id = listing_data.get('shipping_profile', {}).get('id') if has_shipping else None
                profile_name = listing_data.get('shipping_profile', {}).get('name') if has_shipping else None
                
                if has_shipping:
                    print(f"   ✅ Found shipping profile: {profile_name} (ID: {profile_id})")
                else:
                    print(f"   ⚠️  No shipping profile in API response")
                
                # Show some other key fields
                print(f"   - Price: {listing_data.get('price', {}).get('display', 'N/A')}")
                print(f"   - State: {listing_data.get('state', {}).get('slug', 'unknown')}")
                print(f"   - Has shipping rates: {'shipping' in listing_data and 'rates' in listing_data['shipping']}")
                print()
                
            except Exception as e:
                print(f"   ❌ Error: {e}\n")
        
        # Show summary stats
        print("\n" + "=" * 60)
        print("📊 SUMMARY OF LISTINGS NEEDING REFRESH:\n")
        
        stats_query = text("""
            SELECT 
                COUNT(*) as total_needing_refresh,
                COUNT(CASE WHEN status = 'active' THEN 1 END) as active_needing,
                COUNT(CASE WHEN status = 'ended' THEN 1 END) as ended_needing
            FROM platform_common 
            WHERE platform_name = 'reverb'
              AND (platform_specific_data IS NULL OR platform_specific_data::text = '{}')
        """)
        stats_result = await session.execute(stats_query)
        stats = stats_result.fetchone()
        
        print(f"   Total listings needing refresh: {stats[0]}")
        print(f"   - Active: {stats[1]}")
        print(f"   - Ended: {stats[2]}")
        
        print(f"\n   Estimated time to refresh all: ~{stats[1] * 0.5 / 60:.1f} minutes")
        print(f"   (at 0.5 seconds per listing)")

if __name__ == "__main__":
    asyncio.run(test_sample())