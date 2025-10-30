#!/usr/bin/env python3
"""Inspect Shopify listing metadata by legacy ID.

Usage examples:

* Show category assignment only::

      python scripts/shopify/show_shopify_listing.py 12193911374164

* Display the full record (price, status, timestamps, etc.)::

      python scripts/shopify/show_shopify_listing.py 12193911374164 --show-all

* Fetch live category info from Shopify (admin API)::

      python scripts/shopify/show_shopify_listing.py 12193911374164 --live-category

You can pass multiple legacy IDs to inspect several records in one run.
"""

import argparse
import asyncio
from typing import Iterable, Optional

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import async_session
from app.models.platform_common import PlatformCommon
from app.models.product import Product
from app.models.shopify import ShopifyListing
from app.services.shopify.client import ShopifyGraphQLClient

CATEGORY_FIELDS = (
    "category_gid",
    "category_name",
    "category_full_name",
    "category_assignment_status",
    "category_assigned_at",
)

SHOPIFY_CLIENT: Optional[ShopifyGraphQLClient] = None


def get_shopify_client() -> ShopifyGraphQLClient:
    global SHOPIFY_CLIENT
    if SHOPIFY_CLIENT is None:
        SHOPIFY_CLIENT = ShopifyGraphQLClient()
    return SHOPIFY_CLIENT


async def fetch_listing(legacy_id: str) -> ShopifyListing | None:
    async with async_session() as session:
        stmt = (
            select(ShopifyListing)
            .options(
                selectinload(ShopifyListing.platform_listing)
                .selectinload(PlatformCommon.product)
            )
            .where(ShopifyListing.shopify_legacy_id == legacy_id)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()


def format_value(value) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        return ", ".join(str(item) for item in value)
    return str(value)


def resolve_product_gid(listing: ShopifyListing) -> Optional[str]:
    if listing.shopify_product_id:
        return listing.shopify_product_id
    if listing.shopify_legacy_id:
        return f"gid://shopify/Product/{listing.shopify_legacy_id}"
    return None


def fetch_live_category(product_gid: str) -> Optional[dict]:
    try:
        snapshot = get_shopify_client().get_product_snapshot_by_id(
            product_gid,
            num_variants=1,
            num_images=1,
            num_metafields=0,
        )
    except Exception as exc:  # pragma: no cover - network/api failure path
        print(f"⚠️  Failed to fetch live category from Shopify for {product_gid}: {exc}")
        return None

    if not snapshot:
        print(f"⚠️  Shopify returned no data for {product_gid}")
        return None

    return {
        "category": snapshot.get("category"),
        "productCategory": (snapshot.get("productCategory") or {}).get("productTaxonomyNode"),
        "productType": snapshot.get("productType"),
        "status": snapshot.get("status"),
    }


def print_listing(listing: ShopifyListing, *, show_all: bool, live_category: bool) -> None:
    product = listing.platform_listing.product if listing.platform_listing else None

    print("=" * 80)
    print(f"Shopify legacy ID : {listing.shopify_legacy_id}")
    print(f"Shopify product GID: {format_value(listing.shopify_product_id)}")
    if product:
        print(f"Product ID        : {product.id}")
        print(f"SKU               : {format_value(product.sku)}")
        print(f"Title             : {format_value(product.title or product.generate_title())}")
    print("-" * 80)

    print("Category assignment")
    for field in CATEGORY_FIELDS:
        print(f"  {field}: {format_value(getattr(listing, field, None))}")

    if live_category:
        product_gid = resolve_product_gid(listing)
        if product_gid:
            live = fetch_live_category(product_gid)
            if live:
                print("\nLive data from Shopify (read-only)")
                category = live.get("category") or {}
                taxonomy = live.get("productCategory") or {}
                print(f"  category.id        : {format_value(category.get('id'))}")
                print(f"  category.name      : {format_value(category.get('name'))}")
                print(f"  category.fullName  : {format_value(category.get('fullName'))}")
                print(f"  taxonomy.name      : {format_value(taxonomy.get('name'))}")
                print(f"  taxonomy.fullName  : {format_value(taxonomy.get('fullName'))}")
                print(f"  productType        : {format_value(live.get('productType'))}")
                print(f"  status             : {format_value(live.get('status'))}")
        else:
            print("\n⚠️  Unable to derive product GID; skipping live Shopify lookup")

    if show_all:
        print("\nAdditional Shopify listing fields")
        extra_fields = {
            "status": listing.status,
            "vendor": listing.vendor,
            "price": listing.price,
            "handle": listing.handle,
            "seo_title": listing.seo_title,
            "seo_description": listing.seo_description,
            "created_at": listing.created_at,
            "updated_at": listing.updated_at,
            "last_synced_at": listing.last_synced_at,
        }
        for key, value in extra_fields.items():
            print(f"  {key}: {format_value(value)}")

        if listing.extended_attributes:
            print("\nextended_attributes:")
            for key, value in listing.extended_attributes.items():
                print(f"  - {key}: {format_value(value)}")


async def run(legacy_ids: Iterable[str], *, show_all: bool, live_category: bool) -> None:
    for legacy_id in legacy_ids:
        listing = await fetch_listing(legacy_id)
        if not listing:
            print("=" * 80)
            print(f"No Shopify listing found for legacy ID {legacy_id}")
            continue
        print_listing(listing, show_all=show_all, live_category=live_category)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inspect Shopify listing metadata by legacy ID",
    )
    parser.add_argument(
        "legacy_ids",
        metavar="LEGACY_ID",
        nargs="+",
        help="One or more Shopify legacy product IDs (numeric).",
    )
    parser.add_argument(
        "--show-all",
        action="store_true",
        help="Display all stored listing metadata instead of category fields only.",
    )
    parser.add_argument(
        "--live-category",
        action="store_true",
        help="Fetch category information directly from the Shopify Admin API for each product.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    asyncio.run(run(args.legacy_ids, show_all=args.show_all, live_category=args.live_category))


if __name__ == "__main__":
    main()
