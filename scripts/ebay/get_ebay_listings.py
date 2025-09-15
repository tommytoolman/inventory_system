#!/usr/bin/env python3
"""
Enhanced eBay listings fetcher with command line arguments
Uses eBay Trading API to fetch current inventory

Usage Examples:

    # Active listings only (most common)
    python scripts/ebay/get_ebay_listings.py --state active

    # Test in sandbox
    python scripts/ebay/get_ebay_listings.py --state active --sandbox

    # All sold listings for analysis
    python scripts/ebay/get_ebay_listings.py --state sold --analyze

    # Complete inventory (all states)
    python scripts/ebay/get_ebay_listings.py --state all --output both

    # Fast mode - first 100 active listings
    python scripts/ebay/get_ebay_listings.py --fast

    # Detailed data for all listings (slower)
    python scripts/ebay/get_ebay_listings.py --state all --detailed

    # Analysis without saving
    python scripts/ebay/get_ebay_listings.py --state all --no-save --analyze

"""

import pandas as pd
import asyncio
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Dict
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
load_dotenv()

from app.services.ebay.trading import EbayTradingLegacyAPI

async def get_ebay_listings(
    state: str = "active",
    detailed: bool = False,
    limit: int = None,
    output_format: str = "csv",
    sandbox: bool = False,
    use_inventory_api: bool = False,
    enrich_with_details: bool = False  # 
):
    """
    Fetch eBay listings with various options
    
    Args:
        state: Listing state ('active', 'sold', 'unsold', 'all')
        detailed: Whether to fetch full details for each listing
        limit: Maximum number of listings to fetch (None for all)
        output_format: Output format ('csv', 'json', 'both')
        sandbox: Whether to use sandbox environment
        use_inventory_api: Use Inventory API instead of Trading API
    """
    
    api = EbayTradingLegacyAPI(sandbox=sandbox)
    
    print(f"🔄 Fetching {state} eBay listings...")
    if sandbox:
        print("🧪 Using SANDBOX environment")
    if enrich_with_details:
        print("🔍 Will enrich with detailed item information (slower but much more complete)")
    
    start_time = datetime.now()
    all_listings = []  # Initialize shared variable
    
    try:
        if use_inventory_api:
            print("🔄 Using REST Inventory API...")
            # Inventory API specific logic
            inventory_response = await api.get_inventory_items(limit=limit or 100, offset=0)
            print(f"📦 Inventory API response structure: {list(inventory_response.keys())}")
            
            # 🆕 NEW: Enrich with detailed item information
            if enrich_with_details and all_listings:
                print(f"🔍 Enriching {len(all_listings)} listings with detailed information...")
                all_listings = await enrich_listings_with_details(api, all_listings)
        
            
            if 'inventoryItems' in inventory_response:
                all_listings = inventory_response['inventoryItems']
                for listing in all_listings:
                    listing["listing_state"] = "inventory"  # Mark as inventory API
                print(f"📦 Found {len(all_listings)} inventory items")
            else:
                print("❌ No 'inventoryItems' key found in response")
                all_listings = []
        
        else:
            print("🔄 Using XML Trading API...")
            
            # Map state options to eBay API parameters
            include_active = state in ["active", "all"]
            include_sold = state in ["sold", "all"] 
            include_unsold = state in ["unsold", "all"]
            
            print(f"📊 Fetching: Active={include_active}, Sold={include_sold}, Unsold={include_unsold}")
            
            # Get listings using Trading API
            listings_response = await api.get_all_selling_listings(
                include_active=include_active,
                include_sold=include_sold, 
                include_unsold=include_unsold,
                include_details=detailed
            )
            
            # Extract and combine listings from response structure
            if include_active and "active" in listings_response:
                active_listings = listings_response["active"]
                for listing in active_listings:
                    listing["listing_state"] = "active"
                    all_listings.append(listing)
                print(f"📦 Found {len(active_listings)} active listings")
            
            if include_sold and "sold" in listings_response:
                sold_listings = listings_response["sold"]
                for listing in sold_listings:
                    listing["listing_state"] = "sold"
                    all_listings.append(listing)
                print(f"💰 Found {len(sold_listings)} sold listings")
            
            if include_unsold and "unsold" in listings_response:
                unsold_listings = listings_response["unsold"]
                for listing in unsold_listings:
                    listing["listing_state"] = "unsold"
                    all_listings.append(listing)
                print(f"📋 Found {len(unsold_listings)} unsold listings")
        
        # ✅ SHARED LOGIC (applies to both API paths)
        
        # Apply limit if specified
        if limit and len(all_listings) > limit:
            all_listings = all_listings[:limit]
            print(f"📏 Limited to first {limit} listings")
            
        # 🆕 NEW: Enrich with detailed item information (MOVED TO CORRECT LOCATION)
        if enrich_with_details and all_listings:
            print(f"🔍 Enriching {len(all_listings)} listings with detailed information...")
            all_listings = await enrich_listings_with_details(api, all_listings)
        
        # Calculate timing
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        print(f"✅ Found {len(all_listings)} total listings in {duration:.1f} seconds")
        
        return all_listings
        
    except Exception as e:
        print(f"❌ Error fetching eBay listings: {str(e)}")
        return []

