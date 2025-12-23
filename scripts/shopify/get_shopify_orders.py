#!/usr/bin/env python3
"""
Get orders from Shopify.

This script fetches orders from your Shopify store using the GraphQL API, with options to:
- Limit the number of orders fetched
- Output as JSON or formatted text
- Save to a JSON file
- Insert/upsert into database

Usage:
    python scripts/shopify/get_shopify_orders.py [--limit N] [--json] [--detailed] [--save] [--insert-db]

Examples:
    # Get first 50 orders
    python scripts/shopify/get_shopify_orders.py

    # Get first 100 orders
    python scripts/shopify/get_shopify_orders.py --limit 100

    # Get all orders as JSON
    python scripts/shopify/get_shopify_orders.py --all --json

    # Save ALL orders to scripts/shopify/output/all_orders.json
    python scripts/shopify/get_shopify_orders.py --all --save

    # Insert into database
    python scripts/shopify/get_shopify_orders.py --all --insert-db
"""

import argparse
import asyncio
import json
import os
import sys
from decimal import Decimal
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent.parent))

from sqlalchemy import select

from app.services.shopify.client import ShopifyGraphQLClient
from app.core.config import get_settings
from app.database import async_session
from app.models.shopify_order import ShopifyOrder
from app.models.platform_common import PlatformCommon
from app.services.order_sale_processor import OrderSaleProcessor


# GraphQL query for fetching orders
ORDERS_QUERY = """
query GetOrders($first: Int!, $after: String) {
  orders(first: $first, after: $after, reverse: true, sortKey: CREATED_AT) {
    edges {
      node {
        id
        name
        createdAt
        email
        phone
        displayFinancialStatus
        displayFulfillmentStatus
        totalPriceSet {
          shopMoney {
            amount
            currencyCode
          }
        }
        subtotalPriceSet {
          shopMoney {
            amount
            currencyCode
          }
        }
        totalShippingPriceSet {
          shopMoney {
            amount
            currencyCode
          }
        }
        totalTaxSet {
          shopMoney {
            amount
            currencyCode
          }
        }
        customer {
          id
          firstName
          lastName
          email
          phone
        }
        shippingAddress {
          firstName
          lastName
          name
          address1
          address2
          city
          province
          provinceCode
          country
          countryCode
          zip
          phone
          company
        }
        billingAddress {
          firstName
          lastName
          address1
          address2
          city
          province
          country
          zip
        }
        fulfillments {
          id
          status
          createdAt
          trackingInfo {
            company
            number
            url
          }
        }
        lineItems(first: 50) {
          edges {
            node {
              id
              name
              title
              quantity
              sku
              variantTitle
              vendor
              originalUnitPriceSet {
                shopMoney {
                  amount
                  currencyCode
                }
              }
            }
          }
        }
      }
    }
    pageInfo {
      hasNextPage
      endCursor
    }
  }
}
"""


def _parse_decimal(value: Any) -> Optional[Decimal]:
    """Parse a decimal value from various formats."""
    if value in (None, "", "null"):
        return None
    try:
        if isinstance(value, dict) and "amount" in value:
            value = value.get("amount")
        return Decimal(str(value))
    except Exception:
        return None


def _parse_datetime(value: Any) -> Optional[datetime]:
    """Parse a datetime value from ISO format."""
    if not value:
        return None
    try:
        if isinstance(value, str):
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        else:
            dt = value
        # Normalize to naive UTC for TIMESTAMP WITHOUT TIME ZONE columns
        if isinstance(dt, datetime):
            return dt.astimezone(timezone.utc).replace(tzinfo=None)
        return None
    except Exception:
        return None


def _extract_money(money_set: Optional[Dict]) -> tuple[Optional[Decimal], Optional[str]]:
    """Extract amount and currency from a Shopify MoneySet."""
    if not money_set:
        return None, None
    shop_money = money_set.get("shopMoney", {})
    amount = _parse_decimal(shop_money.get("amount"))
    currency = shop_money.get("currencyCode")
    return amount, currency


async def _resolve_platform_common(
    db, sku: Optional[str]
) -> Dict[str, Optional[int]]:
    """Resolve product and platform_listing IDs from SKU."""
    if not sku:
        return {"platform_listing_id": None, "product_id": None}

    # Try to find by SKU in platform_common
    result = await db.execute(
        select(PlatformCommon).where(
            PlatformCommon.platform_name == "shopify",
            PlatformCommon.sku == sku,
        )
    )
    pc = result.scalar_one_or_none()
    if not pc:
        return {"platform_listing_id": None, "product_id": None}
    return {"platform_listing_id": pc.id, "product_id": pc.product_id}


