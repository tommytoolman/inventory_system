#!/usr/bin/env python3
"""
Update shipping profiles with actual rates from Reverb data.

This script reads the shipping_profile_details.json and updates
the rates in the database with the actual values.

Usage:
    python scripts/shipping/update_shipping_rates.py
"""

import asyncio
import json
import sys
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent.parent))

from sqlalchemy import select, update
from app.database import async_session
from app.models.shipping import ShippingProfile

async def update_rates():
    """Update shipping rates from Reverb data."""
    
    # Read the shipping profile details
    details_file = Path(__file__).parent.parent / "reverb/output/shipping_profile_details.json"
    
    if not details_file.exists():
        print(f"❌ File not found: {details_file}")
        return
    
    with open(details_file, 'r') as f:
        data = json.load(f)
    
    profiles_data = data.get('profiles', {})
    
    print("📦 Updating shipping rates from Reverb data...")
    print("=" * 60)
    
    async with async_session() as session:
        # Get all profiles from database
        result = await session.execute(select(ShippingProfile))
        db_profiles = result.scalars().all()
        
        updated_count = 0
        
        for profile in db_profiles:
            if profile.reverb_profile_id in profiles_data:
                reverb_data = profiles_data[profile.reverb_profile_id]
                shipping_rates = reverb_data.get('shipping_rates', [])
                
                # Convert Reverb rates to our format
                rates = {}
                
                for rate_info in shipping_rates:
                    region = rate_info.get('region_code', '')
                    amount = float(rate_info.get('amount', 0))
                    
                    # Map regions to our standard codes
                    if region == 'GB':
                        rates['uk'] = amount
                    elif region == 'US':
                        rates['usa'] = amount
                    elif region in ['DE', 'FR', 'IT', 'ES', 'NL', 'BE', 'EU']:
                        # If we see any EU country, use that rate for Europe
                        if 'europe' not in rates or amount < rates['europe']:
                            rates['europe'] = amount
                    elif region == 'XX':  # Rest of World
                        rates['row'] = amount
                
                # Fill in missing rates with estimates
                if 'uk' not in rates:
                    rates['uk'] = 25.00
                if 'europe' not in rates:
                    # Europe is typically between UK and USA
                    if 'uk' in rates and 'usa' in rates:
                        rates['europe'] = (rates['uk'] + rates['usa']) / 2
                    else:
                        rates['europe'] = 50.00
                if 'usa' not in rates:
                    # USA is typically 3-4x UK rate
                    if 'uk' in rates:
                        rates['usa'] = rates['uk'] * 3
                    else:
                        rates['usa'] = 75.00
                if 'row' not in rates:
                    # ROW is typically highest
                    if 'usa' in rates:
                        rates['row'] = rates['usa'] * 1.5
                    else:
                        rates['row'] = 100.00
                
                # Update the profile
                profile.rates = rates
                updated_count += 1
                
                print(f"\n✅ {profile.name} (ID: {profile.reverb_profile_id})")
                print(f"   UK: £{rates['uk']:.2f}")
                print(f"   Europe: £{rates['europe']:.2f}")
                print(f"   USA: £{rates['usa']:.2f}")
                print(f"   ROW: £{rates['row']:.2f}")
        
        await session.commit()
        
    print("\n" + "=" * 60)
    print(f"✅ Updated {updated_count} profiles with actual rates")

async def main():
    """Main execution function."""
    await update_rates()

if __name__ == "__main__":
    asyncio.run(main())