async def enrich_listings_with_details(api: EbayTradingLegacyAPI, listings: List[Dict]) -> List[Dict]:
    """
    Enrich basic listings with detailed item information
    """
    enriched_listings = []
    total_listings = len(listings)
    
    # Process in batches to avoid overwhelming the API
    batch_size = 10  # Adjust based on rate limits
    
    for i in range(0, total_listings, batch_size):
        batch = listings[i:i+batch_size]
        print(f"🔍 Processing batch {i//batch_size + 1}/{(total_listings + batch_size - 1)//batch_size} ({len(batch)} items)")
        
        # Create tasks for concurrent processing
        tasks = []
        for listing in batch:
            item_id = listing.get('ItemID')
            if item_id:
                task = enrich_single_listing(api, listing, item_id)
                tasks.append(task)
        
        # Wait for all tasks in batch to complete
        batch_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Process results
        for result in batch_results:
            if isinstance(result, Exception):
                print(f"❌ Error enriching listing: {str(result)}")
                continue
            if result:
                enriched_listings.append(result)
        
        # Small delay between batches
        if i + batch_size < total_listings:
            await asyncio.sleep(0.5)
    
    print(f"✅ Successfully enriched {len(enriched_listings)}/{total_listings} listings")
    return enriched_listings

async def enrich_single_listing(api: EbayTradingLegacyAPI, base_listing: Dict, item_id: str) -> Dict:
    """
    Enrich a single listing with detailed information
    """
    try:
        # Get detailed item information
        item_details = await api.get_item_details(item_id)
        
        if not item_details:
            return base_listing
        
        # Start with base listing
        enriched = base_listing.copy()
        
        # Extract item specifics
        item_specifics = extract_item_specifics(item_details)
        
        # Add detailed fields
        enriched.update({
            # Item specifics (brand, model, type, etc.)
            'item_specifics_raw': item_specifics,
            'brand': extract_specific_field(item_specifics, ['Brand', 'Make', 'Manufacturer']),
            'model': extract_specific_field(item_specifics, ['Model', 'Model Name', 'Series']),
            'type': extract_specific_field(item_specifics, ['Type', 'Product Type', 'Item Type', 'Style']),
            'year': extract_specific_field(item_specifics, ['Year', 'Year Made', 'Year Manufactured', 'Vintage']),
            'color': extract_specific_field(item_specifics, ['Color', 'Colour', 'Primary Color', 'Main Color']),
            'size': extract_specific_field(item_specifics, ['Size', 'Dimensions', 'Length', 'Width', 'Height']),
            'material': extract_specific_field(item_specifics, ['Material', 'Materials', 'Body Material']),
            'condition_description': extract_specific_field(item_specifics, ['Condition Description', 'Item Condition']),
            
            # Categories
            'primary_category_id': item_details.get('PrimaryCategory', {}).get('CategoryID'),
            'primary_category_name': item_details.get('PrimaryCategory', {}).get('CategoryName'),
            'secondary_category_id': item_details.get('SecondaryCategory', {}).get('CategoryID'),
            'secondary_category_name': item_details.get('SecondaryCategory', {}).get('CategoryName'),
            
            # Condition
            'condition_id': item_details.get('ConditionID'),
            'condition_display_name': item_details.get('ConditionDisplayName'),
            
            # Description and features
            'description': item_details.get('Description', ''),
            'subtitle': item_details.get('SubTitle', ''),
            
            # Pictures
            'picture_urls': extract_picture_urls(item_details),
            'picture_count': len(extract_picture_urls(item_details)),
            'first_picture_url': extract_picture_urls(item_details)[0] if extract_picture_urls(item_details) else '',
            
            # Shipping and handling
            'dispatch_time_max': item_details.get('DispatchTimeMax'),
            'handling_time': item_details.get('HandlingTime'),
            'shipping_cost': extract_shipping_cost(item_details),
            'free_shipping': extract_free_shipping(item_details),
            
            # Location
            'location': item_details.get('Location'),
            'country': item_details.get('Country'),
            'postal_code': item_details.get('PostalCode'),
            
            # Listing format
            'listing_type': item_details.get('ListingType'),
            'listing_duration': item_details.get('ListingDuration'),
            'buy_it_now_price': extract_buy_it_now_price(item_details),
            
            # Seller info
            'seller_user_id': item_details.get('Seller', {}).get('UserID'),
            'seller_feedback_score': item_details.get('Seller', {}).get('FeedbackScore'),
            'seller_positive_feedback_percent': item_details.get('Seller', {}).get('PositiveFeedbackPercent'),
            'seller_store_name': item_details.get('Seller', {}).get('StoreName'),
            
            # Timestamps
            'start_time': item_details.get('StartTime'),
            'end_time': item_details.get('EndTime'),
            'listing_updated': item_details.get('ReviseDate'),
            
            # Metrics
            'view_count': item_details.get('ViewItemCount'),
            'watch_count': item_details.get('WatchCount'),
            'question_count': item_details.get('QuestionCount'),
            
            # Payment and returns
            'payment_methods': ', '.join(item_details.get('PaymentMethods', [])) if isinstance(item_details.get('PaymentMethods', []), list) else item_details.get('PaymentMethods', ''),
            'returns_accepted': item_details.get('ReturnPolicy', {}).get('ReturnsAcceptedOption'),
            'returns_within': item_details.get('ReturnPolicy', {}).get('ReturnsWithinOption'),
        })
        
        # Flatten all item specifics as individual columns (prefixed)
        for spec_name, spec_value in item_specifics.items():
            safe_name = spec_name.lower().replace(' ', '_').replace('/', '_').replace('-', '_')
            enriched[f'spec_{safe_name}'] = spec_value
        
        return enriched
        
    except Exception as e:
        print(f"❌ Error enriching item {item_id}: {str(e)}")
        return base_listing

