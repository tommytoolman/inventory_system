import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Dict, List

from dotenv import load_dotenv, dotenv_values


def _bootstrap_env(argv: List[str]) -> List[str]:
    """Load .env and apply optional --database-url before importing project modules."""

    bootstrap_parser = argparse.ArgumentParser(add_help=False)
    bootstrap_parser.add_argument("--database-url")
    known, remaining = bootstrap_parser.parse_known_args(argv)

    env_file = os.environ.get("ENV_FILE")
    file_env: Dict[str, str] = {}
    if env_file:
        file_env = dotenv_values(env_file)
        load_dotenv(env_file, override=True)
    else:
        default_env = Path(__file__).resolve().parents[2] / ".env"
        if default_env.exists():
            file_env = dotenv_values(default_env)
            load_dotenv(default_env, override=True)

    if known.database_url:
        os.environ["DATABASE_URL"] = known.database_url
    else:
        file_db_url = file_env.get("DATABASE_URL") if file_env else None
        env_db_url = os.environ.get("DATABASE_URL")
        if file_db_url and (not env_db_url or "internal" in env_db_url) and "internal" not in file_db_url:
            os.environ["DATABASE_URL"] = file_db_url

    return remaining


remaining_args = _bootstrap_env(sys.argv[1:])

from app.core.config import get_settings
from app.database import async_session
from app.models.product import Product
from app.services.image_reconciliation import (
    SUPPORTED_PLATFORMS,
    refresh_canonical_gallery,
    reconcile_ebay,
    reconcile_shopify,
)

logger = logging.getLogger("image_backfill")


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify and backfill platform image galleries from canonical Reverb images.",
    )
    parser.add_argument(
        "product_ids",
        nargs="+",
        type=int,
        help="One or more product IDs to inspect",
    )
    parser.add_argument(
        "-p",
        "--platform",
        dest="platforms",
        action="append",
        choices=sorted(SUPPORTED_PLATFORMS),
        help="Platform(s) to reconcile (default: reverb+shopify)",
    )
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--apply",
        dest="apply_fix",
        action="store_true",
        help="Apply fixes when discrepancies are detected",
    )
    mode_group.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="Force dry-run mode (default)",
    )
    parser.add_argument(
        "--log-level",
        dest="log_level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity (default: INFO)",
    )
    parser.add_argument(
        "--database-url",
        dest="database_url",
        help=argparse.SUPPRESS,
    )
    return parser.parse_args(argv)


def log_platform_result(result: Dict, apply_fix: bool) -> None:
    platform = result.get("platform")
    if not result.get("available"):
        logger.warning("Product has no %s listing", platform)
        return

    if result.get("error"):
        logger.error("%s image reconciliation error: %s", platform.capitalize(), result.get("message"))
        return

    logger.info(
        "%s images: canonical=%s, platform=%s, missing=%s, extra=%s",
        platform.capitalize(),
        result.get("canonical_count"),
        result.get("platform_count"),
        len(result.get("missing", [])),
        len(result.get("extra", [])),
    )

    if not apply_fix and result.get("needs_fix"):
        missing_urls = result.get("missing", [])
        extra_urls = result.get("extra", [])
        for url in missing_urls:
            logger.info("DRY-RUN: would add %s image %s", platform, url)
        for url in extra_urls:
            logger.info("DRY-RUN: would remove %s image %s", platform, url)

    if result.get("updated"):
        logger.info("%s gallery replaced with canonical images", platform.capitalize())


async def process_product(
    product_id: int,
    platforms: List[str],
    apply_fix: bool,
    settings,
) -> None:
    async with async_session() as session:
        product = await session.get(Product, product_id)
        if not product:
            logger.error("Product %s not found", product_id)
            return

        logger.info("Processing product %s (SKU %s)", product.id, product.sku)

        refresh_reverb = "reverb" in platforms
        canonical_gallery, canonical_updated = await refresh_canonical_gallery(
            session,
            settings,
            product,
            refresh_reverb=refresh_reverb,
        )

        if canonical_updated:
            logger.info(
                "Canonical gallery refreshed from Reverb for product %s (now %s images)",
                product.id,
                len(canonical_gallery),
            )

        if "shopify" in platforms:
            shopify_result = await reconcile_shopify(
                session,
                settings,
                product,
                canonical_gallery,
                apply_fix,
                log=logger,
            )
            log_platform_result(shopify_result, apply_fix)
        if "ebay" in platforms:
            ebay_result = await reconcile_ebay(
                session,
                settings,
                product,
                canonical_gallery,
                apply_fix,
                log=logger,
            )
            log_platform_result(ebay_result, apply_fix)


async def main_async(args: argparse.Namespace) -> None:
    logging.basicConfig(level=getattr(logging, args.log_level.upper()))
    settings = get_settings()

    logger.info("Using database URL: %s", settings.DATABASE_URL)

    platforms = args.platforms or ["reverb", "shopify"]
    platforms = [p.lower() for p in platforms]
    for platform in platforms:
        if platform not in SUPPORTED_PLATFORMS:
            raise ValueError(f"Unsupported platform: {platform}")

    apply_fix = bool(args.apply_fix and not args.dry_run)
    logger.info("Running image backfill (%s mode) for products %s", "apply" if apply_fix else "dry-run", args.product_ids)

    for product_id in args.product_ids:
        await process_product(product_id, platforms, apply_fix, settings)


def main() -> None:
    args = parse_args(remaining_args)
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
