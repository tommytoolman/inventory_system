#!/usr/bin/env python3
"""
Test Reverb relist/reactivate API endpoints using sandbox.

This script tests various potential endpoints to relist an ended listing:
1. PUT /my/listings/{id}/state/live
2. PUT /my/listings/{id}/state/publish
3. PUT /listings/{id} with {"publish": "true"}
4. PUT /listings/{id} with {"state": "live"}
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv()

import httpx
from app.core.config import get_settings


async def test_relist_endpoints():
    """Test various potential relist endpoints on Reverb sandbox."""

    settings = get_settings()
    api_key = settings.REVERB_SANDBOX_API_KEY

    if not api_key:
        print("ERROR: REVERB_SANDBOX_API_KEY not set in environment")
        return

    base_url = "https://sandbox.reverb.com/api"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Accept-Version": "3.0"
    }

    async with httpx.AsyncClient(timeout=30.0) as client:

        # Step 1: Get current listings to find one to test with
        print("\n" + "="*60)
        print("Step 1: Fetching current sandbox listings...")
        print("="*60)

        resp = await client.get(
            f"{base_url}/my/listings",
            headers=headers,
            params={"state": "all", "per_page": 10}
        )

        if resp.status_code != 200:
            print(f"Failed to get listings: {resp.status_code}")
            print(resp.text)
            return

        data = resp.json()
        listings = data.get("listings", [])

        print(f"Found {len(listings)} listings")

        # Show listing states
        for listing in listings[:5]:
            state = listing.get('state')
            state_slug = state.get('slug') if isinstance(state, dict) else state
            print(f"  - ID: {listing.get('id')} | State: {state_slug} | Title: {listing.get('title', 'N/A')[:40]}")

        # Find an ended listing, live listing, or draft
        ended_listing = None
        live_listing = None
        draft_listing = None

        for listing in listings:
            state = listing.get("state")
            state_slug = state.get('slug') if isinstance(state, dict) else state

            if state_slug == "ended":
                ended_listing = listing
            elif state_slug == "live":
                live_listing = listing
            elif state_slug == "draft":
                draft_listing = listing

        # Determine test listing
        test_listing_id = None

        if ended_listing:
            test_listing_id = ended_listing.get("id")
            print(f"\nUsing existing ended listing: {test_listing_id}")

        elif live_listing:
            test_listing_id = live_listing.get("id")
            print(f"\nEnding live listing {test_listing_id} for testing...")

            end_resp = await client.put(
                f"{base_url}/my/listings/{test_listing_id}/state/end",
                headers=headers,
                json={"reason": "not_sold"}
            )
            print(f"End response: {end_resp.status_code}")
            if end_resp.status_code != 200:
                print(f"End failed: {end_resp.text}")

        elif draft_listing:
            test_listing_id = draft_listing.get("id")
            print(f"\nPublishing draft listing {test_listing_id} first...")

            # Publish the draft
            pub_resp = await client.put(
                f"{base_url}/listings/{test_listing_id}",
                headers=headers,
                json={"publish": "true"}
            )
            print(f"Publish response: {pub_resp.status_code}")
            if pub_resp.status_code == 200:
                print("Published! Now ending it...")
                # End the listing
                end_resp = await client.put(
                    f"{base_url}/my/listings/{test_listing_id}/state/end",
                    headers=headers,
                    json={"reason": "not_sold"}
                )
                print(f"End response: {end_resp.status_code}")
                if end_resp.status_code != 200:
                    print(f"End failed: {end_resp.text}")
            else:
                print(f"Publish failed: {pub_resp.text}")
                return
        else:
            print("\nNo listings available for testing. Please create a sandbox listing first.")
            return

        if not test_listing_id:
            print("No test listing ID available")
            return

        print(f"\n" + "="*60)
        print(f"Testing relist endpoints on listing ID: {test_listing_id}")
        print("="*60)

        # Test 1: PUT /my/listings/{id}/state/live
        print("\n--- Test 1: PUT /my/listings/{id}/state/live ---")
        try:
            resp = await client.put(
                f"{base_url}/my/listings/{test_listing_id}/state/live",
                headers=headers
            )
            print(f"Status: {resp.status_code}")
            print(f"Response: {resp.text[:500] if resp.text else '(empty)'}")
        except Exception as e:
            print(f"Error: {e}")

        # Test 2: PUT /my/listings/{id}/state/publish
        print("\n--- Test 2: PUT /my/listings/{id}/state/publish ---")
        try:
            resp = await client.put(
                f"{base_url}/my/listings/{test_listing_id}/state/publish",
                headers=headers
            )
            print(f"Status: {resp.status_code}")
            print(f"Response: {resp.text[:500] if resp.text else '(empty)'}")
        except Exception as e:
            print(f"Error: {e}")

        # Test 3: PUT /listings/{id} with {"publish": "true"}
        print('\n--- Test 3: PUT /listings/{id} with {"publish": "true"} ---')
        try:
            resp = await client.put(
                f"{base_url}/listings/{test_listing_id}",
                headers=headers,
                json={"publish": "true"}
            )
            print(f"Status: {resp.status_code}")
            print(f"Response: {resp.text[:500] if resp.text else '(empty)'}")
        except Exception as e:
            print(f"Error: {e}")

        # Test 4: PUT /listings/{id} with {"state": "live"}
        print('\n--- Test 4: PUT /listings/{id} with {"state": "live"} ---')
        try:
            resp = await client.put(
                f"{base_url}/listings/{test_listing_id}",
                headers=headers,
                json={"state": "live"}
            )
            print(f"Status: {resp.status_code}")
            print(f"Response: {resp.text[:500] if resp.text else '(empty)'}")
        except Exception as e:
            print(f"Error: {e}")

        # Test 5: Check what _links are available on an ended listing
        print("\n--- Test 5: Check _links on ended listing ---")
        try:
            resp = await client.get(
                f"{base_url}/listings/{test_listing_id}",
                headers=headers
            )
            if resp.status_code == 200:
                listing_data = resp.json()
                links = listing_data.get("_links", {})
                print(f"Available _links: {list(links.keys())}")

                # Check for any relist-related links
                for key, value in links.items():
                    if any(word in key.lower() for word in ["relist", "publish", "live", "activate"]):
                        print(f"  Potential relist link: {key} -> {value}")
            else:
                print(f"Failed to get listing: {resp.status_code}")
        except Exception as e:
            print(f"Error: {e}")

        # Final check: Get listing state after tests
        print("\n--- Final: Check listing state after tests ---")
        try:
            resp = await client.get(
                f"{base_url}/listings/{test_listing_id}",
                headers=headers
            )
            if resp.status_code == 200:
                listing_data = resp.json()
                print(f"Current state: {listing_data.get('state')}")
            else:
                print(f"Failed: {resp.status_code}")
        except Exception as e:
            print(f"Error: {e}")


if __name__ == "__main__":
    asyncio.run(test_relist_endpoints())
