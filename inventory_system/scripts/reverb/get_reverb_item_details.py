#!/usr/bin/env python3
"""
Get detailed information for a single Reverb listing or look up an existing listing by SKU.

Usage:
    python scripts/reverb/get_reverb_item_details.py [reverb_listing_id] [--sku SKU] [--json] [--check-orders] [--save]
    
Examples:
    # Get details with formatted output
    python scripts/reverb/get_reverb_item_details.py 91978727
    
    # Look up a listing by SKU to test the /my/listings?sku= endpoint
    python scripts/reverb/get_reverb_item_details.py --sku RIFF-10000123
    
    # Get details as pretty-printed JSON
    python scripts/reverb/get_reverb_item_details.py 91978727 --json
    
    # Save details to JSON file with SKU (e.g., REV-91978727.json)
    python scripts/reverb/get_reverb_item_details.py 91978727 --save
    
Options:
    --sku SKU       Query Reverb's /my/listings endpoint using a SKU instead of a listing ID
    --json          Output as pretty-printed JSON to console
    --check-orders  Also check Orders API (slow if many orders)
    --save          Save to JSON file in scripts/reverb/output/ with SKU in filename
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent.parent))

from app.services.reverb.client import ReverbClient
from app.core.config import get_settings

async def test_listing_status(
    listing_id: Optional[str],
    *,
    sku: Optional[str] = None,
    json_output: bool = False,
    check_orders: bool = False,
    save_to_file: bool = False,
):
    """
    Checks a single Reverb Listing ID against the Listings API and optionally the Orders API.
    Can also query the private /my/listings endpoint by SKU to verify uniqueness.
    
    Args:
        listing_id: The Reverb listing ID to check (optional if sku is provided)
        sku: Optional SKU to look up via /my/listings?sku=<value>
        json_output: If True, output as JSON instead of formatted text
        check_orders: If True, also check the Orders API (slow if many orders)
    """
    settings = get_settings()
    client = ReverbClient(api_key=settings.REVERB_API_KEY)
    
    result = {
        "listing_id": listing_id,
        "listings_api": None,
        "orders_api": None,
        "sku_lookup": None,
    }

    if not json_output:
        header = "🔬 Testing Reverb Listing"
        if listing_id:
            header += f" ID: {listing_id}"
        if sku:
            header += f" (SKU lookup: {sku})"
        print(f"{header}\n")

    # 0. Optional SKU lookup via private endpoint
    if sku:
        if not json_output:
            print("--- Checking /my/listings by SKU ---")
        try:
            sku_response = await client.find_listing_by_sku(sku)
            result["sku_lookup"] = sku_response
            listings = []
            if isinstance(sku_response, dict):
                if sku_response.get("listings"):
                    listings = sku_response["listings"]
                elif sku_response.get("_embedded", {}).get("listings"):
                    listings = sku_response["_embedded"]["listings"]
            if not json_output:
                if listings:
                    print(f"✅ SUCCESS: Found {len(listings)} listing(s) for SKU {sku}")
                    for entry in listings[:3]:
                        entry_id = entry.get("id") or entry.get("listing_id")
                        entry_state = entry.get("state", {}).get("slug") if isinstance(entry.get("state"), dict) else entry.get("state")
                        print(f"   - Listing ID: {entry_id}, State: {entry_state}, Title: {entry.get('title')}")
                else:
                    total = sku_response.get("total")
                    if total == 0:
                        print(f"ℹ️  No listings found for SKU {sku}")
                    else:
                        print(f"ℹ️  Received response but no listings parsed. Raw keys: {list(sku_response.keys())}")
        except Exception as sku_error:
            result["sku_lookup_error"] = str(sku_error)
            if not json_output:
                print(f"❌ FAILED: SKU lookup errored - {sku_error}")
        if not json_output:
            print()

    # 1. Test the Public Listings API
    if listing_id and not json_output:
        print("--- Checking Listings API ---")
    if listing_id:
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
    parser = argparse.ArgumentParser(
        description="Inspect a Reverb listing by ID or SKU."
    )
    parser.add_argument(
        "listing_id",
        nargs="?",
        help="Reverb listing ID to inspect",
    )
    parser.add_argument(
        "--sku",
        help="SKU to look up via /my/listings?sku=<value>",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as pretty-printed JSON",
    )
    parser.add_argument(
        "--check-orders",
        action="store_true",
        help="Also check Orders API (slower)",
    )
    parser.add_argument(
        "--save",
        action="store_true",
        help="Save Listings API response to scripts/reverb/output/{SKU}.json",
    )

    args = parser.parse_args()

    if not args.listing_id and not args.sku:
        parser.error("You must supply a listing_id positional argument or --sku.")
    
    asyncio.run(
        test_listing_status(
            args.listing_id,
            sku=args.sku,
            json_output=args.json,
            check_orders=args.check_orders,
            save_to_file=args.save,
        )
    )
    
