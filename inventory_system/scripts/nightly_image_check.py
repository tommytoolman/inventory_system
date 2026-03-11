#!/usr/bin/env python3
"""
Nightly Image Health Check & Repair Script

Checks all product images for 401/404 errors and automatically refreshes
broken images from Reverb API.

Run this as a cron job: 0 2 * * * (2 AM daily)
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import requests
from sqlalchemy import select, text
from app.database import async_session
from app.models.product import Product
from app.core.config import get_settings
from app.routes.inventory import refresh_canonical_gallery
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def check_image_url(url: str) -> bool:
    """
    Check if an image URL is accessible.

    Returns:
        True if image is accessible, False if broken (401/404/timeout)
    """
    if not url or not isinstance(url, str):
        return False

    try:
        # Quick HEAD request to check if image is accessible
        response = requests.head(url, timeout=5, allow_redirects=True)
        if response.status_code in [401, 404]:
            return False
        return response.status_code == 200
    except (requests.RequestException, requests.Timeout):
        # If HEAD fails, try GET with minimal data transfer
        try:
            response = requests.get(url, timeout=5, stream=True, allow_redirects=True)
            response.close()
            return response.status_code == 200
        except:
            return False


async def find_products_with_broken_images(db, batch_size: int = 100):
    """
    Find products with broken image URLs.

    Returns:
        List of (product_id, sku, primary_image) tuples for products with broken images
    """
    logger.info("Fetching products with images...")

    result = await db.execute(
        select(Product.id, Product.sku, Product.primary_image)
        .where(Product.primary_image.isnot(None))
        .where(Product.primary_image != '')
    )
    products = result.all()

    logger.info(f"Checking {len(products)} products for broken images...")

    broken_products = []
    checked = 0

    for product_id, sku, primary_image in products:
        checked += 1
        if checked % 50 == 0:
            logger.info(f"Progress: {checked}/{len(products)} products checked, {len(broken_products)} broken found")

        # Check if image is accessible
        is_accessible = await asyncio.to_thread(check_image_url, primary_image)

        if not is_accessible:
            logger.warning(f"Broken image found: {sku} - {primary_image[:80]}...")
            broken_products.append((product_id, sku, primary_image))

        # Small delay to avoid hammering CDN
        if checked % 10 == 0:
            await asyncio.sleep(0.5)

    logger.info(f"Scan complete: {len(broken_products)} products have broken images")
    return broken_products


async def repair_product_images(db, settings, product_id: int, sku: str, dry_run: bool = False):
    """
    Repair broken images by refreshing from Reverb API.

    Returns:
        True if repair succeeded, False otherwise
    """
    try:
        product = await db.get(Product, product_id)
        if not product:
            logger.error(f"Product {sku} not found in database")
            return False

        if dry_run:
            logger.info(f"[DRY RUN] Would refresh images for {sku}")
            return True

        logger.info(f"Refreshing images for {sku}...")
        canonical_gallery, canonical_updated = await refresh_canonical_gallery(
            db, settings, product, refresh_reverb=True
        )

        if canonical_updated:
            logger.info(f"✓ Successfully refreshed images for {sku}")
            return True
        else:
            logger.warning(f"Images refreshed but no changes detected for {sku}")
            return False

    except Exception as e:
        logger.error(f"Failed to repair images for {sku}: {e}", exc_info=True)
        return False


async def main(dry_run: bool = False, limit: int = None):
    """
    Main function to check and repair broken images.

    Args:
        dry_run: If True, only report broken images without fixing
        limit: Maximum number of products to repair (None = no limit)
    """
    logger.info("=" * 80)
    logger.info("Starting Nightly Image Health Check")
    logger.info(f"Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    if limit:
        logger.info(f"Repair limit: {limit} products")
    logger.info("=" * 80)

    settings = get_settings()

    async with async_session() as db:
        # Find products with broken images
        broken_products = await find_products_with_broken_images(db)

        if not broken_products:
            logger.info("✓ No broken images found. All images are healthy!")
            return

        logger.info(f"\nFound {len(broken_products)} products with broken images")

        if dry_run:
            logger.info("\n[DRY RUN] Products that would be repaired:")
            for product_id, sku, image_url in broken_products[:20]:  # Show first 20
                logger.info(f"  - {sku}: {image_url[:80]}...")
            if len(broken_products) > 20:
                logger.info(f"  ... and {len(broken_products) - 20} more")
            return

        # Repair broken images
        products_to_repair = broken_products[:limit] if limit else broken_products
        logger.info(f"\nRepairing {len(products_to_repair)} products...")

        repaired = 0
        failed = 0

        for product_id, sku, _ in products_to_repair:
            success = await repair_product_images(db, settings, product_id, sku, dry_run=False)
            if success:
                repaired += 1
            else:
                failed += 1

            # Small delay between repairs (2 seconds to be gentle on Reverb API)
            await asyncio.sleep(2)

        logger.info("\n" + "=" * 80)
        logger.info("Image Health Check Complete")
        logger.info(f"  Total broken: {len(broken_products)}")
        logger.info(f"  Repaired: {repaired}")
        logger.info(f"  Failed: {failed}")
        if limit and len(broken_products) > limit:
            logger.info(f"  Remaining: {len(broken_products) - limit} (will repair next run)")
        logger.info("=" * 80)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Check and repair broken product images")
    parser.add_argument('--dry-run', action='store_true', help='Only check, do not repair')
    parser.add_argument('--limit', type=int, help='Maximum number of products to repair')

    args = parser.parse_args()

    asyncio.run(main(dry_run=args.dry_run, limit=args.limit))
