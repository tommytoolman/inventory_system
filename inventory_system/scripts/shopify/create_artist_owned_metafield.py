#!/usr/bin/env python3
"""Create the Shopify metafield definition for the Artist Owned flag."""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.shopify.client import ShopifyGraphQLClient


def main() -> None:
    client = ShopifyGraphQLClient()
    result = client.create_metafield_definition(
        name="Artist Owned",
        namespace="guitar_specs",
        key="artist_owned",
        type_name="boolean",
        owner_type="PRODUCT",
        description="Whether this guitar was previously owned by a notable artist or musician",
    )

    created = result.get("createdDefinition") if result else None
    errors = result.get("userErrors") if result else None

    if created:
        print("✅ Created metafield definition:")
        print(f"  id: {created.get('id')}")
        print(f"  name: {created.get('name')} ({created.get('namespace')}.{created.get('key')})")
    elif errors:
        already_exists = any("in use" in (err.get("message", "").lower()) for err in errors)
        if already_exists:
            print("ℹ️ Metafield definition already exists (nothing to do).")
        else:
            print("⚠️ Shopify reported errors:")
            for err in errors:
                print(f"  - {err.get('message')}")
    else:
        print("No response from Shopify.")


if __name__ == "__main__":
    main()
