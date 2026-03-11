#!/usr/bin/env python3
"""
Reconcile eBay orders against product status.

This script compares eBay orders in the database against product status to identify:
1. Completed orders for ACTIVE single-item products (missed sales)
2. Completed orders for inventorised products (qty adjustments needed)
3. Cancelled orders for SOLD products (potential relists)

Usage:
    python scripts/ebay/reconcile_ebay_orders.py [--fix] [--verbose]

Examples:
    # Dry run - just show discrepancies
    python scripts/ebay/reconcile_ebay_orders.py

    # Verbose output with details
    python scripts/ebay/reconcile_ebay_orders.py --verbose

    # Apply fixes for inventorised items (decrements qty)
    python scripts/ebay/reconcile_ebay_orders.py --fix
"""

import argparse
import asyncio
import sys
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent.parent))

from sqlalchemy import select, text
from app.database import async_session
from app.models.ebay_order import EbayOrder
from app.models.product import Product


async def get_discrepancies(verbose: bool = False) -> Dict[str, List[Dict[str, Any]]]:
    """
    Identify discrepancies between eBay orders and product status.

    Returns dict with:
        - missed_sales: Completed orders where single-item product is still ACTIVE
        - inventorised_adjustments: Completed orders for inventorised products needing qty sync
        - potential_relists: Cancelled orders where product is SOLD
        - ok_cancelled: Cancelled orders where product is correctly ACTIVE (info only)
    """
    results = {
        "missed_sales": [],
        "inventorised_adjustments": [],
        "potential_relists": [],
        "ok_cancelled": [],
    }

    async with async_session() as db:
        # Query all orders with linked products
        query = text("""
            SELECT
                eo.id as order_id,
                eo.order_id as ebay_order_id,
                eo.order_status,
                eo.primary_sku as sku,
                eo.quantity_purchased as order_qty,
                eo.total_amount,
                eo.created_at as order_date,
                eo.product_id,
                eo.item_id,
                p.status as product_status,
                p.quantity as product_qty,
                p.sku as product_sku,
                p.title as product_title
            FROM ebay_orders eo
            JOIN products p ON eo.product_id = p.id
            ORDER BY eo.created_at DESC
        """)

        result = await db.execute(query)
        orders = result.fetchall()

        for order in orders:
            title = order.product_title
            order_dict = {
                "order_id": order.order_id,
                "ebay_order_id": order.ebay_order_id,
                "order_status": order.order_status,
                "sku": order.sku or order.product_sku,
                "title": title[:60] + "..." if title and len(title) > 60 else title,
                "order_qty": order.order_qty,
                "total_amount": float(order.total_amount) if order.total_amount else None,
                "order_date": order.order_date.isoformat() if order.order_date else None,
                "product_id": order.product_id,
                "product_status": order.product_status,
                "product_qty": order.product_qty,
                "item_id": order.item_id,
            }

            # COMPLETED orders (eBay uses "Completed" for shipped/paid orders)
            if order.order_status == "Completed":
                if order.product_status == "ACTIVE":
                    # Is this inventorised (qty > 1) or single item?
                    if order.product_qty and order.product_qty > 1:
                        # Inventorised - needs qty adjustment
                        order_dict["action"] = "DECREMENT_QTY"
                        order_dict["decrement_by"] = order.order_qty or 1
                        results["inventorised_adjustments"].append(order_dict)
                    else:
                        # Single item still ACTIVE - missed sale!
                        order_dict["action"] = "MARK_SOLD"
                        results["missed_sales"].append(order_dict)
                # If product is already SOLD, that's correct - no action needed

            # CANCELLED orders
            elif order.order_status == "Cancelled":
                if order.product_status == "SOLD":
                    # Product marked sold but order was cancelled
                    order_dict["action"] = "REVIEW_RELIST"
                    results["potential_relists"].append(order_dict)
                elif order.product_status == "ACTIVE":
                    # Correct state - cancelled order, product still active
                    order_dict["action"] = "OK"
                    results["ok_cancelled"].append(order_dict)

    return results


