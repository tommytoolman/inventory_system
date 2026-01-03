#!/usr/bin/env python3
"""
Fix Shopify inventory from -1 to 0 for SOLD/ENDED/ARCHIVED products.

BACKGROUND
----------
A bug was discovered where Shopify inventory was being set to -1 instead of
decremented by 1 when items sold. This left unique (qty=1) items with -1
inventory on Shopify instead of 0.

The local database (products.quantity) is correct, but Shopify has the wrong
value. This script queries the Shopify API to find items with -1 inventory
and fixes them to 0.

HOW IT WORKS
------------
1. Queries local database for Shopify listings with specified statuses
   (default: SOLD, ENDED)
2. For each listing, queries Shopify API to get actual inventory level
3. If inventory is -1, sets it to 0 using the Shopify REST API
4. Reports summary of fixed/skipped/error counts

ARGUMENTS
---------
--dry-run       Show what would be fixed without making changes
--limit N       Process only first N items (useful for testing)
--status STATUS Filter by platform_common.status (can specify multiple)
                Default: SOLD, ENDED
                Common values: SOLD, ENDED, ARCHIVED, ACTIVE

EXAMPLES
--------
# Dry run - see what would be fixed (default: SOLD, ENDED statuses)
python scripts/shopify/fix_negative_inventory.py --dry-run

# Check only ARCHIVED items
python scripts/shopify/fix_negative_inventory.py --status ARCHIVED --dry-run

# Check only ARCHIVED items, limit to first 10
python scripts/shopify/fix_negative_inventory.py --status ARCHIVED --dry-run --limit 10

# Check multiple specific statuses
python scripts/shopify/fix_negative_inventory.py --status SOLD --status ARCHIVED --dry-run

# Fix first 5 SOLD/ENDED items (live mode)
python scripts/shopify/fix_negative_inventory.py --limit 5

# Fix all ARCHIVED items (live mode)
python scripts/shopify/fix_negative_inventory.py --status ARCHIVED

# Fix everything with default statuses (SOLD, ENDED)
python scripts/shopify/fix_negative_inventory.py

NOTES
-----
- Always run with --dry-run first to see what would be changed
- Use --limit to process in small batches
- The script queries Shopify API for each item, so large runs may take time
- Fixed items are logged; errors are reported in the summary

Created: 2026-01-03
"""

import asyncio
import argparse
import sys
import os
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from sqlalchemy import text
from app.database import get_session
from app.core.config import get_settings
from app.services.shopify.client import ShopifyGraphQLClient


