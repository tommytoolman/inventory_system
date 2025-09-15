#!/usr/bin/env python3
"""
Test all shipping-related API endpoints for Reverb.

This script tests:
1. get_shop_info() - Full shop information
2. get_shipping_profiles() - Just the shipping profiles
3. get_shipping_regions() - Available shipping regions
4. get_shipping_providers() - Available shipping providers

Usage:
    python scripts/reverb/test_shipping_api.py
    
    # Save all responses to JSON files
    python scripts/reverb/test_shipping_api.py --save
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

async def test_all_shipping_endpoints(save_to_file: bool = False):
    """
    Test all shipping-related endpoints and display results.
    
    Args:
        save_to_file: If True, save all responses to JSON files
    """
    settings = get_settings()
    client = ReverbClient(api_key=settings.REVERB_API_KEY)
    
    results = {}
    
    print("🧪 Testing Reverb Shipping API Endpoints\n")
    print("=" * 60)
    
    # 1. Test get_shop_info()
    print("\n1️⃣  Testing get_shop_info()...")
    try:
        shop_info = await client.get_shop_info()
        results['shop_info'] = shop_info
        
        print("✅ SUCCESS: get_shop_info()")
        print(f"   Shop Name: {shop_info.get('name', 'N/A')}")
        print(f"   Shop ID: {shop_info.get('id', 'N/A')}")
        print(f"   Description: {shop_info.get('description', 'N/A')[:100]}...")
        print(f"   Shipping Profiles Count: {len(shop_info.get('shipping_profiles', []))}")
        
        if save_to_file:
            output_dir = Path(__file__).parent / "output"
            output_dir.mkdir(exist_ok=True)
            with open(output_dir / "shop_info.json", 'w') as f:
                json.dump(shop_info, f, indent=2, default=str)
    except Exception as e:
        print(f"❌ FAILED: get_shop_info()")
        print(f"   Error: {e}")
    
    # 2. Test get_shipping_profiles()
    print("\n2️⃣  Testing get_shipping_profiles()...")
    try:
        profiles = await client.get_shipping_profiles()
        results['shipping_profiles'] = profiles
        
        print("✅ SUCCESS: get_shipping_profiles()")
        print(f"   Found {len(profiles)} profiles:")
        for profile in profiles[:5]:  # Show first 5
            print(f"      - [{profile.get('id')}] {profile.get('name')}")
        if len(profiles) > 5:
            print(f"      ... and {len(profiles) - 5} more")
        
        if save_to_file:
            output_dir = Path(__file__).parent / "output"
            with open(output_dir / "shipping_profiles_only.json", 'w') as f:
                json.dump(profiles, f, indent=2, default=str)
    except Exception as e:
        print(f"❌ FAILED: get_shipping_profiles()")
        print(f"   Error: {e}")
    
    # 3. Test get_shipping_regions()
    print("\n3️⃣  Testing get_shipping_regions()...")
    try:
        regions = await client.get_shipping_regions()
        results['shipping_regions'] = regions
        
        # Extract regions list (API might return it in different formats)
        regions_list = regions.get('regions', regions) if isinstance(regions, dict) else regions
        
        print("✅ SUCCESS: get_shipping_regions()")
        if isinstance(regions_list, list):
            print(f"   Found {len(regions_list)} regions:")
            # Show some example regions
            sample_regions = regions_list[:10] if isinstance(regions_list, list) else []
            for region in sample_regions:
                if isinstance(region, dict):
                    print(f"      - {region.get('code', 'N/A')}: {region.get('name', 'N/A')}")
                else:
                    print(f"      - {region}")
            if len(regions_list) > 10:
                print(f"      ... and {len(regions_list) - 10} more")
        else:
            print(f"   Response type: {type(regions)}")
            print(f"   Keys: {regions.keys() if isinstance(regions, dict) else 'N/A'}")
        
        if save_to_file:
            output_dir = Path(__file__).parent / "output"
            with open(output_dir / "shipping_regions.json", 'w') as f:
                json.dump(regions, f, indent=2, default=str)
    except Exception as e:
        print(f"❌ FAILED: get_shipping_regions()")
        print(f"   Error: {e}")
    
    # 4. Test get_shipping_providers()
    print("\n4️⃣  Testing get_shipping_providers()...")
    try:
        providers = await client.get_shipping_providers()
        results['shipping_providers'] = providers
        
        # Extract providers list
        providers_list = providers.get('providers', providers) if isinstance(providers, dict) else providers
        
        print("✅ SUCCESS: get_shipping_providers()")
        if isinstance(providers_list, list):
            print(f"   Found {len(providers_list)} providers:")
            # Show some example providers
            sample_providers = providers_list[:10] if isinstance(providers_list, list) else []
            for provider in sample_providers:
                if isinstance(provider, dict):
                    print(f"      - {provider.get('name', provider.get('id', 'N/A'))}")
                else:
                    print(f"      - {provider}")
            if len(providers_list) > 10:
                print(f"      ... and {len(providers_list) - 10} more")
        else:
            print(f"   Response type: {type(providers)}")
            print(f"   Keys: {providers.keys() if isinstance(providers, dict) else 'N/A'}")
        
        if save_to_file:
            output_dir = Path(__file__).parent / "output"
            with open(output_dir / "shipping_providers.json", 'w') as f:
                json.dump(providers, f, indent=2, default=str)
    except Exception as e:
        print(f"❌ FAILED: get_shipping_providers()")
        print(f"   Error: {e}")
    
    # Summary
    print("\n" + "=" * 60)
    print("📊 SUMMARY:")
    successful = sum(1 for k in ['shop_info', 'shipping_profiles', 'shipping_regions', 'shipping_providers'] if k in results)
    print(f"   ✅ Successful API calls: {successful}/4")
    
    if save_to_file:
        # Save all results to one file
        output_dir = Path(__file__).parent / "output"
        all_results = {
            "test_date": datetime.now().isoformat(),
            "results": results
        }
        with open(output_dir / "all_shipping_api_results.json", 'w') as f:
            json.dump(all_results, f, indent=2, default=str)
        print(f"\n💾 All results saved to {output_dir}/")
        print("   Files created:")
        print("   - shop_info.json")
        print("   - shipping_profiles_only.json")
        print("   - shipping_regions.json")
        print("   - shipping_providers.json")
        print("   - all_shipping_api_results.json")
    
    return results

if __name__ == "__main__":
    save_to_file = "--save" in sys.argv
    
    if "--help" in sys.argv or "-h" in sys.argv:
        print(__doc__)
        sys.exit(0)
    
    asyncio.run(test_all_shipping_endpoints(save_to_file))