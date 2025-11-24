#!/usr/bin/env python3
"""
Get sold orders from Reverb.

This script fetches sold orders from your Reverb account, with options to:
- Limit the number of pages fetched
- Output as JSON or formatted text
- Save to a JSON file
- Show summary or detailed information

Usage:
    python scripts/reverb/get_reverb_sold_orders.py [--pages N] [--json] [--detailed] [--save]
    
Examples:
    # Get first page of sold orders (50 orders)
    python scripts/reverb/get_reverb_sold_orders.py
    
    # Get first 3 pages (up to 150 orders)
    python scripts/reverb/get_reverb_sold_orders.py --pages 3
    
    # Get all orders as JSON
    python scripts/reverb/get_reverb_sold_orders.py --pages all --json
    
    # Save ALL orders to scripts/reverb/output/all_orders.json
    python scripts/reverb/get_reverb_sold_orders.py --pages all --save
    
    # Get detailed view of first page
    python scripts/reverb/get_reverb_sold_orders.py --detailed
"""

import argparse
import asyncio
import json
import os
import sys
from decimal import Decimal
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, Any

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent.parent))

from sqlalchemy import select

from app.services.reverb.client import ReverbClient
from app.core.config import get_settings
from app.database import async_session
from app.models.reverb_order import ReverbOrder
from app.models.platform_common import PlatformCommon

def _parse_decimal(value: Any) -> Optional[Decimal]:
    if value in (None, "", "null"):
        return None
    try:
        if isinstance(value, dict) and "amount" in value:
            value = value.get("amount")
        return Decimal(str(value))
    except Exception:
        return None


def _parse_datetime(value: Any) -> Optional[datetime]:
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


async def _resolve_platform_common(
    db, listing_id: Optional[str]
) -> Dict[str, Optional[int]]:
    if not listing_id:
        return {"platform_listing_id": None, "product_id": None}
    result = await db.execute(
        select(PlatformCommon).where(
            PlatformCommon.platform_name == "reverb",
            PlatformCommon.external_id == str(listing_id),
        )
    )
    pc = result.scalar_one_or_none()
    if not pc:
        return {"platform_listing_id": None, "product_id": None}
    return {"platform_listing_id": pc.id, "product_id": pc.product_id}


def _extract_presentment(order: Dict[str, Any]) -> Dict[str, Any]:
    keys = [
        "presentment_amount_total",
        "presentment_amount_product",
        "presentment_amount_shipping",
        "presentment_amount_product_subtotal",
        "presentment_amount_tax",
    ]
    return {k: order.get(k) for k in keys if k in order}


