#!/usr/bin/env python3
"""
Fetch overview details for a Reverb shop.

Usage:
    python scripts/reverb/get_reverb_shop_details.py <shop_slug> [--json] [--save] [--include-listings] [--all-listings] [--listings-json-lines]

Examples:
    python scripts/reverb/get_reverb_shop_details.py waxmusical
    python scripts/reverb/get_reverb_shop_details.py waxmusical --json
    python scripts/reverb/get_reverb_shop_details.py waxmusical --save
    python scripts/reverb/get_reverb_shop_details.py waxmusical --include-listings --listings-limit 25
    python scripts/reverb/get_reverb_shop_details.py waxmusical --include-listings --all-listings
    python scripts/reverb/get_reverb_shop_details.py waxmusical --include-listings --listings-json-lines

Options:
    --json               Output as pretty-printed JSON
    --save               Save JSON response to scripts/reverb/output/shop_<slug>.json
    --include-listings   Also fetch listings via /api/listings/all?shop_id=<id>
    --listings-limit     Max listings to collect (default 50)
    --all-listings       Ignore the limit and fetch every page returned by Reverb
    --listings-json-lines
                        Stream listings as newline-delimited JSON (requires --include-listings)
"""

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime

import httpx

sys.path.append(str(Path(__file__).parent.parent.parent))

from app.core.config import get_settings

API_BASE = "https://api.reverb.com/api/shops"
LISTINGS_ENDPOINT = "https://api.reverb.com/api/listings/all"


def build_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Accept-Version": "3.0",
        "Content-Type": "application/json",
        "User-Agent": "RIFF-Inventory-Scripts/1.0",
    }


def fetch_shop_details(slug: str, token: str) -> dict:
    url = f"{API_BASE}/{slug}".rstrip("/")
    headers = build_headers(token)
    try:
        response = httpx.get(url, headers=headers, timeout=30.0)
    except httpx.RequestError as exc:
        raise RuntimeError(f"Network error calling {url}: {exc}") from exc

    if response.status_code == 404:
        raise RuntimeError(f"Shop '{slug}' not found (404)")
    if response.status_code >= 300:
        raise RuntimeError(
            f"Failed to fetch shop '{slug}'. Status {response.status_code}: {response.text[:200]}"
        )

    try:
        return response.json()
    except ValueError as exc:
        raise RuntimeError(f"Invalid JSON response from {url}") from exc


def fetch_shop_listings(shop_id: int, token: str, *, limit: int | None = 50) -> dict:
    if limit is not None and limit <= 0:
        return {"listings": [], "collected": 0}

    headers = build_headers(token)
    listings: list[dict] = []
    page = 1
    remaining = limit if limit is not None else float("inf")

    while remaining > 0:
        per_page = 50 if remaining == float("inf") else min(remaining, 50)
        params = {"shop_id": shop_id, "page": page, "per_page": per_page}
        try:
            response = httpx.get(
                LISTINGS_ENDPOINT, params=params, headers=headers, timeout=30.0
            )
        except httpx.RequestError as exc:
            raise RuntimeError(
                f"Network error calling {LISTINGS_ENDPOINT}: {exc}"
            ) from exc

        if response.status_code >= 300:
            raise RuntimeError(
                "Failed to fetch listings for shop "
                f"{shop_id}. Status {response.status_code}: {response.text[:200]}"
            )

        data = response.json()
        page_listings: list[dict]
        if isinstance(data, dict) and "listings" in data:
            page_listings = data.get("listings") or []
        elif isinstance(data, list):
            page_listings = data
        else:
            raise RuntimeError(
                "Unexpected listings payload structure "
                f"for shop {shop_id}: {type(data).__name__}"
            )

        if not page_listings:
            break

        if remaining == float("inf"):
            listings.extend(page_listings)
        else:
            listings.extend(page_listings[:remaining])
            remaining = limit - len(listings)
            if remaining <= 0:
                break
        page += 1

    return {
        "collected": len(listings),
        "listings": listings,
    }


