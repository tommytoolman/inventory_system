#!/usr/bin/env python3
"""Refresh Shopify extended attributes for listings that lack inventory detail."""

import argparse
import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import text, update

from app.models.shopify import ShopifyListing

from app.database import async_session
from app.services.shopify.client import ShopifyGraphQLClient

PRODUCT_QUERY = """
query GetProduct($id: ID!) {
  product(id: $id) {
    id
    title
    handle
    vendor
    productType
    tags
    status
    onlineStoreUrl
    publishedAt
    totalInventory
    seo {
      title
      description
    }
    category {
      id
      name
      fullName
    }
    images(first: 10) {
      edges {
        node {
          url
          altText
        }
      }
    }
    variants(first: 50) {
      nodes {
        id
        sku
        price
        inventoryQuantity
        inventoryItem {
          id
          sku
          tracked
        }
      }
    }
    resourcePublications(first: 5) {
      nodes {
        publishDate
        isPublished
        publication {
          name
        }
      }
    }
  }
}
"""


async def fetch_listings(session, skus: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    base_query = """
        SELECT
            sl.id AS listing_id,
            pc.external_id AS shopify_id,
            p.sku,
            sl.extended_attributes
        FROM shopify_listings sl
        JOIN platform_common pc ON sl.platform_id = pc.id
        JOIN products p ON pc.product_id = p.id
        WHERE pc.platform_name = 'shopify'
    """

    params: Dict[str, Any] = {}
    if skus:
        placeholders = ", ".join(f":sku_{i}" for i in range(len(skus)))
        base_query += f" AND p.sku IN ({placeholders})"
        params.update({f"sku_{i}": sku for i, sku in enumerate(skus)})
    else:
        base_query += " AND (sl.extended_attributes IS NULL OR sl.extended_attributes::text = '{}' OR NOT (sl.extended_attributes ? 'variants'))"

    result = await session.execute(text(base_query), params)
    return [row._asdict() for row in result.fetchall()]


async def save_extended_attributes(session, listing_id: int, payload: Dict[str, Any]) -> None:
    stmt = (
        update(ShopifyListing)
        .where(ShopifyListing.id == listing_id)
        .values(extended_attributes=payload, updated_at=datetime.utcnow())
    )
    await session.execute(stmt)


async def refresh_extended_attributes(skus: Optional[List[str]] = None) -> None:
    async with async_session() as session:
        listings = await fetch_listings(session, skus)

    if not listings:
        print("No Shopify listings found for the given criteria.")
        return

    client = ShopifyGraphQLClient()

    async with async_session() as session:
        for listing in listings:
            raw_id = listing.get("shopify_id")
            sku = listing.get("sku")

            if not raw_id:
                print(f"[WARN] {sku}: listing missing Shopify product id; skipping")
                continue

            product_gid = raw_id if raw_id.startswith("gid://") else f"gid://shopify/Product/{raw_id}"

            data = client._make_request(PRODUCT_QUERY, {"id": product_gid})
            product = data.get("product") if data else None
            if not product:
                print(f"[WARN] {sku}: unable to fetch product details from Shopify")
                continue

            variants = product.get("variants", {}).get("nodes", [])
            if not variants:
                print(f"[WARN] {sku}: product has no variants in Shopify response")

            payload = {
                "id": product.get("id"),
                "title": product.get("title"),
                "handle": product.get("handle"),
                "vendor": product.get("vendor"),
                "productType": product.get("productType"),
                "tags": product.get("tags", []),
                "status": product.get("status"),
                "onlineStoreUrl": product.get("onlineStoreUrl"),
                "publishedAt": product.get("publishedAt"),
                "totalInventory": product.get("totalInventory"),
                "seo": product.get("seo"),
                "category": product.get("category"),
                "images": product.get("images", {}).get("edges", []),
                "variants": {"nodes": variants},
                "resourcePublications": product.get("resourcePublications", {}).get("nodes", []),
            }

            await save_extended_attributes(session, listing["listing_id"], payload)
            print(f"[OK] {sku}: refreshed extended_attributes")

        await session.commit()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Refresh Shopify extended attributes")
    parser.add_argument("--sku", action="append", dest="skus", help="SKU(s) to refresh")
    args = parser.parse_args()

    asyncio.run(refresh_extended_attributes(args.skus))