class NegativeInventoryFixer:

    def __init__(self, dry_run: bool = False, statuses: list = None):
        self.settings = get_settings()
        self.dry_run = dry_run
        self.statuses = statuses or ['SOLD', 'ENDED']
        self.shopify_client = ShopifyGraphQLClient()
        self.fixed_count = 0
        self.skipped_count = 0
        self.error_count = 0

    async def get_all_shopify_listings(self, limit: int = None) -> list:
        """Get Shopify listings matching specified statuses.

        Only checks items where platform_common.status matches the configured statuses.
        """
        # Build status filter
        status_list = ", ".join(f"'{s.upper()}'" for s in self.statuses)

        async with get_session() as db:
            query = text(f"""
                SELECT
                    p.id as product_id,
                    p.sku,
                    p.title,
                    p.quantity as local_quantity,
                    pc.status as platform_status,
                    sl.shopify_product_id,
                    sl.handle
                FROM products p
                JOIN platform_common pc ON p.id = pc.product_id AND pc.platform_name = 'shopify'
                JOIN shopify_listings sl ON pc.id = sl.platform_id
                WHERE sl.shopify_product_id IS NOT NULL
                  AND UPPER(pc.status) IN ({status_list})
                ORDER BY p.id
            """ + (f" LIMIT {limit}" if limit else ""))

            result = await db.execute(query)
            return result.fetchall()

    def get_shopify_inventory(self, shopify_product_id: str) -> dict:
        """Query Shopify API to get current inventory level."""
        inventory_query = """
        query getProductInventory($id: ID!) {
            product(id: $id) {
                id
                title
                variants(first: 1) {
                    edges {
                        node {
                            id
                            sku
                            inventoryQuantity
                            inventoryItem {
                                id
                                inventoryLevels(first: 1) {
                                    edges {
                                        node {
                                            id
                                            quantities(names: "available") {
                                                quantity
                                            }
                                            location {
                                                id
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        """

        variables = {"id": shopify_product_id}
        result = self.shopify_client._make_request(inventory_query, variables, estimated_cost=10)

        if not result or not result.get("product"):
            return None

        product = result["product"]
        variants = product.get("variants", {}).get("edges", [])

        if not variants:
            return None

        variant = variants[0]["node"]
        inventory_item = variant.get("inventoryItem", {})
        levels = inventory_item.get("inventoryLevels", {}).get("edges", [])

        if not levels:
            return None

        level = levels[0]["node"]
        quantities = level.get("quantities", [])
        available = quantities[0]["quantity"] if quantities else variant.get("inventoryQuantity")

        # Extract numeric IDs from GIDs
        variant_gid = variant["id"]  # gid://shopify/ProductVariant/12345
        variant_id = variant_gid.split("/")[-1]

        inventory_item_id = inventory_item["id"].split("/")[-1]
        location_id = level["location"]["id"].split("/")[-1]

        return {
            "variant_id": variant_id,
            "inventory_item_id": inventory_item_id,
            "location_id": location_id,
            "current_quantity": available,
            "sku": variant.get("sku")
        }

    def set_inventory_to_zero(self, inventory_item_id: str, location_id: str) -> bool:
        """Set inventory to 0 using REST API."""
        if self.dry_run:
            return True

        try:
            set_url = f"https://{self.shopify_client.store_domain}/admin/api/{self.shopify_client.api_version}/inventory_levels/set.json"
            headers = {"X-Shopify-Access-Token": self.shopify_client.admin_api_token}

            payload = {
                "location_id": int(location_id),
                "inventory_item_id": int(inventory_item_id),
                "available": 0
            }

            response = requests.post(set_url, headers=headers, json=payload, timeout=30)
            response.raise_for_status()
            return True

        except requests.exceptions.RequestException as e:
            print(f"      ❌ API Error: {e}")
            return False

    async def run(self, limit: int = None):
        """Main execution."""
        print("=" * 60)
        print("SHOPIFY NEGATIVE INVENTORY FIXER")
        print("=" * 60)

        if self.dry_run:
            print("🔍 DRY RUN MODE - No changes will be made\n")
        else:
            print("⚠️  LIVE MODE - Will update Shopify inventory\n")

        # Get Shopify listings with specified statuses - check API for -1 inventory
        products = await self.get_all_shopify_listings(limit)
        status_str = ", ".join(self.statuses)
        print(f"Found {len(products)} Shopify listings with status [{status_str}] to check\n")

        for row in products:
            print(f"📦 {row.sku}: {row.title[:50]}...")
            print(f"   Shopify ID: {row.shopify_product_id}")
            print(f"   Local qty: {row.local_quantity} | Platform status: {row.platform_status}")

            # Get current Shopify inventory
            inv_data = self.get_shopify_inventory(row.shopify_product_id)

            if not inv_data:
                print(f"   ⚠️  Could not fetch inventory data - SKIPPED")
                self.skipped_count += 1
                continue

            current_qty = inv_data["current_quantity"]
            print(f"   Current quantity: {current_qty}")

            if current_qty == -1:
                print(f"   🔧 Fixing: -1 → 0")

                if self.set_inventory_to_zero(inv_data["inventory_item_id"], inv_data["location_id"]):
                    if self.dry_run:
                        print(f"   ✅ Would fix (dry run)")
                    else:
                        print(f"   ✅ Fixed!")
                    self.fixed_count += 1
                else:
                    print(f"   ❌ Failed to fix")
                    self.error_count += 1

            elif current_qty == 0:
                print(f"   ✓ Already correct (0)")
                self.skipped_count += 1

            elif current_qty > 0:
                print(f"   ⚠️  Has positive inventory ({current_qty}) - SKIPPED")
                self.skipped_count += 1

            else:
                print(f"   ⚠️  Unexpected value ({current_qty}) - SKIPPED")
                self.skipped_count += 1

            print()

        # Summary
        print("=" * 60)
        print("SUMMARY")
        print("=" * 60)
        print(f"Fixed:   {self.fixed_count}")
        print(f"Skipped: {self.skipped_count}")
        print(f"Errors:  {self.error_count}")

        if self.dry_run and self.fixed_count > 0:
            print(f"\nRun without --dry-run to apply {self.fixed_count} fixes")


async def main():
    parser = argparse.ArgumentParser(description="Fix Shopify -1 inventory to 0")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be fixed without making changes")
    parser.add_argument("--limit", type=int, help="Limit number of products to process")
    parser.add_argument("--status", type=str, action="append",
                        help="Status to check (can specify multiple). Default: SOLD, ENDED. Example: --status ARCHIVED")

    args = parser.parse_args()

    # Default to SOLD, ENDED if no status specified
    statuses = args.status if args.status else ['SOLD', 'ENDED']

    fixer = NegativeInventoryFixer(dry_run=args.dry_run, statuses=statuses)
    await fixer.run(limit=args.limit)


if __name__ == "__main__":
    asyncio.run(main())
