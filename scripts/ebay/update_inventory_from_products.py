#!/usr/bin/env python3
"""Push inventorised product quantities to the live eBay listings."""

import argparse
import asyncio
from typing import Any, Dict, List, Sequence

from sqlalchemy import text

from app.core.config import get_settings
from app.database import async_session
from app.services.ebay_service import EbayService


async def fetch_ebay_inventory_rows(session, skus: Sequence[str] | None = None) -> List[Dict[str, Any]]:
    query_str = """
        SELECT
            p.id,
            p.sku,
            p.quantity,
            p.is_stocked_item,
            pc.id AS platform_common_id,
            pc.external_id,
            el.quantity AS listing_quantity,
            el.quantity_available,
        el.listing_data
        FROM products p
        JOIN platform_common pc ON pc.product_id = p.id
        JOIN ebay_listings el ON el.platform_id = pc.id
        WHERE pc.platform_name = 'ebay'
          AND p.is_stocked_item = true
    """

    params: Dict[str, Any] = {}
    if skus:
        placeholders = ", ".join(f":sku_{i}" for i in range(len(skus)))
        query_str += f" AND p.sku IN ({placeholders})"
        params.update({f"sku_{i}": sku for i, sku in enumerate(skus)})

    query_str += " ORDER BY p.sku"

    result = await session.execute(text(query_str), params)
    return [row._asdict() for row in result.fetchall()]


def has_variations(listing_payload: Dict[str, Any] | None) -> bool:
    if not listing_payload:
        return False

    item = listing_payload.get('Item') if isinstance(listing_payload, dict) else None
    if item and isinstance(item, dict):
        return bool(item.get('Variations'))

    return False


def coerce_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


async def update_ebay_inventory(skus: Sequence[str] | None = None, dry_run: bool = False) -> None:
    settings = get_settings()

    async with async_session() as session:
        rows = await fetch_ebay_inventory_rows(session, skus)

        if not rows:
            print("No eBay listings found for the given criteria.")
            return

        service = EbayService(session, settings)

        for row in rows:
            sku = row["sku"]
            product_qty = max(coerce_int(row.get("quantity")), 0)
            listing_qty = row.get("quantity_available")
            if listing_qty is None:
                listing_qty = row.get("listing_quantity")
            listing_qty = max(coerce_int(listing_qty), 0)

            external_id = row.get("external_id")
            if not external_id:
                print(f"[WARN] {sku}: missing eBay item ID; skipping")
                continue

            if has_variations(row.get("listing_data")):
                print(f"[WARN] {sku}: listing has variations; manual update required")
                continue

            if product_qty == listing_qty:
                print(f"[SKIP] {sku}: quantity already {product_qty}")
                continue

            if dry_run:
                print(
                    f"[DRY-RUN] {sku}: would update eBay item {external_id} from {listing_qty} to {product_qty}"
                )
                continue

            success = await service.update_listing_quantity(
                external_id,
                product_qty,
                platform_common_id=row.get("platform_common_id"),
                sku=sku,
            )

            if success:
                print(f"[OK] {sku}: set quantity {product_qty}")
            else:
                print(f"[ERROR] {sku}: failed to update quantity; see logs for details")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Push inventorised product quantities to their eBay listings"
    )
    parser.add_argument(
        "--sku",
        action="append",
        dest="skus",
        help="Limit the update to specific SKU(s); repeat for multiple",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview the changes without calling the eBay API",
    )

    args = parser.parse_args()

    asyncio.run(update_ebay_inventory(args.skus, dry_run=args.dry_run))