# Helper functions for extracting specific data
def extract_item_specifics(item_details: Dict) -> Dict:
    """Extract item specifics as a flat dictionary"""
    specifics = {}
    
    item_specifics = item_details.get('ItemSpecifics', {})
    if 'NameValueList' in item_specifics:
        name_value_lists = item_specifics['NameValueList']
        if not isinstance(name_value_lists, list):
            name_value_lists = [name_value_lists]
        
        for nvl in name_value_lists:
            name = nvl.get('Name', '')
            value = nvl.get('Value', '')
            if name and value:
                # Handle multiple values
                if isinstance(value, list):
                    specifics[name] = ', '.join(str(v) for v in value)
                else:
                    specifics[name] = str(value)
    
    return specifics

def extract_specific_field(item_specifics: Dict, field_names: List[str]) -> str:
    """Extract a specific field from item specifics, trying multiple field names"""
    for field_name in field_names:
        if field_name in item_specifics:
            return item_specifics[field_name]
    return ''

def extract_picture_urls(item_details: Dict) -> List[str]:
    """Extract picture URLs"""
    picture_details = item_details.get('PictureDetails', {})
    picture_urls = picture_details.get('PictureURL', [])
    
    if isinstance(picture_urls, str):
        return [picture_urls]
    elif isinstance(picture_urls, list):
        return picture_urls
    else:
        return []

