#!/usr/bin/env python3
"""Convert Seller Hub "Orders" CSV exports into pseudo GetOrders JSON."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

OUTPUT_DIR = Path(__file__).resolve().parent / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def _clean_amount(raw: Any) -> str:
    if raw is None:
        return "0"
    text = str(raw).strip()
    if not text:
        return "0"
    for symbol in ["£", ",", "$"]:
        text = text.replace(symbol, "")
    return text.strip() or "0"


def _currency_block(value: Any, currency: str = "GBP") -> Dict[str, Any]:
    return {"@currencyID": currency, "#text": _clean_amount(value)}


def _build_transaction(row: Dict[str, Any], currency: str) -> Dict[str, Any]:
    buyer_name = row.get("Buyer name") or ""
    parts = buyer_name.split()
    first_name = parts[0] if parts else None
    last_name = " ".join(parts[1:]) if len(parts) > 1 else None

    return {
        "Buyer": {
            "Email": row.get("Buyer email"),
            "UserFirstName": first_name,
            "UserLastName": last_name,
        },
        "CreatedDate": row.get("Sale date"),
        "Item": {
            "ItemID": row.get("Item number"),
            "Title": row.get("Item title"),
            "SKU": row.get("Custom label"),
            "Location": row.get("Item location"),
        },
        "QuantityPurchased": str(row.get("Quantity")) if row.get("Quantity") not in (None, "") else None,
        "TransactionPrice": _currency_block(row.get("Sold for"), currency),
        "ActualShippingCost": _currency_block(row.get("Postage and packaging"), currency),
        "TransactionID": row.get("Transaction ID") or row.get("Global Shipping Reference ID"),
        "ShippingServiceSelected": {
            "ShippingService": row.get("Delivery service"),
            "ShipmentTrackingDetails": {
                "ShippingCarrierUsed": row.get("Delivery service"),
                "ShipmentTrackingNumber": row.get("Tracking number"),
            },
        },
        "ShippedTime": row.get("Dispatched on date"),
    }


def _build_order(order_id: str, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    first = rows[0]
    currency = "GBP"
    shipping_address = {
        "Name": first.get("Post to name"),
        "Street1": first.get("Post to address 1"),
        "Street2": first.get("Post to address 2"),
        "CityName": first.get("Post to city"),
        "StateOrProvince": first.get("Post to county"),
        "PostalCode": first.get("Post to postcode"),
        "CountryName": first.get("Post to country"),
    }

    transactions = [_build_transaction(r, currency) for r in rows]
    transaction_payload: Any
    if len(transactions) == 1:
        transaction_payload = transactions[0]
    else:
        transaction_payload = transactions

    total_price = first.get("Total price") or first.get("Sold for")

    order = {
        "OrderID": order_id,
        "OrderStatus": "Completed" if first.get("Dispatched on date") else "Active",
        "BuyerUserID": first.get("Buyer username"),
        "BuyerEmail": first.get("Buyer email"),
        "CreatedTime": first.get("Sale date"),
        "PaidTime": first.get("Paid on date"),
        "ShippedTime": first.get("Dispatched on date"),
        "ShippingAddress": shipping_address,
        "ShippingServiceSelected": {
            "ShippingService": first.get("Delivery service"),
            "ShippingServiceCost": _currency_block(first.get("Postage and packaging"), currency),
        },
        "Total": _currency_block(total_price, currency),
        "TransactionArray": {"Transaction": transaction_payload},
        "MonetaryDetails": {
            "Payments": {
                "Payment": {
                    "PaymentStatus": "Succeeded" if first.get("Paid on date") else "Pending",
                    "PaymentTime": first.get("Paid on date"),
                    "PaymentAmount": _currency_block(total_price, currency),
                }
            }
        },
    }

    return order


def convert_csv(path: Path) -> List[Dict[str, Any]]:
    df = pd.read_csv(path, header=1, dtype=str)
    df = df.fillna("")
    orders: List[Dict[str, Any]] = []

    def key_for_row(row: Dict[str, Any]) -> Optional[str]:
        order_no = str(row.get("Order number") or "").strip()
        if order_no:
            return order_no
        srn = str(row.get("Sales record number") or "").strip()
        if srn:
            return f"SRN-{srn}"
        return None

    grouped_orders: Dict[str, List[Dict[str, Any]]] = {}
    for _, record in df.iterrows():
        key = key_for_row(record)
        if not key:
            continue
        grouped_orders.setdefault(key, []).append(record.to_dict())

    for order_id, records in grouped_orders.items():
        orders.append(_build_order(order_id, records))

    return orders


def write_json(data: List[Dict[str, Any]], source: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = OUTPUT_DIR / f"legacy_orders_{timestamp}.json"
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    print(f"💾 Wrote {len(data)} orders to {out_path}")
    print(f"📁 Source CSV: {source}")
    return out_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert Seller Hub orders CSV to JSON")
    parser.add_argument("csv_path", help="Path to Seller Hub orders CSV export")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    csv_path = Path(args.csv_path)
    if not csv_path.exists():
        raise SystemExit(f"CSV not found: {csv_path}")

    orders = convert_csv(csv_path)
    if not orders:
        print("⚠️ No rows found in CSV")
        return

    write_json(orders, csv_path)


if __name__ == "__main__":
    main()
