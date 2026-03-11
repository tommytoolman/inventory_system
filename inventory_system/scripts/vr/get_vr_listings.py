#!/usr/bin/env python3
"""
Enhanced V&R listings fetcher with command line arguments
Downloads inventory CSV and filters locally

Usage examples:

    # Live listings only (your most common use case)
    python scripts/vr/get_vr_listings.py --state live

    # All sold listings for analysis
    python scripts/vr/get_vr_listings.py --state sold --analyze

    # Complete inventory (all listings)
    python scripts/vr/get_vr_listings.py --state all --output both

    # Fast mode - first 100 live listings
    python scripts/vr/get_vr_listings.py --fast

    # Analysis without saving
    python scripts/vr/get_vr_listings.py --state all --no-save --analyze

    # First 50 live listings with analysis
    python scripts/vr/get_vr_listings.py --state live --limit 50 --analyze


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

from app.services.vintageandrare.client import VintageAndRareClient

async def get_vr_listings(
    state: str = "live",
    limit: int = None,
    output_format: str = "csv",
    save_to_file: bool = True
):
    """
    Fetch V&R listings with various filtering options
    
    Args:
        state: Listing state ('live', 'sold', 'all')
        limit: Maximum number of listings to return (None for all)
        output_format: Output format ('csv', 'json', 'both')
        save_to_file: Whether to save intermediate inventory file
    """
    username = os.environ.get("VINTAGE_AND_RARE_USERNAME")
    password = os.environ.get("VR_PASSWORD") or os.environ.get("VINTAGE_AND_RARE_PASSWORD")
    
    if not username or not password:
        raise ValueError("V&R credentials required in environment variables")
    
    client = VintageAndRareClient(username=username, password=password)
    
    print(f"🔄 Fetching V&R inventory...")
    start_time = datetime.now()
    
    try:
        # Authenticate first
        if not await client.authenticate():
            raise Exception("Failed to authenticate with V&R")
        
        print("✅ Authenticated with V&R")
        
        # Download inventory CSV as DataFrame
        print("📊 Downloading inventory CSV...")
        df = await client.download_inventory_dataframe(
            save_to_file=save_to_file,
            output_path=None  # Let it create temp file
        )
        
        if df is None or df.empty:
            print("❌ No inventory data received")
            return []
        
        print(f"📦 Downloaded {len(df)} total listings")
        
        # Apply state filtering locally
        if state == "live":
            filtered_df = df[df['product_sold'] == 'no']
        elif state == "sold":
            filtered_df = df[df['product_sold'] == 'yes']
        elif state == "all":
            filtered_df = df  # No filtering
        else:
            raise ValueError(f"Invalid state: {state}. Use 'live', 'sold', or 'all'")
        
        print(f"📋 Filtered to {len(filtered_df)} {state} listings")
        
        # Apply limit if specified
        if limit and len(filtered_df) > limit:
            filtered_df = filtered_df.head(limit)
            print(f"📏 Limited to first {limit} listings")
        
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        print(f"✅ Processing complete in {duration:.1f} seconds")
        
        # Convert back to list of dicts for consistency with Reverb script
        listings = filtered_df.to_dict('records')
        
        return listings
        
    except Exception as e:
        print(f"❌ Error fetching V&R listings: {str(e)}")
        return []
    finally:
        # Cleanup temp files
        client.cleanup_temp_files()

def save_vr_listings(listings, state, output_format):
    """Save V&R listings to file(s)"""
    if not listings:
        print("No listings to save")
        return
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_filename = f"vr_listings_{state}_{timestamp}"
    
    # Create output directory
    output_dir = Path("scripts/vr/output")
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

def analyze_vr_listings(listings, state):
    """Provide basic analysis of V&R listings"""
    if not listings:
        return
    
    df = pd.DataFrame(listings)
    
    print(f"\n📊 **ANALYSIS FOR {state.upper()} V&R LISTINGS**")
    print("=" * 50)
    print(f"Total listings: {len(listings)}")
    
    # Show available columns
    print(f"Available data fields: {len(df.columns)}")
    print(f"Key columns: {', '.join(['brand_name', 'product_model_name', 'product_price', 'category_name', 'product_sold'])}")
    
    # Price analysis
    if 'product_price' in df.columns:
        try:
            # Clean price data (remove empty strings, convert to numeric)
            prices = pd.to_numeric(df['product_price'], errors='coerce').dropna()
            prices = prices[prices > 0]  # Remove zero prices
            
            if len(prices) > 0:
                print(f"\n💰 **PRICE ANALYSIS**")
                print(f"Listings with prices: {len(prices)}")
                print(f"Price range: £{prices.min():.2f} - £{prices.max():.2f}")
                print(f"Average price: £{prices.mean():.2f}")
                print(f"Median price: £{prices.median():.2f}")
        except Exception as e:
            print(f"Could not analyze prices: {e}")
    
    # Brand breakdown
    if 'brand_name' in df.columns:
        try:
            brand_counts = df['brand_name'].value_counts().head(10)
            print(f"\n🏷️  **TOP 10 BRANDS**")
            for brand, count in brand_counts.items():
                print(f"  {brand}: {count}")
        except Exception as e:
            print(f"Could not analyze brands: {e}")
    
    # Category breakdown
    if 'category_name' in df.columns:
        try:
            category_counts = df['category_name'].value_counts().head(10)
            print(f"\n📂 **TOP 10 CATEGORIES**")
            for category, count in category_counts.items():
                print(f"  {category}: {count}")
        except Exception as e:
            print(f"Could not analyze categories: {e}")
    
    # State breakdown for 'all' listings
    if state == "all" and 'product_sold' in df.columns:
        try:
            state_counts = df['product_sold'].value_counts()
            print(f"\n📈 **LISTING STATE BREAKDOWN**")
            for listing_state, count in state_counts.items():
                state_name = "Live" if listing_state == "no" else "Sold" if listing_state == "yes" else listing_state
                print(f"  {state_name}: {count}")
        except Exception as e:
            print(f"Could not analyze states: {e}")

async def main():
    parser = argparse.ArgumentParser(description="Fetch V&R inventory with various options")
    
    # State options (local filtering only)
    parser.add_argument(
        "--state", 
        choices=["live", "sold", "all"],
        default="live",
        help="Listing state to filter (default: live)"
    )
    
    # Performance options
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
    
    parser.add_argument(
        "--keep-temp", 
        action="store_true",
        help="Keep temporary inventory CSV file"
    )
    
    # Performance presets
    parser.add_argument(
        "--fast", 
        action="store_true",
        help="Fast mode: live listings only, first 100"
    )
    
    args = parser.parse_args()
    
    # Handle presets
    if args.fast:
        args.state = "live"
        args.limit = 100
        print("🏃 Fast mode: Live listings, first 100 only")
    
    # Fetch listings
    listings = await get_vr_listings(
        state=args.state,
        limit=args.limit,
        output_format=args.output,
        save_to_file=args.keep_temp
    )
    
    # Save results
    if not args.no_save and listings:
        save_vr_listings(listings, args.state, args.output)
    
    # Analyze if requested
    if args.analyze:
        analyze_vr_listings(listings, args.state)

if __name__ == "__main__":
    asyncio.run(main())