def extract_shipping_cost(item_details: Dict) -> str:
    """Extract primary shipping cost"""
    shipping_details = item_details.get('ShippingDetails', {})
    service_options = shipping_details.get('ShippingServiceOptions', [])
    
    if not isinstance(service_options, list):
        service_options = [service_options]
    
    if service_options and len(service_options) > 0:
        first_option = service_options[0]
        cost = first_option.get('ShippingServiceCost', {})
        if isinstance(cost, dict):
            return cost.get('#text', '0.00')
        return str(cost) if cost else '0.00'
    
    return '0.00'

def extract_free_shipping(item_details: Dict) -> bool:
    """Check if item has free shipping"""
    shipping_cost = extract_shipping_cost(item_details)
    try:
        return float(shipping_cost) == 0.0
    except (ValueError, TypeError):
        return False

def extract_buy_it_now_price(item_details: Dict) -> str:
    """Extract Buy It Now price"""
    bin_price = item_details.get('BuyItNowPrice', {})
    if isinstance(bin_price, dict):
        return bin_price.get('#text', '')
    return str(bin_price) if bin_price else ''

def flatten_ebay_data(listings):
    """
    Intelligently flatten eBay listing data based on what fields are actually present
    
    Args:
        listings: List of eBay listing dictionaries
        
    Returns:
        List of flattened dictionaries with consistent field ordering
    """
    if not listings:
        return []
    
    flattened_listings = []
    
    # Analyze the first listing to determine what type of data we have
    sample_listing = listings[0]
    has_enriched_data = any(key in sample_listing for key in [
        'brand', 'model', 'type', 'item_specifics_raw', 'primary_category_name'
    ])
    
    print(f"🔧 Flattening {len(listings)} listings...")
    if has_enriched_data:
        print("   📊 Detected enriched data - using enhanced field order")
    else:
        print("   📊 Detected basic data - using standard field extraction")
    
    # Define field order based on data type
    if has_enriched_data:
        # Enhanced field order for enriched data
        field_order = [
            # Core identification
            'ItemID', 'Title', 'listing_state', 'SKU',
            
            # Product details (from enrichment)
            'brand', 'model', 'type', 'year', 'color', 'size', 'material',
            'condition_display_name', 'condition_id', 'condition_description',
            
            # Category (enhanced)
            'primary_category_name', 'primary_category_id', 
            'secondary_category_name', 'secondary_category_id',
            
            # Pricing
            'price', 'currency', 'buy_it_now_price',
            
            # Quantity and availability
            'Quantity', 'QuantityAvailable', 'quantity_sold',
            
            # Listing details
            'listing_type', 'listing_duration', 'format',
            
            # Timing
            'start_time', 'end_time', 'TimeLeft', 'listing_updated',
            
            # Location and shipping
            'location', 'country', 'postal_code', 'dispatch_time_max',
            'shipping_cost', 'free_shipping',
            
            # Pictures
            'picture_count', 'first_picture_url',
            
            # Metrics
            'view_count', 'watch_count', 'question_count',
            
            # Seller
            'seller_user_id', 'seller_feedback_score', 'seller_positive_feedback_percent',
            'seller_store_name',
            
            # Payment and returns
            'payment_methods', 'returns_accepted', 'returns_within',
            
            # URLs
            'ViewItemURL',
            
            # Description (at end as it can be very long)
            'subtitle', 'description',
        ]
    else:
        # Basic field order for standard Trading API data
        field_order = [
            # Core identification
            'ItemID', 'Title', 'listing_state',
            
            # Pricing (extracted)
            'price', 'currency',
            
            # Category (extracted)
            'category_name', 'category_id',
            'secondary_category_name', 'secondary_category_id',
            
            # Quantity
            'Quantity', 'QuantityAvailable', 'quantity_sold',
            
            # Status
            'listing_status', 'bid_count',
            
            # Timing
            'start_time', 'end_time', 'TimeLeft',
            
            # Shipping
            'shipping_cost', 'shipping_service',
            
            # Seller
            'seller_username', 'seller_feedback_score',
            
            # URLs
            'listing_url', 'ViewItemURL',
        ]
    
    for listing in listings:
        flattened = {}
        
        # First, add fields in the desired order (only if they exist)
        for field in field_order:
            if field in listing:
                flattened[field] = listing[field]
        
        # Handle nested dictionaries from basic Trading API responses
        for key, value in listing.items():
            if key in field_order:
                continue  # Already processed
                
            if not isinstance(value, dict):
                # Simple field not in field_order
                flattened[key] = value
            else:
                # Handle nested dictionaries from Trading API
                if key == "CurrentPrice" or key == "StartPrice":
                    if "price" not in flattened:  # Don't overwrite enriched price
                        flattened["price"] = value.get("#text", "")
                        flattened["currency"] = value.get("currencyID", "")
                        
                elif key == "SellingStatus":
                    if "price" not in flattened:  # Don't overwrite enriched price
                        current_price = value.get("CurrentPrice", {})
                        flattened["price"] = current_price.get("#text", "")
                        flattened["currency"] = current_price.get("currencyID", "")
                    if "quantity_sold" not in flattened:
                        flattened["quantity_sold"] = value.get("QuantitySold", "")
                    flattened["bid_count"] = value.get("BidCount", "")
                    flattened["listing_status"] = value.get("ListingStatus", "")
                    
                elif key == "PrimaryCategory":
                    if "primary_category_name" not in flattened:  # Don't overwrite enriched data
                        flattened["category_id"] = value.get("CategoryID", "")
                        flattened["category_name"] = value.get("CategoryName", "")
                        flattened["primary_category_id"] = value.get("CategoryID", "")
                        flattened["primary_category_name"] = value.get("CategoryName", "")
                    
                elif key == "SecondaryCategory":
                    if "secondary_category_name" not in flattened:  # Don't overwrite enriched data
                        flattened["secondary_category_id"] = value.get("CategoryID", "")
                        flattened["secondary_category_name"] = value.get("CategoryName", "")
                    
                elif key == "ListingDetails":
                    if "start_time" not in flattened:
                        flattened["start_time"] = value.get("StartTime", "")
                        flattened["end_time"] = value.get("EndTime", "")
                    if "listing_url" not in flattened and "ViewItemURL" not in flattened:
                        flattened["listing_url"] = value.get("ViewItemURL", "")
                        flattened["ViewItemURL"] = value.get("ViewItemURL", "")
                    
                elif key == "ShippingDetails":
                    if "shipping_cost" not in flattened:
                        shipping_service = value.get("ShippingServiceOptions", {})
                        if isinstance(shipping_service, list) and shipping_service:
                            shipping_service = shipping_service[0]
                        flattened["shipping_cost"] = shipping_service.get("ShippingServiceCost", {}).get("#text", "")
                        flattened["shipping_service"] = shipping_service.get("ShippingService", "")
                    
                elif key == "Seller":
                    if "seller_user_id" not in flattened:  # Don't overwrite enriched data
                        flattened["seller_username"] = value.get("UserID", "")
                        flattened["seller_user_id"] = value.get("UserID", "")
                        flattened["seller_feedback_score"] = value.get("FeedbackScore", "")
                        
                elif key == "item_specifics_raw" and isinstance(value, dict):
                    # Flatten item specifics with spec_ prefix (from enriched data)
                    for spec_name, spec_value in value.items():
                        safe_name = spec_name.lower().replace(' ', '_').replace('/', '_').replace('-', '_')
                        flattened[f'spec_{safe_name}'] = spec_value
                        
                else:
                    # For other nested objects, either flatten or convert to JSON string
                    if key in ['PictureDetails', 'ItemSpecifics']:
                        # Convert complex nested structures to JSON strings
                        flattened[f"{key}_json"] = json.dumps(value, default=str)
                    else:
                        # Simple nested dict - try to extract useful fields
                        if isinstance(value, dict) and len(value) <= 3:
                            # Small dict - flatten with prefix
                            for sub_key, sub_value in value.items():
                                flattened[f"{key}_{sub_key}"] = sub_value
                        else:
                            # Large dict - convert to JSON
                            flattened[f"{key}_json"] = json.dumps(value, default=str)
        
        # Add any spec_ fields at the end (they're dynamic based on item type)
        spec_fields = {k: v for k, v in listing.items() if k.startswith('spec_')}
        flattened.update(spec_fields)
        
        flattened_listings.append(flattened)
    
    return flattened_listings

