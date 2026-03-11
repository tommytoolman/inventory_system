#!/usr/bin/env python3
"""Backfill Shopify taxonomy categories using stored Reverb mappings.

Usage examples (covering every flag):

* Preview the first 25 uncategorised listings::

      python scripts/shopify/backfill_shopify_categories.py --dry-run

* Apply categories to a specific product and SKU while reviewing output::

      python scripts/shopify/backfill_shopify_categories.py \
          --product-id 642 --sku RIFF-10000068 --dry-run

* Process up to 50 listings (including already tagged ones) and push updates::

      python scripts/shopify/backfill_shopify_categories.py \
          --limit 50 --include-existing

"""

import argparse
import asyncio
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from app.database import async_session
from app.models.category_mappings import ReverbCategory, ShopifyCategoryMapping
from app.models.platform_common import PlatformCommon
from app.models.product import Product
from app.models.shopify import ShopifyListing
from app.services.shopify_service import ShopifyService


@dataclass
class CategoryResult:
    product_id: int
    sku: Optional[str]
    title: str
    reverb_label: Optional[str]
    reverb_uuid: Optional[str]
    shopify_label: Optional[str]
    shopify_short: Optional[str]
    shopify_gid: Optional[str]
    status: str
    note: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Assign Shopify taxonomy categories based on Reverb mapping data.",
    )
    parser.add_argument(
        "--product-id",
        dest="product_ids",
        action="append",
        type=int,
        help="Limit to one or more specific product IDs (can be repeated).",
    )
    parser.add_argument(
        "--sku",
        dest="skus",
        action="append",
        help="Limit to one or more SKUs (case-insensitive, can be repeated).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=25,
        help="Maximum listings to process in this run (default: 25). Use 0 for no limit.",
    )
    parser.add_argument(
        "--include-existing",
        action="store_true",
        help="Include listings that already have a Shopify category assigned.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview the proposed changes without calling Shopify or updating the database.",
    )
    return parser.parse_args()


async def fetch_candidates(session, args: argparse.Namespace) -> List[PlatformCommon]:
    stmt = (
        select(PlatformCommon)
        .join(PlatformCommon.shopify_listing)
        .join(Product)
        .options(
            selectinload(PlatformCommon.shopify_listing),
            selectinload(PlatformCommon.product)
            .selectinload(Product.platform_listings)
            .selectinload(PlatformCommon.reverb_listing),
        )
        .where(func.lower(PlatformCommon.platform_name) == "shopify")
    )

    if not args.include_existing:
        stmt = stmt.where(
            or_(
                ShopifyListing.category_gid.is_(None),
                ShopifyListing.category_gid == "",
            )
        )

    if args.product_ids:
        stmt = stmt.where(PlatformCommon.product_id.in_(set(args.product_ids)))

    if args.skus:
        lowered = [sku.lower() for sku in args.skus]
        stmt = stmt.where(func.lower(Product.sku).in_(lowered))

    stmt = stmt.order_by(PlatformCommon.product_id)

    if args.limit and args.limit > 0:
        stmt = stmt.limit(args.limit)

    result = await session.execute(stmt)
    return result.scalars().unique().all()


