#!/usr/bin/env python3
"""
Test script: Change Shopify product template to 'sold-product'.

Uses product 1162 (RIFF) / Shopify ID 15021539787092 — a known sold item.

Usage:
    source venv/bin/activate
    python scripts/test_shopify_sold_template.py            # Apply sold template
    python scripts/test_shopify_sold_template.py --revert   # Revert to default template
    python scripts/test_shopify_sold_template.py --check    # Check current template only
"""

import os
import sys
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.shopify.client import ShopifyGraphQLClient

SHOPIFY_LEGACY_ID = "15021539787092"
PRODUCT_GID       = f"gid://shopify/Product/{SHOPIFY_LEGACY_ID}"
SOLD_TEMPLATE     = "sold-product"
DEFAULT_TEMPLATE  = ""  # Empty string = revert to default product template


def get_current_template(client: ShopifyGraphQLClient) -> dict:
    """Fetch current templateSuffix and title for the product."""
    query = """
    query getProduct($id: ID!) {
      product(id: $id) {
        id
        legacyResourceId
        title
        status
        templateSuffix
      }
    }
    """
    data = client._make_request(query, {"id": PRODUCT_GID}, estimated_cost=10)
    if data and data.get("product"):
        return data["product"]
    return {}


def set_template(client: ShopifyGraphQLClient, template_suffix: str) -> dict:
    """Set the templateSuffix on the product via productUpdate."""
    result = client.update_product({
        "id": PRODUCT_GID,
        "templateSuffix": template_suffix,
    })
    return result or {}


def main():
    parser = argparse.ArgumentParser(description="Test Shopify sold-product template change")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--revert", action="store_true", help="Revert to default template")
    group.add_argument("--check",  action="store_true", help="Check current template only")
    args = parser.parse_args()

    print(f"\n── Shopify Template Test ────────────────────────────────────")
    print(f"  Product GID : {PRODUCT_GID}")
    print(f"  Legacy ID   : {SHOPIFY_LEGACY_ID}")

    client = ShopifyGraphQLClient()

    # Always fetch current state first
    print("\n  Fetching current product state...")
    current = get_current_template(client)
    if not current:
        print("  ERROR: Could not fetch product. Check Shopify credentials.")
        sys.exit(1)

    print(f"  Title           : {current.get('title', '?')}")
    print(f"  Status          : {current.get('status', '?')}")
    print(f"  Template suffix : '{current.get('templateSuffix') or '(default)'}'")

    if args.check:
        print("\n  [CHECK ONLY] No changes made.")
        return

    # Determine target template
    if args.revert:
        target = DEFAULT_TEMPLATE
        action = "Reverting to default template"
    else:
        target = SOLD_TEMPLATE
        action = f"Applying sold template: '{SOLD_TEMPLATE}'"

    # Skip if already set
    current_suffix = current.get("templateSuffix") or ""
    if current_suffix == target:
        print(f"\n  Already set to '{target or '(default)'}' — nothing to do.")
        return

    print(f"\n  {action}...")
    result = set_template(client, target)

    if result.get("product"):
        new_suffix = result["product"].get("templateSuffix") or "(default)"
        print(f"  ✓ Success. Template is now: '{new_suffix}'")
    elif result.get("userErrors"):
        print(f"  ✗ User errors: {result['userErrors']}")
        sys.exit(1)
    else:
        print(f"  ✗ Unexpected response: {result}")
        sys.exit(1)

    # Verify by re-fetching
    print("\n  Verifying via fresh fetch...")
    verified = get_current_template(client)
    verified_suffix = verified.get("templateSuffix") or "(default)"
    print(f"  Confirmed template: '{verified_suffix}'")

    if (verified.get("templateSuffix") or "") == target:
        print("  ✓ Verified.\n")
    else:
        print("  ✗ Mismatch — template may not have updated correctly.\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
