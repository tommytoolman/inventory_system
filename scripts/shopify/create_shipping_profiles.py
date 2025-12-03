#!/usr/bin/env python3
"""
Shopify Shipping Profile Creation Script
=========================================

Creates Shopify delivery profiles that mirror your Reverb shipping profiles.
Reads rates from the local shipping_profiles table and creates matching
profiles in Shopify via GraphQL API.

SCOPE OPTIONS (pick one):
-------------------------
  --name <name>     Create single profile by name (e.g., "Bass Guitars")
  --missing         Create all profiles that don't have a Shopify GID yet
  --all             Recreate ALL profiles (use with caution)

CONTROL OPTIONS:
----------------
  --dry-run         Show what would be created, don't execute
  --verbose         Show detailed progress

EXAMPLES:
---------

# Preview what would be created for Bass Guitars
python scripts/shopify/create_shipping_profiles.py --name "Bass Guitars" --dry-run

# Create Bass Guitars profile for real
python scripts/shopify/create_shipping_profiles.py --name "Bass Guitars" --verbose

# Preview all missing profiles
python scripts/shopify/create_shipping_profiles.py --missing --dry-run

# Create all missing profiles
python scripts/shopify/create_shipping_profiles.py --missing --verbose


ZONE STRUCTURE:
---------------
Each profile creates 4 shipping zones:
  - UK (GB only)
  - Europe (EU + Norway, Switzerland, Iceland)
  - USA (US only)
  - Rest of World (all other countries)

Rates are read from the shipping_profiles.rates JSONB column:
  {"uk": 30.0, "europe": 65.0, "usa": 100.0, "row": 140.0}
"""

import argparse
import asyncio
import sys
from pathlib import Path

import requests

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sqlalchemy import text
from app.database import async_session
from app.core.config import get_settings


# Shopify GraphQL mutation for creating a delivery profile
DELIVERY_PROFILE_CREATE_MUTATION = """
mutation deliveryProfileCreate($profile: DeliveryProfileInput!) {
  deliveryProfileCreate(profile: $profile) {
    profile {
      id
      name
    }
    userErrors {
      field
      message
    }
  }
}
"""

# European country codes (EU + EEA)
# Apply includeAllProvinces to all countries to avoid province errors
EUROPE_COUNTRIES = [
    {"code": "AT", "includeAllProvinces": True},
    {"code": "BE", "includeAllProvinces": True},
    {"code": "BG", "includeAllProvinces": True},
    {"code": "HR", "includeAllProvinces": True},
    {"code": "CY", "includeAllProvinces": True},
    {"code": "CZ", "includeAllProvinces": True},
    {"code": "DK", "includeAllProvinces": True},
    {"code": "EE", "includeAllProvinces": True},
    {"code": "FI", "includeAllProvinces": True},
    {"code": "FR", "includeAllProvinces": True},
    {"code": "DE", "includeAllProvinces": True},
    {"code": "GR", "includeAllProvinces": True},
    {"code": "HU", "includeAllProvinces": True},
    {"code": "IE", "includeAllProvinces": True},
    {"code": "IT", "includeAllProvinces": True},
    {"code": "LV", "includeAllProvinces": True},
    {"code": "LT", "includeAllProvinces": True},
    {"code": "LU", "includeAllProvinces": True},
    {"code": "MT", "includeAllProvinces": True},
    {"code": "NL", "includeAllProvinces": True},
    {"code": "PL", "includeAllProvinces": True},
    {"code": "PT", "includeAllProvinces": True},
    {"code": "RO", "includeAllProvinces": True},
    {"code": "SK", "includeAllProvinces": True},
    {"code": "SI", "includeAllProvinces": True},
    {"code": "ES", "includeAllProvinces": True},
    {"code": "SE", "includeAllProvinces": True},
    {"code": "NO", "includeAllProvinces": True},
    {"code": "CH", "includeAllProvinces": True},
    {"code": "IS", "includeAllProvinces": True}
]


