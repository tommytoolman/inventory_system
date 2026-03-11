#!/usr/bin/env python
# scripts/get_reverb_conditions.py

import asyncio
import os
import json
import sys
import argparse
from pathlib import Path

# Add the parent directory to Python path to import app modules
parent_dir = Path(__file__).resolve().parent.parent
sys.path.append(str(parent_dir))

from app.services.reverb.client import ReverbClient

async def get_conditions(use_sandbox=False):
    """Get and print listing conditions from Reverb API"""
    # Determine which API key to use based on the use_sandbox flag
    api_key = os.environ.get("REVERB_SANDBOX_API_KEY") if use_sandbox else os.environ.get("REVERB_API_KEY")
    
    # If specified key isn't available, try the other one as fallback
    if not api_key:
        api_key = os.environ.get("REVERB_SANDBOX_API_KEY" if not use_sandbox else "REVERB_API_KEY")
        if api_key:
            use_sandbox = not use_sandbox
            print(f"Warning: Requested API key not found, falling back to {'sandbox' if use_sandbox else 'production'}")
        else:
            print("Error: No Reverb API keys found in environment variables")
            sys.exit(1)
    
    print(f"Using {'sandbox' if use_sandbox else 'production'} Reverb API")
    
    try:
        client = ReverbClient(api_key=api_key, use_sandbox=use_sandbox)
        
        # For production API, we need to add the Accept-Version header
        if not use_sandbox:
            # Create a custom version of _get_headers that includes the Accept-Version header
            original_get_headers = client._get_headers
            client._get_headers = lambda: {
                **original_get_headers(),
                "Accept-Version": "3.0"  # This is the required header for production API
            }
        
        conditions = await client.get_listing_conditions()
        
        # Pretty print the conditions
        print(json.dumps(conditions, indent=2))
        
        # Also print mapping of slugs to UUIDs for easy reference
        print("\n=== CONDITION MAPPING ===")
        if "conditions" in conditions:
            for condition in conditions["conditions"]:
                print(f"{condition['display_name']}: {condition['uuid']}")
        
    except Exception as e:
        print(f"Error: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Get Reverb listing conditions")
    parser.add_argument('--sandbox', action='store_true', help='Use sandbox API instead of production')
    args = parser.parse_args()
    
    asyncio.run(get_conditions(use_sandbox=args.sandbox))