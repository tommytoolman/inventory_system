#!/usr/bin/env python3
"""
Set Shopify metafields for artist-owned products.

Default behavior:
- Fetch products where products.artist_owned is true and that have a Shopify platform_common entry.
- For each, set metafields on the Shopify product:
    custom.artist_owned (boolean) = true
    custom.artist_names (single_line_text_field) = comma-separated list from products.artist_names

Options:
    --ids 123,456    Comma-separated product IDs (local DB IDs) to limit scope
    --dry-run        Show what would be sent without calling Shopify
"""

import argparse
import asyncio
from typing import List, Optional

from sqlalchemy import text

from app.database import get_session
from app.services.shopify.client import ShopifyGraphQLClient


DEFAULT_NAMESPACE = "custom"
ALT_NAMESPACE = "guitar_specs"
ARTIST_OWNED_KEY = "artist_owned"
ARTIST_NAMES_KEY = "artist_names"


def comma_join(values: Optional[List[str]]) -> str:
    if not values:
        return ""
    return ", ".join([v for v in values if v])


async def fetch_artist_owned_products(filter_ids: Optional[List[int]] = None):
    query = """
    SELECT p.id AS product_id,
           p.artist_owned,
           p.artist_names,
           pc.external_id AS shopify_legacy_id
    FROM products p
    JOIN platform_common pc
      ON pc.product_id = p.id AND pc.platform_name = 'shopify'
    WHERE p.artist_owned = true
      {id_filter}
    ORDER BY p.id ASC
    """
    id_clause = ""
    params = {}
    if filter_ids:
        id_clause = "AND p.id = ANY(:ids)"
        params["ids"] = filter_ids
    query = query.format(id_filter=id_clause)

    async with get_session() as session:
        result = await session.execute(text(query), params)
        rows = result.fetchall()
        return rows


def build_metafields(product_gid: str, artist_owned: bool, artist_names: List[str]):
    metafields = [
        {
            "ownerId": product_gid,
            "namespace": DEFAULT_NAMESPACE,
            "key": ARTIST_OWNED_KEY,
            "type": "boolean",
            "value": "true" if artist_owned else "false",
        },
        {
            "ownerId": product_gid,
            "namespace": DEFAULT_NAMESPACE,
            "key": ARTIST_NAMES_KEY,
            # Definition in Shopify is multi_line_text_field
            "type": "multi_line_text_field",
            "value": comma_join(artist_names),
        },
    ]
    # Also set the legacy/UI namespace used by the Shopify UI: guitar_specs.artist_owned
    metafields.append(
        {
            "ownerId": product_gid,
            "namespace": ALT_NAMESPACE,
            "key": ARTIST_OWNED_KEY,
            "type": "boolean",
            "value": "true" if artist_owned else "false",
        }
    )
    return metafields


async def main():
    parser = argparse.ArgumentParser(
        description="Set Shopify artist-owned metafields from local DB."
    )
    parser.add_argument(
        "--ids",
        help="Comma-separated local product IDs to limit (optional).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show intended changes without calling Shopify.",
    )
    args = parser.parse_args()

    filter_ids = None
    if args.ids:
        filter_ids = [int(x.strip()) for x in args.ids.split(",") if x.strip().isdigit()]

    rows = await fetch_artist_owned_products(filter_ids)
    if not rows:
        print("No artist-owned Shopify products found with the given criteria.")
        return

    client = ShopifyGraphQLClient()

    for row in rows:
        product_id = row.product_id
        shopify_legacy_id = row.shopify_legacy_id
        artist_names = row.artist_names or []
        product_gid = f"gid://shopify/Product/{shopify_legacy_id}"

        print(f"\n=== Product {product_id} (Shopify {shopify_legacy_id}) ===")
        print(f"Artist owned: {row.artist_owned}")
        print(f"Artist names: {artist_names}")

        metafields = build_metafields(product_gid, bool(row.artist_owned), artist_names)
        if args.dry_run:
            print("DRY RUN: would set metafields:")
            for mf in metafields:
                print(f"  - {mf['namespace']}.{mf['key']} ({mf['type']}): {mf['value']}")
            continue

        result = client.set_metafields(metafields)
        errors = (result or {}).get("userErrors") or []
        if errors:
            print(f"⚠️ Shopify userErrors: {errors}")
        else:
            print("✅ Metafields set")


if __name__ == "__main__":
    asyncio.run(main())