def save_ebay_listings(listings, state, output_format, detailed, sandbox, flatten=True):
    """Save eBay listings to file(s) with optional flattening"""
    if not listings:
        print("No listings to save")
        return
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    detail_suffix = "_detailed" if detailed else ""
    sandbox_suffix = "_sandbox" if sandbox else ""
    flatten_suffix = "_flat" if flatten else ""
    base_filename = f"ebay_listings_{state}{detail_suffix}{sandbox_suffix}{flatten_suffix}_{timestamp}"
    
    # Create output directory
    output_dir = Path("scripts/ebay/output")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Apply flattening if requested
    if flatten:
        print("🔧 Flattening nested data for better CSV readability...")
        processed_listings = flatten_ebay_data(listings)
    else:
        processed_listings = listings
    
    if output_format in ["csv", "both"]:
        csv_file = output_dir / f"{base_filename}.csv"
        df = pd.DataFrame(processed_listings)
        df.to_csv(csv_file, index=False)
        print(f"💾 Saved CSV: {csv_file}")
        
        # Show column info for flattened data
        if flatten:
            print(f"📊 Flattened CSV contains {len(df.columns)} columns:")
            key_columns = [col for col in df.columns if col in [
                'ItemID', 'Title', 'price', 'currency', 'category_name', 
                'listing_status', 'quantity_sold', 'listing_url'
            ]]
            if key_columns:
                print(f"   Key columns: {', '.join(key_columns)}")
    
    if output_format in ["json", "both"]:
        import json
        json_file = output_dir / f"{base_filename}.json"
        with open(json_file, 'w') as f:
            json.dump(processed_listings, f, indent=2, default=str)
        print(f"💾 Saved JSON: {json_file}")