def build_profile_input(profile_name: str, rates: dict, location_gid: str) -> dict:
    """Build the GraphQL input for creating a delivery profile."""

    zones = []

    # UK Zone - must include provinces
    if rates.get("uk"):
        zones.append({
            "name": f"{profile_name} - UK",
            "countries": [{
                "code": "GB",
                "includeAllProvinces": True
            }],
            "methodDefinitionsToCreate": [{
                "name": "Standard Shipping",
                "rateDefinition": {
                    "price": {
                        "amount": rates["uk"],
                        "currencyCode": "GBP"
                    }
                }
            }]
        })

    # Europe Zone
    if rates.get("europe"):
        zones.append({
            "name": f"{profile_name} - Europe",
            "countries": EUROPE_COUNTRIES,
            "methodDefinitionsToCreate": [{
                "name": "Standard Shipping",
                "rateDefinition": {
                    "price": {
                        "amount": rates["europe"],
                        "currencyCode": "GBP"
                    }
                }
            }]
        })

    # USA Zone - must include all states
    if rates.get("usa"):
        zones.append({
            "name": f"{profile_name} - USA",
            "countries": [{"code": "US", "includeAllProvinces": True}],
            "methodDefinitionsToCreate": [{
                "name": "Standard Shipping",
                "rateDefinition": {
                    "price": {
                        "amount": rates["usa"],
                        "currencyCode": "GBP"
                    }
                }
            }]
        })

    # Rest of World Zone - major countries not covered above
    # Apply includeAllProvinces to all countries to avoid province errors
    if rates.get("row"):
        row_countries = [
            {"code": "AU", "includeAllProvinces": True},
            {"code": "NZ", "includeAllProvinces": True},
            {"code": "CA", "includeAllProvinces": True},
            {"code": "JP", "includeAllProvinces": True},
            {"code": "KR", "includeAllProvinces": True},
            {"code": "SG", "includeAllProvinces": True},
            {"code": "HK", "includeAllProvinces": True},
            {"code": "TW", "includeAllProvinces": True},
            {"code": "BR", "includeAllProvinces": True},
            {"code": "MX", "includeAllProvinces": True},
            {"code": "AR", "includeAllProvinces": True},
            {"code": "CL", "includeAllProvinces": True},
            {"code": "ZA", "includeAllProvinces": True},
            {"code": "AE", "includeAllProvinces": True},
            {"code": "IL", "includeAllProvinces": True},
            {"code": "IN", "includeAllProvinces": True},
            {"code": "TH", "includeAllProvinces": True},
            {"code": "MY", "includeAllProvinces": True},
            {"code": "PH", "includeAllProvinces": True},
            {"code": "ID", "includeAllProvinces": True},
        ]
        zones.append({
            "name": f"{profile_name} - Rest of World",
            "countries": row_countries,
            "methodDefinitionsToCreate": [{
                "name": "Standard Shipping",
                "rateDefinition": {
                    "price": {
                        "amount": rates["row"],
                        "currencyCode": "GBP"
                    }
                }
            }]
        })

    return {
        "name": profile_name,
        "locationGroupsToCreate": [{
            "locationsToAdd": [location_gid],
            "zonesToCreate": zones
        }]
    }


async def get_profiles_to_create(session, args) -> list:
    """Get shipping profiles to create based on command line scope."""

    if args.name:
        # Single profile by name
        result = await session.execute(text("""
            SELECT id, name, rates, shopify_profile_id
            FROM shipping_profiles
            WHERE name = :name
        """), {"name": args.name})

    elif args.missing:
        # All profiles without Shopify GID
        result = await session.execute(text("""
            SELECT id, name, rates, shopify_profile_id
            FROM shipping_profiles
            WHERE shopify_profile_id IS NULL
              AND rates IS NOT NULL
            ORDER BY name
        """))

    elif args.all:
        # All profiles with rates
        result = await session.execute(text("""
            SELECT id, name, rates, shopify_profile_id
            FROM shipping_profiles
            WHERE rates IS NOT NULL
            ORDER BY name
        """))

    else:
        print("Error: Must specify one of --name, --missing, or --all")
        return []

    rows = result.fetchall()
    return [
        {
            "id": row[0],
            "name": row[1],
            "rates": row[2],
            "shopify_profile_id": row[3]
        }
        for row in rows
    ]