async def upsert_orders(db, orders):
    summary = {"fetched": len(orders), "inserted": 0, "updated": 0, "skipped": 0, "errors": 0}
    for order in orders:
        try:
            order_uuid = (order.get("uuid") or order.get("order_number") or "").strip()
            if not order_uuid:
                summary["skipped"] += 1
                continue

            listing_id = order.get("product_id")

            existing = (
                await db.execute(
                    select(ReverbOrder).where(ReverbOrder.order_uuid == order_uuid)
                )
            ).scalar_one_or_none()

            presentment = _extract_presentment(order)
            amounts = {
                "amount_product": _parse_decimal(order.get("amount_product")),
                "amount_product_currency": (order.get("amount_product") or {}).get("currency") if isinstance(order.get("amount_product"), dict) else None,
                "amount_product_subtotal": _parse_decimal(order.get("amount_product_subtotal")),
                "amount_product_subtotal_currency": (order.get("amount_product_subtotal") or {}).get("currency") if isinstance(order.get("amount_product_subtotal"), dict) else None,
                "shipping_amount": _parse_decimal(order.get("shipping")),
                "shipping_currency": (order.get("shipping") or {}).get("currency") if isinstance(order.get("shipping"), dict) else None,
                "tax_amount": _parse_decimal(order.get("amount_tax")),
                "tax_currency": (order.get("amount_tax") or {}).get("currency") if isinstance(order.get("amount_tax"), dict) else None,
                "total_amount": _parse_decimal(order.get("total")),
                "total_currency": (order.get("total") or {}).get("currency") if isinstance(order.get("total"), dict) else None,
                "direct_checkout_fee_amount": _parse_decimal(order.get("direct_checkout_fee")),
                "direct_checkout_fee_currency": (order.get("direct_checkout_fee") or {}).get("currency") if isinstance(order.get("direct_checkout_fee"), dict) else None,
                "direct_checkout_payout_amount": _parse_decimal(order.get("direct_checkout_payout")),
                "direct_checkout_payout_currency": (order.get("direct_checkout_payout") or {}).get("currency") if isinstance(order.get("direct_checkout_payout"), dict) else None,
                "tax_on_fees_amount": _parse_decimal(order.get("tax_on_fees")),
                "tax_on_fees_currency": (order.get("tax_on_fees") or {}).get("currency") if isinstance(order.get("tax_on_fees"), dict) else None,
            }

            linkage = await _resolve_platform_common(db, listing_id)

            data = {
                "order_uuid": order_uuid,
                "order_number": order.get("order_number"),
                "order_bundle_id": order.get("order_bundle_id"),
                "reverb_listing_id": listing_id,
                "title": order.get("title"),
                "shop_name": order.get("shop_name"),
                "sku": order.get("sku"),
                "status": order.get("status"),
                "order_type": order.get("order_type"),
                "order_source": order.get("order_source"),
                "shipment_status": order.get("shipment_status"),
                "shipping_method": order.get("shipping_method"),
                "payment_method": order.get("payment_method"),
                "local_pickup": bool(order.get("local_pickup")),
                "needs_feedback_for_buyer": bool(order.get("needs_feedback_for_buyer")),
                "needs_feedback_for_seller": bool(order.get("needs_feedback_for_seller")),
                "shipping_taxed": bool(order.get("shipping_taxed")),
                "tax_responsible_party": order.get("tax_responsible_party"),
                "tax_rate": _parse_decimal(order.get("tax_rate")),
                "quantity": order.get("quantity"),
                "buyer_id": order.get("buyer_id"),
                "buyer_name": order.get("buyer_name"),
                "buyer_first_name": order.get("buyer_first_name"),
                "buyer_last_name": order.get("buyer_last_name"),
                "buyer_email": order.get("buyer_email"),
                "shipping_name": (order.get("shipping_address") or {}).get("name"),
                "shipping_phone": (order.get("shipping_address") or {}).get("phone") or (order.get("shipping_address") or {}).get("unformatted_phone"),
                "shipping_city": (order.get("shipping_address") or {}).get("locality"),
                "shipping_region": (order.get("shipping_address") or {}).get("region"),
                "shipping_postal_code": (order.get("shipping_address") or {}).get("postal_code"),
                "shipping_country_code": (order.get("shipping_address") or {}).get("country_code"),
                "created_at": _parse_datetime(order.get("created_at")),
                "paid_at": _parse_datetime(order.get("paid_at")),
                "updated_at": _parse_datetime(order.get("updated_at")),
                **amounts,
                "shipping_address": order.get("shipping_address"),
                "order_notes": order.get("order_notes"),
                "photos": order.get("photos"),
                "links": order.get("_links"),
                "presentment_amounts": presentment,
                "raw_payload": order,
                "product_id": linkage["product_id"],
                "platform_listing_id": linkage["platform_listing_id"],
            }

            if existing:
                for key, value in data.items():
                    setattr(existing, key, value)
                summary["updated"] += 1
            else:
                db.add(ReverbOrder(**data))
                summary["inserted"] += 1

        except Exception:
            await db.rollback()
            summary["errors"] += 1
            continue

    await db.commit()
    return summary