def analyze_ebay_listings(listings, state):
    """Provide basic analysis of eBay listings"""
    if not listings:
        return
    
    df = pd.DataFrame(listings)
    
    print(f"\n📊 **ANALYSIS FOR {state.upper()} EBAY LISTINGS**")
    print("=" * 50)
    print(f"Total listings: {len(listings)}")
    
    # Show available columns
    print(f"Available data fields: {len(df.columns)}")
    key_columns = [col for col in ['Title', 'ItemID', 'CurrentPrice', 'Quantity', 'listing_state', 'ListingType'] if col in df.columns]
    if key_columns:
        print(f"Key columns: {', '.join(key_columns)}")
    
    # Price analysis
    if 'CurrentPrice' in df.columns:
        try:
            # Handle eBay price structure (might be nested dict)
            prices = []
            for price_data in df['CurrentPrice']:
                if isinstance(price_data, dict):
                    price_val = price_data.get('#text', price_data.get('value', 0))
                else:
                    price_val = price_data
                try:
                    prices.append(float(price_val))
                except (ValueError, TypeError):
                    continue
            
            if prices:
                prices_series = pd.Series(prices)
                print(f"\n💰 **PRICE ANALYSIS**")
                print(f"Listings with prices: {len(prices)}")
                print(f"Price range: £{prices_series.min():.2f} - £{prices_series.max():.2f}")
                print(f"Average price: £{prices_series.mean():.2f}")
                print(f"Median price: £{prices_series.median():.2f}")
        except Exception as e:
            print(f"Could not analyze prices: {e}")
    
    # Category breakdown
    if 'PrimaryCategory' in df.columns:
        try:
            categories = []
            for cat_data in df['PrimaryCategory']:
                if isinstance(cat_data, dict):
                    cat_name = cat_data.get('CategoryName', 'Unknown')
                    categories.append(cat_name)
            
            if categories:
                category_counts = pd.Series(categories).value_counts().head(10)
                print(f"\n📂 **TOP 10 CATEGORIES**")
                for category, count in category_counts.items():
                    print(f"  {category}: {count}")
        except Exception as e:
            print(f"Could not analyze categories: {e}")
    
    # State breakdown for 'all' listings
    if state == "all" and 'listing_state' in df.columns:
        try:
            state_counts = df['listing_state'].value_counts()
            print(f"\n📈 **LISTING STATE BREAKDOWN**")
            for listing_state, count in state_counts.items():
                print(f"  {listing_state.title()}: {count}")
        except Exception as e:
            print(f"Could not analyze states: {e}")