def print_report(results: Dict[str, List], verbose: bool = False):
    """Print the reconciliation report."""

    print("\n" + "=" * 80)
    print("EBAY ORDERS RECONCILIATION REPORT")
    print(f"Generated: {datetime.now().isoformat()}")
    print("=" * 80)

    # Summary
    print("\n## SUMMARY")
    print(f"  Missed sales (single-item ACTIVE after complete):  {len(results['missed_sales'])}")
    print(f"  Inventorised qty adjustments needed:               {len(results['inventorised_adjustments'])}")
    print(f"  Potential relists (cancelled SOLD):                {len(results['potential_relists'])}")
    print(f"  OK cancelled (correctly ACTIVE):                   {len(results['ok_cancelled'])}")

    # Missed Sales - CRITICAL
    if results["missed_sales"]:
        print("\n" + "-" * 80)
        print("## MISSED SALES (Single-item products still ACTIVE)")
        print("   These orders completed but product was never marked SOLD")
        print("-" * 80)
        for item in results["missed_sales"]:
            print(f"  Order {item['ebay_order_id'][:20]}... | {item['order_status']}")
            print(f"    SKU: {item['sku']} | Product Status: {item['product_status']}")
            print(f"    Title: {item['title']}")
            print(f"    Total: £{item['total_amount']:,.2f}" if item['total_amount'] else "    Total: N/A")
            print(f"    Action: {item['action']}")
            print()

    # Inventorised Adjustments - ACTION REQUIRED
    if results["inventorised_adjustments"]:
        print("\n" + "-" * 80)
        print("## INVENTORISED QTY ADJUSTMENTS NEEDED")
        print("   These are multi-qty products that sold - need qty decrement")
        print("-" * 80)
        for item in results["inventorised_adjustments"]:
            print(f"  Order {item['ebay_order_id'][:20]}... | {item['order_status']}")
            print(f"    SKU: {item['sku']} | Current Qty: {item['product_qty']}")
            print(f"    Title: {item['title']}")
            print(f"    Action: Decrement by {item['decrement_by']} -> sync to Reverb/Shopify")
            print()

    # Potential Relists - USER REVIEW
    if results["potential_relists"]:
        print("\n" + "-" * 80)
        print("## POTENTIAL RELISTS (Cancelled but product is SOLD)")
        print("   Review these - may need to relist if stock still available")
        print("-" * 80)
        for item in results["potential_relists"]:
            print(f"  Order {item['ebay_order_id'][:20]}... | {item['order_status']}")
            print(f"    SKU: {item['sku']} | Product Status: {item['product_status']}")
            print(f"    Title: {item['title']}")
            print(f"    Action: USER REVIEW - consider relisting?")
            print()

    # OK Cancelled - info only
    if verbose and results["ok_cancelled"]:
        print("\n" + "-" * 80)
        print("## OK - CANCELLED ORDERS (Product correctly ACTIVE)")
        print("   No action needed - these are correct")
        print("-" * 80)
        for item in results["ok_cancelled"][:5]:  # Show first 5 only
            print(f"  Order {item['ebay_order_id'][:20]}... | {item['order_status']} | Product: {item['product_status']} | OK")
        if len(results["ok_cancelled"]) > 5:
            print(f"  ... and {len(results['ok_cancelled']) - 5} more")

    print("\n" + "=" * 80)


async def apply_inventorised_fixes(results: Dict[str, List], dry_run: bool = True) -> Dict[str, int]:
    """
    Apply qty decrements for inventorised items.

    Returns summary of actions taken.
    """
    summary = {"decremented": 0, "errors": 0, "skipped": 0}

    if not results["inventorised_adjustments"]:
        print("No inventorised adjustments to apply.")
        return summary

    async with async_session() as db:
        for item in results["inventorised_adjustments"]:
            try:
                product_id = item["product_id"]
                decrement = item["decrement_by"]

                # Get current product
                product = await db.get(Product, product_id)
                if not product:
                    print(f"  Product {product_id} not found - skipping")
                    summary["skipped"] += 1
                    continue

                new_qty = max(0, (product.quantity or 0) - decrement)

                if dry_run:
                    print(f"  [DRY RUN] Would decrement {item['sku']}: {product.quantity} -> {new_qty}")
                else:
                    product.quantity = new_qty
                    print(f"  Decremented {item['sku']}: {product.quantity + decrement} -> {new_qty}")

                    # If qty hits 0, should mark as SOLD
                    if new_qty == 0:
                        product.status = "SOLD"
                        print(f"    -> Qty hit 0, marked as SOLD")

                summary["decremented"] += 1

            except Exception as e:
                print(f"  Error processing {item['sku']}: {e}")
                summary["errors"] += 1

        if not dry_run:
            await db.commit()

    return summary


async def main():
    parser = argparse.ArgumentParser(description="Reconcile eBay orders against product status")
    parser.add_argument("--fix", action="store_true", help="Apply fixes for inventorised items")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show verbose output")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without making changes (default)")

    args = parser.parse_args()

    print("Fetching order discrepancies...")
    results = await get_discrepancies(verbose=args.verbose)

    print_report(results, verbose=args.verbose)

    if args.fix:
        print("\n" + "=" * 80)
        print("APPLYING FIXES")
        print("=" * 80)

        dry_run = args.dry_run or not args.fix
        summary = await apply_inventorised_fixes(results, dry_run=not args.fix)

        print(f"\nFix summary: {summary}")

        if not args.fix:
            print("\nRun with --fix to apply changes (inventorised qty decrements only)")


if __name__ == "__main__":
    asyncio.run(main())
