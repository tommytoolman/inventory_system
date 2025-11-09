#!/usr/bin/env python3
"""Fetch eBay orders via the Trading API (GetOrders)."""
from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

import sys
project_root = Path(__file__).resolve().parents[2]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from app.services.ebay.trading import EbayTradingLegacyAPI

OUTPUT_DIR = Path(__file__).resolve().parent / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def _parse_date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Invalid ISO datetime: {value}") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _extract_amount(node: Dict[str, Any]) -> Dict[str, Optional[str]]:
    if not isinstance(node, dict):
        return {"amount": node, "currency": None}
    return {
        "amount": node.get("#text") or node.get("value"),
        "currency": node.get("@currencyID") or node.get("currencyID"),
    }


def _flatten_order(order: Dict[str, Any]) -> Dict[str, Any]:
    total_info = _extract_amount(order.get("Total", {}))

    buyer_info = order.get("Buyer", {}) if isinstance(order.get("Buyer"), dict) else {}
    buyer_email = order.get("BuyerEmail") or buyer_info.get("Email")
    buyer_name = buyer_info.get("UserFirstName")

    shipping_address = order.get("ShippingAddress", {}) or {}
    shipping_service = order.get("ShippingServiceSelected", {}) or {}
    shipping_cost_info = _extract_amount(shipping_service.get("ShippingServiceCost", {}))

    checkout_status = order.get("CheckoutStatus", {}) or {}
    payment_methods = order.get("PaymentMethods")
    if isinstance(payment_methods, list):
        payment_methods_str = ", ".join(payment_methods)
    else:
        payment_methods_str = payment_methods

    line_items = order.get("TransactionArray", {}).get("Transaction", [])
    if isinstance(line_items, dict):
        line_items = [line_items]

    sku_list: List[str] = []
    titles: List[str] = []
    item_ids: List[str] = []
    quantities: List[str] = []
    prices: List[str] = []
    line_rows: List[Dict[str, Any]] = []

    for tx in line_items:
        item = tx.get("Item", {}) or {}
        sku = tx.get("SKU") or item.get("SKU")
        title = item.get("Title")
        ebay_item_id = item.get("ItemID")
        quantity = tx.get("QuantityPurchased") or tx.get("Quantity")
        price_info = _extract_amount(tx.get("TransactionPrice", {}) or item.get("StartPrice", {}))

        if sku:
            sku_list.append(str(sku))
        if title:
            titles.append(title)
        if ebay_item_id:
            item_ids.append(str(ebay_item_id))
        if quantity is not None:
            quantities.append(str(quantity))
        if price_info.get("amount"):
            price_str = f"{price_info['amount']} {price_info.get('currency') or ''}".strip()
            prices.append(price_str)

        line_rows.append(
            {
                "sku": sku,
                "title": title,
                "item_id": ebay_item_id,
                "quantity": quantity,
                "price": price_info.get("amount"),
                "price_currency": price_info.get("currency"),
            }
        )

    return {
        "order_id": order.get("OrderID"),
        "status": order.get("OrderStatus"),
        "buyer": order.get("BuyerUserID") or buyer_info.get("UserID"),
        "buyer_email": buyer_email,
        "buyer_name": buyer_name,
        "created": order.get("CreatedTime"),
        "paid_time": order.get("PaidTime"),
        "shipped_time": order.get("ShippedTime"),
        "checkout_status": checkout_status.get("Status"),
        "payment_status": checkout_status.get("PaymentStatus"),
        "payment_methods": payment_methods_str,
        "shipping_service": shipping_service.get("ShippingService"),
        "shipping_cost": shipping_cost_info.get("amount"),
        "shipping_cost_currency": shipping_cost_info.get("currency"),
        "ship_name": shipping_address.get("Name"),
        "ship_street1": shipping_address.get("Street1"),
        "ship_street2": shipping_address.get("Street2"),
        "ship_city": shipping_address.get("CityName"),
        "ship_state": shipping_address.get("StateOrProvince"),
        "ship_postal_code": shipping_address.get("PostalCode"),
        "ship_country": shipping_address.get("CountryName") or shipping_address.get("Country"),
        "currency": total_info.get("currency"),
        "amount": total_info.get("amount"),
        "skus": " | ".join(sku_list),
        "line_titles": " | ".join(titles),
        "line_item_ids": " | ".join(item_ids),
        "line_quantities": " | ".join(quantities),
        "line_prices": " | ".join(prices),
        "line_items_json": json.dumps(line_rows),
    }


