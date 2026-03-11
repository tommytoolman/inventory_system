#!/usr/bin/env python3
"""One-off script to push canonical product quantities to Shopify via the Admin API."""

import argparse
import asyncio
from typing import Any, Dict, List, Sequence

from sqlalchemy import text

from app.database import async_session
from app.services.shopify.client import ShopifyGraphQLClient, ShopifyGraphQLError
from app.core.config import get_settings

INVENTORY_MUTATION = """
mutation inventorySetOnHandQuantities($input: InventorySetOnHandQuantitiesInput!) {
  inventorySetOnHandQuantities(input: $input) {
    userErrors {
      field
      message
    }
  }
}
"""

VARIANT_INVENTORY_QUERY = """
query GetInventoryVariants($id: ID!) {
  product(id: $id) {
    id
    variants(first: 100) {
      nodes {
        id
        sku
        inventoryItem {
          id
          sku
          tracked
        }
      }
    }
  }
}
"""


async def fetch_shopify_inventory_rows(session, skus: Sequence[str] | None = None) -> List[Dict[str, Any]]:
    query_str = """
        SELECT
            p.id,
            p.sku,
            p.quantity,
            sl.extended_attributes,
            pc.external_id AS shopify_external_id
        FROM products p
        JOIN platform_common pc ON pc.product_id = p.id
        JOIN shopify_listings sl ON sl.platform_id = pc.id
        WHERE pc.platform_name = 'shopify'
    """

    params: Dict[str, Any] = {}
    if skus:
        placeholders = ", ".join(f":sku_{i}" for i in range(len(skus)))
        query_str += f" AND p.sku IN ({placeholders})"
        params.update({f"sku_{i}": sku for i, sku in enumerate(skus)})

    query = text(query_str)
    result = await session.execute(query, params)
    return [row._asdict() for row in result.fetchall()]


def extract_variant_inventory_nodes(ext_attrs: Dict[str, Any]) -> List[Dict[str, Any]]:
    variants = (ext_attrs or {}).get("variants", {}).get("nodes", [])
    return variants if isinstance(variants, list) else []


def normalise_sku(value: str | None) -> str | None:
    return value.strip().lower() if value else None


def resolve_location_gid(raw_location_id: str | None) -> str:
    """Return a Shopify location GID or raise if configuration is missing."""
    if not raw_location_id:
        raise ValueError("SHOPIFY_LOCATION_GID is not configured; update the .env file")

    return (
        raw_location_id
        if raw_location_id.startswith("gid://")
        else f"gid://shopify/Location/{raw_location_id}"
    )


def resolve_product_gid(row: Dict[str, Any], ext_attrs: Dict[str, Any]) -> str | None:
    raw_id = row.get("shopify_external_id") or (ext_attrs or {}).get("id")
    if not raw_id:
        return None
    return raw_id if str(raw_id).startswith("gid://") else f"gid://shopify/Product/{raw_id}"


def fetch_fresh_variant_nodes(client: ShopifyGraphQLClient, product_gid: str) -> List[Dict[str, Any]]:
    try:
        data = client.execute(VARIANT_INVENTORY_QUERY, {"id": product_gid})
    except ShopifyGraphQLError as exc:  # pragma: no cover - passthrough to caller messaging
        print(f"[ERROR] Failed to fetch product {product_gid}: {exc}")
        return []

    product = (data or {}).get("product") if data else None
    if not product:
        return []
    variants = product.get("variants", {}).get("nodes")
    return variants or []


async def update_shopify_inventory(skus: Sequence[str] | None = None) -> None:
    async with async_session() as session:
        rows = await fetch_shopify_inventory_rows(session, skus)

    client = ShopifyGraphQLClient()
    settings = get_settings()
    location_gid = resolve_location_gid(settings.SHOPIFY_LOCATION_GID)

    for row in rows:
        sku = row["sku"]
        quantity = row["quantity"] or 0
        extended_attrs = row["extended_attributes"] or {}

        variants = extract_variant_inventory_nodes(extended_attrs)
        product_gid = resolve_product_gid(row, extended_attrs)

        if not variants and product_gid:
            fresh_nodes = fetch_fresh_variant_nodes(client, product_gid)
            if fresh_nodes:
                variants = fresh_nodes
                print(
                    f"[INFO] {sku}: using live Shopify variant data because stored payload was empty"
                )

        if not variants:
            print(f"[WARN] {sku}: no variants found in extended_attributes; skipping")
            continue

        fallback_map: Dict[str, Dict[str, Any]] = {}
        requires_refresh = any(
            not ((variant or {}).get("inventoryItem") or {}).get("id")
            and not (variant or {}).get("inventoryItemId")
            for variant in variants
        )

        if requires_refresh:
            if not product_gid:
                print(
                    f"[WARN] {sku}: cannot refresh Shopify product data because the product GID is missing"
                )
            else:
                fresh_nodes = fetch_fresh_variant_nodes(client, product_gid)
                fallback_map = {
                    normalise_sku(node.get("sku")): node for node in fresh_nodes if node.get("sku")
                }
                if fallback_map:
                    print(f"[INFO] {sku}: refreshed variant inventory data from Shopify")
                else:
                    print(
                        f"[WARN] {sku}: Shopify product refresh did not return inventory item IDs; "
                        "consider re-running the extended attribute refresh"
                    )

        adjustments = []
        for variant in variants:
            variant = variant or {}
            inventory_item = variant.get("inventoryItem") or {}
            inventory_item_id = inventory_item.get("id") or variant.get("inventoryItemId")

            if not inventory_item_id and fallback_map:
                lookup = fallback_map.get(normalise_sku(variant.get("sku")))
                if lookup:
                    inventory_item_id = ((lookup.get("inventoryItem") or {}).get("id"))

                    if not inventory_item_id and lookup.get("id"):
                        rest_variant = client.get_variant_details_rest(lookup["id"])
                        inventory_item_id = (rest_variant or {}).get("inventory_item_id")
                        if inventory_item_id:
                            inventory_item_id = (
                                f"gid://shopify/InventoryItem/{inventory_item_id}"
                                if not str(inventory_item_id).startswith("gid://")
                                else inventory_item_id
                            )

            if not inventory_item_id:
                print(
                    f"[WARN] {sku}: variant missing inventory item id; raw variant = {variant}"
                )
                continue

            adjustments.append(
                {
                    "inventoryItemId": inventory_item_id,
                    "locationId": location_gid,
                    "quantity": int(quantity),
                }
            )

        if not adjustments:
            print(f"[WARN] {sku}: no inventory adjustments generated; skipping")
            continue

        variables = {
            "input": {
                "reason": "correction",
                "setQuantities": adjustments,
            }
        }

        response = client.execute(INVENTORY_MUTATION, variables)
        errors = (
            response.get("data", {})
            .get("inventorySetOnHandQuantities", {})
            .get("userErrors", [])
        )
        if errors:
            print(f"[ERROR] {sku}: {errors}")
        else:
            print(f"[OK] {sku}: set quantity {quantity}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Push product quantities to Shopify")
    parser.add_argument(
        "--sku",
        action="append",
        dest="skus",
        help="Limit the update to specific SKU(s); use multiple times for multiple SKUs",
    )
    args = parser.parse_args()

    asyncio.run(update_shopify_inventory(args.skus))
