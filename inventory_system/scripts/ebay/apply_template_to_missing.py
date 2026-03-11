#!/usr/bin/env python3
"""
Batch-apply the eBay listing template to all active listings missing a template.

This script:
1. Finds all active eBay listings where uses_crazylister = false
2. Renders the template for each product
3. Calls ReviseFixedPriceItem to update the Description field on eBay
4. Logs results and errors

Usage:
    python scripts/ebay/apply_template_to_missing.py --dry-run
    python scripts/ebay/apply_template_to_missing.py --limit 10
    python scripts/ebay/apply_template_to_missing.py
"""
import argparse
import asyncio
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import get_settings
from app.database import async_session
from app.services.ebay_service import EbayService
from app.models.ebay import EbayListing
from app.models.platform_common import PlatformCommon
from app.models.product import Product
from sqlalchemy import and_, select

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def run(dry_run=False, limit=None):
    """Run the batch template application."""
    settings = get_settings()
    async with async_session() as session:
        service = EbayService(session, settings)

        # Query: all active eBay listings missing the CrazyLister template
        stmt = (
            select(EbayListing, PlatformCommon, Product)
            .join(
                PlatformCommon,
                EbayListing.platform_id == PlatformCommon.id
            )
            .join(
                Product,
                PlatformCommon.product_id == Product.id
            )
            .where(PlatformCommon.platform_name == "ebay")
            .where(PlatformCommon.status == "ACTIVE")
            .where(Product.status == "ACTIVE")
            .where(
                EbayListing.listing_data["uses_crazylister"].astext == "false"
            )
        )

        if limit:
            stmt = stmt.limit(limit)

        result = await session.execute(stmt)
        rows = result.all()

        total = len(rows)
        logger.info(f"Found {total} listings missing template")

        if dry_run:
            logger.info("DRY RUN — no changes will be made")
            for listing, pc, product in rows:
                logger.info(
                    f"  Would revise: {listing.ebay_item_id} "
                    f"({product.sku})"
                )
            return

        updated = 0
        errors = 0

        for idx, (listing, pc, product) in enumerate(rows, 1):
            try:
                logger.info(
                    f"[{idx}/{total}] Rendering template for "
                    f"{product.sku} ({listing.ebay_item_id})..."
                )
                description_html = await service._render_ebay_template(product)

                logger.info(
                    f"[{idx}/{total}] Revising eBay listing "
                    f"{listing.ebay_item_id}..."
                )
                await service.trading_api.revise_fixed_price_item(
                    item_id=listing.ebay_item_id,
                    Description=description_html
                )

                logger.info(f"  ✓ Success: {listing.ebay_item_id}")
                updated += 1

            except Exception as e:
                logger.error(
                    f"  ✗ Failed {listing.ebay_item_id} "
                    f"({product.sku}): {str(e)}"
                )
                errors += 1

        logger.info(
            f"\n{'='*60}\n"
            f"Batch complete: {updated} updated, {errors} errors\n"
            f"{'='*60}\n"
            f"Next step: Run refresh_metadata.py to update "
            f"uses_crazylister flags\n"
            f"  python scripts/ebay/refresh_metadata.py --state active\n"
        )


def main():
    parser = argparse.ArgumentParser(
        description="Apply eBay template to listings missing it"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be changed without making changes"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit to N listings (useful for testing)"
    )

    args = parser.parse_args()

    try:
        asyncio.run(run(dry_run=args.dry_run, limit=args.limit))
    except KeyboardInterrupt:
        logger.info("\nCancelled by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
