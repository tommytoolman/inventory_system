"""Refresh Shopify handles/URLs for legacy listings.

Usage examples:
    python scripts/utilities/fix_shopify_listing_urls.py \  # dry run range
        --min-product-id 608 --max-product-id 655

    python scripts/utilities/fix_shopify_listing_urls.py --apply \
        --product-id 640 --product-id 655

Pass one or more ``--product-id`` flags to target specific records. When no
explicit IDs are provided the script defaults to the range 608–655 (adjustable
via ``--min-product-id`` / ``--max-product-id``).
"""

import argparse
import asyncio
import logging
import os
from pathlib import Path

from dotenv import load_dotenv, dotenv_values
from sqlalchemy import select
from sqlalchemy.orm import selectinload


def _bootstrap_env() -> None:
    """Load environment variables from .env if present."""

    env_file = os.environ.get("ENV_FILE")
    if env_file:
        load_dotenv(env_file, override=True)
        return

    default_env = Path(__file__).resolve().parents[2] / ".env"
    if default_env.exists():
        load_dotenv(default_env, override=True)


_bootstrap_env()

from app.core.config import get_settings
from app.database import async_session
from app.models.platform_common import PlatformCommon
from app.services.shopify_service import ShopifyService

logger = logging.getLogger("fix_shopify_urls")

SHOP_DOMAIN = "https://londonvintageguitars.myshopify.com"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fix Shopify listing URLs that still contain SKU tokens.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply the updates. Without this flag the script runs in dry-run mode.",
    )
    parser.add_argument(
        "--product-id",
        dest="product_ids",
        type=int,
        action="append",
        help="Specific product ID to update (repeatable). Overrides the min/max range.",
    )
    parser.add_argument(
        "--min-product-id",
        type=int,
        default=608,
        help="Minimum product ID to consider (default: 608)",
    )
    parser.add_argument(
        "--max-product-id",
        type=int,
        default=655,
        help="Maximum product ID to consider (default: 655)",
    )
    return parser.parse_args()


async def fix_urls(
    apply: bool,
    product_ids: list[int] | None,
    min_product_id: int,
    max_product_id: int,
) -> None:
    """Fetch canonical handles from Shopify and update local records.

    Args:
        apply: When ``True`` commits changes; otherwise runs in dry-run mode.
        product_ids: Optional list of product IDs to target explicitly.
            Overrides the min/max range when provided.
        min_product_id: Lower bound for product IDs when ``product_ids`` is
            not supplied.
        max_product_id: Upper bound for product IDs when ``product_ids`` is
            not supplied.
    """
    settings = get_settings()
    logger.info("Using database: %s", settings.DATABASE_URL)

    async with async_session() as session:
        filters = [
            PlatformCommon.platform_name == "shopify",
            PlatformCommon.listing_url.ilike('%-riff-%'),
        ]

        if product_ids:
            filters.append(PlatformCommon.product_id.in_(product_ids))
            logger.info("Restricting to explicit product IDs: %s", sorted(set(product_ids)))
        else:
            filters.extend([
                PlatformCommon.product_id >= min_product_id,
                PlatformCommon.product_id <= max_product_id,
            ])

        stmt = (
            select(PlatformCommon)
            .options(selectinload(PlatformCommon.shopify_listing))
            .where(*filters)
        )

        result = await session.execute(stmt)
        platform_links = result.scalars().all()

        logger.info("Found %s candidate Shopify listings", len(platform_links))

        shopify_service = ShopifyService(session, settings)

        updates = 0
        skipped_no_handle = 0
        skipped_no_snapshot = 0
        for link in platform_links:
            shopify_listing = link.shopify_listing
            if not shopify_listing:
                skipped_no_handle += 1
                logger.warning(
                    "Skipping platform_common %s (product %s): no Shopify listing record",
                    link.id,
                    link.product_id,
                )
                continue

            product_gid = shopify_service._resolve_product_gid(link, shopify_listing)
            if not product_gid:
                skipped_no_handle += 1
                logger.warning(
                    "Skipping platform_common %s (product %s): unable to resolve Shopify product GID",
                    link.id,
                    link.product_id,
                )
                continue

            snapshot = None
            try:
                snapshot = shopify_service.client.get_product_snapshot_by_id(
                    product_gid,
                    num_variants=1,
                    num_images=1,
                    num_metafields=0,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Failed to fetch Shopify snapshot for product %s (%s): %s",
                    link.product_id,
                    product_gid,
                    exc,
                )

            fresh_handle = (snapshot or {}).get("handle") if snapshot else None
            if not fresh_handle:
                skipped_no_snapshot += 1
                logger.warning(
                    "No handle returned from Shopify for platform_common %s (product %s)",
                    link.id,
                    link.product_id,
                )
                continue

            new_url = f"{SHOP_DOMAIN}/products/{fresh_handle}"

            if (
                link.listing_url == new_url
                and shopify_listing.handle == fresh_handle
            ):
                logger.debug(
                    "Platform_common %s already has correct URL (%s)",
                    link.id,
                    new_url,
                )
                continue

            logger.info(
                "Product %s: %s -> %s%s",
                link.product_id,
                link.listing_url,
                new_url,
                "; updating stored handle" if shopify_listing.handle != fresh_handle else "",
            )

            if apply:
                link.listing_url = new_url
                shopify_listing.handle = fresh_handle
            updates += 1

        if apply and updates:
            await session.commit()
            logger.info("Committed %s listing updates", updates)
        else:
            await session.rollback()
            if apply:
                logger.info("No updates to commit")

        logger.info(
            "Summary: %s processed, %s updated, %s skipped (missing handle/GID), %s skipped (no Shopify snapshot)",
            len(platform_links),
            updates,
            skipped_no_handle,
            skipped_no_snapshot,
        )


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    args = parse_args()
    asyncio.run(fix_urls(args.apply, args.product_ids, args.min_product_id, args.max_product_id))


if __name__ == "__main__":
    main()
