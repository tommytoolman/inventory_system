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


def _supersize_url(url: str) -> str:
    """Return a Cloudinary URL that requests the t_supersize rendition."""
    if not url:
        return url

    if "f_auto,t_supersize" in url:
        return url

    transformed = url
    if "f_auto,t_large" in transformed:
        transformed = transformed.replace("f_auto,t_large", "f_auto,t_supersize")
    elif "t_card-square" in transformed:
        transformed = transformed.replace("t_card-square", "t_supersize")
    elif "/image/upload/" in transformed and "t_supersize" not in transformed:
        prefix, remainder = transformed.split("/image/upload/", 1)
        if remainder.startswith("s--"):
            marker, _, rest = remainder.partition("/")
            if rest and not rest.startswith("f_auto"):
                transformed = f"{prefix}/image/upload/{marker}/f_auto,t_supersize/{rest}"
        else:
            if not remainder.startswith("f_auto"):
                transformed = f"{prefix}/image/upload/f_auto,t_supersize/{remainder}"

    return transformed


def _extract_image_urls(listing_data: dict) -> List[str]:
    """Build an ordered list of CDN URLs from the Reverb listing payload."""
    urls: List[str] = []

    for photo in listing_data.get("photos") or []:
        link = (photo.get("_links") or {}).get("full", {}).get("href")
        if link:
            link = _supersize_url(link)
        if link and link not in urls:
            urls.append(link)

    if not urls:
        for photo in listing_data.get("cloudinary_photos") or []:
            link = photo.get("preview_url")
            if not link and photo.get("path"):
                link = f"https://rvb-img.reverb.com/image/upload/f_auto,t_supersize/{photo['path']}"
            else:
                link = _supersize_url(link)
            if link and link not in urls:
                urls.append(link)

    return urls


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
