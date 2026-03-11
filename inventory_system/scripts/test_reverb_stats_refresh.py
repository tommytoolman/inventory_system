#!/usr/bin/env python3
"""
Test script for the Reverb stats refresh job.

Run this to manually test the stats snapshot functionality before
relying on the scheduler.

Usage:
    python scripts/test_reverb_stats_refresh.py [--dry-run]
"""

import asyncio
import argparse
import logging
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / '.env')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def main(dry_run: bool = False):
    from app.core.config import get_settings
    from app.database import async_session
    from app.services.listing_stats_service import ListingStatsService

    settings = get_settings()

    if not settings.REVERB_API_KEY:
        logger.error("REVERB_API_KEY not found in environment")
        return False

    logger.info("=" * 60)
    logger.info("Reverb Stats Refresh Test")
    logger.info(f"Dry run: {dry_run}")
    logger.info("=" * 60)

    async with async_session() as db:
        stats_service = ListingStatsService(db)

        result = await stats_service.refresh_reverb_stats(
            api_key=settings.REVERB_API_KEY,
            dry_run=dry_run
        )

        logger.info("")
        logger.info("=" * 60)
        logger.info("RESULTS:")
        logger.info("=" * 60)
        for key, value in result.items():
            logger.info(f"  {key}: {value}")

        if result.get("status") == "success":
            logger.info("")
            logger.info("✅ Stats refresh completed successfully!")

            if not dry_run:
                # Show a sample of what was recorded
                from sqlalchemy import select, desc
                from app.models.listing_stats_history import ListingStatsHistory

                query = (
                    select(ListingStatsHistory)
                    .where(ListingStatsHistory.platform == "reverb")
                    .order_by(desc(ListingStatsHistory.recorded_at))
                    .limit(5)
                )
                result = await db.execute(query)
                samples = result.scalars().all()

                if samples:
                    logger.info("")
                    logger.info("Sample of recorded stats:")
                    for s in samples:
                        price_str = f"£{s.price:.0f}" if s.price else "N/A"
                        logger.info(
                            f"  Listing {s.platform_listing_id} (product_id={s.product_id}): "
                            f"views={s.view_count}, watches={s.watch_count}, "
                            f"price={price_str}"
                        )

            return True
        else:
            logger.error(f"❌ Stats refresh failed: {result.get('message')}")
            return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test Reverb stats refresh")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Don't write to database, just fetch and display"
    )
    args = parser.parse_args()

    success = asyncio.run(main(dry_run=args.dry_run))
    sys.exit(0 if success else 1)
