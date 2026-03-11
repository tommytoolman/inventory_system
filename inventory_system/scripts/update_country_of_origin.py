#!/usr/bin/env python3
"""
Update country-of-origin for products (DB + Shopify/Reverb/eBay) using the Excel workbook.

Usage:
    python scripts/update_country_of_origin.py --excel data/country_of_origin_work.xlsx --sku RIFF-10000160 --apply
    python scripts/update_country_of_origin.py --excel data/country_of_origin_work.xlsx --sku-range RIFF-10000150:RIFF-10000180 --apply
    python scripts/update_country_of_origin.py --excel data/country_of_origin_work.xlsx --reverb-id 93031521 --apply

Without --apply it runs in dry-run mode (just prints what would happen).
"""
from __future__ import annotations

import argparse
import asyncio
import re
from pathlib import Path
from typing import Iterable, List, Optional, Set

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import select, func

from app.core.config import Settings, get_settings
from app.core.enums import ManufacturingCountry
from app.database import async_session
from app.models.platform_common import PlatformCommon
from app.models.product import Product
from app.services.ebay_service import EbayService
from app.services.reverb_service import ReverbService
from app.services.shopify_service import ShopifyService

load_dotenv()


def normalize_country(value: Optional[str]) -> Optional[str]:
    """Convert long-form names into ISO codes that match our ManufacturingCountry enum."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    mapping = {
        "australia": "AU",
        "china": "CN",
        "mexico": "MX",
        "south korea": "KR",
        "korea": "KR",
        "uk": "GB",
        "united kingdom": "GB",
        "usa": "US",
        "united states": "US",
    }
    lowered = text.lower()
    return mapping.get(lowered, text.upper())


def _parse_sku_parts(value: str) -> tuple[str, int, int]:
    match = re.match(r"^(?P<prefix>[^\d]+?)(?P<number>\d+)$", value.strip())
    if not match:
        raise ValueError(f"SKU '{value}' must end with digits to use range mode.")
    prefix = match.group("prefix")
    number_str = match.group("number")
    return prefix, int(number_str), len(number_str)


def expand_sku_range(expr: str) -> List[str]:
    if ":" not in expr:
        raise ValueError("SKU range must be in the format START:END (e.g., RIFF-10000150:RIFF-10000180).")
    start_raw, end_raw = [part.strip() for part in expr.split(":", 1)]
    prefix_start, num_start, width_start = _parse_sku_parts(start_raw)
    prefix_end, num_end, width_end = _parse_sku_parts(end_raw)
    if prefix_start != prefix_end:
        raise ValueError(f"SKU prefixes do not match: '{prefix_start}' vs '{prefix_end}'.")
    if num_end < num_start:
        raise ValueError("SKU range END must be greater than or equal to START.")
    width = max(width_start, width_end)
    return [
        f"{prefix_start}{str(num).zfill(width)}"
        for num in range(num_start, num_end + 1)
    ]


async def update_single_product(
    sku: Optional[str],
    country_code: str,
    apply: bool,
    settings: Settings,
    ebay_id: Optional[int] = None,
) -> None:
    async with async_session() as session:
        services = {
            "ebay": EbayService(session, settings),
            "reverb": ReverbService(session, settings),
            "shopify": ShopifyService(session, settings),
        }

        product_obj = None
        normalized_sku = sku.strip() if sku else None
        if normalized_sku:
            product_result = await session.execute(
                select(Product).where(func.lower(Product.sku) == normalized_sku.lower())
            )
            product_obj = product_result.scalar_one_or_none()

        if not product_obj and ebay_id is not None:
            platform_result = await session.execute(
                select(PlatformCommon).where(
                    PlatformCommon.platform_name == "ebay",
                    PlatformCommon.external_id == str(ebay_id),
                )
            )
            platform_link = platform_result.scalar_one_or_none()
            if platform_link:
                product_obj = await session.get(Product, platform_link.product_id)

        if not product_obj:
            identifier = normalized_sku or f"eBay ID {ebay_id}"
            print(f"[WARN] {identifier} not found in products table.")
            return

        product_id = product_obj.id
        try:
            enum_value = ManufacturingCountry(country_code.upper())
        except ValueError:
            print(f"[WARN] SKU {sku}: {country_code} is not a valid ManufacturingCountry.")
            return

        if not apply:
            print(f"[DRY-RUN] Would set {sku} manufacturing_country -> {enum_value.value}")
            return

        product_obj.manufacturing_country = enum_value.value
        await session.commit()
        print(f"[OK] Updated manufacturing_country for {sku} to {enum_value.value}")

        platform_stmt = await session.execute(
            select(PlatformCommon).where(PlatformCommon.product_id == product_id)
        )
        platform_links = platform_stmt.scalars().all()

        changed_fields: Set[str] = {"manufacturing_country"}
        product_payload = Product(
            id=product_id, sku=product_obj.sku, manufacturing_country=enum_value
        )

        for platform_link in platform_links:
            if platform_link.platform_name == "ebay":
                await services["ebay"].apply_product_update(
                    product_payload,
                    platform_link,
                    changed_fields,
                )
                print(f"[OK] Synced eBay country for {sku}")
            elif platform_link.platform_name == "reverb":
                await services["reverb"].apply_product_update(
                    product_payload,
                    platform_link,
                    changed_fields,
                )
                print(f"[OK] Synced Reverb country for {sku}")
            elif platform_link.platform_name == "shopify":
                await services["shopify"].apply_product_update(
                    product_payload,
                    platform_link,
                    changed_fields,
                )
                print(f"[OK] Synced Shopify country for {sku}")


def load_dataframe(path: Path) -> pd.DataFrame:
    df = pd.read_excel(path)
    if "validated_country_code" not in df.columns:
        df["validated_country_code"] = df["origin_country_code"].apply(normalize_country)
    return df


def filter_rows(
    df: pd.DataFrame,
    sku_targets: Optional[List[str]],
    reverb_id: Optional[int],
    ebay_ids: Optional[List[int]],
) -> Iterable[pd.Series]:
    data = df
    if sku_targets:
        sku_series = data["sku"].astype(str)
        target_upper_map = {sku.upper(): sku for sku in sku_targets}
        target_upper = set(target_upper_map.keys())
        sku_upper = sku_series.str.upper()
        existing_upper = set(sku_upper[sku_upper.isin(target_upper)])
        missing = sorted(target_upper - existing_upper)
        for sku_upper_val in missing:
            print(f"[WARN] SKU {target_upper_map[sku_upper_val]} not found in spreadsheet; skipping.")
        mask = sku_upper.isin(target_upper)
        data = data[mask]
    if reverb_id is not None:
        data = data[data["reverb_id"] == reverb_id]
    if ebay_ids:
        ebay_series = (
            pd.to_numeric(data["ebay_id"], errors="coerce")
            .astype("Int64")
        )
        target_set = set(int(e) for e in ebay_ids)
        mask = ebay_series.isin(target_set)
        missing = sorted(target_set - set(ebay_series[mask].dropna().astype(int)))
        for eid in missing:
            print(f"[WARN] eBay ID {eid} not found in spreadsheet; skipping.")
        data = data[mask]
    return data.itertuples(index=False)


async def main():
    parser = argparse.ArgumentParser(description="Update country of origin across platforms.")
    parser.add_argument("--excel", type=Path, required=True, help="Path to country_of_origin_work.xlsx")
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--sku",
        nargs="+",
        help="Update one or more specific SKUs (space-separated)",
    )
    group.add_argument(
        "--sku-range",
        help="Process SKUs from START:END inclusive (e.g., RIFF-10000150:RIFF-10000180). Missing SKUs are skipped.",
    )
    group.add_argument("--reverb-id", type=int, help="Update only this Reverb listing ID")
    parser.add_argument(
        "--ebay-id",
        nargs="+",
        type=int,
        help="Update rows matching these eBay item IDs",
    )
    parser.add_argument("--apply", action="store_true", help="Persist changes; otherwise dry-run")
    args = parser.parse_args()

    df = load_dataframe(args.excel)
    settings = get_settings()
    sku_targets: Optional[List[str]] = None
    if args.sku:
        sku_targets = args.sku
    elif args.sku_range:
        try:
            sku_targets = expand_sku_range(args.sku_range)
        except ValueError as exc:
            print(f"[ERROR] {exc}")
            return
    processed_any = False
    for row in filter_rows(df, sku_targets, args.reverb_id, args.ebay_id):
        sku = getattr(row, "sku", None)
        code = getattr(row, "validated_country_code", None)
        if not code:
            print(f"[SKIP] Missing country in row: {row}")
            continue
        ebay_id_value = getattr(row, "ebay_id", None)
        ebay_id_int = None
        if pd.notna(ebay_id_value):
            try:
                ebay_id_int = int(float(ebay_id_value))
            except (ValueError, TypeError):
                ebay_id_int = None
        await update_single_product(
            sku,
            code,
            args.apply,
            settings,
            ebay_id=ebay_id_int,
        )
        processed_any = True

    if not processed_any:
        print("No matching rows to process.")


if __name__ == "__main__":
    asyncio.run(main())