async def resolve_reverb_context(
    session,
    shopify_link: PlatformCommon,
) -> Tuple[Optional[str], Optional[ReverbCategory], Optional[str]]:
    product = shopify_link.product
    if not product:
        return None, None, None

    reverb_link: Optional[PlatformCommon] = None
    for candidate in product.platform_listings or []:
        if candidate.id == shopify_link.id:
            continue
        if (candidate.platform_name or "").lower() == "reverb":
            reverb_link = candidate
            break

    reverb_uuid: Optional[str] = None
    label_hint: Optional[str] = None

    if reverb_link:
        if reverb_link.reverb_listing and reverb_link.reverb_listing.reverb_category_uuid:
            reverb_uuid = reverb_link.reverb_listing.reverb_category_uuid
        payload = reverb_link.platform_specific_data or {}
        label_hint = (
            payload.get("reverb_category_name")
            or payload.get("category")
            or label_hint
        )
        reverb_uuid = reverb_uuid or payload.get("reverb_category_uuid") or payload.get("category_uuid")
        listing_data = payload.get("listing_data") or {}
        if not reverb_uuid and isinstance(listing_data, dict):
            categories = listing_data.get("categories")
            if isinstance(categories, list) and categories:
                first_cat = categories[0]
                if isinstance(first_cat, dict):
                    reverb_uuid = first_cat.get("uuid") or first_cat.get("id")
                    label_hint = label_hint or first_cat.get("full_name") or first_cat.get("name")

    if not label_hint and product.category:
        label_hint = product.category

    reverb_category: Optional[ReverbCategory] = None

    if reverb_uuid:
        reverb_category = (
            await session.execute(
                select(ReverbCategory).where(ReverbCategory.uuid == reverb_uuid)
            )
        ).scalar_one_or_none()

    if not reverb_category and label_hint:
        normalized = label_hint.strip().lower()
        if normalized:
            reverb_category = (
                await session.execute(
                    select(ReverbCategory).where(
                        or_(
                            func.lower(ReverbCategory.name) == normalized,
                            func.lower(ReverbCategory.full_path) == normalized,
                        )
                    )
                )
            ).scalar_one_or_none()
            if reverb_category:
                reverb_uuid = reverb_category.uuid

    display_label = (
        (reverb_category.full_path if reverb_category else None)
        or label_hint
    )

    return reverb_uuid, reverb_category, display_label


async def select_shopify_mapping(
    session,
    reverb_category: Optional[ReverbCategory],
) -> Optional[ShopifyCategoryMapping]:
    if not reverb_category:
        return None

    stmt = (
        select(ShopifyCategoryMapping)
        .where(ShopifyCategoryMapping.reverb_category_id == reverb_category.id)
        .order_by(ShopifyCategoryMapping.is_verified.desc(), ShopifyCategoryMapping.confidence_score.desc())
    )
    result = await session.execute(stmt)
    return result.scalars().first()


def format_reverb_display(label: Optional[str], uuid: Optional[str]) -> Optional[str]:
    if not label and not uuid:
        return None
    if not uuid:
        return label
    if not label:
        return uuid
    return f"{label} ({uuid})"


def format_shopify_display(gid: Optional[str], label: Optional[str]) -> Optional[str]:
    if not gid and not label:
        return None
    if not gid:
        return label
    if not label:
        return gid
    return f"{gid} ({label})"


def summarise(results: Sequence[CategoryResult], *, dry_run: bool) -> None:
    if not results:
        print("No Shopify listings matched the criteria.")
        return

    mode = "DRY RUN" if dry_run else "APPLY"
    print(f"\n{mode}: processed {len(results)} Shopify listing(s)\n")

    header = (
        f"{'Product':<8} {'SKU':<16} {'Title':<40} "
        f"{'Reverb Category':<56} {'Shopify Category':<72} {'Result':<10} Notes"
    )
    print(header)
    print("-" * len(header))

    def shorten(value: Optional[str], width: int) -> str:
        if not value:
            return "-".ljust(width)
        if len(value) <= width:
            return value.ljust(width)
        return (value[: max(0, width - 1)] + "…")

    for row in results:
        print(
            f"{row.product_id:<8} "
            f"{shorten(row.sku or '-', 16)} "
            f"{shorten(row.title, 42)} "
            f"{shorten(format_reverb_display(row.reverb_label, row.reverb_uuid), 56)} "
            f"{shorten(format_shopify_display(row.shopify_gid, row.shopify_label), 72)} "
            f"{row.status:<10} {row.note}"
        )

    applied = sum(1 for r in results if r.status == "APPLIED")
    previewed = sum(1 for r in results if r.status == "DRY-RUN")
    skipped = sum(1 for r in results if r.status == "SKIPPED")
    failed = sum(1 for r in results if r.status == "FAILED")

    print(
        "\nSummary: "
        f"{applied} applied, {previewed} previewed, {skipped} skipped, {failed} failed"
    )


