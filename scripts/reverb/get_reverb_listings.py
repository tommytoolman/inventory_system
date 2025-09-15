
# TO DO: not lightweight enough, refactor using rever_service._get_all_listings_from_api()

"""
Enhanced Reverb listings fetcher with command line arguments:

# Fast: Only live listings, basic data
python scripts/reverb/get_reverb_listings.py --fast

# Your current use case: Live listings only
python scripts/reverb/get_reverb_listings.py --state live
    - recommended for SPEED
    - Uses get_all_listings(state="live")
    - Filters server-side, not locally
    - Much faster than downloading all + filtering

# Complete data for all listings (slow but comprehensive)
python scripts/reverb/get_reverb_listings.py --complete

# Sold listings with analysis
python scripts/reverb/get_reverb_listings.py --state sold --analyze

# First 100 live listings with full details
python scripts/reverb/get_reverb_listings.py --state live --detailed --limit 100

# All states, save as both CSV and JSON
python scripts/reverb/get_reverb_listings.py --state all --output both

# Quick analysis without saving
python scripts/reverb/get_reverb_listings.py --state live --no-save --analyze


---------------------------------------------------

Performance Recommendations

    For Speed (Your Original Use Case):
    - Uses get_all_listings(state="live")
    - Filters server-side, not locally
    - Much faster than downloading all + filtering

    For Complete Data:
    - python scripts/reverb/get_reverb_listings.py --state live --detailed
    - Uses get_all_listings_detailed()
    - Gets full listing details
    - Slower but comprehensive

    For Analysis:
    - python scripts/reverb/get_reverb_listings.py --state all --analyze
    - Gets all states for comparison
    - Shows breakdown and statistics

This approach is much more efficient than old method because it:

    - Filters server-side instead of downloading everything
    - Provides options for different data completeness levels
    - Includes performance controls (concurrency limits, row limits)
    - Saves time by not fetching unneeded data

"""

import pandas as pd
import asyncio
import argparse
import os
import sys
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
load_dotenv()

from app.services.reverb.client import ReverbClient

async def get_reverb_listings(
    state: str = "live",
    detailed: bool = False,
    max_concurrent: int = 10,
    limit: int = None,
    output_format: str = "csv"
):
    """
    Fetch Reverb listings with various options
    
    Args:
        state: Listing state ('live', 'sold', 'draft', 'ended', 'all')
        detailed: Whether to fetch full details for each listing
        max_concurrent: Max concurrent requests for detailed mode
        limit: Maximum number of listings to fetch (None for all)
        output_format: Output format ('csv', 'json', 'both')
    """
    api_key = os.environ.get("REVERB_API_KEY")
    if not api_key:
        raise ValueError("REVERB_API_KEY environment variable required")
    
    client = ReverbClient(api_key)
    
    print(f"🔄 Fetching {state} listings from Reverb...")
    start_time = datetime.now()
    
    try:
        if state == "sold":
            print("📦 Using get_all_sold_orders for sold listings")
            listings = await client.get_all_sold_orders()
        elif detailed:
            print(f"📊 Using detailed mode (max {max_concurrent} concurrent requests)")
            listings = await client.get_all_listings_detailed(
                max_concurrent=max_concurrent, 
                state=state
            )
        else:
            print("⚡ Using basic mode (faster)")
            listings = await client.get_all_listings(state=state)
        
        # Debugging: Log the number of listings retrieved
        print(f"DEBUG: Retrieved {len(listings)} listings for state '{state}'")
        
        # Apply limit if specified
        if limit and len(listings) > limit:
            listings = listings[:limit]
            print(f"📏 Limited to first {limit} listings")
        
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        print(f"✅ Found {len(listings)} {state} listings in {duration:.1f} seconds")
        
        return listings
        
    except Exception as e:
        print(f"❌ Error fetching listings: {str(e)}")
        return []