async def main():
    parser = argparse.ArgumentParser(description="Fetch eBay inventory with enhanced details")
    
    # State options
    parser.add_argument(
        "--state", 
        choices=["active", "sold", "unsold", "all"],
        default="active",
        help="Listing state to fetch (default: active)"
    )
    
    # 🆕 Add enrichment argument
    parser.add_argument(
        "--enrich", 
        action="store_true",
        help="Enrich listings with detailed item information (slower but much more data)"
    )
    
    # Detail level
    parser.add_argument(
        "--detailed", 
        action="store_true",
        help="Fetch full details for each listing (slower but more complete)"
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
    
    # Environment options
    parser.add_argument(
        "--sandbox", 
        action="store_true",
        help="Use eBay Sandbox environment"
    )
    
    # Performance presets
    parser.add_argument(
        "--fast", 
        action="store_true",
        help="Fast mode: active listings only, first 100"
    )
    
    parser.add_argument(
        "--complete", 
        action="store_true",
        help="Complete mode: all listings, detailed data"
    )
    
    parser.add_argument(
        "--no-flatten", 
        action="store_true",
        help="Don't flatten nested data (keep original structure)"
    )
    
    parser.add_argument(
        "--use-inventory-api", 
        action="store_true",
        help="Use Inventory API instead of Trading API"
    )
    
    args = parser.parse_args()
    
    # Handle presets
    if args.fast:
        args.state = "active"
        args.detailed = False
        args.limit = 100
        print("🏃 Fast mode: Active listings, first 100 only")
    
    if args.complete:
        args.state = "all" 
        args.detailed = True
        args.enrich = True
        print("🎯 Complete mode: All listings with detailed data and enrichment")
    
    # Fetch listings
    listings = await get_ebay_listings(
        state=args.state,
        detailed=args.detailed,
        limit=args.limit,
        output_format=args.output,
        sandbox=args.sandbox,
        use_inventory_api=args.use_inventory_api,
        enrich_with_details=args.enrich
    )
    
    # Save results
    if not args.no_save and listings:
        save_ebay_listings(
            listings, 
            args.state, 
            args.output, 
            args.detailed, 
            args.sandbox, 
            flatten=not args.no_flatten
        )
    
    # Analyze if requested
    if args.analyze:
        analyze_ebay_listings(listings, args.state)

if __name__ == "__main__":
    asyncio.run(main())