def _extract_primary_item(line_items: List[Dict]) -> Dict[str, Any]:
    """Extract primary line item info (first item with SKU)."""
    for item in line_items:
        node = item.get("node", item)
        if node.get("sku"):
            return {
                "primary_sku": node.get("sku"),
                "primary_title": node.get("title") or node.get("name"),
                "primary_quantity": node.get("quantity"),
                "primary_price": _parse_decimal(
                    (node.get("originalUnitPriceSet") or {}).get("shopMoney", {}).get("amount")
                ),
                "primary_price_currency": (node.get("originalUnitPriceSet") or {}).get("shopMoney", {}).get("currencyCode"),
            }
    # Fallback to first item
    if line_items:
        node = line_items[0].get("node", line_items[0])
        return {
            "primary_sku": node.get("sku"),
            "primary_title": node.get("title") or node.get("name"),
            "primary_quantity": node.get("quantity"),
            "primary_price": _parse_decimal(
                (node.get("originalUnitPriceSet") or {}).get("shopMoney", {}).get("amount")
            ),
            "primary_price_currency": (node.get("originalUnitPriceSet") or {}).get("shopMoney", {}).get("currencyCode"),
        }
    return {
        "primary_sku": None,
        "primary_title": None,
        "primary_quantity": None,
        "primary_price": None,
        "primary_price_currency": None,
    }


def _extract_tracking(fulfillments: List[Dict]) -> Dict[str, Optional[str]]:
    """Extract tracking info from first fulfillment with tracking."""
    for f in fulfillments or []:
        tracking_info = f.get("trackingInfo", [])
        if tracking_info:
            first_tracking = tracking_info[0] if isinstance(tracking_info, list) else tracking_info
            return {
                "tracking_number": first_tracking.get("number"),
                "tracking_company": first_tracking.get("company") or f.get("trackingCompany"),
                "tracking_url": first_tracking.get("url"),
            }
    return {"tracking_number": None, "tracking_company": None, "tracking_url": None}


async def upsert_orders(db, orders: List[Dict]) -> Dict[str, int]:
    """Upsert orders into the shopify_orders table."""
    summary = {"fetched": len(orders), "inserted": 0, "updated": 0, "skipped": 0, "errors": 0}

    for order in orders:
        try:
            shopify_order_id = order.get("id", "").strip()
            if not shopify_order_id:
                summary["skipped"] += 1
                continue

            # Check if order exists
            existing = (
                await db.execute(
                    select(ShopifyOrder).where(ShopifyOrder.shopify_order_id == shopify_order_id)
                )
            ).scalar_one_or_none()

            # Extract financial data
            total_amount, total_currency = _extract_money(order.get("totalPriceSet"))
            subtotal_amount, subtotal_currency = _extract_money(order.get("subtotalPriceSet"))
            shipping_amount, shipping_currency = _extract_money(order.get("totalShippingPriceSet"))
            tax_amount, tax_currency = _extract_money(order.get("totalTaxSet"))

            # Extract shipping address
            shipping = order.get("shippingAddress") or {}

            # Extract customer
            customer = order.get("customer") or {}

            # Extract line items
            line_items_edges = (order.get("lineItems") or {}).get("edges", [])
            line_items = [edge.get("node", edge) for edge in line_items_edges]

            # Extract primary item
            primary = _extract_primary_item(line_items_edges)

            # Extract tracking
            tracking = _extract_tracking(order.get("fulfillments", []))

            # Resolve product linkage
            linkage = await _resolve_platform_common(db, primary["primary_sku"])

            # Get fulfillment timestamp from first completed fulfillment
            fulfilled_at = None
            for f in order.get("fulfillments", []):
                if f.get("status") == "SUCCESS":
                    fulfilled_at = _parse_datetime(f.get("createdAt"))
                    break

            data = {
                "shopify_order_id": shopify_order_id,
                "order_name": order.get("name"),
                "financial_status": order.get("displayFinancialStatus"),
                "fulfillment_status": order.get("displayFulfillmentStatus"),
                "created_at": _parse_datetime(order.get("createdAt")),
                "paid_at": None,  # Not directly available in GraphQL response
                "fulfilled_at": fulfilled_at,
                "total_amount": total_amount,
                "total_currency": total_currency,
                "subtotal_amount": subtotal_amount,
                "subtotal_currency": subtotal_currency,
                "shipping_amount": shipping_amount,
                "shipping_currency": shipping_currency,
                "tax_amount": tax_amount,
                "tax_currency": tax_currency,
                "customer_id": customer.get("id"),
                "customer_first_name": customer.get("firstName"),
                "customer_last_name": customer.get("lastName"),
                "customer_email": customer.get("email") or order.get("email"),
                "customer_phone": customer.get("phone") or order.get("phone"),
                "shipping_name": shipping.get("name") or f"{shipping.get('firstName', '')} {shipping.get('lastName', '')}".strip(),
                "shipping_address1": shipping.get("address1"),
                "shipping_address2": shipping.get("address2"),
                "shipping_city": shipping.get("city"),
                "shipping_province": shipping.get("province"),
                "shipping_province_code": shipping.get("provinceCode"),
                "shipping_country": shipping.get("country"),
                "shipping_country_code": shipping.get("countryCode"),
                "shipping_zip": shipping.get("zip"),
                "shipping_phone": shipping.get("phone"),
                "shipping_company": shipping.get("company"),
                "billing_address": order.get("billingAddress"),
                **tracking,
                "fulfillments": order.get("fulfillments"),
                **primary,
                "line_items": line_items,
                "raw_payload": order,
                "product_id": linkage["product_id"],
                "platform_listing_id": linkage["platform_listing_id"],
            }

            if existing:
                for key, value in data.items():
                    setattr(existing, key, value)
                existing.updated_row_at = datetime.now(timezone.utc).replace(tzinfo=None)
                summary["updated"] += 1
            else:
                db.add(ShopifyOrder(**data))
                summary["inserted"] += 1

        except Exception as e:
            print(f"Error processing order {order.get('id', 'unknown')}: {e}")
            summary["errors"] += 1
            continue

    await db.commit()
    return summary


