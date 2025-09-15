#!/usr/bin/env python3
"""
Get detailed information for a single Reverb listing.

Usage:
    python scripts/reverb/get_reverb_item_details.py <reverb_listing_id> [--json] [--check-orders] [--save]
    
Examples:
    # Get details with formatted output
    python scripts/reverb/get_reverb_item_details.py 91978727
    
    # Get details as pretty-printed JSON
    python scripts/reverb/get_reverb_item_details.py 91978727 --json
    
    # Save details to JSON file with SKU (e.g., REV-91978727.json)
    python scripts/reverb/get_reverb_item_details.py 91978727 --save
    
    # Save listing details to scripts/reverb/output/{SKU}.json
    # This will extract shipping profile, rates, and other details
    python scripts/reverb/get_reverb_item_details.py 91978727 --save
    
Options:
    --json          Output as pretty-printed JSON to console
    --check-orders  Also check Orders API (slow if many orders)
    --save          Save to JSON file in scripts/reverb/output/ with SKU in filename
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

async def test_listing_status(listing_id: str, json_output: bool = False, check_orders: bool = False, save_to_file: bool = False):
    """
    Checks a single Reverb Listing ID against the Listings API and optionally the Orders API.
    
    Args:
        listing_id: The Reverb listing ID to check
        json_output: If True, output as JSON instead of formatted text
        check_orders: If True, also check the Orders API (slow if many orders)
    """
    settings = get_settings()
    client = ReverbClient(api_key=settings.REVERB_API_KEY)
    
    result = {
        "listing_id": listing_id,
        "listings_api": None,
        "orders_api": None
    }

    if not json_output:
        print(f"🔬 Testing Reverb Listing ID: {listing_id}\n")

    # 1. Test the Public Listings API
    if not json_output:
        print("--- Checking Listings API ---")
    try:
        details = await client.get_listing_details(listing_id)
        result["listings_api"] = details
        if not json_output:
            print(f"✅ SUCCESS: Found in Listings API.")
            print(f"   - Status: {details.get('state', {}).get('slug')}")
            print(f"   - Title: {details.get('title')}")
            # Show key fields
            if details.get('shipping_profile'):
                print(f"   - Shipping Profile ID: {details.get('shipping_profile', {}).get('id')}")
            if details.get('slug'):
                print(f"   - Slug: {details.get('slug')}")
    except Exception as e:
        result["listings_api_error"] = str(e)
        if not json_output:
            print(f"❌ FAILED: Could not find in Listings API.")
            print(f"   - Error: {e}")

    # 2. Test the Orders API (our proposed fallback) - only if requested
    if check_orders:
        if not json_output:
            print("\n--- Checking Orders API (this may take a while) ---")
        try:
            # First, get a quick count of total orders
            test_response = await client._make_request("GET", "/my/orders/selling/all", params={"per_page": 1})
            total_orders = test_response.get('total', 0)
            if not json_output:
                print(f"   📊 Total sold orders in account: {total_orders}")
                print(f"   🔍 Checking first 5 pages (up to 250 orders)...")
            
            all_sold_orders = await client.get_all_sold_orders(max_pages=5)  # Limit to 5 pages for speed
            found_in_orders = False
            for order in all_sold_orders:
                for listing in order.get('listings', []):
                    if str(listing.get('id', '')) == listing_id:
                        result["orders_api"] = order
                        found_in_orders = True
                        if not json_output:
                            print(f"✅ SUCCESS: Found in Orders API.")
                            print(f"   - Order Number: {order.get('order_number')}")
                            print(f"   - Order Status: {order.get('status')}")
                        break
                if found_in_orders:
                    break
            
            if not found_in_orders:
                result["orders_api_status"] = "not_found"
                if not json_output:
                    print("❌ FAILED: Could not find in any sold orders (checked first 5 pages).")

        except Exception as e:
            result["orders_api_error"] = str(e)
            if not json_output:
                print(f"❌ FAILED: Could not check Orders API.")
                print(f"   - Error: {e}")
    else:
        if not json_output:
            print("\n--- Skipping Orders API check (use --check-orders to enable) ---")
    
    # Save to file if requested
    if save_to_file:
        # Create output directory if it doesn't exist
        output_dir = Path(__file__).parent / "output"
        output_dir.mkdir(exist_ok=True)
        
        # Get SKU from the listing details
        sku = "UNK"
        if result.get("listings_api"):
            sku = result["listings_api"].get("sku", "UNK")
            if not sku:
                sku = "UNK"
        
        # Save with SKU-based filename (e.g., REV-91978727.json)
        filename = f"REV-{listing_id}.json" if sku == "UNK" else f"{sku}.json"
        output_file = output_dir / filename
        
        # Add metadata
        result["fetch_metadata"] = {
            "listing_id": listing_id,
            "fetch_date": json.dumps(datetime.now(), default=str).strip('"'),
            "sku": sku
        }
        
        with open(output_file, 'w') as f:
            json.dump(result, f, indent=2, default=str)
        
        print(f"✅ Saved listing details to {output_file}")
        
        # Show shipping info if found
        if result.get("listings_api") and result["listings_api"].get("shipping"):
            shipping = result["listings_api"]["shipping"]
            print("\n📦 Shipping data found in listing:")
            if shipping.get("rates"):
                print(f"   - {len(shipping['rates'])} shipping rates defined")
            if result["listings_api"].get("shipping_profile"):
                profile = result["listings_api"]["shipping_profile"]
                print(f"   - Profile ID: {profile.get('id')}")
                print(f"   - Profile Name: {profile.get('name')}")
    
    # Output JSON if requested
    if json_output and not save_to_file:
        print(json.dumps(result, indent=2, default=str))
    
    return result

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/reverb/get_reverb_item_details.py <reverb_listing_id> [--json] [--check-orders] [--save]")
        print("\nExamples:")
        print("  python scripts/reverb/get_reverb_item_details.py 91978727")
        print("  python scripts/reverb/get_reverb_item_details.py 91978727 --json")
        print("  python scripts/reverb/get_reverb_item_details.py 91978727 --save")
        print("  python scripts/reverb/get_reverb_item_details.py 91978727 --json --check-orders")
        print("\nOptions:")
        print("  --json          Output as pretty-printed JSON")
        print("  --check-orders  Also check Orders API (slow if many orders)")
        print("  --save          Save to JSON file with SKU in filename")
        sys.exit(1)
    
    item_id_to_test = sys.argv[1]
    json_output = "--json" in sys.argv
    check_orders = "--check-orders" in sys.argv
    save_to_file = "--save" in sys.argv
    
    asyncio.run(test_listing_status(item_id_to_test, json_output, check_orders, save_to_file))
    
