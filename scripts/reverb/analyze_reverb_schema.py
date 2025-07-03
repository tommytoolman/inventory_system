#!/usr/bin/env python
# scripts/analyze_reverb_schema.py

import asyncio
import json
import sys
from pathlib import Path

# Add the parent directory to Python path to import app modules
parent_dir = Path(__file__).resolve().parent.parent
sys.path.append(str(parent_dir))

from app.database import get_session
from app.services.reverb.client import ReverbClient
from app.models.product import Product
from app.models.platform_common import PlatformCommon
from app.models.reverb import ReverbListing
from app.core.config import get_settings

async def flatten_dict(d, result, prefix=''):
    """Flatten a nested dictionary structure"""
    for k, v in d.items():
        key = f"{prefix}.{k}" if prefix else k
        
        if isinstance(v, dict):
            await flatten_dict(v, result, key)
        elif isinstance(v, list):
            for i, item in enumerate(v):
                list_key = f"{key}[{i}]"
                if isinstance(item, dict):
                    await flatten_dict(item, result, list_key)
                else:
                    result[list_key] = item
        else:
            result[key] = v


async def analyze_reverb_schema(sample_listing_id=None):
    """Analyze the schema of a Reverb listing to ensure we're capturing all fields"""
    settings = get_settings()
    client = ReverbClient(settings.REVERB_API_KEY)
    
    if not sample_listing_id:
        # Get any listing
        listings = await client.get_my_listings(page=1, per_page=1)
        if not listings or not listings.get('listings'):
            print("No listings found for schema analysis")
            return
        
        sample_listing_id = listings['listings'][0]['id']
    
    print(f"Analyzing schema for listing ID: {sample_listing_id}")
    
    # Get detailed listing
    details = await client.get_listing_details(sample_listing_id)
    
    # Flatten the nested structure for analysis
    flattened = {}
    await flatten_dict(details, flattened)
    
    # Compare with our database schema
    db_fields = {
        'Product': [c.name for c in Product.__table__.columns],
        'PlatformCommon': [c.name for c in PlatformCommon.__table__.columns],
        'ReverbListing': [c.name for c in ReverbListing.__table__.columns],
    }
    
    # Find missing fields
    api_fields = set(flattened.keys())
    all_db_fields = set()
    for table_fields in db_fields.values():
        all_db_fields.update(table_fields)
    
    missing_fields = api_fields - all_db_fields
    
    print(f"API has {len(api_fields)} fields, our DB has {len(all_db_fields)} fields")
    print(f"Missing {len(missing_fields)} fields from API in our database schema")
    
    # Log missing fields with their values
    print("\nMissing fields from API in our database schema:")
    for field in sorted(missing_fields):
        print(f"  {field} = {flattened[field]}")
    
    # Save results to file
    results = {
        'api_fields': list(api_fields),
        'db_fields': list(all_db_fields),
        'missing_fields': list(missing_fields),
        'sample': details
    }
    
    with open('reverb_schema_analysis.json', 'w') as f:
        json.dump(results, f, indent=2)
    
    print(f"\nSaved analysis to reverb_schema_analysis.json")
    
    return results


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Analyze Reverb API schema')
    parser.add_argument('--listing-id', help='Specific listing ID to analyze')
    
    args = parser.parse_args()
    
    asyncio.run(analyze_reverb_schema(args.listing_id))