async def get_sold_orders(
    max_pages: Optional[int] = 1,
    per_page: int = 50,
    json_output: bool = False,
    detailed: bool = False,
    save_to_file: bool = False,
    insert_db: bool = False,
):
    """
    Fetch and display sold orders from Reverb.
    
    Args:
        max_pages: Number of pages to fetch (None for all)
        json_output: If True, output as JSON
        detailed: If True, show detailed information for each order
    """
    # Allow the script to run without a SECRET_KEY present
    os.environ.setdefault("SECRET_KEY", "script-only-secret")
    settings = get_settings()
    client = ReverbClient(api_key=settings.REVERB_API_KEY)
    
    # First get the total count
    if not json_output:
        print("📊 Fetching sold orders from Reverb...\n")
    
    try:
        # Get total count with a minimal request
        test_response = await client._make_request(
            "GET", "/my/orders/selling/all", params={"per_page": 1}
        )
        total_orders = test_response.get('total', 0)
    except Exception as e:
        print(f"❌ Error accessing Reverb Orders API: {e}")
        print("\nPossible issues:")
        print("  • Check your REVERB_API_KEY in .env")
        print("  • Ensure the API key has order read permissions")
        print("  • The account may not have seller privileges")
        return []
    total_pages = (total_orders + per_page - 1) // per_page  # per_page per page
    
    if not json_output:
        print(f"📦 Total sold orders: {total_orders}")
        print(f"📄 Total pages: {total_pages}")
        
        if max_pages:
            pages_to_fetch = min(max_pages, total_pages)
            print(f"🔍 Fetching {pages_to_fetch} page(s) (up to {pages_to_fetch * per_page} orders)\n")
        else:
            print(f"🔍 Fetching ALL {total_pages} pages\n")
    
    # Fetch the orders
    orders = await client.get_all_sold_orders(per_page=per_page, max_pages=max_pages)

    if insert_db:
        async with async_session() as db:
            summary = await upsert_orders(db, orders)
        if not json_output:
            print(f"\n💾 DB upsert summary: {summary}")
    
    # Save to file if requested
    if save_to_file:
        # Create output directory if it doesn't exist
        output_dir = Path(__file__).parent / "output"
        output_dir.mkdir(exist_ok=True)
        
        # Save to all_orders.json
        output_file = output_dir / "all_orders.json"
        output_data = {
            "total_orders": total_orders,
            "fetched_orders": len(orders),
            "fetch_date": datetime.now().isoformat(),
            "orders": orders
        }
        
        with open(output_file, 'w') as f:
            json.dump(output_data, f, indent=2, default=str)
        
        print(f"✅ Saved {len(orders)} orders to {output_file}")
        if not json_output:
            print(f"   File size: {output_file.stat().st_size / 1024:.1f} KB")
        return orders
    
    if json_output:
        # Output as JSON
        output = {
            "total_orders": total_orders,
            "fetched_orders": len(orders),
            "orders": orders
        }
        print(json.dumps(output, indent=2, default=str))
    else:
        # Format and display orders
        print(f"✅ Fetched {len(orders)} orders\n")
        print("-" * 80)
        
        for idx, order in enumerate(orders, 1):
            # Basic order info
            order_number = order.get('order_number', 'N/A')
            status = order.get('status', 'N/A')
            created_at = order.get('created_at', 'N/A')
            buyer_name = order.get('buyer', {}).get('name', 'N/A')
            total = order.get('total', {}).get('display', 'N/A')
            
            # Parse date if available
            if created_at != 'N/A':
                try:
                    dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                    created_at = dt.strftime('%Y-%m-%d %H:%M')
                except:
                    pass
            
            print(f"Order #{idx}: {order_number}")
            print(f"  Status: {status}")
            print(f"  Date: {created_at}")
            print(f"  Buyer: {buyer_name}")
            print(f"  Total: {total}")
            
            # Show listings in the order
            listings = order.get('listings', [])
            if listings:
                print(f"  Items ({len(listings)}):")
                for listing in listings:
                    listing_id = listing.get('id', 'N/A')
                    title = listing.get('title', 'N/A')
                    sku = listing.get('sku', 'N/A')
                    price = listing.get('price', {}).get('display', 'N/A')
                    
                    if detailed:
                        print(f"    • [{listing_id}] {title}")
                        print(f"      SKU: {sku}")
                        print(f"      Price: {price}")
                    else:
                        # Truncate title if too long
                        if len(title) > 50:
                            title = title[:47] + "..."
                        print(f"    • [{listing_id}] {title} (SKU: {sku})")
            
            # Shipping info if detailed
            if detailed:
                shipping_method = order.get('shipping_method', 'N/A')
                tracking = order.get('shipment_tracking_number', 'N/A')
                if shipping_method != 'N/A':
                    print(f"  Shipping: {shipping_method}")
                if tracking != 'N/A':
                    print(f"  Tracking: {tracking}")
            
            print("-" * 80)
            
            # Limit display in non-detailed mode
            if not detailed and idx >= 20:
                remaining = len(orders) - 20
                if remaining > 0:
                    print(f"\n... and {remaining} more orders (use --detailed to see all)")
                break
    
    return orders

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch sold orders from Reverb.")
    parser.add_argument("--pages", type=str, default="1", help="Number of pages to fetch (number or 'all').")
    parser.add_argument("--per-page", type=int, default=50, help="Orders per page (default 50; Reverb max is 50).")
    parser.add_argument("--json", action="store_true", help="Output as JSON.")
    parser.add_argument("--detailed", action="store_true", help="Show detailed information.")
    parser.add_argument("--save", action="store_true", help="Save all fetched orders to scripts/reverb/output/all_orders.json.")
    parser.add_argument("--insert-db", action="store_true", help="Upsert fetched orders into the reverb_orders table.")

    args = parser.parse_args()

    # Pages parsing
    if args.pages.lower() == "all":
        max_pages = None
    else:
        try:
            max_pages = int(args.pages)
        except ValueError:
            print(f"Error: Invalid pages value '{args.pages}'. Use a number or 'all'.")
            sys.exit(1)

    per_page = args.per_page if args.per_page and args.per_page > 0 else 50

    asyncio.run(
        get_sold_orders(
            max_pages=max_pages,
            per_page=per_page,
            json_output=args.json,
            detailed=args.detailed,
            save_to_file=args.save,
            insert_db=args.insert_db,
        )
    )
