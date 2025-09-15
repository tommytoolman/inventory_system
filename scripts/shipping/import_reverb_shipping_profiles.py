#!/usr/bin/env python3
"""
Import Reverb shipping profiles into the database.

This script:
1. Fetches shipping profiles from Reverb API
2. Fetches sample listings to extract rate information
3. Updates the shipping_profiles table with real Reverb data
4. Creates a mapping structure for other platforms

Usage:
    python scripts/shipping/import_reverb_shipping_profiles.py
"""

import asyncio
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent.parent))

from sqlalchemy import select, delete
from app.database import async_session
from app.models.shipping import ShippingProfile
from app.services.reverb.client import ReverbClient
from app.core.config import get_settings

# Mapping of Reverb profile names to eBay profile IDs (to be configured)
REVERB_TO_EBAY_MAPPING = {
    "Electric Guitars": None,  # Will need to be mapped to actual eBay profile ID
    "Acoustic Guitars": None,
    "Bass Guitars": None,
    "Effects Pedals": None,
    "Amp Heads": None,
    "Guitar Cabs": None,
    "Small Spares": None,
    # Add more as needed
}

async def fetch_reverb_profiles():
    """Fetch shipping profiles from Reverb API."""
    settings = get_settings()
    client = ReverbClient(api_key=settings.REVERB_API_KEY)
    
    print("📦 Fetching Reverb shipping profiles...")
    
    # Get shop info which includes shipping profiles
    shop_info = await client.get_shop_info()
    
    if not shop_info or 'shipping_profiles' not in shop_info:
        print("❌ No shipping profiles found")
        return []
    
    profiles = shop_info['shipping_profiles']
    print(f"✅ Found {len(profiles)} shipping profiles")
    
    return profiles

async def fetch_sample_rates(client: ReverbClient, profile_id: str) -> Dict[str, float]:
    """
    Fetch sample listings using this profile to extract rate information.
    
    Returns dict with region codes as keys and rates as values.
    """
    rates = {}
    
    try:
        # Try to get a few listings that use this shipping profile
        # We'll need to check the all_live_listings.json file if it exists
        output_file = Path(__file__).parent.parent / "reverb/output/all_live_listings.json"
        
        if output_file.exists():
            with open(output_file, 'r') as f:
                data = json.load(f)
                
            for listing in data.get('listings', []):
                if (listing.get('shipping', {}).get('profile', {}).get('id') == profile_id or
                    str(listing.get('shipping_profile_id')) == str(profile_id)):
                    
                    shipping_rates = listing.get('shipping', {}).get('rates', [])
                    for rate_info in shipping_rates:
                        region = rate_info.get('region_code', '')
                        amount = rate_info.get('rate', {}).get('amount', 0)
                        
                        if region and amount:
                            # Map regions to our standard codes
                            if region == 'GB':
                                rates['uk'] = float(amount)
                            elif region == 'US':
                                rates['usa'] = float(amount)
                            elif region in ['DE', 'FR', 'IT', 'ES', 'NL', 'BE']:  # EU countries
                                rates['europe'] = float(amount)
                            elif region == 'XX':  # Rest of World
                                rates['row'] = float(amount)
                    
                    # If we found rates, we can stop
                    if rates:
                        break
    except Exception as e:
        print(f"⚠️ Could not extract rates for profile {profile_id}: {e}")
    
    # Default rates if we couldn't extract them
    if not rates:
        rates = {
            'uk': 25.00,
            'europe': 50.00,
            'usa': 75.00,
            'row': 100.00
        }
    
    return rates

async def import_profiles_to_db(profiles: List[Dict]):
    """Import Reverb shipping profiles to database."""
    
    settings = get_settings()
    client = ReverbClient(api_key=settings.REVERB_API_KEY)
    
    async with async_session() as session:
        # First, clear existing dummy data
        print("\n🗑️ Clearing existing dummy shipping profiles...")
        await session.execute(delete(ShippingProfile))
        await session.commit()
        
        print("\n📥 Importing Reverb shipping profiles...")
        
        for profile in profiles:
            reverb_id = profile.get('id')
            name = profile.get('name', '')
            
            print(f"\n  Processing: {name} (ID: {reverb_id})")
            
            # Fetch sample rates for this profile
            rates = await fetch_sample_rates(client, reverb_id)
            
            # Determine package type and dimensions based on profile name
            package_info = get_package_info(name)
            
            # Create new shipping profile
            new_profile = ShippingProfile(
                reverb_profile_id=reverb_id,  # Store Reverb ID
                name=name,
                description=f"Reverb Profile: {name} (ID: {reverb_id})",
                package_type=package_info['package_type'],
                weight=package_info['weight'],
                dimensions=package_info['dimensions'],
                carriers=["dhl", "fedex", "tnt"],  # Default carriers
                options={
                    "fragile": package_info['fragile'],
                    "insurance": True,
                    "require_signature": package_info['require_signature']
                },
                rates=rates,
                ebay_profile_id=REVERB_TO_EBAY_MAPPING.get(name),  # Will be None initially
                is_default=(name == "Electric Guitars")  # Set a default
            )
            
            session.add(new_profile)
            print(f"    ✅ Added with rates: UK £{rates.get('uk', 0):.2f}, "
                  f"EU £{rates.get('europe', 0):.2f}, "
                  f"USA £{rates.get('usa', 0):.2f}, "
                  f"ROW £{rates.get('row', 0):.2f}")
        
        await session.commit()
        print("\n✅ All profiles imported successfully!")