async def run(args: argparse.Namespace) -> None:
    async with async_session() as session:
        service = ShopifyService(session)
        candidates = await fetch_candidates(session, args)

        results: List[CategoryResult] = []

        for shopify_link in candidates:
            product = shopify_link.product
            if not product:
                results.append(
                    CategoryResult(
                        product_id=shopify_link.product_id,
                        sku=None,
                        title="<missing product>",
                        reverb_label=None,
                        reverb_uuid=None,
                        shopify_label=None,
                        shopify_short=None,
                        shopify_gid=None,
                        status="FAILED",
                        note="PlatformCommon has no product relationship",
                    )
                )
                continue

            title = (
                product.title
                or product.generate_title()
                or f"Product {product.id}"
            )

            reverb_uuid, reverb_category, reverb_label = await resolve_reverb_context(session, shopify_link)
            mapping = await select_shopify_mapping(session, reverb_category)

            shopify_label = None
            shopify_short = None
            shopify_gid = None

            if mapping:
                shopify_label = mapping.shopify_category_name or mapping.merchant_type
                if shopify_label:
                    parts = [part.strip() for part in shopify_label.split(" > ") if part.strip()]
                    shopify_short = parts[-1] if parts else shopify_label
                shopify_gid = mapping.shopify_gid

            if not reverb_uuid:
                results.append(
                    CategoryResult(
                        product_id=product.id,
                        sku=product.sku,
                        title=title,
                        reverb_label=reverb_label,
                        reverb_uuid=None,
                        shopify_label=shopify_label,
                        shopify_short=shopify_short,
                        shopify_gid=shopify_gid,
                        status="SKIPPED",
                        note="Could not determine Reverb category UUID",
                    )
                )
                continue

            if not mapping or not shopify_gid:
                note = "No Shopify mapping found for Reverb category"
                if reverb_label:
                    note += f" '{reverb_label}'"
                elif reverb_uuid:
                    note += f" ({reverb_uuid})"
                results.append(
                    CategoryResult(
                        product_id=product.id,
                        sku=product.sku,
                        title=title,
                        reverb_label=reverb_label,
                        reverb_uuid=reverb_uuid,
                        shopify_label=shopify_label,
                        shopify_short=shopify_short,
                        shopify_gid=shopify_gid,
                        status="SKIPPED",
                        note=note,
                    )
                )
                continue

            if args.dry_run:
                results.append(
                    CategoryResult(
                        product_id=product.id,
                        sku=product.sku,
                        title=title,
                        reverb_label=reverb_label,
                        reverb_uuid=reverb_uuid,
                        shopify_label=shopify_label,
                        shopify_short=shopify_short,
                        shopify_gid=shopify_gid,
                        status="DRY-RUN",
                        note="Would assign category",
                    )
                )
                continue

            success = await service.apply_category_assignment(
                shopify_link,
                shopify_gid,
                category_full_name=shopify_label,
                category_name=shopify_short,
            )

            results.append(
                CategoryResult(
                    product_id=product.id,
                    sku=product.sku,
                    title=title,
                    reverb_label=reverb_label,
                    reverb_uuid=reverb_uuid,
                    shopify_label=shopify_label,
                    shopify_short=shopify_short,
                    shopify_gid=shopify_gid,
                    status="APPLIED" if success else "FAILED",
                    note="Category assigned" if success else "Shopify API call failed",
                )
            )

        if args.dry_run:
            await session.rollback()
        else:
            await session.commit()

    summarise(results, dry_run=args.dry_run)


def main() -> None:
    args = parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
