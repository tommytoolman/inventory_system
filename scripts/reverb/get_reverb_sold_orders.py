#!/usr/bin/env python3
"""
Get sold orders from Reverb.

This script fetches sold orders from your Reverb account, with options to:
- Limit the number of pages fetched
- Output as JSON or formatted text
- Save to a JSON file
- Show summary or detailed information

Usage:
    python scripts/reverb/get_reverb_sold_orders.py [--pages N] [--json] [--detailed] [--save]
    
Examples:
    # Get first page of sold orders (50 orders)
    python scripts/reverb/get_reverb_sold_orders.py
    
    # Get first 3 pages (up to 150 orders)
    python scripts/reverb/get_reverb_sold_orders.py --pages 3
    
    # Get all orders as JSON
    python scripts/reverb/get_reverb_sold_orders.py --pages all --json
    
    # Save ALL orders to scripts/reverb/output/all_orders.json
    python scripts/reverb/get_reverb_sold_orders.py --pages all --save
    
    # Get detailed view of first page
    python scripts/reverb/get_reverb_sold_orders.py --detailed
"""

import asyncio
import json
import sys
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent.parent))

from app.services.reverb.client import ReverbClient
from app.core.config import get_settings

async def get_sold_orders(max_pages: Optional[int] = 1, json_output: bool = False, detailed: bool = False, save_to_file: bool = False):
    """
    Fetch and display sold orders from Reverb.
    
    Args:
        max_pages: Number of pages to fetch (None for all)
        json_output: If True, output as JSON
        detailed: If True, show detailed information for each order
    """
    settings = get_settings()
    client = ReverbClient(api_key=settings.REVERB_API_KEY)
    
    # First get the total count
    if not json_output:
        print("📊 Fetching sold orders from Reverb...\n")
    
    try:
        # Get total count with a minimal request
        test_response = await client._make_request("GET", "/my/orders/selling/all", params={"per_page": 1})
        total_orders = test_response.get('total', 0)
    except Exception as e:
        print(f"❌ Error accessing Reverb Orders API: {e}")
        print("\nPossible issues:")
        print("  • Check your REVERB_API_KEY in .env")
        print("  • Ensure the API key has order read permissions")
        print("  • The account may not have seller privileges")
        return []
    total_pages = (total_orders + 49) // 50  # 50 per page
    
    if not json_output:
        print(f"📦 Total sold orders: {total_orders}")
        print(f"📄 Total pages: {total_pages}")
        
        if max_pages:
            pages_to_fetch = min(max_pages, total_pages)
            print(f"🔍 Fetching {pages_to_fetch} page(s) (up to {pages_to_fetch * 50} orders)\n")
        else:
            print(f"🔍 Fetching ALL {total_pages} pages\n")
    
    # Fetch the orders
    orders = await client.get_all_sold_orders(max_pages=max_pages)
    
    # Save to file if requested
    if save_to_file:
        # Create output directory if it doesn't exist
        output_dir = Path(__file__).parent / "output"
        output_dir.mkdir(exist_ok=True)
        
        # Save to all_orders.json
        output_file = output_dir / "all_orders.json"
        output_data = {
            "total_orders": total_orders,
            "fetched_orders": len(orders),
            "fetch_date": datetime.now().isoformat(),
            "orders": orders
        }
        
        with open(output_file, 'w') as f:
            json.dump(output_data, f, indent=2, default=str)
        
        print(f"✅ Saved {len(orders)} orders to {output_file}")
        if not json_output:
            print(f"   File size: {output_file.stat().st_size / 1024:.1f} KB")
        return orders
    
    if json_output:
        # Output as JSON
        output = {
            "total_orders": total_orders,
            "fetched_orders": len(orders),
            "orders": orders
        }
        print(json.dumps(output, indent=2, default=str))
    else:
        # Format and display orders
        print(f"✅ Fetched {len(orders)} orders\n")
        print("-" * 80)
        
        for idx, order in enumerate(orders, 1):
            # Basic order info
            order_number = order.get('order_number', 'N/A')
            status = order.get('status', 'N/A')
            created_at = order.get('created_at', 'N/A')
            buyer_name = order.get('buyer', {}).get('name', 'N/A')
            total = order.get('total', {}).get('display', 'N/A')
            
            # Parse date if available
            if created_at != 'N/A':
                try:
                    dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                    created_at = dt.strftime('%Y-%m-%d %H:%M')
                except:
                    pass
            
            print(f"Order #{idx}: {order_number}")
            print(f"  Status: {status}")
            print(f"  Date: {created_at}")
            print(f"  Buyer: {buyer_name}")
            print(f"  Total: {total}")
            
            # Show listings in the order
            listings = order.get('listings', [])
            if listings:
                print(f"  Items ({len(listings)}):")
                for listing in listings:
                    listing_id = listing.get('id', 'N/A')
                    title = listing.get('title', 'N/A')
                    sku = listing.get('sku', 'N/A')
                    price = listing.get('price', {}).get('display', 'N/A')
                    
                    if detailed:
                        print(f"    • [{listing_id}] {title}")
                        print(f"      SKU: {sku}")
                        print(f"      Price: {price}")
                    else:
                        # Truncate title if too long
                        if len(title) > 50:
                            title = title[:47] + "..."
                        print(f"    • [{listing_id}] {title} (SKU: {sku})")
            
            # Shipping info if detailed
            if detailed:
                shipping_method = order.get('shipping_method', 'N/A')
                tracking = order.get('shipment_tracking_number', 'N/A')
                if shipping_method != 'N/A':
                    print(f"  Shipping: {shipping_method}")
                if tracking != 'N/A':
                    print(f"  Tracking: {tracking}")
            
            print("-" * 80)
            
            # Limit display in non-detailed mode
            if not detailed and idx >= 20:
                remaining = len(orders) - 20
                if remaining > 0:
                    print(f"\n... and {remaining} more orders (use --detailed to see all)")
                break
    
    return orders

if __name__ == "__main__":
    # Parse arguments
    max_pages = 1  # Default to 1 page
    json_output = False
    detailed = False
    save_to_file = False
    
    if "--help" in sys.argv or "-h" in sys.argv:
        print(__doc__)
        sys.exit(0)
    
    # Parse pages argument
    if "--pages" in sys.argv:
        idx = sys.argv.index("--pages")
        if idx + 1 < len(sys.argv):
            pages_arg = sys.argv[idx + 1]
            if pages_arg.lower() == "all":
                max_pages = None
            else:
                try:
                    max_pages = int(pages_arg)
                except ValueError:
                    print(f"Error: Invalid pages value '{pages_arg}'. Use a number or 'all'.")
                    sys.exit(1)
    
    if "--json" in sys.argv:
        json_output = True
    
    if "--detailed" in sys.argv:
        detailed = True
    
    if "--save" in sys.argv:
        save_to_file = True
        # If saving, default to fetching all pages unless otherwise specified
        if "--pages" not in sys.argv:
            max_pages = None
    
    # Run the async function
    asyncio.run(get_sold_orders(max_pages, json_output, detailed, save_to_file))