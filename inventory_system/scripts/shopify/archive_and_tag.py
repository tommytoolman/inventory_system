#!/usr/bin/env python3
"""
Archive a Shopify product by legacy ID, add standard archive tags, and zero inventory.

Usage:
    python scripts/shopify/archive_and_tag.py <legacy_product_id> [more_ids...] [--tags "Archived,Sold Archive"]
"""

import argparse
import sys
from typing import List

from app.services.shopify.client import ShopifyGraphQLClient
from app.core.config import get_settings


ARCHIVE_TAGS = ["Archived", "Sold Archive", "Gallery", "World's Finest"]


def unique_merge(existing: List[str], extra: List[str]) -> List[str]:
    """Merge tags keeping order of existing tags and appending missing extras."""
    seen = set()
    merged: List[str] = []
    for tag in existing:
        if tag not in seen:
            merged.append(tag)
            seen.add(tag)
    for tag in extra:
        if tag not in seen:
            merged.append(tag)
            seen.add(tag)
    return merged


def archive_product(legacy_product_id: str, tags_to_apply: List[str]) -> bool:
    settings = get_settings()
    client = ShopifyGraphQLClient()

    product_gid = f"gid://shopify/Product/{legacy_product_id}"
    print(f"🔗 Shopify product GID: {product_gid}")

    product_data = client.get_product_snapshot_by_id(product_gid, num_variants=1)
    if not product_data:
        print("❌ Could not load product snapshot.")
        return False

    product_node = product_data.get("product") if "product" in product_data else product_data
    if not product_node:
        print("❌ Product node missing in snapshot response.")
        return False

    existing_tags = product_node.get("tags") or []
    merged_tags = unique_merge(existing_tags, tags_to_apply)
    print(f"📝 Existing tags: {existing_tags}")
    print(f"➕ Merged tags:   {merged_tags}")

    # Update product status and tags
    client.update_product({
        "id": product_gid,
        "status": "ARCHIVED",
        "tags": merged_tags,
    })
    print("✅ Product status set to ARCHIVED and tags updated")

    # Update first variant inventory to 0
    variants = (product_node.get("variants") or {}).get("edges") or []
    if not variants:
        print("⚠️ No variants found; skipping inventory update.")
        return True

    variant_gid = variants[0]["node"]["id"]
    location_gid = settings.SHOPIFY_LOCATION_GID or "gid://shopify/Location/109766639956"
    client.update_variant_rest(
        variant_gid,
        {
            "inventoryQuantities": [
                {
                    "availableQuantity": 0,
                    "locationId": location_gid,
                }
            ],
            "inventoryItem": {"tracked": True},
            "inventoryPolicy": "DENY",
        },
    )
    print(f"✅ Inventory set to 0 for variant {variant_gid} at location {location_gid}")
    return True


def parse_args():
    parser = argparse.ArgumentParser(
        description="Archive Shopify products by legacy ID, add tags, and zero inventory."
    )
    parser.add_argument(
        "ids",
        nargs="+",
        help="Legacy Shopify product IDs (numeric).",
    )
    parser.add_argument(
        "--tags",
        help="Comma-separated list of tags to add (default: Archived,Sold Archive,Gallery,World's Finest).",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    tags_to_apply = (
        [tag.strip() for tag in args.tags.split(",") if tag.strip()]
        if args.tags
        else ARCHIVE_TAGS
    )

    ids = args.ids
    overall_success = True
    for legacy_id in ids:
        print(f"\n=== Processing {legacy_id} ===")
        success = archive_product(legacy_id, tags_to_apply)
        overall_success = overall_success and success

    if overall_success:
        print("\n🎉 Done.")
    else:
        print("\n⚠️ Completed with errors.")


if __name__ == "__main__":
    main()