def create_shopify_profile(profile_input: dict, settings, dry_run: bool = False) -> dict:
    """Execute the GraphQL mutation to create a delivery profile."""

    if dry_run:
        return {"success": True, "dry_run": True, "profile_id": "(dry-run)"}

    response = requests.post(
        f"https://{settings.SHOPIFY_SHOP_URL}/admin/api/2025-01/graphql.json",
        json={"query": DELIVERY_PROFILE_CREATE_MUTATION, "variables": {"profile": profile_input}},
        headers={
            "X-Shopify-Access-Token": settings.SHOPIFY_ADMIN_API_ACCESS_TOKEN,
            "Content-Type": "application/json"
        }
    )

    result = response.json()

    if "errors" in result:
        return {"success": False, "errors": result["errors"]}

    user_errors = result.get("data", {}).get("deliveryProfileCreate", {}).get("userErrors", [])
    if user_errors:
        return {"success": False, "errors": user_errors}

    profile = result.get("data", {}).get("deliveryProfileCreate", {}).get("profile", {})
    return {"success": True, "profile_id": profile.get("id"), "profile_name": profile.get("name")}


async def main():
    parser = argparse.ArgumentParser(
        description="Create Shopify shipping profiles from local database",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    # Scope options (mutually exclusive)
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--name", type=str, help="Create single profile by name")
    scope.add_argument("--missing", action="store_true", help="Create all profiles without Shopify GID")
    scope.add_argument("--all", action="store_true", help="Recreate all profiles")

    # Control options
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without executing")
    parser.add_argument("--verbose", action="store_true", help="Show detailed progress")

    args = parser.parse_args()

    settings = get_settings()
    location_gid = settings.SHOPIFY_LOCATION_GID

    if not location_gid:
        print("Error: SHOPIFY_LOCATION_GID not set in environment")
        return

    # Ensure location_gid is in full GID format
    if not location_gid.startswith("gid://"):
        location_gid = f"gid://shopify/Location/{location_gid}"

    async with async_session() as session:
        # Get profiles to create
        profiles = await get_profiles_to_create(session, args)

        if not profiles:
            print("No profiles found matching criteria")
            return

        print(f"Found {len(profiles)} profile(s) to create\n")

        created = 0
        skipped = 0
        errors = 0

        for profile in profiles:
            name = profile["name"]
            rates = profile["rates"]
            existing_gid = profile["shopify_profile_id"]

            # Skip if already has Shopify GID (unless --all)
            if existing_gid and not args.all:
                print(f"  Skip: {name} (already has Shopify GID)")
                skipped += 1
                continue

            if args.verbose:
                print(f"Processing: {name}")
                print(f"  Rates: UK=£{rates.get('uk', 0)}, EU=£{rates.get('europe', 0)}, USA=£{rates.get('usa', 0)}, ROW=£{rates.get('row', 0)}")

            # Build profile input
            profile_input = build_profile_input(name, rates, location_gid)

            if args.dry_run:
                print(f"  [DRY RUN] Would create: {name}")
                print(f"    Zones: UK (£{rates.get('uk', 0)}), Europe (£{rates.get('europe', 0)}), USA (£{rates.get('usa', 0)}), ROW (£{rates.get('row', 0)})")
                created += 1
            else:
                result = create_shopify_profile(profile_input, settings)

                if result["success"]:
                    shopify_gid = result["profile_id"]
                    print(f"  ✓ Created: {name}")
                    print(f"    Shopify GID: {shopify_gid}")

                    # Update database with new Shopify GID
                    await session.execute(
                        text("""
                            UPDATE shipping_profiles
                            SET shopify_profile_id = :shopify_gid
                            WHERE id = :profile_id
                        """),
                        {"shopify_gid": shopify_gid, "profile_id": profile["id"]}
                    )
                    await session.commit()
                    print(f"    ✓ Database updated")
                    created += 1
                else:
                    print(f"  ✗ Failed: {name}")
                    print(f"    Error: {result['errors']}")
                    errors += 1

        # Summary
        print("\n" + "=" * 50)
        print("SUMMARY")
        print("=" * 50)
        print(f"Created:  {created}")
        print(f"Skipped:  {skipped}")
        print(f"Errors:   {errors}")

        if args.dry_run:
            print("\n[DRY RUN - No changes made]")


if __name__ == "__main__":
    asyncio.run(main())
