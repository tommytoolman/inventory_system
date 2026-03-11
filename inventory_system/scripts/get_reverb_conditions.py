#!/usr/bin/env python3
"""Get valid Reverb condition UUIDs"""

import asyncio
import os
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.reverb.client import ReverbClient
from app.core.config import get_settings

async def get_conditions():
    """Get all valid condition UUIDs from Reverb"""
    settings = get_settings()

    client = ReverbClient(
        api_key=settings.REVERB_API_KEY,
        use_sandbox=False
    )

    try:
        # Get conditions
        result = await client.get_listing_conditions()
        conditions = result.get('listing_conditions', [])

        if not conditions:
            # Try alternate endpoint
            result = await client.get("/listing_conditions")
            conditions = result.get('conditions', result.get('listing_conditions', []))

        print(f"\n=== Reverb Listing Conditions ===")
        print(f"Found {len(conditions)} conditions\n")

        for condition in conditions:
            print(f"Name: {condition.get('name', 'N/A')}")
            print(f"UUID: {condition.get('uuid', 'N/A')}")
            print(f"Display Name: {condition.get('display_name', 'N/A')}")
            print(f"Description: {condition.get('description', 'N/A')}")
            print("-" * 50)

        return conditions

    except Exception as e:
        print(f"Error getting conditions: {e}")
        print(f"Error type: {type(e).__name__}")

        # Try direct API call to see raw response
        try:
            import httpx
            headers = client._get_headers()
            async with httpx.AsyncClient() as http_client:
                response = await http_client.get(
                    f"{client.BASE_URL}/listing_conditions",
                    headers=headers
                )
                print(f"\nRaw response status: {response.status_code}")
                print(f"Raw response: {response.text[:500]}")
        except Exception as e2:
            print(f"Could not get raw response: {e2}")

if __name__ == "__main__":
    asyncio.run(get_conditions())