def fetch_orders_sync(client: ShopifyGraphQLClient, max_orders: Optional[int] = 50) -> List[Dict]:
    """
    Fetch orders from Shopify using GraphQL (synchronous).

    Args:
        client: ShopifyGraphQLClient instance
        max_orders: Maximum number of orders to fetch (None for all)

    Returns:
        List of order dictionaries
    """
    all_orders = []
    after_cursor = None
    page_size = min(50, max_orders) if max_orders else 50
    page_num = 1

    while True:
        print(f"Fetching page {page_num}...")

        variables = {"first": page_size}
        if after_cursor:
            variables["after"] = after_cursor

        data = client._make_request(ORDERS_QUERY, variables, estimated_cost=20)

        if not data or "orders" not in data:
            print("No orders data returned")
            break

        orders_data = data["orders"]
        edges = orders_data.get("edges", [])

        for edge in edges:
            all_orders.append(edge["node"])

        page_info = orders_data.get("pageInfo", {})
        has_next_page = page_info.get("hasNextPage", False)
        after_cursor = page_info.get("endCursor")

        print(f"  Fetched {len(edges)} orders (total: {len(all_orders)})")

        # Check if we've reached the limit
        if max_orders and len(all_orders) >= max_orders:
            all_orders = all_orders[:max_orders]
            break

        if not has_next_page:
            break

        page_num += 1

    return all_orders


