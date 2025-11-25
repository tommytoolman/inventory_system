#!/usr/bin/env python3
"""
Dump Shopify product metafields for given legacy product IDs.

Usage:
    python scripts/shopify/dump_metafields.py 12193919172948 12379426455892
"""

import sys
import json

from app.services.shopify.client import ShopifyGraphQLClient


def dump_metafields(legacy_ids):
    client = ShopifyGraphQLClient()
    results = []
    for legacy_id in legacy_ids:
        product_gid = f"gid://shopify/Product/{legacy_id}"
        data = client.get_product_snapshot_by_id(product_gid, num_metafields=100)
        product = data.get("product") or data
        mfs = []
        for edge in (product.get("metafields", {}) or {}).get("edges", []):
            node = edge.get("node") or {}
            mfs.append(
                {
                    "namespace": node.get("namespace"),
                    "key": node.get("key"),
                    "type": node.get("type"),
                    "value": node.get("value"),
                    "id": node.get("id"),
                }
            )
        results.append({"legacy_id": legacy_id, "metafields": mfs})
    return results


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/shopify/dump_metafields.py <legacy_id1> [legacy_id2 ...]")
        sys.exit(1)
    legacy_ids = sys.argv[1:]
    output = dump_metafields(legacy_ids)
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
