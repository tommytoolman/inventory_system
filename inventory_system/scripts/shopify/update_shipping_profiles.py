#!/usr/bin/env python3
"""
Shopify Shipping Profile Update Script
=======================================

Updates Shopify products to use the correct shipping profile based on their
category. Uses the Shopify GraphQL Admin API to assign product variants to
delivery profiles.

IMPORTANT: Shopify assigns shipping profiles at the VARIANT level, not product
level. Each API call can handle max 250 variants. For categories with more
products, the script automatically batches into multiple API calls to the
same profile.

Example: 520 Electric Guitars → 3 API calls (250 + 250 + 20 variants),
all assigned to the same "Electric Guitars" shipping profile.


SCOPE OPTIONS (pick one):
-------------------------
  --shopify-id <id>      Update single product by Shopify legacy ID
  --sku <sku>            Update single product by SKU
  --category <category>  Update all products in a Reverb category
  --reverb-profile <id>  Update all products with a specific Reverb shipping profile ID
  --unmapped             Update all products currently missing a shipping profile
  --all                  Update ALL products that have a mapped shipping profile

CONTROL OPTIONS:
----------------
  --dry-run              Show what would be updated, don't execute
  --limit <n>            Limit to first N products (for testing)
  --batch-size <n>       Variants per API call (default: 250, max: 250)
  --force                Skip category check, use default profile

OUTPUT OPTIONS:
---------------
  --verbose              Show detailed progress
  --output <file>        Write results to JSON file


EXAMPLES:
---------

# Test with single product (dry run)
python scripts/shopify/update_shipping_profiles.py --sku RIFF-12345 --dry-run

# Update one product by Shopify ID
python scripts/shopify/update_shipping_profiles.py --shopify-id 8234567890123

# Preview all Electric Guitars that would be updated
python scripts/shopify/update_shipping_profiles.py --category "Electric Guitars" --dry-run

# Update all Electric Guitars for real
python scripts/shopify/update_shipping_profiles.py --category "Electric Guitars" --verbose

# Test batch mode with limit
python scripts/shopify/update_shipping_profiles.py --all --limit 10 --dry-run

# Full batch run - update everything
python scripts/shopify/update_shipping_profiles.py --all --verbose

# Find products without shipping profiles assigned
python scripts/shopify/update_shipping_profiles.py --unmapped --dry-run

# Update all products with Reverb "Effects Pedals" profile (15654) to Shopify
python scripts/shopify/update_shipping_profiles.py --reverb-profile 15654 --dry-run


PRE-REQUISITES:
---------------
1. shipping_profiles table must have category → Shopify profile GID mappings
2. Products must have category set in products table
3. Products must have Shopify variant IDs in shopify_listings table
4. SHOPIFY_ADMIN_API_ACCESS_TOKEN must be set in environment


FLOW:
-----
1. Parse args → determine scope (single product or batch)
2. Query products based on scope
3. For each product:
   - Get category from products table
   - Look up shipping_profiles for category → profile GID
   - If no profile mapped, skip with warning
   - Get Shopify variant ID(s) from shopify_listings
4. Group variants by shipping profile
5. Batch into chunks of 250 variants per profile
6. Execute GraphQL mutations (unless --dry-run)
7. Report: X updated, Y skipped (no profile), Z errors
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sqlalchemy import text
from app.database import async_session
from app.core.config import get_settings


# Shopify GraphQL mutation for assigning variants to a delivery profile
DELIVERY_PROFILE_UPDATE_MUTATION = """
mutation deliveryProfileUpdate($id: ID!, $profile: DeliveryProfileInput!) {
  deliveryProfileUpdate(id: $id, profile: $profile) {
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

MAX_VARIANTS_PER_BATCH = 250


def chunks(lst: list, n: int):
    """Yield successive n-sized chunks from lst."""
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


async def get_shipping_profile_for_category(session, category: str) -> dict | None:
    """Look up the Shopify shipping profile GID for a given category.

    Matches by checking if the product category starts with the profile name.
    E.g., "Electric Guitars / Solid Body" matches profile "Electric Guitars"
    """
    if not category:
        return None

    # Get all profiles with Shopify GIDs, ordered by name length (longest first for best match)
    result = await session.execute(text("""
        SELECT id, name, shopify_profile_id
        FROM shipping_profiles
        WHERE shopify_profile_id IS NOT NULL
        ORDER BY LENGTH(name) DESC
    """))

    for row in result.fetchall():
        profile_id, profile_name, shopify_gid = row
        # Check if category starts with profile name (case-insensitive)
        if category.lower().startswith(profile_name.lower()):
            return {
                "id": profile_id,
                "name": profile_name,
                "shopify_profile_gid": shopify_gid
            }

    return None


async def get_shipping_profile_by_reverb_id(session, reverb_profile_id: str) -> dict | None:
    """Look up the Shopify shipping profile GID by Reverb profile ID."""
    result = await session.execute(text("""
        SELECT id, name, shopify_profile_id
        FROM shipping_profiles
        WHERE reverb_profile_id = :reverb_id
          AND shopify_profile_id IS NOT NULL
    """), {"reverb_id": reverb_profile_id})

    row = result.fetchone()
    if row:
        return {
            "id": row[0],
            "name": row[1],
            "shopify_profile_gid": row[2]
        }
    return None


async def fetch_variant_gids_from_shopify(product_gid: str, settings) -> list:
    """Fetch variant GIDs from Shopify API for a product."""
    import requests

    query = """
    query getProductVariants($id: ID!) {
      product(id: $id) {
        variants(first: 100) {
          nodes {
            id
          }
        }
      }
    }
    """

    response = requests.post(
        f"https://{settings.SHOPIFY_SHOP_URL}/admin/api/2025-01/graphql.json",
        json={"query": query, "variables": {"id": product_gid}},
        headers={
            "X-Shopify-Access-Token": settings.SHOPIFY_ADMIN_API_ACCESS_TOKEN,
            "Content-Type": "application/json"
        }
    )

    result = response.json()

    if "errors" in result:
        print(f"  Error fetching variants for {product_gid}: {result['errors']}")
        return []

    product = result.get("data", {}).get("product")
    if not product:
        return []

    variants = product.get("variants", {}).get("nodes", [])
    return [v["id"] for v in variants if v.get("id")]


async def get_products_by_scope(session, args) -> list:
    """Get products to update based on command line scope.

    Returns products with their Shopify product GID. Variant GIDs will be
    fetched from Shopify API separately since they're not stored locally.
    """

    if args.shopify_id:
        # Single product by Shopify ID (always process, even if already assigned)
        result = await session.execute(text("""
            SELECT p.id, p.sku, p.category, sl.shopify_product_id, sl.id, sl.shipping_profile_id
            FROM products p
            JOIN platform_common pc ON p.id = pc.product_id AND pc.platform_name = 'shopify'
            JOIN shopify_listings sl ON pc.id = sl.platform_id
            WHERE sl.shopify_legacy_id = :shopify_id
               OR sl.shopify_product_id = :shopify_gid
        """), {"shopify_id": str(args.shopify_id), "shopify_gid": f"gid://shopify/Product/{args.shopify_id}"})

    elif args.sku:
        # Single product by SKU (always process, even if already assigned)
        result = await session.execute(text("""
            SELECT p.id, p.sku, p.category, sl.shopify_product_id, sl.id, sl.shipping_profile_id
            FROM products p
            JOIN platform_common pc ON p.id = pc.product_id AND pc.platform_name = 'shopify'
            JOIN shopify_listings sl ON pc.id = sl.platform_id
            WHERE p.sku = :sku
        """), {"sku": args.sku})

    elif args.category:
        # All products in a category (skip already-assigned unless --force)
        query = """
            SELECT p.id, p.sku, p.category, sl.shopify_product_id, sl.id, sl.shipping_profile_id
            FROM products p
            JOIN platform_common pc ON p.id = pc.product_id AND pc.platform_name = 'shopify'
            JOIN shopify_listings sl ON pc.id = sl.platform_id
            WHERE p.category ILIKE :category || '%'
        """
        if not args.force:
            query += " AND sl.shipping_profile_id IS NULL"
        if not args.include_inactive:
            query += " AND sl.status = 'active'"
        query += " ORDER BY p.id"
        if args.limit:
            query += f" LIMIT {args.limit}"
        result = await session.execute(text(query), {"category": args.category})

    elif args.reverb_profile:
        # All products with a specific Reverb shipping profile (live only)
        # These products must also have a Shopify listing
        query = """
            SELECT DISTINCT p.id, p.sku, p.category, sl.shopify_product_id, sl.id, sl.shipping_profile_id
            FROM products p
            JOIN platform_common pc_reverb ON p.id = pc_reverb.product_id AND pc_reverb.platform_name = 'reverb'
            JOIN reverb_listings rl ON pc_reverb.id = rl.platform_id
            JOIN platform_common pc_shopify ON p.id = pc_shopify.product_id AND pc_shopify.platform_name = 'shopify'
            JOIN shopify_listings sl ON pc_shopify.id = sl.platform_id
            WHERE rl.shipping_profile_id = :reverb_profile_id
              AND rl.reverb_state = 'live'
        """
        if not args.force:
            query += " AND sl.shipping_profile_id IS NULL"
        if not args.include_inactive:
            query += " AND sl.status = 'active'"
        query += " ORDER BY p.id"
        if args.limit:
            query += f" LIMIT {args.limit}"
        result = await session.execute(text(query), {"reverb_profile_id": args.reverb_profile})

    elif args.unmapped:
        # Products without shipping profile assigned
        query = """
            SELECT p.id, p.sku, p.category, sl.shopify_product_id, sl.id, sl.shipping_profile_id
            FROM products p
            JOIN platform_common pc ON p.id = pc.product_id AND pc.platform_name = 'shopify'
            JOIN shopify_listings sl ON pc.id = sl.platform_id
            WHERE p.category IS NOT NULL
              AND sl.shipping_profile_id IS NULL
        """
        if not args.include_inactive:
            query += " AND sl.status = 'active'"
        query += " ORDER BY p.id"
        if args.limit:
            query += f" LIMIT {args.limit}"
        result = await session.execute(text(query))

    elif args.all:
        # All products with Shopify listings (skip already-assigned unless --force)
        query = """
            SELECT p.id, p.sku, p.category, sl.shopify_product_id, sl.id, sl.shipping_profile_id
            FROM products p
            JOIN platform_common pc ON p.id = pc.product_id AND pc.platform_name = 'shopify'
            JOIN shopify_listings sl ON pc.id = sl.platform_id
            WHERE p.category IS NOT NULL
        """
        if not args.force:
            query += " AND sl.shipping_profile_id IS NULL"
        if not args.include_inactive:
            query += " AND sl.status = 'active'"
        query += " ORDER BY p.id"
        if args.limit:
            query += f" LIMIT {args.limit}"
        result = await session.execute(text(query))

    else:
        print("Error: Must specify one of --shopify-id, --sku, --category, --unmapped, or --all")
        return []

    rows = result.fetchall()
    return [
        {
            "product_id": row[0],
            "sku": row[1],
            "category": row[2],
            "shopify_product_gid": row[3],
            "shopify_listing_id": row[4],
            "current_shipping_profile_id": row[5]
        }
        for row in rows
    ]


async def execute_profile_update(profile_gid: str, variant_gids: list, settings, dry_run: bool = False) -> dict:
    """Execute the GraphQL mutation to assign variants to a shipping profile."""
    import requests

    if dry_run:
        return {"success": True, "dry_run": True, "variant_count": len(variant_gids)}

    variables = {
        "id": profile_gid,
        "profile": {
            "variantsToAssociate": variant_gids
        }
    }

    response = requests.post(
        f"https://{settings.SHOPIFY_SHOP_URL}/admin/api/2025-01/graphql.json",
        json={"query": DELIVERY_PROFILE_UPDATE_MUTATION, "variables": variables},
        headers={
            "X-Shopify-Access-Token": settings.SHOPIFY_ADMIN_API_ACCESS_TOKEN,
            "Content-Type": "application/json"
        }
    )

    result = response.json()

    if "errors" in result:
        return {"success": False, "errors": result["errors"]}

    user_errors = result.get("data", {}).get("deliveryProfileUpdate", {}).get("userErrors", [])
    if user_errors:
        return {"success": False, "errors": user_errors}

    return {"success": True, "variant_count": len(variant_gids)}


async def main():
    parser = argparse.ArgumentParser(
        description="Update Shopify shipping profiles for products",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    # Scope options (mutually exclusive)
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--shopify-id", type=str, help="Update single product by Shopify legacy ID")
    scope.add_argument("--sku", type=str, help="Update single product by SKU")
    scope.add_argument("--category", type=str, help="Update all products in a category")
    scope.add_argument("--reverb-profile", type=str, help="Update all products with a Reverb shipping profile ID")
    scope.add_argument("--unmapped", action="store_true", help="Update products without shipping profile")
    scope.add_argument("--all", action="store_true", help="Update all products")

    # Control options
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without executing")
    parser.add_argument("--limit", type=int, help="Limit number of products to process")
    parser.add_argument("--batch-size", type=int, default=250, help="Variants per API call (max 250)")
    parser.add_argument("--force", action="store_true", help="Reassign even if already has a profile")
    parser.add_argument("--include-inactive", action="store_true", help="Include ended/archived products (default: active only)")

    # Output options
    parser.add_argument("--verbose", action="store_true", help="Show detailed progress")
    parser.add_argument("--output", type=str, help="Write results to JSON file")

    args = parser.parse_args()

    # Validate batch size
    if args.batch_size > MAX_VARIANTS_PER_BATCH:
        print(f"Warning: batch-size capped at {MAX_VARIANTS_PER_BATCH}")
        args.batch_size = MAX_VARIANTS_PER_BATCH

    settings = get_settings()

    async with async_session() as session:
        # Get products to update
        products = await get_products_by_scope(session, args)

        if not products:
            print("No products found matching criteria")
            return

        print(f"Found {len(products)} product(s) to process")

        # If using --reverb-profile, look up the Shopify profile once
        reverb_profile_mapping = None
        if args.reverb_profile:
            reverb_profile_mapping = await get_shipping_profile_by_reverb_id(session, args.reverb_profile)
            if not reverb_profile_mapping:
                print(f"Error: No Shopify profile mapped for Reverb profile {args.reverb_profile}")
                print("Run create_shipping_profiles.py first to create the Shopify profile")
                return
            print(f"Using Shopify profile: {reverb_profile_mapping['name']} ({reverb_profile_mapping['shopify_profile_gid']})")

        # Group products by shipping profile
        profile_variants = {}  # profile_gid -> {profile_name, variants, shopify_listing_ids}
        skipped_no_profile = []
        skipped_no_variant = []
        skipped_already_assigned = []

        print("\nFetching variant GIDs from Shopify API...")

        for i, product in enumerate(products):
            if args.verbose:
                print(f"  [{i+1}/{len(products)}] Processing {product['sku']}...")

            # Check if already assigned (for single-item modes that bypass query filter)
            if product["current_shipping_profile_id"] and not args.force:
                if args.shopify_id or args.sku:
                    skipped_already_assigned.append(product)
                    if args.verbose:
                        print(f"    Skip: Already assigned to {product['current_shipping_profile_id']}")
                    continue

            # Get shipping profile - use reverb mapping if specified, otherwise look up by category
            if reverb_profile_mapping:
                profile = reverb_profile_mapping
            else:
                profile = await get_shipping_profile_for_category(session, product["category"])

            if not profile:
                skipped_no_profile.append(product)
                if args.verbose:
                    print(f"    Skip: No shipping profile for '{product['category']}'")
                continue

            # Fetch variant GIDs from Shopify API
            if not product["shopify_product_gid"]:
                skipped_no_variant.append(product)
                if args.verbose:
                    print(f"    Skip: No Shopify product GID")
                continue

            variant_gids = await fetch_variant_gids_from_shopify(product["shopify_product_gid"], settings)

            if not variant_gids:
                skipped_no_variant.append(product)
                if args.verbose:
                    print(f"    Skip: Could not fetch variants from Shopify")
                continue

            # Add to profile group
            profile_gid = profile["shopify_profile_gid"]
            if profile_gid not in profile_variants:
                profile_variants[profile_gid] = {
                    "profile_name": profile["name"],
                    "variants": [],
                    "shopify_listing_ids": []
                }
            profile_variants[profile_gid]["variants"].extend(variant_gids)
            profile_variants[profile_gid]["shopify_listing_ids"].append(product["shopify_listing_id"])

            if args.verbose:
                print(f"    -> {profile['name']} ({len(variant_gids)} variant(s))")

        # Execute updates
        total_updated = 0
        total_errors = 0
        total_db_updated = 0

        for profile_gid, data in profile_variants.items():
            variants = data["variants"]
            profile_name = data["profile_name"]
            listing_ids = data["shopify_listing_ids"]

            print(f"\nProfile: {profile_name} ({len(variants)} variants, {len(listing_ids)} products)")

            # Batch into chunks
            for i, batch in enumerate(chunks(variants, args.batch_size)):
                batch_num = i + 1
                total_batches = (len(variants) + args.batch_size - 1) // args.batch_size

                if args.dry_run:
                    print(f"  [DRY RUN] Batch {batch_num}/{total_batches}: Would assign {len(batch)} variants")
                    total_updated += len(batch)
                else:
                    print(f"  Batch {batch_num}/{total_batches}: Assigning {len(batch)} variants...")
                    result = await execute_profile_update(profile_gid, batch, settings, args.dry_run)

                    if result["success"]:
                        total_updated += len(batch)
                        print(f"    ✓ Success")
                    else:
                        total_errors += len(batch)
                        print(f"    ✗ Error: {result['errors']}")

            # After all batches succeed for this profile, update the database
            if not args.dry_run and listing_ids:
                try:
                    await session.execute(
                        text("""
                            UPDATE shopify_listings
                            SET shipping_profile_id = :profile_gid
                            WHERE id = ANY(:listing_ids)
                        """),
                        {"profile_gid": profile_gid, "listing_ids": listing_ids}
                    )
                    await session.commit()
                    total_db_updated += len(listing_ids)
                    print(f"  ✓ Updated {len(listing_ids)} shopify_listings records")
                except Exception as e:
                    print(f"  ✗ Failed to update database: {e}")

        # Summary
        print("\n" + "=" * 50)
        print("SUMMARY")
        print("=" * 50)
        print(f"Variants assigned:      {total_updated}")
        print(f"DB records updated:     {total_db_updated}")
        print(f"Skipped (no profile):   {len(skipped_no_profile)}")
        print(f"Skipped (no variant):   {len(skipped_no_variant)}")
        print(f"Skipped (already done): {len(skipped_already_assigned)}")
        print(f"Errors:                 {total_errors}")

        if args.dry_run:
            print("\n[DRY RUN - No changes made]")

        # Write output file if requested
        if args.output:
            output_data = {
                "variants_assigned": total_updated,
                "db_records_updated": total_db_updated,
                "skipped_no_profile": [p["sku"] for p in skipped_no_profile],
                "skipped_no_variant": [p["sku"] for p in skipped_no_variant],
                "skipped_already_assigned": [p["sku"] for p in skipped_already_assigned],
                "errors": total_errors,
                "dry_run": args.dry_run
            }
            with open(args.output, "w") as f:
                json.dump(output_data, f, indent=2)
            print(f"\nResults written to: {args.output}")


if __name__ == "__main__":
    asyncio.run(main())