async def get_shopify_orders(
    max_orders: Optional[int] = 50,
    json_output: bool = False,
    detailed: bool = False,
    save_to_file: bool = False,
    insert_db: bool = False,
):
    """
    Fetch and display orders from Shopify.

    Args:
        max_orders: Maximum number of orders to fetch (None for all)
        json_output: If True, output as JSON
        detailed: If True, show detailed information for each order
        save_to_file: If True, save to JSON file
        insert_db: If True, upsert into database
    """
    # Initialize client
    os.environ.setdefault("SECRET_KEY", "script-only-secret")

    if not json_output:
        print("Fetching orders from Shopify...\n")

    try:
        client = ShopifyGraphQLClient()
    except Exception as e:
        print(f"Error initializing Shopify client: {e}")
        print("\nPossible issues:")
        print("  - Check SHOPIFY_SHOP_URL in .env")
        print("  - Check SHOPIFY_ADMIN_API_ACCESS_TOKEN in .env")
        return []

    # Fetch orders
    orders = fetch_orders_sync(client, max_orders)

    if not json_output:
        print(f"\nFetched {len(orders)} orders\n")

    # Insert into database if requested
    if insert_db:
        async with async_session() as db:
            summary = await upsert_orders(db, orders)
            # Process orders for inventory management
            processor = OrderSaleProcessor(db)
            sale_summary = await processor.process_unprocessed_orders("shopify", dry_run=False)
            await db.commit()
        if not json_output:
            print(f"DB upsert summary: {summary}")
            print(f"Sale processing: {sale_summary['sales_detected']} sales detected, "
                  f"{sale_summary['quantity_decrements']} quantity decrements")

    # Save to file if requested
    if save_to_file:
        output_dir = Path(__file__).parent / "output"
        output_dir.mkdir(exist_ok=True)

        output_file = output_dir / "all_orders.json"
        output_data = {
            "total_orders": len(orders),
            "fetch_date": datetime.now().isoformat(),
            "orders": orders
        }

        with open(output_file, 'w') as f:
            json.dump(output_data, f, indent=2, default=str)

        print(f"Saved {len(orders)} orders to {output_file}")
        if not json_output:
            print(f"   File size: {output_file.stat().st_size / 1024:.1f} KB")
        return orders

    if json_output:
        output = {
            "total_orders": len(orders),
            "orders": orders
        }
        print(json.dumps(output, indent=2, default=str))
    else:
        # Format and display orders
        print("-" * 80)

        for idx, order in enumerate(orders, 1):
            order_name = order.get('name', 'N/A')
            status = order.get('displayFinancialStatus', 'N/A')
            fulfillment = order.get('displayFulfillmentStatus', 'N/A')
            created_at = order.get('createdAt', 'N/A')

            total_set = order.get('totalPriceSet', {}).get('shopMoney', {})
            total = f"£{float(total_set.get('amount', 0)):,.2f}" if total_set.get('amount') else 'N/A'

            customer = order.get('customer', {})
            customer_name = f"{customer.get('firstName', '')} {customer.get('lastName', '')}".strip() or 'Guest'

            # Parse date
            if created_at != 'N/A':
                try:
                    dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                    created_at = dt.strftime('%Y-%m-%d %H:%M')
                except:
                    pass

            print(f"Order #{idx}: {order_name}")
            print(f"  Status: {status} | Fulfillment: {fulfillment}")
            print(f"  Date: {created_at}")
            print(f"  Customer: {customer_name}")
            print(f"  Total: {total}")

            # Show line items
            line_items = (order.get('lineItems') or {}).get('edges', [])
            if line_items:
                print(f"  Items ({len(line_items)}):")
                for item_edge in line_items:
                    item = item_edge.get('node', item_edge)
                    title = item.get('title', 'N/A')
                    sku = item.get('sku', 'N/A')
                    qty = item.get('quantity', 1)

                    if detailed:
                        price_set = (item.get('originalUnitPriceSet') or {}).get('shopMoney', {})
                        price = f"£{float(price_set.get('amount', 0)):,.2f}" if price_set.get('amount') else 'N/A'
                        print(f"    - {title}")
                        print(f"      SKU: {sku} | Qty: {qty} | Price: {price}")
                    else:
                        if len(title) > 50:
                            title = title[:47] + "..."
                        print(f"    - [{sku}] {title} (x{qty})")

            # Tracking info if detailed
            if detailed:
                fulfillments = order.get('fulfillments', [])
                for f in fulfillments:
                    tracking_info = f.get('trackingInfo', [])
                    for t in tracking_info:
                        print(f"  Tracking: {t.get('company', 'N/A')} - {t.get('number', 'N/A')}")

            print("-" * 80)

            # Limit display in non-detailed mode
            if not detailed and idx >= 20:
                remaining = len(orders) - 20
                if remaining > 0:
                    print(f"\n... and {remaining} more orders (use --detailed to see all)")
                break

    return orders


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch orders from Shopify.")
    parser.add_argument("--limit", type=int, default=50, help="Maximum number of orders to fetch.")
    parser.add_argument("--all", action="store_true", help="Fetch all orders (no limit).")
    parser.add_argument("--json", action="store_true", help="Output as JSON.")
    parser.add_argument("--detailed", action="store_true", help="Show detailed information.")
    parser.add_argument("--save", action="store_true", help="Save orders to scripts/shopify/output/all_orders.json.")
    parser.add_argument("--insert-db", action="store_true", help="Upsert orders into the shopify_orders table.")

    args = parser.parse_args()

    max_orders = None if args.all else args.limit

    asyncio.run(
        get_shopify_orders(
            max_orders=max_orders,
            json_output=args.json,
            detailed=args.detailed,
            save_to_file=args.save,
            insert_db=args.insert_db,
        )
    )
