#!/usr/bin/env python3
"""
Get shipping profiles from Reverb API.

This script fetches and displays all shipping profiles configured in your Reverb account.
Shipping profiles are pre-configured shipping rate templates that can be applied to listings.
These must be created through the Reverb website UI and cannot be created via API.

Usage:
    # Display all shipping profiles
    python scripts/reverb/get_shipping_profiles.py
    
    # Save to JSON file at scripts/reverb/output/shipping_profiles.json
    python scripts/reverb/get_shipping_profiles.py --save

Example Output:
    📦 Found 15 Shipping Profiles:
    ------------------------------------------------------------
    ID         Name                                    
    ------------------------------------------------------------
    15655      Electric Guitars                        
    15654      Effects Pedals                          
    15658      Amp Heads                               
    23177      Small Spares                            
    15659      Guitar Cabs                             
    
API Information:
    - Endpoint: GET /api/shop
    - Returns: Shop information including shipping_profiles array
    - Profile Format: {"id": "15655", "name": "Electric Guitars"}
    - Read-only: Profiles can only be viewed, not created/modified via API
    
Related Scripts:
    - test_shipping_api.py: Tests all shipping-related endpoints
    - analyze_shipping_profiles.py: Analyzes profile usage across listings
    
Output Files (when using --save):
    - scripts/reverb/output/shipping_profiles.json: All profiles with metadata
"""

import asyncio
import json
import sys
from pathlib import Path
from datetime import datetime

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent.parent))

from app.services.reverb.client import ReverbClient
from app.core.config import get_settings

async def get_shipping_profiles(save_to_file: bool = False):
    """
    Fetch and display shipping profiles from Reverb.
    
    Args:
        save_to_file: If True, save profiles to JSON file
    """
    settings = get_settings()
    client = ReverbClient(api_key=settings.REVERB_API_KEY)
    
    print("📦 Fetching shipping profiles from Reverb API...\n")
    
    try:
        # Get shop info which includes shipping profiles
        shop_info = await client.get_shop_info()
        
        print(f"🏪 Shop: {shop_info.get('name', 'Unknown')}")
        print(f"   ID: {shop_info.get('id', 'Unknown')}")
        print()
        
        # Get shipping profiles
        profiles = shop_info.get('shipping_profiles', [])
        
        if not profiles:
            print("❌ No shipping profiles found!")
            return
        
        print(f"📦 Found {len(profiles)} Shipping Profiles:")
        print("-" * 60)
        print(f"{'ID':<10} {'Name':<40}")
        print("-" * 60)
        
        for profile in profiles:
            profile_id = profile.get('id', 'Unknown')
            profile_name = profile.get('name', 'Unknown')
            print(f"{profile_id:<10} {profile_name:<40}")
        
        print("-" * 60)
        
        # Save to file if requested
        if save_to_file:
            output_dir = Path(__file__).parent / "output"
            output_dir.mkdir(exist_ok=True)
            
            output_file = output_dir / "shipping_profiles.json"
            output_data = {
                "fetch_date": datetime.now().isoformat(),
                "shop_name": shop_info.get('name'),
                "shop_id": shop_info.get('id'),
                "shipping_profiles": profiles
            }
            
            with open(output_file, 'w') as f:
                json.dump(output_data, f, indent=2)
            
            print(f"\n✅ Saved to {output_file}")
        
        # Compare with our analysis
        print("\n📊 Comparison with listing analysis:")
        print("These are the profiles found in your live listings:")
        expected_profiles = {
            "15655": "Electric Guitars",
            "15654": "Effects Pedals",
            "15658": "Amp Heads",
            "23177": "Small Spares",
            "15659": "Guitar Cabs",
            "107308": "10kg",
            "59948": "New Acoustic",
            "15656": "Acoustic Guitars",
            "106058": "Amp Panels 24",
            "85687": "Amp Panels",
            "105662": "Production Cases",
            "106057": "Amp Logos",
            "15657": "Bass Guitars",
            "103323": "Very Large Items",
            "63784": "Regular Synth"
        }
        
        api_profile_ids = {str(p.get('id')) for p in profiles}
        expected_ids = set(expected_profiles.keys())
        
        missing_from_api = expected_ids - api_profile_ids
        extra_in_api = api_profile_ids - expected_ids
        
        if missing_from_api:
            print(f"\n⚠️  Profiles used in listings but not in API response:")
            for pid in missing_from_api:
                print(f"   - {pid}: {expected_profiles[pid]}")
        
        if extra_in_api:
            print(f"\n➕ Profiles in API but not used in current listings:")
            for pid in extra_in_api:
                profile = next((p for p in profiles if str(p.get('id')) == pid), None)
                if profile:
                    print(f"   - {pid}: {profile.get('name')}")
        
        if not missing_from_api and not extra_in_api:
            print("✅ All profiles match between API and listings!")
        
    except Exception as e:
        print(f"❌ Error fetching shipping profiles: {e}")
        return None

if __name__ == "__main__":
    save_to_file = "--save" in sys.argv
    
    asyncio.run(get_shipping_profiles(save_to_file))