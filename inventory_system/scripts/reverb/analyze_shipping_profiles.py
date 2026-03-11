#!/usr/bin/env python3
"""
Analyze Reverb shipping profiles across all live listings.

This script:
1. Fetches all LIVE listings from Reverb
2. Saves them to a JSON file
3. Analyzes shipping profile usage
4. Shows count of listings per shipping profile

Usage:
    # Fetch all live listings and analyze shipping profiles
    python scripts/reverb/analyze_shipping_profiles.py
    
    # With detailed listing info (slower)
    python scripts/reverb/analyze_shipping_profiles.py --detailed
    
    # Save intermediate JSON for inspection
    python scripts/reverb/analyze_shipping_profiles.py --save-json
"""

import asyncio
import json
import sys
from pathlib import Path
from collections import defaultdict
from datetime import datetime
from typing import Dict, List

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent.parent))

from app.services.reverb.client import ReverbClient
from app.core.config import get_settings

async def analyze_shipping_profiles(detailed: bool = False, save_json: bool = True):
    """
    Fetch all live listings and analyze shipping profiles.
    
    Args:
        detailed: If True, fetch full details for each listing
        save_json: If True, save all listings to JSON file
    """
    settings = get_settings()
    client = ReverbClient(api_key=settings.REVERB_API_KEY)
    
    print("📊 Fetching all LIVE listings from Reverb...")
    print("This may take a while depending on the number of listings...\n")
    
    # Fetch all live listings
    if detailed:
        print("Fetching with full details (slower)...")
        listings = await client.get_all_listings_detailed(state="live")
    else:
        print("Fetching basic listing info (faster)...")
        listings = await client.get_all_listings(state="live")
    
    print(f"✅ Fetched {len(listings)} live listings\n")
    
    # Save to JSON if requested
    if save_json:
        output_dir = Path(__file__).parent / "output"
        output_dir.mkdir(exist_ok=True)
        
        output_file = output_dir / "all_live_listings.json"
        output_data = {
            "fetch_date": datetime.now().isoformat(),
            "total_listings": len(listings),
            "state": "live",
            "listings": listings
        }
        
        with open(output_file, 'w') as f:
            json.dump(output_data, f, indent=2, default=str)
        
        print(f"💾 Saved all listings to {output_file}")
        print(f"   File size: {output_file.stat().st_size / 1024 / 1024:.1f} MB\n")
    
    # Analyze shipping profiles
    print("📦 Analyzing Shipping Profiles...")
    print("-" * 60)
    
    profile_counts = defaultdict(lambda: {"count": 0, "name": "Unknown", "listings": []})
    no_profile_count = 0
    no_shipping_count = 0
    
    for listing in listings:
        listing_id = listing.get("id", "unknown")
        sku = listing.get("sku", f"REV-{listing_id}")
        
        # Check for shipping profile
        shipping_profile = listing.get("shipping_profile")
        
        if shipping_profile:
            profile_id = shipping_profile.get("id", "unknown")
            profile_name = shipping_profile.get("name", "Unknown")
            
            profile_counts[profile_id]["name"] = profile_name
            profile_counts[profile_id]["count"] += 1
            profile_counts[profile_id]["listings"].append({
                "id": listing_id,
                "sku": sku,
                "title": listing.get("title", "")[:50]  # First 50 chars
            })
        else:
            # Check if there's shipping data without a profile
            if listing.get("shipping"):
                no_profile_count += 1
            else:
                no_shipping_count += 1
    
    # Sort profiles by count (most used first)
    sorted_profiles = sorted(profile_counts.items(), key=lambda x: x[1]["count"], reverse=True)
    
    # Display results
    print(f"📊 Shipping Profile Analysis Results:")
    print(f"   Total Live Listings: {len(listings)}")
    print(f"   Unique Shipping Profiles: {len(profile_counts)}")
    if no_profile_count > 0:
        print(f"   Listings with shipping but no profile: {no_profile_count}")
    if no_shipping_count > 0:
        print(f"   Listings with no shipping data: {no_shipping_count}")
    print()
    
    print("📦 Shipping Profiles by Usage:")
    print("-" * 60)
    print(f"{'Profile ID':<15} {'Profile Name':<30} {'Count':<10} {'Percentage':<10}")
    print("-" * 60)
    
    for profile_id, data in sorted_profiles:
        percentage = (data["count"] / len(listings)) * 100
        print(f"{profile_id:<15} {data['name'][:29]:<30} {data['count']:<10} {percentage:.1f}%")
    
    if no_profile_count > 0:
        percentage = (no_profile_count / len(listings)) * 100
        print(f"{'NO_PROFILE':<15} {'(Has shipping, no profile)':<30} {no_profile_count:<10} {percentage:.1f}%")
    
    if no_shipping_count > 0:
        percentage = (no_shipping_count / len(listings)) * 100
        print(f"{'NO_SHIPPING':<15} {'(No shipping data at all)':<30} {no_shipping_count:<10} {percentage:.1f}%")
    
    print("-" * 60)
    
    # Save detailed analysis
    if save_json:
        analysis_file = output_dir / "shipping_profile_analysis.json"
        analysis_data = {
            "analysis_date": datetime.now().isoformat(),
            "total_listings": len(listings),
            "unique_profiles": len(profile_counts),
            "no_profile_count": no_profile_count,
            "no_shipping_count": no_shipping_count,
            "profiles": [
                {
                    "profile_id": profile_id,
                    "profile_name": data["name"],
                    "count": data["count"],
                    "percentage": round((data["count"] / len(listings)) * 100, 2),
                    "sample_listings": data["listings"][:5]  # First 5 as examples
                }
                for profile_id, data in sorted_profiles
            ]
        }
        
        with open(analysis_file, 'w') as f:
            json.dump(analysis_data, f, indent=2, default=str)
        
        print(f"\n📊 Saved detailed analysis to {analysis_file}")
    
    # Show top 3 most used profiles with examples
    print("\n🔍 Top 3 Most Used Profiles:")
    for i, (profile_id, data) in enumerate(sorted_profiles[:3], 1):
        print(f"\n{i}. {data['name']} (ID: {profile_id})")
        print(f"   Used by {data['count']} listings ({(data['count']/len(listings)*100):.1f}%)")
        print(f"   Example SKUs:")
        for listing in data["listings"][:3]:
            print(f"      - {listing['sku']}: {listing['title']}")
    
    return listings, profile_counts

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Analyze Reverb shipping profiles")
    parser.add_argument("--detailed", action="store_true", help="Fetch full listing details")
    parser.add_argument("--no-save", action="store_true", help="Don't save JSON files")
    
    args = parser.parse_args()
    
    asyncio.run(analyze_shipping_profiles(
        detailed=args.detailed,
        save_json=not args.no_save
    ))