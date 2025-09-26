#!/usr/bin/env python3
"""Test Reverb API connection and listing creation"""

import asyncio
import os
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.reverb.client import ReverbClient
from app.core.config import get_settings

async def test_reverb_connection():
    """Test basic Reverb API connection"""
    settings = get_settings()

    # Test with production API
    print("\n=== Testing Reverb API Connection ===")
    print(f"Using production API: {not settings.REVERB_USE_SANDBOX}")
    print(f"API Key exists: {bool(settings.REVERB_API_KEY)}")
    print(f"API Key first 10 chars: {settings.REVERB_API_KEY[:10]}...")

    client = ReverbClient(
        api_key=settings.REVERB_API_KEY,
        use_sandbox=False
    )

    print(f"\nBase URL: {client.BASE_URL}")

    # Test basic API connection
    try:
        print("\n1. Testing account access...")
        account = await client.get_account()
        print(f"✓ Account access successful: {account.get('username', 'N/A')}")
    except Exception as e:
        print(f"✗ Account access failed: {e}")
        return

    # Test categories
    try:
        print("\n2. Testing categories endpoint...")
        categories = await client.get_categories()
        print(f"✓ Categories retrieved: {len(categories.get('categories', []))} categories")
    except Exception as e:
        print(f"✗ Categories failed: {e}")

    # Test conditions
    try:
        print("\n3. Testing conditions endpoint...")
        conditions = await client.get_listing_conditions()
        print(f"✓ Conditions retrieved: {len(conditions.get('listing_conditions', []))} conditions")
    except Exception as e:
        print(f"✗ Conditions failed: {e}")

    # Test minimal listing creation payload
    print("\n4. Testing listing creation with minimal payload...")
    test_payload = {
        "make": "Test",
        "model": "API Test",
        "title": "Test API Listing - Please Ignore",
        "condition": {
            "uuid": "ae4d9114-604a-4949-a77a-18630f1e358f"  # Excellent condition
        },
        "categories": [{
            "uuid": "72bf5ff0-f6e0-4502-ad7d-ecab2a1e6ba9"  # Electric guitars
        }],
        "price": {
            "amount": "100.00",
            "currency": "GBP"
        },
        "description": "This is a test listing created by API test script. Please ignore.",
        "sku": f"API-TEST-{int(asyncio.get_event_loop().time())}",
        "photos": [],  # Empty photos array
        "publish": False  # Keep as draft
    }

    try:
        print(f"\nSending payload: {test_payload}")
        result = await client.create_listing(test_payload)
        print(f"✓ Listing created successfully!")
        print(f"  Listing ID: {result.get('id')}")
        print(f"  State: {result.get('state')}")

        # Try to delete the test listing
        if result.get('id'):
            try:
                await client.end_listing(result['id'])
                print(f"✓ Test listing deleted")
            except:
                print(f"Note: Could not delete test listing {result['id']}")

    except Exception as e:
        print(f"✗ Listing creation failed: {e}")
        print(f"  Error type: {type(e).__name__}")

if __name__ == "__main__":
    asyncio.run(test_reverb_connection())