def save_output(slug: str, payload: dict) -> Path:
    output_dir = Path(__file__).parent / "output"
    output_dir.mkdir(exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    file_path = output_dir / f"shop_{slug}_{timestamp}.json"
    file_path.write_text(json.dumps(payload, indent=2, default=str))
    return file_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch Reverb shop details")
    parser.add_argument("slug", help="Shop slug, e.g. 'waxmusical'")
    parser.add_argument("--json", action="store_true", help="Pretty-print JSON output")
    parser.add_argument("--save", action="store_true", help="Save JSON response to scripts/reverb/output")
    parser.add_argument(
        "--include-listings",
        action="store_true",
        help="Fetch listings for the shop via /api/listings/all",
    )
    parser.add_argument(
        "--listings-limit",
        type=int,
        default=50,
        help="Maximum number of listings to fetch when --include-listings is set (default: 50)",
    )
    parser.add_argument(
        "--all-listings",
        action="store_true",
        help="Fetch every available listings page (overrides --listings-limit)",
    )
    parser.add_argument(
        "--listings-json-lines",
        action="store_true",
        help="Stream each listing as newline-delimited JSON (implies machine-readable output)",
    )
    args = parser.parse_args()

    if args.listings_json_lines and not args.include_listings:
        parser.error("--listings-json-lines requires --include-listings")

    settings = get_settings()
    token = settings.REVERB_API_KEY
    if not token:
        raise RuntimeError("REVERB_API_KEY is not configured in settings")

    shop_payload = fetch_shop_details(args.slug, token)

    human_summary = not (args.json or args.listings_json_lines)
    if human_summary:
        print(f"\n🏪 Reverb shop: {shop_payload.get('name', 'N/A')} (slug: {args.slug})")
        print(f"   Shop ID: {shop_payload.get('id', 'N/A')}")
        print(f"   Country: {shop_payload.get('shop_location', {}).get('country', 'N/A')}")
        print(f"   City: {shop_payload.get('shop_location', {}).get('city', 'N/A')}")
        print(
            f"   Owner: {shop_payload.get('owners', [{}])[0].get('display_name', 'N/A') if shop_payload.get('owners') else 'N/A'}"
        )
        print(f"   Created: {shop_payload.get('created_at', 'N/A')}")
        print(f"   Followers: {shop_payload.get('followers_count', 'N/A')}")
        print(f"   Listings: {shop_payload.get('listing_count', 'N/A')}")

    combined_payload: dict = {"shop": shop_payload}
    if args.include_listings:
        shop_id = shop_payload.get("id")
        if not shop_id:
            raise RuntimeError(
                "Shop response did not include an 'id'; cannot fetch listings."
            )
        listings_limit = None if args.all_listings else args.listings_limit
        listings_payload = fetch_shop_listings(
            shop_id=int(shop_id), token=token, limit=listings_limit
        )
        combined_payload["listings"] = listings_payload

        sample = listings_payload.get("listings", [])[:3]
        if human_summary:
            print(
                f"\n📦 Retrieved {listings_payload.get('collected', 0)} listing(s) "
                f"(limit {'all' if args.all_listings else args.listings_limit})"
            )
            if sample:
                print("   Sample titles:")
                for item in sample:
                    title = item.get("title") or item.get("make") or "Untitled"
                    listing_id = item.get("id", "N/A")
                    print(f"     • {title} (ID: {listing_id})")
            else:
                print("   No listings returned.")

    output_payload = combined_payload if args.include_listings else shop_payload

    if args.json:
        print(json.dumps(output_payload, indent=2, default=str))

    if args.listings_json_lines and args.include_listings:
        listings_list = combined_payload.get("listings", {}).get("listings", [])
        for listing in listings_list:
            if not isinstance(listing, dict):
                continue
            enriched = {
                "_shop": {
                    "slug": args.slug,
                    "id": shop_payload.get("id"),
                    "name": shop_payload.get("name"),
                },
                **listing,
            }
            print(json.dumps(enriched, separators=(",", ":"), default=str))

    if args.save:
        path = save_output(args.slug, output_payload)
        print(f"\n💾 Saved JSON to {path}")


if __name__ == "__main__":
    main()
