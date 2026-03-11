#!/usr/bin/env python3
"""Pull full image sets from Reverb for given listing IDs and update local products."""

import argparse
import asyncio
from typing import Iterable, List

from app.core.config import get_settings
from app.database import async_session
from app.models.platform_common import PlatformCommon
from app.models.product import Product
from app.services.reverb.client import ReverbClient
from app.services.reverb_service import ReverbService


def _supersize_url(url: str) -> str:
    return ReverbService._normalize_image_url(url)


def _extract_image_urls(listing_data: dict) -> List[str]:
    return ReverbService._extract_image_urls(listing_data)


async def backfill_images(reverb_ids: Iterable[str]) -> None:
    settings = get_settings()
    client = ReverbClient(
        api_key=settings.REVERB_API_KEY,
        use_sandbox=settings.REVERB_USE_SANDBOX,
    )

    async with async_session() as session:
        for raw_id in reverb_ids:
            reverb_id = str(raw_id).strip()
            if not reverb_id:
                continue

            try:
                response = await client.get_listing_details(reverb_id)
            except Exception as exc:  # noqa: BLE001
                print(f"[{reverb_id}] Failed to fetch listing: {exc}")
                continue

            listing_data = response.get("listing", response) or {}
            photo_urls = _extract_image_urls(listing_data)

            if not photo_urls:
                print(f"[{reverb_id}] No photo URLs available; skipping.")
                continue

            platform_common_result = await session.execute(
                PlatformCommon.__table__.select().where(
                    (PlatformCommon.platform_name == "reverb")
                    & (PlatformCommon.external_id == reverb_id)
                )
            )
            platform_row = platform_common_result.first()

            if platform_row is None:
                print(f"[{reverb_id}] No platform_common row found; skipping.")
                continue

            platform_common_id = platform_row._mapping["id"]
            platform_product_id = platform_row._mapping["product_id"]

            # Load ORM instance for convenience
            platform_common = await session.get(PlatformCommon, platform_common_id)

            if not platform_common:
                print(f"[{reverb_id}] No platform_common row found; skipping.")
                continue

            product = await session.get(Product, platform_product_id)
            if not product:
                print(
                    f"[{reverb_id}] PlatformCommon {platform_common.id} references missing product {platform_common.product_id}; skipping."
                )
                continue

            product.primary_image = photo_urls[0]
            product.additional_images = photo_urls[1:]
            await session.flush()
            print(
                f"[{reverb_id}] Updated product {product.id} with {len(photo_urls)} image(s)."
            )

        await session.commit()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill product images using live Reverb listing data."
    )
    parser.add_argument(
        "reverb_ids",
        metavar="REVERB_ID",
        nargs="+",
        help="One or more Reverb listing IDs to refresh",
    )
    args = parser.parse_args()

    asyncio.run(backfill_images(args.reverb_ids))


if __name__ == "__main__":
    main()
