import logging
import os
import re
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import Settings
from app.core.utils import ImageQuality, ImageTransformer
from app.models.ebay import EbayListing
from app.models.platform_common import PlatformCommon
from app.models.product import Product
from app.models.shopify import ShopifyListing
from app.services.ebay_service import EbayService
from app.services.reverb_service import ReverbService
from app.services.shopify_service import ShopifyService

logger = logging.getLogger("image_reconciliation")

SUPPORTED_PLATFORMS = {"reverb", "shopify", "ebay"}


def normalize_gallery(urls: Iterable[str]) -> List[Tuple[str, str]]:
    pairs: List[Tuple[str, str]] = []
    for url in urls:
        if not url:
            continue
        normalized = ImageTransformer.transform_reverb_url(url, ImageQuality.MAX_RES) or url
        pairs.append((normalized, url))
    return pairs


def _url_signature(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    segments = [segment for segment in parsed.path.split("/") if segment]
    if not segments:
        return (parsed.netloc or "").lower()

    filename = segments[-1].split("?")[0]
    stem, _ext = os.path.splitext(filename)

    normalized_stem = re.sub(r"_(\d+x\d+)(@\dx)?$", "", stem)
    normalized_stem = re.sub(
        r"_(\d+x\d+)(_[0-9a-z-]{6,})?$",
        "",
        normalized_stem,
        flags=re.IGNORECASE,
    )
    normalized_stem = re.sub(
        r"_(grande|large|medium|small|compact|master)$",
        "",
        normalized_stem,
        flags=re.IGNORECASE,
    )

    return normalized_stem.lower()


async def refresh_canonical_gallery(
    session: AsyncSession,
    settings: Settings,
    product: Product,
    refresh_reverb: bool = True,
) -> Tuple[List[str], bool]:
    """Return canonical gallery for product, optionally refreshing from Reverb."""

    gallery: List[str] = []
    if product.primary_image:
        gallery.append(product.primary_image)
    if product.additional_images:
        gallery.extend([img for img in product.additional_images if img])

    original_gallery = list(gallery)

    if not refresh_reverb:
        return gallery, False

    stmt = (
        select(PlatformCommon)
        .where(
            PlatformCommon.product_id == product.id,
            PlatformCommon.platform_name == "reverb",
        )
    )
    result = await session.execute(stmt)
    platform_common = result.scalar_one_or_none()

    if not platform_common or not platform_common.external_id:
        logger.warning("Product %s has no Reverb listing; skipping canonical refresh", product.id)
        return gallery, False

    expected = len(gallery) or None
    reverb_service = ReverbService(session, settings)
    logger.info(
        "Refreshing Reverb gallery for product %s (listing %s, expected %s images)",
        product.id,
        platform_common.external_id,
        expected,
    )
    refreshed = await reverb_service.refresh_product_images_from_listing(
        str(platform_common.external_id),
        expected_count=expected,
    )

    if refreshed:
        await session.commit()
        await session.refresh(product)

        new_gallery: List[str] = []
        if product.primary_image:
            new_gallery.append(product.primary_image)
        if product.additional_images:
            new_gallery.extend([img for img in product.additional_images if img])

        if new_gallery != original_gallery:
            logger.info(
                "Canonical gallery updated for product %s: %s -> %s images",
                product.id,
                len(original_gallery),
                len(new_gallery),
            )
            return new_gallery, True
        logger.info(
            "Canonical gallery refreshed for product %s with no material change (%s images)",
            product.id,
            len(new_gallery),
        )
        return new_gallery, False

    await session.rollback()
    logger.info("Reverb refresh returned no changes for product %s", product.id)
    return gallery, False


async def reconcile_shopify(
    session: AsyncSession,
    settings: Settings,
    product: Product,
    canonical_gallery: List[str],
    apply_fix: bool,
    log: Optional[logging.Logger] = None,
) -> Dict:
    log = log or logger

    stmt = (
        select(PlatformCommon)
        .options(selectinload(PlatformCommon.shopify_listing))
        .where(
            PlatformCommon.product_id == product.id,
            PlatformCommon.platform_name == "shopify",
        )
    )
    result = await session.execute(stmt)
    common = result.scalar_one_or_none()

    response: Dict = {
        "platform": "shopify",
        "available": bool(common),
        "canonical_count": len(canonical_gallery),
        "platform_count": 0,
        "missing": [],
        "extra": [],
        "needs_fix": False,
        "updated": False,
        "message": "",
        "error": None,
    }

    if not common:
        response["message"] = "Product has no Shopify listing."
        return response

    listing: Optional[ShopifyListing] = common.shopify_listing
    if not listing:
        listing_result = await session.execute(
            select(ShopifyListing).where(ShopifyListing.platform_id == common.id)
        )
        listing = listing_result.scalar_one_or_none()

    product_gid = None
    if listing:
        product_gid = listing.shopify_product_id or listing.handle
    if not product_gid:
        pdata = common.platform_specific_data or {}
        candidate = pdata.get("id") if isinstance(pdata, dict) else None
        if candidate and str(candidate).startswith("gid://"):
            product_gid = candidate

    if not product_gid:
        response["message"] = "Cannot determine Shopify product ID."
        response["error"] = "missing_product_gid"
        return response

    shopify_service = ShopifyService(session, settings)
    try:
        snapshot = shopify_service.client.get_product_snapshot_by_id(
            product_gid,
            num_images=50,
            num_variants=1,
            num_metafields=0,
        )
    except Exception as exc:  # noqa: BLE001
        response["message"] = f"Failed to fetch Shopify snapshot: {exc}"
        response["error"] = "snapshot_error"
        log.error("Failed to fetch Shopify snapshot for product %s: %s", product.id, exc)
        return response

    if not snapshot:
        response["message"] = "Shopify returned empty snapshot."
        response["error"] = "empty_snapshot"
        return response

    image_edges = (snapshot.get("images") or {}).get("edges") or []
    shopify_urls: List[str] = []
    shopify_image_ids: List[str] = []
    for edge in image_edges:
        node = edge.get("node") if isinstance(edge, dict) else None
        if not node:
            continue
        image_id = node.get("id")
        if image_id:
            shopify_image_ids.append(image_id)
        url = node.get("url") or node.get("src") or node.get("originalSrc")
        if url:
            shopify_urls.append(url)

    canonical_pairs = normalize_gallery(canonical_gallery)
    shopify_pairs = normalize_gallery(shopify_urls)

    response.update(
        {
            "platform_count": len(shopify_pairs),
            "missing": [],
            "extra": [],
            "needs_fix": len(shopify_pairs) != len(canonical_pairs),
            "message": "Shopify gallery matches canonical set." if len(shopify_pairs) == len(canonical_pairs) else "Shopify gallery count differs from canonical set.",
        }
    )

    log.info(
        "Product %s Shopify images: canonical=%s, shopify=%s",
        product.id,
        len(canonical_pairs),
        len(shopify_pairs),
    )

    if not apply_fix or not response["needs_fix"]:
        return response

    try:
        if shopify_image_ids:
            log.info(
                "Deleting %s existing Shopify images for product %s", len(shopify_image_ids), product_gid
            )
            shopify_service.client.delete_product_images_rest(product_gid, shopify_image_ids)

        payload = [{"src": url} for url in canonical_gallery]
        log.info(
            "Uploading %s canonical images to Shopify product %s", len(payload), product_gid
        )
        shopify_service.client.create_product_images(product_gid, payload)

        response["updated"] = True
        response["needs_fix"] = False
        response["missing"] = []
        response["extra"] = []
        response["platform_count"] = len(canonical_gallery)
        response["message"] = "Replaced Shopify gallery with canonical images."
    except Exception as exc:  # noqa: BLE001
        await session.rollback()
        response["error"] = "apply_error"
        response["message"] = f"Failed to update Shopify images: {exc}"
        log.error("Failed to add images to Shopify product %s: %s", product_gid, exc)
        return response

    return response


async def reconcile_ebay(
    session: AsyncSession,
    settings: Settings,
    product: Product,
    canonical_gallery: List[str],
    apply_fix: bool,
    log: Optional[logging.Logger] = None,
) -> Dict:
    log = log or logger

    stmt = (
        select(PlatformCommon)
        .options(selectinload(PlatformCommon.ebay_listing))
        .where(
            PlatformCommon.product_id == product.id,
            PlatformCommon.platform_name == "ebay",
        )
    )
    result = await session.execute(stmt)
    common = result.scalar_one_or_none()

    response: Dict = {
        "platform": "ebay",
        "available": bool(common),
        "canonical_count": len(canonical_gallery),
        "platform_count": 0,
        "missing": [],
        "extra": [],
        "needs_fix": False,
        "updated": False,
        "message": "",
        "error": None,
    }

    if not common:
        response["message"] = "Product has no eBay listing."
        return response

    listing: Optional[EbayListing] = common.ebay_listing

    item_id: Optional[str] = None
    if listing and listing.ebay_item_id:
        item_id = listing.ebay_item_id
    elif common.external_id:
        item_id = str(common.external_id)
    else:
        pdata = common.platform_specific_data or {}
        candidate = pdata.get("item_id") if isinstance(pdata, dict) else None
        if candidate:
            item_id = str(candidate)

    if not item_id:
        response["message"] = "Cannot determine eBay listing ID."
        response["error"] = "missing_item_id"
        return response

    ebay_service = EbayService(session, settings)

    stored_gallery: List[str] = []
    if listing and listing.picture_urls:
        stored_gallery = [url for url in listing.picture_urls if url]

    live_gallery: List[str] = []
    try:
        api_response = await ebay_service.trading_api.get_item(item_id)
        response_payload = api_response.get("GetItemResponse", {}) if isinstance(api_response, dict) else {}
        item_node = response_payload.get("Item") if isinstance(response_payload, dict) else None
        picture_details = item_node.get("PictureDetails") if item_node else None
        if picture_details:
            raw_urls = picture_details.get("PictureURL")
            if isinstance(raw_urls, list):
                live_gallery = [url for url in raw_urls if url]
            elif isinstance(raw_urls, str):
                live_gallery = [raw_urls]
    except Exception as exc:  # noqa: BLE001
        response["message"] = f"Failed to fetch live eBay gallery: {exc}"
        response["error"] = "get_item_error"
        log.warning(
            "Failed to fetch live eBay gallery for product %s (item %s): %s",
            product.id,
            item_id,
            exc,
        )

    current_gallery = live_gallery if live_gallery else stored_gallery

    canonical_pairs = normalize_gallery(canonical_gallery)
    current_pairs = normalize_gallery(current_gallery)

    response.update(
        {
            "platform_count": len(current_pairs),
            "live_count": len(live_gallery),
            "stored_count": len(stored_gallery),
            "missing": [],
            "extra": [],
            "needs_fix": len(current_pairs) != len(canonical_pairs),
            "message": "eBay gallery matches canonical set." if len(current_pairs) == len(canonical_pairs) else "eBay gallery count differs from canonical set.",
        }
    )

    log.info(
        "Product %s eBay images: canonical=%s, stored=%s, live=%s, using=%s",
        product.id,
        len(canonical_gallery),
        len(stored_gallery),
        len(live_gallery),
        len(current_gallery),
    )

    if not apply_fix or not response["needs_fix"]:
        return response

    upload_gallery = canonical_gallery[:24]
    if len(canonical_gallery) > 24:
        log.warning(
            "Canonical gallery for product %s exceeds eBay limit; truncating to first 24 images",
            product.id,
        )

    try:
        revise_response = await ebay_service.trading_api.revise_listing_images(item_id, upload_gallery)
        ack = revise_response.get("Ack") if isinstance(revise_response, dict) else None
        if ack not in {"Success", "Warning"}:
            response["error"] = "apply_error"
            response["message"] = f"Failed to update eBay images (ack={ack})."
            log.error(
                "Failed to update eBay images for product %s (item %s): %s",
                product.id,
                item_id,
                revise_response,
            )
            return response

        log.info(
            "Successfully updated eBay images for product %s (item %s) with %s images (ack=%s)",
            product.id,
            item_id,
            len(upload_gallery),
            ack,
        )

        if listing:
            listing.picture_urls = upload_gallery
        else:
            metadata: Dict = {}
            if isinstance(common.platform_specific_data, dict):
                metadata = dict(common.platform_specific_data)
            metadata["last_image_sync"] = upload_gallery
            common.platform_specific_data = metadata

        await session.commit()

        response["updated"] = True
        response["needs_fix"] = False
        response["missing"] = []
        response["extra"] = []
        response["platform_count"] = len(upload_gallery)
        response["message"] = "Replaced eBay gallery with canonical images."
    except Exception as exc:  # noqa: BLE001
        await session.rollback()
        response["error"] = "apply_error"
        response["message"] = f"Failed to update eBay images: {exc}"
        log.error(
            "Failed to revise eBay images for product %s (item %s): %s",
            product.id,
            item_id,
            exc,
        )

    return response
