#!/usr/bin/env python3
"""
Get shipping profiles with detailed rate information from Reverb.

Since the API only returns profile ID and name, this script:
1. Fetches all shipping profiles from the API
2. Uses the saved all_live_listings.json to find example listings for each profile
3. Extracts the shipping rates from those listings
4. Builds a complete picture of each profile's shipping configuration

Usage:
    # Analyze profiles using the saved listings data
    python scripts/reverb/get_shipping_profile_details.py
    
    # Fetch fresh listing data first (slower)
    python scripts/reverb/get_shipping_profile_details.py --fetch-fresh
    
    # Save detailed analysis to JSON
    python scripts/reverb/get_shipping_profile_details.py --save

Prerequisites:
    Requires scripts/reverb/output/all_live_listings.json to exist.
    Run analyze_shipping_profiles.py first if needed.

Example Output:
    Profile: Electric Guitars (ID: 15655)
    Used by 180 listings
    Shipping Rates:
      - GB: £60
      - US: £200
      - EUR_EU: £200
      - XX: £200
"""

import asyncio
import json
import sys
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from typing import Dict, List, Optional

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent.parent))

from app.services.reverb.client import ReverbClient
from app.core.config import get_settings

async def get_profile_details_from_listings(fetch_fresh: bool = False, save_to_file: bool = False):
    """
    Get shipping profile details by analyzing listings.
    
    Args:
        fetch_fresh: If True, fetch new listing data (slower)
        save_to_file: If True, save detailed analysis to JSON
    """
    settings = get_settings()
    client = ReverbClient(api_key=settings.REVERB_API_KEY)
    
    output_dir = Path(__file__).parent / "output"
    output_dir.mkdir(exist_ok=True)
    
    # Get shipping profiles from API
    print("📦 Fetching shipping profiles from API...\n")
    shop_info = await client.get_shop_info()
    profiles = shop_info.get('shipping_profiles', [])
    
    print(f"Found {len(profiles)} shipping profiles\n")
    
    # Get listings data
    listings_file = output_dir / "all_live_listings.json"
    
    if fetch_fresh or not listings_file.exists():
        print("🔄 Fetching fresh listing data (this may take a while)...")
        listings = await client.get_all_listings_detailed(state="live")
        
        # Save for future use
        with open(listings_file, 'w') as f:
            json.dump({
                "fetch_date": datetime.now().isoformat(),
                "total_listings": len(listings),
                "listings": listings
            }, f, indent=2, default=str)
        print(f"✅ Fetched {len(listings)} listings\n")
    else:
        print(f"📂 Loading existing listings from {listings_file}")
        with open(listings_file, 'r') as f:
            data = json.load(f)
            listings = data.get('listings', [])
        print(f"✅ Loaded {len(listings)} listings\n")
    
    # Analyze each profile
    profile_details = {}
    
    for profile in profiles:
        profile_id = str(profile.get('id'))
        profile_name = profile.get('name')
        
        print(f"Analyzing Profile: {profile_name} (ID: {profile_id})")
        print("-" * 60)
        
        # Find listings using this profile
        profile_listings = []
        shipping_rates_samples = []
        
        for listing in listings:
            listing_profile = listing.get('shipping_profile', {})
            if str(listing_profile.get('id')) == profile_id:
                profile_listings.append(listing)
                
                # Get shipping rates if available
                if listing.get('shipping', {}).get('rates'):
                    shipping_rates_samples.append(listing['shipping']['rates'])
        
        print(f"  Found {len(profile_listings)} listings using this profile")
        
        # Analyze shipping rates
        if shipping_rates_samples:
            # Use the first sample as the template (they should all be the same for the same profile)
            sample_rates = shipping_rates_samples[0]
            
            print(f"  Shipping Rates:")
            rate_summary = []
            for rate in sample_rates:
                region = rate.get('region_code', 'Unknown')
                amount = rate.get('rate', {}).get('display', 'N/A')
                print(f"    • {region}: {amount}")
                rate_summary.append({
                    "region_code": region,
                    "amount": rate.get('rate', {}).get('amount'),
                    "display": amount,
                    "currency": rate.get('rate', {}).get('currency', 'GBP')
                })
            
            # Check consistency across samples
            if len(shipping_rates_samples) > 1:
                # Compare first few to ensure consistency
                consistent = True
                for other_rates in shipping_rates_samples[1:min(5, len(shipping_rates_samples))]:
                    if len(other_rates) != len(sample_rates):
                        consistent = False
                        break
                    for i, rate in enumerate(other_rates):
                        if (rate.get('region_code') != sample_rates[i].get('region_code') or
                            rate.get('rate', {}).get('amount') != sample_rates[i].get('rate', {}).get('amount')):
                            consistent = False
                            break
                
                if consistent:
                    print(f"  ✅ Rates are consistent across all {len(shipping_rates_samples)} sampled listings")
                else:
                    print(f"  ⚠️  Rates vary across listings (showing first found)")
        else:
            print(f"  ❌ No shipping rates found in listings")
            rate_summary = []
        
        # Store profile details
        profile_details[profile_id] = {
            "id": profile_id,
            "name": profile_name,
            "listing_count": len(profile_listings),
            "shipping_rates": rate_summary,
            "sample_listings": [
                {
                    "id": l.get('id'),
                    "sku": l.get('sku', f"REV-{l.get('id')}"),
                    "title": l.get('title', '')[:50]
                } for l in profile_listings[:3]  # First 3 examples
            ]
        }
        print()
    
    # Summary
    print("=" * 60)
    print("📊 SUMMARY\n")
    print(f"{'ID':<10} {'Name':<30} {'Listings':<10} {'Regions':<10}")
    print("-" * 60)
    
    for pid, details in profile_details.items():
        num_regions = len(details['shipping_rates'])
        print(f"{pid:<10} {details['name'][:29]:<30} {details['listing_count']:<10} {num_regions:<10}")
    
    # Save detailed analysis if requested
    if save_to_file:
        analysis_file = output_dir / "shipping_profile_details.json"
        output_data = {
            "analysis_date": datetime.now().isoformat(),
            "shop_name": shop_info.get('name'),
            "shop_id": shop_info.get('id'),
            "total_profiles": len(profiles),
            "profiles": profile_details
        }
        
        with open(analysis_file, 'w') as f:
            json.dump(output_data, f, indent=2, default=str)
        
        print(f"\n💾 Saved detailed analysis to {analysis_file}")
    
    return profile_details

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Get shipping profile details from listings")
    parser.add_argument("--fetch-fresh", action="store_true", 
                       help="Fetch fresh listing data instead of using cached")
    parser.add_argument("--save", action="store_true",
                       help="Save detailed analysis to JSON file")
    
    args = parser.parse_args()
    
    asyncio.run(get_profile_details_from_listings(
        fetch_fresh=args.fetch_fresh,
        save_to_file=args.save
    ))