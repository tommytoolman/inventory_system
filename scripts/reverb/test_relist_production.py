#!/usr/bin/env python3
"""
Test Reverb relist on production with a real listing.

Listing: https://reverb.com/uk/item/93437484-vox-ac30-head-black-1963-top-boost-rare-beatles
"""

import asyncio
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv()

import httpx
from app.core.config import get_settings


async def check_listing(listing_id: str):
    """Check the listing's current state and available links."""

    settings = get_settings()
    api_key = settings.REVERB_API_KEY

    if not api_key:
        print("ERROR: REVERB_API_KEY not set")
        return

    base_url = "https://api.reverb.com/api"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Accept-Version": "3.0"
    }

    async with httpx.AsyncClient(timeout=30.0) as client:

        print(f"\n{'='*60}")
        print(f"Checking listing {listing_id}")
        print(f"{'='*60}")

        resp = await client.get(
            f"{base_url}/listings/{listing_id}",
            headers=headers
        )

        if resp.status_code != 200:
            print(f"Failed to get listing: {resp.status_code}")
            print(resp.text[:500])
            return

        data = resp.json()

        print(f"\nTitle: {data.get('title')}")
        print(f"State: {data.get('state')}")
        print(f"Price: {data.get('price', {}).get('display')}")
        print(f"SKU: {data.get('sku')}")

        # Show all available _links
        links = data.get("_links", {})
        print(f"\nAvailable _links ({len(links)} total):")
        for key in sorted(links.keys()):
            link_data = links[key]
            if isinstance(link_data, dict):
                method = link_data.get('method', 'GET')
                href = link_data.get('href', str(link_data))
            else:
                method = 'GET'
                href = str(link_data)
            # Highlight potentially interesting ones
            highlight = ""
            if any(word in key.lower() for word in ["relist", "publish", "live", "end", "state"]):
                highlight = " <-- INTERESTING"
            href_short = href[:80] if isinstance(href, str) else str(href)[:80]
            print(f"  {key}: [{method}] {href_short}{highlight}")

        return data


async def end_listing(listing_id: str):
    """End the listing."""

    settings = get_settings()
    api_key = settings.REVERB_API_KEY

    base_url = "https://api.reverb.com/api"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Accept-Version": "3.0"
    }

    async with httpx.AsyncClient(timeout=30.0) as client:

        print(f"\n{'='*60}")
        print(f"ENDING listing {listing_id}")
        print(f"{'='*60}")

        resp = await client.put(
            f"{base_url}/my/listings/{listing_id}/state/end",
            headers=headers,
            json={"reason": "not_sold"}
        )

        print(f"Status: {resp.status_code}")
        print(f"Response: {resp.text[:500] if resp.text else '(empty)'}")

        return resp.status_code == 200


async def test_relist_endpoints(listing_id: str):
    """Try various relist endpoints on the ended listing."""

    settings = get_settings()
    api_key = settings.REVERB_API_KEY

    base_url = "https://api.reverb.com/api"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Accept-Version": "3.0"
    }

    async with httpx.AsyncClient(timeout=30.0) as client:

        print(f"\n{'='*60}")
        print(f"Testing RELIST endpoints on {listing_id}")
        print(f"{'='*60}")

        # Test 1: PUT /my/listings/{id}/state/live
        print("\n--- Test 1: PUT /my/listings/{id}/state/live ---")
        resp = await client.put(
            f"{base_url}/my/listings/{listing_id}/state/live",
            headers=headers
        )
        print(f"Status: {resp.status_code}")
        print(f"Response: {resp.text[:300] if resp.text else '(empty)'}")

        # Test 2: PUT /my/listings/{id}/state/publish
        print("\n--- Test 2: PUT /my/listings/{id}/state/publish ---")
        resp = await client.put(
            f"{base_url}/my/listings/{listing_id}/state/publish",
            headers=headers
        )
        print(f"Status: {resp.status_code}")
        print(f"Response: {resp.text[:300] if resp.text else '(empty)'}")

        # Test 3: PUT /listings/{id} with {"publish": true}
        print('\n--- Test 3: PUT /listings/{id} with {"publish": true} ---')
        resp = await client.put(
            f"{base_url}/listings/{listing_id}",
            headers=headers,
            json={"publish": True}
        )
        print(f"Status: {resp.status_code}")
        print(f"Response: {resp.text[:300] if resp.text else '(empty)'}")

        # Check final state
        print("\n--- Final state check ---")
        resp = await client.get(
            f"{base_url}/listings/{listing_id}",
            headers=headers
        )
        if resp.status_code == 200:
            data = resp.json()
            print(f"State: {data.get('state')}")

            # Check _links on ended listing
            links = data.get("_links", {})
            print(f"\nAvailable _links on ended listing:")
            for key in sorted(links.keys()):
                link_data = links[key]
                method = link_data.get('method', 'GET') if isinstance(link_data, dict) else 'GET'
                highlight = ""
                if any(word in key.lower() for word in ["relist", "publish", "live", "end", "state"]):
                    highlight = " <-- INTERESTING"
                print(f"  {key}: [{method}]{highlight}")


async def main():
    import sys

    if len(sys.argv) < 3:
        print("Usage:")
        print("  python test_relist_production.py check <listing_id>   - Check listing state and links")
        print("  python test_relist_production.py end <listing_id>     - End the listing")
        print("  python test_relist_production.py relist <listing_id>  - Try relist endpoints")
        print("")
        print("Example:")
        print("  python test_relist_production.py check 93437484")
        return

    cmd = sys.argv[1]
    listing_id = sys.argv[2]

    if cmd == "check":
        await check_listing(listing_id)
    elif cmd == "end":
        await end_listing(listing_id)
    elif cmd == "relist":
        await test_relist_endpoints(listing_id)
    else:
        print(f"Unknown command: {cmd}")


if __name__ == "__main__":
    asyncio.run(main())
