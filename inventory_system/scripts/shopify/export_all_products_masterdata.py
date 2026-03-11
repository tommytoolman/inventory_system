#!/usr/bin/env python3
"""
Export a flattened view of every Shopify product (and its variants) so we can
verify SKU coverage and master data outside the app.

Usage:
    source venv/bin/activate
    python scripts/shopify/export_all_products_masterdata.py \
        --page-size 150 \
        --output data/shopify/shopify_masterdata.csv

If --output is omitted, a timestamped CSV is written under data/shopify/.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from app.services.shopify.client import ShopifyGraphQLClient


def _extract_country_metafield(product_node: Dict[str, Any]) -> Optional[str]:
    metafields = (product_node.get("metafields") or {}).get("nodes") or []
    for node in metafields:
        if not isinstance(node, dict):
            continue
        namespace = (node.get("namespace") or "").strip().lower()
        key = (node.get("key") or "").strip().lower()
        if namespace == "extra_info" and key == "country_of_origin":
            return node.get("value")
    return None


def _variant_rows(product_node: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    product_id = product_node.get("id")
    legacy_id = product_node.get("legacyResourceId")
    base = {
        "product_gid": product_id,
        "legacy_product_id": legacy_id,
        "title": product_node.get("title"),
        "status": product_node.get("status"),
        "vendor": product_node.get("vendor"),
        "product_type": product_node.get("productType"),
        "tags": "|".join(product_node.get("tags") or []),
        "total_inventory": product_node.get("totalInventory"),
        "created_at": product_node.get("createdAt"),
        "updated_at": product_node.get("updatedAt"),
        "published_at": product_node.get("publishedAt"),
        "category_name": (product_node.get("category") or {}).get("name"),
        "category_full_name": (product_node.get("category") or {}).get("fullName"),
        "country_of_origin": _extract_country_metafield(product_node),
    }
    variants = (product_node.get("variants") or {}).get("nodes") or []
    if not variants:
        yield {**base, "variant_sku": None, "variant_price": None, "variant_available": None}
        return
    for variant in variants:
        yield {
            **base,
            "variant_sku": (variant or {}).get("sku"),
            "variant_price": (variant or {}).get("price"),
            "variant_available": (variant or {}).get("availableForSale"),
        }


def export_masterdata(page_size: int, output_path: Optional[Path]) -> Path:
    client = ShopifyGraphQLClient()
    products = client.get_all_products_summary(page_size=page_size)
    rows: List[Dict[str, Any]] = []
    for node in products:
        rows.extend(_variant_rows(node))

    if output_path is None:
        output_dir = Path("data/shopify")
        output_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        output_path = output_dir / f"shopify_masterdata_{ts}.csv"
    else:
        output_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "product_gid",
        "legacy_product_id",
        "title",
        "status",
        "vendor",
        "product_type",
        "tags",
        "total_inventory",
        "variant_sku",
        "variant_price",
        "variant_available",
        "country_of_origin",
        "category_name",
        "category_full_name",
        "created_at",
        "updated_at",
        "published_at",
    ]
    with output_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    print(f"Exported {len(rows)} Shopify variant rows to {output_path}")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Export Shopify master data snapshot.")
    parser.add_argument("--page-size", type=int, default=150, help="GraphQL page size (<=250).")
    parser.add_argument("--output", type=Path, help="Optional output CSV path.")
    args = parser.parse_args()
    export_masterdata(args.page_size, args.output)


if __name__ == "__main__":
    main()
