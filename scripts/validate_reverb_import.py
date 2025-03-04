#!/usr/bin/env python
# scripts/validate_reverb_import.py

import asyncio
import json
import sys
from pathlib import Path

# Add the parent directory to Python path to import app modules
parent_dir = Path(__file__).resolve().parent.parent
sys.path.append(str(parent_dir))

from sqlalchemy import select
from app.database import get_session
from app.services.reverb.client import ReverbClient
from app.models.product import Product
from app.models.platform_common import PlatformCommon
from app.models.reverb import ReverbListing
from app.core.config import get_settings
from app.services.reverb.importer import ReverbImporter


async def validate_import(listing_id):
    """Compare imported data with API data for a specific listing"""
    settings = get_settings()
    client = ReverbClient(settings.REVERB_API_KEY)
    
    async with get_session() as db:
        importer = ReverbImporter(db)
        
        # Get API data
        print(f"Fetching API data for listing: {listing_id}")
        api_data = await client.get_listing_details(listing_id)
        
        # Get database data
        print("Fetching database data...")
        query = select(Product, PlatformCommon, ReverbListing)\
            .join(PlatformCommon, Product.id == PlatformCommon.product_id)\
            .join(ReverbListing, PlatformCommon.id == ReverbListing.platform_id)\
            .where(PlatformCommon.external_id == listing_id)
            
        result = await db.execute(query)
        db_data = result.first()
        
        if not db_data:
            print(f"ERROR: Listing {listing_id} not found in database")
            return
        
        product, platform, reverb = db_data
        
        # Map API data to expected DB structure
        expected_product, expected_platform, expected_reverb = await map_reverb_to_db(api_data)
        
        # Compare fields
        product_diff = compare_objects(product, expected_product)
        platform_diff = compare_objects(platform, expected_platform)
        reverb_diff = compare_objects(reverb, expected_reverb)
        
        # Print results
        print("\nValidation Results:")
        
        if not product_diff and not platform_diff and not reverb_diff:
            print("✓ All data matches between API and database!")
            return
        
        if product_diff:
            print("\nProduct differences:")
            for key, diff in product_diff.items():
                print(f"  {key}: Expected '{diff['expected']}', Actual '{diff['actual']}'")
        
        if platform_diff:
            print("\nPlatform differences:")
            for key, diff in platform_diff.items():
                print(f"  {key}: Expected '{diff['expected']}', Actual '{diff['actual']}'")
        
        if reverb_diff:
            print("\nReverb listing differences:")
            for key, diff in reverb_diff.items():
                print(f"  {key}: Expected '{diff['expected']}', Actual '{diff['actual']}'")
        
        # Save results to file
        results = {
            'product_diff': product_diff,
            'platform_diff': platform_diff,
            'reverb_diff': reverb_diff
        }
        
        with open('reverb_validation_results.json', 'w') as f:
            json.dump(results, f, indent=2)
        
        print("\nSaved detailed results to reverb_validation_results.json")


async def map_reverb_to_db(listing_data):
    """Complete mapping of Reverb API fields to database fields"""
    # Extract necessary data
    # Note: This is a simplified version - expand with all your field mappings
    brand = listing_data.get('make', '')
    model = listing_data.get('model', '')
    price_data = listing_data.get('price', {})
    price = float(price_data.get('amount', 0)) if isinstance(price_data, dict) else 0
    
    product_fields = {
        'brand': brand,
        'model': model,
        'year': int(listing_data.get('year', 0)) if listing_data.get('year') else None,
        'description': listing_data.get('description', ''),
        'sku': f"REV-{listing_data.get('id', '')}",
        'base_price': price,
        # Add other Product fields here
    }
    
    platform_fields = {
        'platform_name': 'reverb',
        'external_id': str(listing_data.get('id', '')),
        'status': 'active',  # Map from listing_data.get('state')
        'listing_url': listing_data.get('_links', {}).get('web', {}).get('href', ''),
        # Add other PlatformCommon fields here
    }
    
    reverb_fields = {
        'reverb_listing_id': str(listing_data.get('id', '')),
        'reverb_category_uuid': next((c.get('uuid', '') for c in listing_data.get('categories', [])), ''),
        'condition_rating': 4.5,  # You'd map this from the condition
        'handmade': bool(listing_data.get('handmade', False)),
        'offers_enabled': bool(listing_data.get('offers_enabled', False)),
        # Add other ReverbListing fields here
    }
    
    return product_fields, platform_fields, reverb_fields


def compare_objects(obj, expected_data):
    """Compare object attributes with expected values"""
    diffs = {}
    for key, expected_value in expected_data.items():
        if hasattr(obj, key):
            actual_value = getattr(obj, key)
            if actual_value != expected_value:
                diffs[key] = {
                    'expected': expected_value,
                    'actual': actual_value
                }
    return diffs


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Validate Reverb import')
    parser.add_argument('listing_id', help='Reverb listing ID to validate')
    
    args = parser.parse_args()
    
    asyncio.run(validate_import(args.listing_id))