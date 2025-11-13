#!/usr/bin/env python3
"""
CLI helper to refresh eBay listing metadata (descriptions, pictures, CrazyLister flag).

Intended for scheduled runs (e.g., Railway cron). Keeps the heavy GetItem workflow
separate from the hourly status sync.
"""

import argparse
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import get_settings
from app.database import async_session
from app.services.ebay_service import EbayService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh eBay listing metadata.")
    parser.add_argument(
        "--state",
        choices=["active", "sold", "unsold", "all"],
        default="active",
        help="Which listing state(s) to refresh (default: active).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of listings to refresh.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=10,
        help="How many GetItem calls to run concurrently (default: 10).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch metadata but do not persist any changes.",
    )
    parser.add_argument(
        "--sku",
        action="append",
        dest="skus",
        help="Limit the refresh to one or more SKUs. Repeat the flag for multiple SKUs.",
    )
    parser.add_argument(
        "--item-id",
        action="append",
        dest="item_ids",
        help="Limit the refresh to specific eBay Item IDs (repeat for multiples).",
    )
    return parser.parse_args()


async def run_refresh(args: argparse.Namespace) -> None:
    settings = get_settings()
    async with async_session() as session:
        service = EbayService(session, settings)
        summary = await service.refresh_listing_metadata(
            state=args.state,
            limit=args.limit,
            batch_size=args.batch_size,
            dry_run=args.dry_run,
            skus=args.skus,
            item_ids=args.item_ids,
        )

    print("=== eBay Metadata Refresh ===")
    print(f"Started:  {datetime.now(timezone.utc).isoformat()}")
    for key in ["total_listings", "processed", "updated", "unchanged", "missing", "api_calls", "duration_seconds"]:
        print(f"{key:>16}: {summary.get(key)}")


def main() -> None:
    args = parse_args()
    asyncio.run(run_refresh(args))


if __name__ == "__main__":
    main()