async def fetch_orders(args: argparse.Namespace) -> List[Dict[str, Any]]:
    api = EbayTradingLegacyAPI(sandbox=args.sandbox)

    created_from = _parse_date(args.created_from)
    created_to = _parse_date(args.created_to)
    mod_from = _parse_date(args.modified_from)
    mod_to = _parse_date(args.modified_to)

    number_of_days = args.days
    if created_from and created_to:
        number_of_days = None
    elif mod_from and mod_to:
        number_of_days = None
    elif number_of_days is None:
        number_of_days = 30

    orders: List[Dict[str, Any]] = []
    page = 1
    remaining = args.limit

    while True:
        response = await api.get_orders(
            number_of_days=number_of_days,
            created_time_from=created_from,
            created_time_to=created_to,
            last_modified_from=mod_from,
            last_modified_to=mod_to,
            order_status=args.status,
            order_role="Seller",
            entries_per_page=args.page_size,
            page_number=page,
        )

        batch = response.get("orders", [])
        if not batch:
            break

        orders.extend(batch)
        if remaining is not None and len(orders) >= remaining:
            orders = orders[:remaining]
            break

        if not response.get("has_more"):
            break

        page += 1

    return orders


def write_outputs(orders: List[Dict[str, Any]], args: argparse.Namespace) -> None:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    base_name = OUTPUT_DIR / f"ebay_orders_{timestamp}"

    if args.output in {"json", "both"}:
        json_path = base_name.with_suffix(".json")
        with json_path.open("w", encoding="utf-8") as fh:
            json.dump(orders, fh, indent=2)
        print(f"💾 Saved raw orders JSON to {json_path}")

    if args.output in {"csv", "both"}:
        rows = [_flatten_order(order) for order in orders]
        df = pd.DataFrame(rows)
        csv_path = base_name.with_suffix(".csv")
        df.to_csv(csv_path, index=False)
        print(f"💾 Saved flattened CSV to {csv_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch eBay orders via Trading API")
    parser.add_argument("--status", default="All", help="OrderStatus filter (All, Completed, Cancelled, Active)")
    parser.add_argument("--days", type=int, default=7, help="NumberOfDays lookback (ignored if date range provided)")
    parser.add_argument("--created-from", dest="created_from", help="ISO datetime for CreateTimeFrom")
    parser.add_argument("--created-to", dest="created_to", help="ISO datetime for CreateTimeTo")
    parser.add_argument("--modified-from", dest="modified_from", help="ISO datetime for ModTimeFrom")
    parser.add_argument("--modified-to", dest="modified_to", help="ISO datetime for ModTimeTo")
    parser.add_argument("--page-size", type=int, default=100, help="Entries per page (max 100)")
    parser.add_argument("--limit", type=int, help="Optional cap on total orders fetched")
    parser.add_argument("--output", choices=["json", "csv", "both"], default="both")
    parser.add_argument("--sandbox", action="store_true", help="Use eBay sandbox environment")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    print("🔄 Fetching eBay orders via Trading API...")
    if args.sandbox:
        print("🧪 Using SANDBOX environment")

    orders = await fetch_orders(args)
    print(f"✅ Retrieved {len(orders)} orders")

    if orders:
        write_outputs(orders, args)
    else:
        print("⚠️ No orders returned for the requested filter")


if __name__ == "__main__":
    asyncio.run(main())