def get_package_info(profile_name: str) -> Dict:
    """
    Determine package information based on profile name.
    
    Returns dict with package_type, weight, dimensions, fragile, and require_signature.
    """
    profile_name_lower = profile_name.lower()
    
    # Default values
    info = {
        'package_type': 'custom',
        'weight': 10.0,
        'dimensions': {'length': 100, 'width': 50, 'height': 30, 'unit': 'cm'},
        'fragile': True,
        'require_signature': True
    }
    
    # Customize based on profile name
    if 'guitar' in profile_name_lower:
        if 'electric' in profile_name_lower:
            info.update({
                'package_type': 'guitar_case',
                'weight': 10.0,
                'dimensions': {'length': 135, 'width': 60, 'height': 20, 'unit': 'cm'}
            })
        elif 'acoustic' in profile_name_lower:
            info.update({
                'package_type': 'guitar_case',
                'weight': 8.0,
                'dimensions': {'length': 135, 'width': 60, 'height': 25, 'unit': 'cm'}
            })
        elif 'bass' in profile_name_lower:
            info.update({
                'package_type': 'guitar_case',
                'weight': 12.0,
                'dimensions': {'length': 145, 'width': 60, 'height': 20, 'unit': 'cm'}
            })
    elif 'amp' in profile_name_lower:
        if 'head' in profile_name_lower:
            info.update({
                'package_type': 'amp_head',
                'weight': 25.0,
                'dimensions': {'length': 70, 'width': 45, 'height': 45, 'unit': 'cm'}
            })
        elif 'cab' in profile_name_lower or 'cabinet' in profile_name_lower:
            info.update({
                'package_type': 'amp_cab',
                'weight': 40.0,
                'dimensions': {'length': 79, 'width': 79, 'height': 45, 'unit': 'cm'}
            })
    elif 'pedal' in profile_name_lower or 'effects' in profile_name_lower:
        info.update({
            'package_type': 'pedal_small',
            'weight': 1.0,
            'dimensions': {'length': 30, 'width': 30, 'height': 15, 'unit': 'cm'},
            'require_signature': False
        })
    elif 'small' in profile_name_lower or 'spare' in profile_name_lower:
        info.update({
            'package_type': 'small_box',
            'weight': 0.5,
            'dimensions': {'length': 30, 'width': 20, 'height': 10, 'unit': 'cm'},
            'fragile': False,
            'require_signature': False
        })
    elif 'synth' in profile_name_lower:
        info.update({
            'package_type': 'synth',
            'weight': 15.0,
            'dimensions': {'length': 100, 'width': 50, 'height': 30, 'unit': 'cm'}
        })
    elif 'panel' in profile_name_lower:
        info.update({
            'package_type': 'custom',
            'weight': 2.0,
            'dimensions': {'length': 68, 'width': 10, 'height': 10, 'unit': 'cm'}
        })
    elif 'case' in profile_name_lower:
        info.update({
            'package_type': 'custom',
            'weight': 15.0,
            'dimensions': {'length': 100, 'width': 60, 'height': 40, 'unit': 'cm'}
        })
    elif 'logo' in profile_name_lower:
        info.update({
            'package_type': 'envelope',
            'weight': 0.1,
            'dimensions': {'length': 20, 'width': 15, 'height': 2, 'unit': 'cm'},
            'fragile': False,
            'require_signature': False
        })
    elif 'kg' in profile_name_lower:
        # Extract weight from name if it contains kg
        try:
            weight = float(profile_name_lower.split('kg')[0].strip())
            info['weight'] = weight
        except:
            pass
    
    return info

async def main():
    """Main execution function."""
    print("=" * 60)
    print("REVERB SHIPPING PROFILES IMPORT")
    print("=" * 60)
    
    # Fetch profiles from Reverb
    profiles = await fetch_reverb_profiles()
    
    if not profiles:
        print("❌ No profiles to import")
        return
    
    # Import to database
    await import_profiles_to_db(profiles)
    
    print("\n" + "=" * 60)
    print("IMPORT COMPLETE")
    print("=" * 60)
    print("\n⚠️ Note: eBay profile mappings need to be configured manually")
    print("   Edit REVERB_TO_EBAY_MAPPING in this script with actual eBay profile IDs")

if __name__ == "__main__":
    asyncio.run(main())