def save_listings(listings, state, output_format, detailed):
    """Save listings to file(s)"""
    if not listings:
        print("No listings to save")
        return
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    detail_suffix = "_detailed" if detailed else ""
    base_filename = f"reverb_listings_{state}{detail_suffix}_{timestamp}"
    
    # Create output directory
    output_dir = Path("scripts/reverb/output")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    if output_format in ["csv", "both"]:
        csv_file = output_dir / f"{base_filename}.csv"
        df = pd.DataFrame(listings)
        df.to_csv(csv_file, index=False)
        print(f"💾 Saved CSV: {csv_file}")
    
    if output_format in ["json", "both"]:
        import json
        json_file = output_dir / f"{base_filename}.json"
        with open(json_file, 'w') as f:
            json.dump(listings, f, indent=2, default=str)
        print(f"💾 Saved JSON: {json_file}")

def analyze_listings(listings, state):
    """Provide basic analysis of the listings"""
    if not listings:
        return
    
    df = pd.DataFrame(listings)
    
    print(f"\n📊 **ANALYSIS FOR {state.upper()} LISTINGS**")
    print("=" * 50)
    print(f"Total listings: {len(listings)}")
    
    # Show available columns
    print(f"Available data fields: {len(df.columns)}")
    if len(df.columns) < 50:  # Don't spam if too many columns
        print(f"Columns: {', '.join(df.columns[:10])}{'...' if len(df.columns) > 10 else ''}")
    
    # Basic stats if we have price data
    if 'price' in df.columns:
        try:
            prices = pd.to_numeric(df['price'], errors='coerce').dropna()
            if len(prices) > 0:
                print(f"Price range: £{prices.min():.2f} - £{prices.max():.2f}")
                print(f"Average price: £{prices.mean():.2f}")
        except:
            pass
    
    # State breakdown for 'all' listings
    if state == "all" and 'state' in df.columns:
        try:
            if isinstance(df['state'].iloc[0], dict):
                state_counts = df['state'].apply(lambda x: x.get('slug', 'unknown') if isinstance(x, dict) else str(x)).value_counts()
            else:
                state_counts = df['state'].value_counts()
            print(f"\nState breakdown:")
            for state_name, count in state_counts.items():
                print(f"  {state_name}: {count}")
        except:
            pass

async def main():
    parser = argparse.ArgumentParser(description="Fetch Reverb listings with various options")
    
    # State options
    parser.add_argument(
        "--state", 
        choices=["live", "sold", "draft", "ended", "suspended", "all"],
        default="live",
        help="Listing state to fetch (default: live)"
    )
    
    # Detail level
    parser.add_argument(
        "--detailed", 
        action="store_true",
        help="Fetch full details for each listing (slower but more complete)"
    )
    
    # Performance options
    parser.add_argument(
        "--max-concurrent", 
        type=int, 
        default=10,
        help="Max concurrent requests for detailed mode (default: 10)"
    )
    
    parser.add_argument(
        "--limit", 
        type=int,
        help="Maximum number of listings to fetch (default: all)"
    )
    
    # Output options
    parser.add_argument(
        "--output", 
        choices=["csv", "json", "both"],
        default="csv",
        help="Output format (default: csv)"
    )
    
    parser.add_argument(
        "--no-save", 
        action="store_true",
        help="Don't save to file, just analyze"
    )
    
    parser.add_argument(
        "--analyze", 
        action="store_true",
        help="Show analysis of the fetched listings"
    )
    
    # Performance presets
    parser.add_argument(
        "--fast", 
        action="store_true",
        help="Fast mode: basic data, live listings only"
    )
    
    parser.add_argument(
        "--complete", 
        action="store_true",
        help="Complete mode: detailed data, all states"
    )
    
    args = parser.parse_args()
    
    # Handle presets
    if args.fast:
        args.state = "live"
        args.detailed = False
        print("🏃 Fast mode: Live listings, basic data")
    
    if args.complete:
        args.state = "all" 
        args.detailed = True
        args.max_concurrent = 15
        print("🎯 Complete mode: All listings, detailed data")
    
    # Fetch listings
    listings = await get_reverb_listings(
        state=args.state,
        detailed=args.detailed,
        max_concurrent=args.max_concurrent,
        limit=args.limit,
        output_format=args.output
    )
    
    # Save results
    if not args.no_save and listings:
        save_listings(listings, args.state, args.output, args.detailed)
    
    # Analyze if requested
    if args.analyze:
        analyze_listings(listings, args.state)

if __name__ == "__main__":
    asyncio.run(main())