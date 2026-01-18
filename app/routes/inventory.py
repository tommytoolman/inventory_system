import os
import re
import json
import math
import asyncio
import aiofiles
import logging
import iso8601

from decimal import Decimal
from enum import Enum
from pathlib import Path
from urllib.parse import quote_plus, urlparse
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any, Union, Tuple

from fastapi import (
    APIRouter, 
    Depends, 
    Request, 
    HTTPException, 
    BackgroundTasks,
    Form, 
    File, 
    UploadFile,
    Query,
)

from fastapi.responses import HTMLResponse, StreamingResponse, RedirectResponse, JSONResponse
from fastapi.encoders import jsonable_encoder

from sqlalchemy import select, or_, distinct, func, desc, and_, delete, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, selectinload

from app.core.config import Settings, get_settings
from app.core.enums import (
    PlatformName,
    ProductCondition,
    ProductStatus,
    Handedness,
    ManufacturingCountry,
    InventoryLocation,
    Storefront,
    CaseStatus,
)
from app.core.events import StockUpdateEvent
from app.core.exceptions import ProductCreationError, PlatformIntegrationError
from app.database import async_session
from app.dependencies import get_db, templates
from app.models.product import Product
from app.models.sync_event import SyncEvent
from app.models.category_mappings import ReverbCategory
from app.data.spec_fields import SPEC_FIELD_MAP, SPEC_FIELDS
from app.models.platform_common import PlatformCommon, ListingStatus, SyncStatus
from app.models.shipping import ShippingProfile
from app.models.vr import VRListing
from app.models.reverb import ReverbListing
from app.models.ebay import EbayListing
from app.models.shopify import ShopifyListing
# from app.services.dropbox.dropbox_async_service import AsyncDropboxClient
from app.services.category_mapping_service import CategoryMappingService
from app.services.product_service import ProductService
from app.services.ebay_service import EbayService, MUSICAL_INSTRUMENT_CATEGORY_IDS
from app.services.reverb_service import ReverbService
from app.services.shopify_service import ShopifyService
from app.services.condition_mapping_service import ConditionMappingService
from app.services.image_reconciliation import (
    refresh_canonical_gallery,
    reconcile_shopify,
    reconcile_ebay,
)
from app.services.shopify.utils import (
    ensure_description_has_standard_footer,
    generate_shopify_keywords,
    generate_shopify_short_description,
)
from app.services.vintageandrare.brand_validator import VRBrandValidator
from app.services.vintageandrare.client import VintageAndRareClient
from app.services.vintageandrare.export import VRExportService
from app.services.vintageandrare.constants import DEFAULT_VR_BRAND
from app.schemas.product import ProductCreate
from app.services.sync_services import SyncService
from app.services.vr_job_queue import enqueue_vr_job

router = APIRouter()

# Configuration for file uploads
UPLOAD_DIR = "app/static/uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

DRAFT_UPLOAD_DIR = Path(get_settings().DRAFT_UPLOAD_DIR).expanduser()
DRAFT_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
DRAFT_UPLOAD_URL_PREFIX = "/static/drafts"


async def get_dropbox_client(request: Request, settings: Settings = None) -> 'AsyncDropboxClient':
    """
    Get or create a shared Dropbox client with token persistence.

    This solves the token refresh issue where each request was creating a new client
    with a stale token, causing 401 errors on every request.

    The refreshed token is stored in app.state.dropbox_access_token so it persists
    across requests.
    """
    from app.services.dropbox.dropbox_async_service import AsyncDropboxClient

    if settings is None:
        settings = get_settings()

    # Check for refreshed token in app.state first (persists across requests)
    access_token = getattr(request.app.state, 'dropbox_access_token', None)

    # Fall back to settings/environment if no refreshed token
    if not access_token:
        access_token = getattr(settings, 'DROPBOX_ACCESS_TOKEN', None) or os.environ.get('DROPBOX_ACCESS_TOKEN')

    refresh_token = getattr(settings, 'DROPBOX_REFRESH_TOKEN', None) or os.environ.get('DROPBOX_REFRESH_TOKEN')
    app_key = getattr(settings, 'DROPBOX_APP_KEY', None) or os.environ.get('DROPBOX_APP_KEY')
    app_secret = getattr(settings, 'DROPBOX_APP_SECRET', None) or os.environ.get('DROPBOX_APP_SECRET')

    client = AsyncDropboxClient(
        access_token=access_token,
        refresh_token=refresh_token,
        app_key=app_key,
        app_secret=app_secret
    )

    # Test connection and refresh if needed
    if not await client.test_connection():
        # If test failed but we have refresh credentials, token may have been refreshed
        # Store the new token in app.state for future requests
        if client.access_token and client.access_token != access_token:
            request.app.state.dropbox_access_token = client.access_token
            logging.getLogger(__name__).info("Stored refreshed Dropbox token in app.state")
    else:
        # Connection succeeded, store token in case it was refreshed during test
        if client.access_token:
            request.app.state.dropbox_access_token = client.access_token

    return client


def _calculate_default_platform_price(
    platform: str,
    base_price: Optional[float],
    reverb_price: Optional[float] = None,  # Kept for backwards compatibility, but ignored
) -> float:
    """Return the suggested platform price given a base price.

    Uses centralized pricing from app/services/pricing.py with configurable
    markup percentages from environment variables:
    - EBAY_PRICE_MARKUP_PERCENT (default 10%)
    - VR_PRICE_MARKUP_PERCENT (default 5%)
    - REVERB_PRICE_MARKUP_PERCENT (default 5%)
    - SHOPIFY_PRICE_MARKUP_PERCENT (default 0%)

    All platforms calculate from BASE price, not from each other.
    """
    from app.services.pricing import calculate_platform_price

    if base_price is None:
        return 0.0

    base_value = float(base_price) if base_price else 0.0
    if base_value <= 0:
        return 0.0

    return calculate_platform_price(platform, base_value)


def _build_platform_stub(
    platform: str,
    base_price: Optional[float],
    reverb_price: Optional[float] = None,
) -> Dict[str, Any]:
    """Create a default platform entry for the edit form."""
    return {
        "status": "inactive",
        "external_id": None,
        "url": None,
        "price": _calculate_default_platform_price(platform, base_price, reverb_price),
    }


def _normalize_storefront_input(
    raw_value: Optional[str],
    default: Optional[Storefront] = None,
) -> Optional[Storefront]:
    """
    Normalize storefront input strings (enum names/values, mixed casing).
    Returns the matching Storefront or the provided default.
    """
    if not isinstance(raw_value, str):
        return default

    candidate = raw_value.strip()
    if not candidate:
        return default

    candidate_upper = candidate.upper()
    candidate_compact = candidate_upper.replace(" ", "_")

    for option in Storefront:
        if (
            candidate_upper == option.value.upper()
            or candidate_compact == option.name.upper()
        ):
            return option

    logger.warning(
        "Invalid storefront input '%s'; defaulting to %s",
        candidate,
        (default or Storefront.HANKS).value,
    )
    return default


async def _fetch_current_platform_prices(db: AsyncSession, product_id: int) -> Dict[str, float]:
    """Return the latest stored price for each platform for comparison."""
    result = await db.execute(select(PlatformCommon).where(PlatformCommon.product_id == product_id))
    platform_links = result.scalars().all()
    prices: Dict[str, float] = {}

    for link in platform_links:
        platform_key = (link.platform_name or "").lower()
        if not platform_key:
            continue

        price_value: Optional[float] = None
        stmt = None

        if platform_key == "shopify":
            stmt = select(ShopifyListing.price).where(ShopifyListing.platform_id == link.id)
        elif platform_key == "reverb":
            stmt = select(ReverbListing.list_price).where(ReverbListing.platform_id == link.id)
        elif platform_key == "ebay":
            stmt = select(EbayListing.price).where(EbayListing.platform_id == link.id)
        elif platform_key == "vr":
            stmt = select(VRListing.price_notax).where(VRListing.platform_id == link.id)

        if stmt is not None:
            price_value = (await db.execute(stmt)).scalar_one_or_none()

        if price_value is None:
            platform_specific = link.platform_specific_data or {}
            if isinstance(platform_specific, dict):
                raw_price = platform_specific.get("price")
                try:
                    price_value = float(raw_price) if raw_price is not None else None
                except (TypeError, ValueError):
                    price_value = None

        if price_value is not None:
            prices[platform_key] = float(price_value)

    return prices


PRICE_CHANGE_EPSILON = 0.01

# DEFAULT_EBAY_BRAND = "Gibson" # <<< ***IMPORTANT: CHOOSE A VALID BRAND FROM YOUR eBay Accepted Brands TABLE***
# DEFAULT_REVERB_BRAND = "Gibson" # <<< ***IMPORTANT: CHOOSE A VALID BRAND FROM YOUR Reverb Accepted Brands TABLE***

logger = logging.getLogger(__name__)


UPLOAD_DIR_PATH = Path(UPLOAD_DIR)
# DROPBOX_UPLOAD_ROOT = "/InventorySystem/auto-uploads"

def _is_local_upload(url: Optional[str]) -> bool:
    return bool(url and url.startswith("/static/uploads/"))


def _parse_price_to_decimal(value: Optional[Any]) -> Optional[Decimal]:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if isinstance(value, str):
        cleaned = value.replace(",", "").strip()
        if not cleaned:
            return None
        try:
            return Decimal(cleaned)
        except Exception:
            logger.warning("Unable to parse price value '%s'", value)
            return None
    return None


def _extract_saved_platform_price(product: Product, platform_key: str) -> Optional[float]:
    package_blob = product.package_dimensions if isinstance(product.package_dimensions, dict) else None
    if not package_blob:
        return None

    platform_data = package_blob.get("platform_data")
    if not isinstance(platform_data, dict):
        return None

    platform_blob = platform_data.get(platform_key)
    if not isinstance(platform_blob, dict):
        return None

    raw_price = platform_blob.get("price") or platform_blob.get("price_display")
    price_decimal = _parse_price_to_decimal(raw_price)
    return float(price_decimal) if price_decimal is not None else None


async def _fetch_latest_platform_listing_price(
    db: AsyncSession,
    product_id: int,
    platform: str,
) -> Optional[float]:
    platform = platform.lower()

    if platform == "reverb":
        stmt = (
            select(ReverbListing.list_price)
            .join(PlatformCommon, ReverbListing.platform_id == PlatformCommon.id)
            .where(
                PlatformCommon.product_id == product_id,
                PlatformCommon.platform_name == "reverb",
            )
            .order_by(ReverbListing.updated_at.desc())
            .limit(1)
        )
    elif platform == "ebay":
        stmt = (
            select(EbayListing.price)
            .join(PlatformCommon, EbayListing.platform_id == PlatformCommon.id)
            .where(
                PlatformCommon.product_id == product_id,
                PlatformCommon.platform_name == "ebay",
            )
            .order_by(EbayListing.updated_at.desc())
            .limit(1)
        )
    else:
        return None

    value = (await db.execute(stmt)).scalar_one_or_none()
    value_decimal = _parse_price_to_decimal(value)
    return float(value_decimal) if value_decimal is not None else None


async def _determine_vr_price(
    product: Product,
    db: AsyncSession,
    logger_instance: Optional[logging.Logger] = None,
) -> Optional[float]:
    if not product:
        return None

    # 1) Saved platform data (most recent form submission)
    saved_price = _extract_saved_platform_price(product, "vr")
    if saved_price is not None:
        if logger_instance:
            logger_instance.info(
                "Using saved VR price %.2f from platform options for SKU %s",
                saved_price,
                product.sku,
            )
        return saved_price

    # 2) Existing Reverb listing price
    reverb_price = await _fetch_latest_platform_listing_price(db, product.id, "reverb")
    if reverb_price is not None:
        if logger_instance:
            logger_instance.info(
                "Using latest Reverb price %.2f for SKU %s as VR reference",
                reverb_price,
                product.sku,
            )
        return reverb_price

    # 3) Existing eBay listing price
    ebay_price = await _fetch_latest_platform_listing_price(db, product.id, "ebay")
    if ebay_price is not None:
        if logger_instance:
            logger_instance.info(
                "Using latest eBay price %.2f for SKU %s as VR reference",
                ebay_price,
                product.sku,
            )
        return ebay_price

    # 4) Fallback: apply the standard markup logic
    if product.base_price is not None:
        reverb_price_fallback = float(product.price) if product.price else None
        fallback = _calculate_default_platform_price("vr", product.base_price, reverb_price_fallback)
        if logger_instance:
            logger_instance.info(
                "Calculated fallback VR price %.2f from base price %.2f for SKU %s",
                fallback,
                product.base_price,
                product.sku,
            )
        return fallback

    if logger_instance:
        logger_instance.warning(
            "Unable to determine VR price for SKU %s; base price missing", product.sku
        )
    return None
    if isinstance(value, str):
        cleaned = value.replace(",", "").strip()
        if not cleaned:
            return None
        try:
            return Decimal(cleaned)
        except Exception:
            logger.warning("Unable to parse price value '%s'", value)
            return None
    return None


def _decimal_to_str(value: Decimal) -> str:
    try:
        return format(value.quantize(Decimal("0.01")), "f")
    except Exception:
        return format(value, "f")


def _parse_iso_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = iso8601.parse_date(value)
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)
    except Exception:
        try:
            normalized = value.replace("Z", "+00:00")
            return datetime.fromisoformat(normalized)
        except Exception:
            logger.warning("Unable to parse ISO datetime value '%s'", value)
            return None


def _ensure_url_scheme(value: Optional[str]) -> Optional[str]:
    if value and not value.startswith(("http://", "https://")):
        return f"https://{value.lstrip('/')}"
    return value


def _generate_shopify_handle(brand: Optional[str], model: Optional[str], sku: Optional[str]) -> Optional[str]:
    """Create a stable Shopify handle from product attributes."""
    import re

    parts = [str(part) for part in [brand, model, sku] if part and str(part).lower() != "nan"]
    if not parts:
        return None

    text = "-".join(parts).lower()
    text = re.sub(r"[^a-z0-9\-]+", "-", text)
    handle = text.strip('-')
    return handle or None


async def _lookup_shopify_category(
    db: AsyncSession,
    reverb_category_name: Optional[str],
) -> Optional[Dict[str, Optional[str]]]:
    """Return Shopify category data mapped from a Reverb category name."""

    if not reverb_category_name:
        logger.debug("Shopify category lookup skipped: no reverb category provided")
        return None

    lowered = reverb_category_name.lower()
    params = {"category_name": lowered}

    base_query = text(
        """
        SELECT
            shopify_gid,
            target_category_name
        FROM platform_category_mappings
        WHERE source_platform = 'reverb'
          AND target_platform = 'shopify'
          AND lower(source_category_name) = :category_name
        ORDER BY COALESCE(is_verified, false) DESC,
                 COALESCE(confidence_score, 0) DESC,
                 id ASC
        LIMIT 1
        """
    )

    logger.debug("Looking up Shopify category for '%s'", lowered)
    result = await db.execute(base_query, params)
    row = result.mappings().first()

    if not row:
        logger.debug("No exact Shopify category match for '%s'; trying fuzzy lookup", lowered)
        fuzzy_query = text(
            """
            SELECT
                shopify_gid,
                target_category_name
            FROM platform_category_mappings
            WHERE source_platform = 'reverb'
              AND target_platform = 'shopify'
              AND lower(source_category_name) LIKE :category_like
            ORDER BY COALESCE(is_verified, false) DESC,
                     COALESCE(confidence_score, 0) DESC,
                     id ASC
            LIMIT 1
            """
        )
        result = await db.execute(fuzzy_query, {"category_like": f"{lowered}%"})
        row = result.mappings().first()

    if not row:
        logger.warning("Shopify category mapping missing for '%s'", lowered)
        return None

    shopify_gid = row.get("shopify_gid")
    if not shopify_gid:
        logger.warning("Shopify mapping for '%s' missing gid", lowered)
        return None

    category_full_name = row.get("target_category_name")
    category_name = (
        category_full_name.split(" > ")[-1].strip()
        if isinstance(category_full_name, str)
        else None
    )

    logger.debug(
        "Shopify category resolved for '%s': gid=%s, name=%s",
        lowered,
        shopify_gid,
        category_full_name,
    )

    return {
        "category_gid": shopify_gid,
        "category_full_name": category_full_name,
        "category_name": category_name,
    }


async def _persist_shopify_listing(
    db: AsyncSession,
    settings: Settings,
    product: Product,
    shopify_result: Dict[str, Any],
    *,
    shopify_options: Optional[Dict[str, Any]] = None,
    shopify_generated_keywords: Optional[List[str]] = None,
    shopify_generated_seo_title: Optional[str] = None,
    shopify_generated_short_description: Optional[str] = None,
) -> Dict[str, Any]:
    """Upsert platform_common and shopify_listings entries from a Shopify publish result."""

    if not isinstance(shopify_result, dict):
        logger.error("Shopify persistence aborted: result is not a dict (%s)", type(shopify_result))
        return {
            "status": "error",
            "message": "Invalid Shopify response; could not persist listing",
        }

    if shopify_result.get("status") != "success":
        return {
            "status": "error",
            "message": shopify_result.get("message", "Failed to create Shopify listing"),
        }

    shopify_options = shopify_options or {}
    if not isinstance(shopify_options, dict):
        logger.warning("Shopify options payload was %s; defaulting to empty dict", type(shopify_options))
        shopify_options = {}

    snapshot_payload = shopify_result.get("snapshot")
    if not isinstance(snapshot_payload, dict):
        if snapshot_payload not in (None, {}):
            logger.warning(
                "Shopify snapshot payload was unexpected type %s; falling back to empty dict",
                type(snapshot_payload),
            )
        snapshot_payload = {}

    platform_payload = snapshot_payload or shopify_result

    external_id_raw = (
        shopify_result.get("external_id")
        or shopify_result.get("shopify_product_id")
        or snapshot_payload.get("legacyResourceId")
    )
    external_id = str(external_id_raw or "")

    if not external_id:
        return {
            "status": "error",
            "message": "No Shopify legacy ID returned",
        }

    base_title = (
        snapshot_payload.get("title")
        or shopify_result.get("title")
        or product.title
        or product.generate_title()
        or ""
    )

    handle = None
    if base_title:
        import re

        normalized = re.sub(r"[^a-zA-Z0-9\s-]", "", base_title)
        normalized = re.sub(r"\s+", "-", normalized.strip())
        handle = normalized.lower()
    if not handle and product.sku:
        handle = _generate_shopify_handle(product.brand, product.model, product.sku)


    listing_url = (
        snapshot_payload.get("onlineStoreUrl")
        or snapshot_payload.get("onlineStorePreviewUrl")
        or shopify_result.get("listing_url")
    )
    if not listing_url and handle:
        base_url = getattr(settings, "SHOPIFY_SHOP_URL", None)
        if base_url:
            parsed = urlparse(base_url if base_url.startswith("http") else f"https://{base_url}")
            domain = parsed.netloc or parsed.path
            if domain:
                listing_url = f"https://{domain.rstrip('/')}/products/{handle}"
        if not listing_url:
            listing_url = f"https://londonvintageguitars.myshopify.com/products/{handle}"

    listing_url = _ensure_url_scheme(listing_url)

    existing_platform_common = await db.execute(
        select(PlatformCommon).where(
            and_(
                PlatformCommon.product_id == product.id,
                PlatformCommon.platform_name == "shopify",
            )
        )
    )
    platform_common = existing_platform_common.scalar_one_or_none()

    seo_data = snapshot_payload.get("seo") if isinstance(snapshot_payload.get("seo"), dict) else {}
    seo_title = seo_data.get("title") or shopify_generated_seo_title
    seo_description = seo_data.get("description") or shopify_generated_short_description

    category_node = snapshot_payload.get("category") if isinstance(snapshot_payload, dict) else None
    category_gid = (
        shopify_options.get("category")
        or shopify_options.get("category_gid")
        or shopify_result.get("category_gid")
        or (category_node.get("id") if isinstance(category_node, dict) else None)
    )
    category_name = (
        shopify_result.get("category_name")
        or shopify_options.get("category_name")
        or None
    )
    category_full_name = (
        shopify_result.get("category_full_name")
        or shopify_options.get("category_full_name")
        or None
    )
    category_assignment_status = None
    category_assigned_at = None

    product_category = snapshot_payload.get("productCategory")
    if isinstance(product_category, dict):
        taxonomy_node = product_category.get("productTaxonomyNode") or {}
        category_gid = category_gid or taxonomy_node.get("id")
        category_name = category_name or taxonomy_node.get("name")
        category_full_name = category_full_name or taxonomy_node.get("fullName")

    if isinstance(category_node, dict):
        category_gid = category_gid or category_node.get("id")
        category_name = category_name or category_node.get("name")
        category_full_name = category_full_name or category_node.get("fullName")

    if category_gid:
        category_assignment_status = "assigned"
        updated_at = snapshot_payload.get("updatedAt") or shopify_result.get("updated_at")
        category_assigned_at = _parse_iso_datetime(updated_at)

    if not category_gid:
        mapped_category = await _lookup_shopify_category(db, product.category)
        if mapped_category:
            logger.info(
                "Persist: using fallback Shopify category for product %s (%s) -> %s",
                product.id,
                product.category,
                mapped_category,
            )
            category_gid = mapped_category.get("category_gid")
            category_name = mapped_category.get("category_name") or category_name
            category_full_name = mapped_category.get("category_full_name") or category_full_name
            category_assignment_status = category_assignment_status or "assigned"
            if not category_assigned_at:
                category_assigned_at = datetime.utcnow()
            shopify_options.setdefault("category_gid", category_gid)
            if category_full_name:
                shopify_options.setdefault("category_full_name", category_full_name)
            if category_name:
                shopify_options.setdefault("category_name", category_name)
        else:
            logger.warning(
                "Persist: category still missing for product %s (%s)",
                product.id,
                product.category,
            )

    snapshot_tags = snapshot_payload.get("tags") if isinstance(snapshot_payload.get("tags"), list) else None
    resolved_keywords = snapshot_tags or shopify_generated_keywords or None

    price_decimal = _parse_price_to_decimal(
        shopify_result.get("price")
        or shopify_options.get("price")
        or shopify_options.get("price_display")
        or product.base_price
    )
    price_float = float(price_decimal) if price_decimal is not None else None

    product_title = (
        snapshot_payload.get("title")
        or product.title
        or product.generate_title()
    )

    sync_status_value = SyncStatus.SYNCED.value.upper()

    if platform_common:
        platform_common.external_id = external_id
        platform_common.status = "active"
        platform_common.listing_url = listing_url or platform_common.listing_url
        platform_common.sync_status = sync_status_value
        platform_common.last_sync = datetime.utcnow()
        platform_common.platform_specific_data = platform_payload
    else:
        platform_common = PlatformCommon(
            product_id=product.id,
            platform_name="shopify",
            external_id=external_id,
            status="active",
            listing_url=listing_url,
            sync_status=sync_status_value,
            last_sync=datetime.utcnow(),
            platform_specific_data=platform_payload,
        )
        db.add(platform_common)

    await db.flush()

    listing_stmt = select(ShopifyListing).where(ShopifyListing.platform_id == platform_common.id)
    existing_listing = await db.execute(listing_stmt)
    shopify_listing = existing_listing.scalar_one_or_none()

    product_gid = shopify_result.get("product_gid") or (
        snapshot_payload.get("id") if str(snapshot_payload.get("id", "")).startswith("gid://") else None
    )
    if not product_gid:
        product_gid = f"gid://shopify/Product/{external_id}"

    # Get shipping profile GID from result if it was assigned
    shipping_profile_gid = shopify_result.get("shipping_profile_gid")

    listing_payload = {
        "platform_id": platform_common.id,
        "shopify_product_id": product_gid,
        "shopify_legacy_id": external_id,
        "handle": handle,
        "title": product_title,
        "status": "active",
        "vendor": snapshot_payload.get("vendor") or product.brand,
        "price": price_float,
        "category_gid": category_gid,
        "category_name": category_name,
        "category_full_name": category_full_name,
        "category_assigned_at": category_assigned_at,
        "category_assignment_status": category_assignment_status,
        "seo_title": seo_title,
        "seo_description": seo_description,
        "seo_keywords": resolved_keywords,
        "shipping_profile_id": shipping_profile_gid,
        "extended_attributes": platform_payload,
        "last_synced_at": datetime.utcnow(),
    }

    if shopify_listing:
        for field, value in listing_payload.items():
            setattr(shopify_listing, field, value)
    else:
        shopify_listing = ShopifyListing(**listing_payload)
        db.add(shopify_listing)

    await db.commit()

    message = f"Listed on Shopify with ID: {external_id}"
    if listing_url:
        message += " (link updated)"

    return {
        "status": "success",
        "message": message,
        "external_id": external_id,
        "listing_url": listing_url,
    }


async def _upload_local_image_to_dropbox(
    local_url: str,
    sku: str,
    *args: Any,
    **kwargs: Any,
) -> Optional[str]:
    """Placeholder while Dropbox uploads are disabled.

    Uploading to Dropbox currently requires the `files.content.write` scope,
    which is not enabled on the connected app. Keep the helper in place so it
    can be reactivated quickly once the permissions are updated.
    """

    logger.debug(
        "Dropbox upload disabled; returning local URL for %s (SKU %s)",
        local_url,
        sku,
    )
    return None


async def ensure_remote_media_urls(
    primary_image: Optional[str],
    additional_images: List[str],
    sku: str,
    settings: Settings,
) -> tuple[Optional[str], List[str]]:
    notice_logged = False  # Disabled 2025-10-31: Dropbox upload path paused (missing Dropbox scope)

    async def convert(url: Optional[str]) -> Optional[str]:
        nonlocal notice_logged
        if not _is_local_upload(url):
            return url
        if not notice_logged:
            logger.info(
                "Skipping Dropbox upload for %s (app lacks files.content.write scope)",
                url,
            )
            notice_logged = True
        return url

    converted_primary = await convert(primary_image) if primary_image else primary_image
    converted_additional = []
    for image_url in additional_images:
        converted_additional.append(await convert(image_url))

    return converted_primary, converted_additional


def schedule_reverb_image_refresh(
    reverb_listing_id: Optional[str],
    *,
    expected_count: Optional[int],
    settings: Settings,
) -> None:
    """Run the Reverb image refresh in the background once the request completes."""

    if not reverb_listing_id:
        return

    async def _runner() -> None:
        async with async_session() as session:
            service = ReverbService(session, settings)
            try:
                updated = await service.refresh_product_images_from_listing(
                    str(reverb_listing_id),
                    expected_count=expected_count,
                    retry_delays=[2.0, 2.0, 2.0, 5.0, 5.0, 10.0, 10.0],
                )
                if updated:
                    await session.commit()
                else:
                    await session.rollback()
            except Exception:  # pragma: no cover - background path
                logger.exception(
                    "Background Reverb image refresh failed for listing %s",
                    reverb_listing_id,
                )
                await session.rollback()

    asyncio.create_task(_runner())


def generate_shopify_handle(brand: Optional[str], model: Optional[str], sku: Optional[str]) -> str:
    parts = [str(part) for part in [brand, model, sku] if part]
    text = "-".join(parts).lower()
    text = re.sub(r"[^a-z0-9\-]+", "-", text)
    return text.strip('-')


async def _prepare_vr_payload_from_product_object(
    product: Product,
    db: AsyncSession,
    logger_instance: logging.Logger,
    use_fallback_brand: bool = False,
    override_price: Optional[float] = None,
) -> tuple[Dict[str, Any], bool]:
    """
    Prepares the rich dictionary payload for V&R export from an existing Product object.
    
    Args:
        use_fallback_brand: If True, uses DEFAULT_VR_BRAND instead of product.brand
    
    Note: Brand validation should be performed via VRBrandValidator.validate_brand() 
    before calling this function to ensure the brand is accepted by V&R.
    """
    
    brand_was_defaulted = False
    payload = {}
    logger_instance.debug(f"Preparing V&R payload for product SKU '{product.sku}'.")


    # --- ITEM INFORMATION ---
    
    # Category (Mandatory for V&R). Ensure product.category is a string, strip whitespace for reliable key lookup
    product_reverb_category = str(product.category).strip() if product.category else None
    
    if not product_reverb_category:
        logger_instance.error(f"Product SKU '{product.sku}' has no Reverb category (product.category is None or empty). Cannot map to V&R.")
        raise ValueError(f"Product SKU '{product.sku}' has no Reverb category set, which is needed for V&R mapping.")

    # Resolve category mapping from platform_category_mappings instead of JSON cache
    category_lookup_query = text(
        """
        SELECT
            vr_category_id,
            vr_subcategory_id,
            vr_sub_subcategory_id,
            vr_sub_sub_subcategory_id
        FROM platform_category_mappings
        WHERE source_platform = 'reverb'
          AND target_platform = 'vintageandrare'
          AND lower(source_category_name) = :category_name
        ORDER BY COALESCE(is_verified, false) DESC,
                 COALESCE(confidence_score, 0) DESC,
                 id ASC
        LIMIT 1
        """
    )

    mapping_result = await db.execute(
        category_lookup_query,
        {"category_name": product_reverb_category.lower()}
    )
    mapping_row = mapping_result.mappings().first()

    if not mapping_row:
        # Fallback: try a prefix match to allow for minor label differences
        logger_instance.warning(
            "No exact V&R mapping found for '%s'; attempting prefix search in platform_category_mappings.",
            product_reverb_category,
        )
        fuzzy_query = text(
            """
            SELECT
                vr_category_id,
                vr_subcategory_id,
                vr_sub_subcategory_id,
                vr_sub_sub_subcategory_id
            FROM platform_category_mappings
            WHERE source_platform = 'reverb'
              AND target_platform = 'vintageandrare'
              AND lower(source_category_name) LIKE :category_like
            ORDER BY COALESCE(is_verified, false) DESC,
                     COALESCE(confidence_score, 0) DESC,
                     id ASC
            LIMIT 1
            """
        )
        fuzzy_result = await db.execute(
            fuzzy_query,
            {"category_like": f"{product_reverb_category.lower()}%"}
        )
        mapping_row = fuzzy_result.mappings().first()

    if not mapping_row or not mapping_row.get("vr_category_id"):
        logger_instance.error(
            "No platform_category_mappings entry found for Reverb category '%s' (SKU '%s').",
            product_reverb_category,
            product.sku,
        )
        raise ValueError(
            f"Category mapping missing for Reverb category '{product_reverb_category}' (SKU: '{product.sku}'). "
            "Please add this category to the platform_category_mappings table."
        )

    payload["Category"] = mapping_row.get("vr_category_id")
    if mapping_row.get("vr_subcategory_id"):
        payload["SubCategory1"] = mapping_row.get("vr_subcategory_id")
    if mapping_row.get("vr_sub_subcategory_id"):
        payload["SubCategory2"] = mapping_row.get("vr_sub_subcategory_id")
    if mapping_row.get("vr_sub_sub_subcategory_id"):
        payload["SubCategory3"] = mapping_row.get("vr_sub_sub_subcategory_id")

    # Construct log message for mapped categories
    log_message_parts = [f"Cat1='{payload.get('Category')}'"]
    if payload.get("SubCategory1"):
        log_message_parts.append(f"Cat2='{payload.get('SubCategory1')}'")
    if payload.get("SubCategory2"):
        log_message_parts.append(f"Cat3='{payload.get('SubCategory2')}'")
    if payload.get("SubCategory3"):
        log_message_parts.append(f"Cat4='{payload.get('SubCategory3')}'")

    logger_instance.info(
        "Mapped Reverb category '%s' to V&R categories: %s for SKU '%s'.",
        product_reverb_category,
        ', '.join(log_message_parts),
        product.sku,
    )

    # --- Brand / Maker (With fallback support) ---
    if not product.brand:
        logger_instance.warning(f"Product SKU '{product.sku}' has no brand set. Using '{DEFAULT_VR_BRAND}' for V&R.")
        payload["brand"] = DEFAULT_VR_BRAND
        brand_was_defaulted = True
    elif use_fallback_brand:
        # User chose to proceed with fallback brand for unrecognized brand
        logger_instance.info(f"Using fallback brand '{DEFAULT_VR_BRAND}' for SKU '{product.sku}' (original brand '{product.brand}' not recognized by V&R).")
        payload["brand"] = DEFAULT_VR_BRAND
        brand_was_defaulted = True
    else:
        # Use the validated brand
        payload["brand"] = product.brand
        logger_instance.info(f"Using validated brand '{product.brand}' for SKU '{product.sku}'.")
    
    
    # --- Model Name --- (Mandatory)
    if not product.model:
        raise ValueError(f"Model name is mandatory for V&R listing (product SKU: {product.sku}).")
    payload["model"] = product.model

    # --- Year --- (Optional)
    if product.year:
        payload["year"] = str(product.year)
        payload["decade"] = f"{str(product.year // 10 * 10)}s"

    # --- Finish/Color --- (Optional)
    if product.finish:
        payload["finish"] = product.finish # V&R uses "FinishColour"

    # --- Item Description --- (User-side mandatory for you)
    if not product.description: # Ensuring it's not empty, as per your requirement
        raise ValueError(f"Description is mandatory for V&R listing (product SKU: {product.sku}).")
    payload["description"] = product.description

    # --- SKU --- 
    if product.sku:
        # payload["sku"] = product.sku  # ✅ Keep this for reference  
        payload["external_id"] = product.sku  # ✅ Add this - what client.py expects
            
    #  --- Condition --- (not a value in V&R)
    if product.condition:
        payload["condition"] = product.condition.value if isinstance(product.condition, Enum) else str(product.condition)

    # --- Item Price ---
    resolved_price = override_price if override_price is not None else product.base_price
    if resolved_price is None:
        raise ValueError(f"Price is mandatory for V&R listing (product SKU: {product.sku}).")
    try:
        payload["price"] = float(Decimal(str(resolved_price)))  # Ensure proper formatting
    except Exception:
        raise ValueError(f"Invalid price format for product SKU '{product.sku}': {resolved_price}")
    payload["currency"] = "GBP"

    # --- Media (Structured for client.py) ---
    payload['primary_image'] = product.primary_image if product.primary_image and isinstance(product.primary_image, str) else None
    
    additional_images_list: List[str] = []
    if product.additional_images:
        source_images = product.additional_images
        if isinstance(source_images, str): # If it's a JSON string
            try:
                parsed_images = json.loads(source_images)
                if isinstance(parsed_images, list): source_images = parsed_images
                else: source_images = [str(parsed_images)]
            except json.JSONDecodeError: source_images = [source_images] # Treat as single URL string
        
        if isinstance(source_images, list):
            for img_item in source_images:
                url_to_add: Optional[str] = None
                if isinstance(img_item, dict) and 'url' in img_item and isinstance(img_item['url'], str):
                    url_to_add = img_item['url']
                elif isinstance(img_item, str):
                    url_to_add = img_item
                
                if url_to_add and url_to_add != payload['primary_image'] and url_to_add not in additional_images_list:
                    additional_images_list.append(url_to_add)
        else:
            logger_instance.warning(f"product.additional_images for SKU {product.sku} unhandled type: {type(source_images)}")
            
    payload['additional_images'] = additional_images_list

    payload['video_url'] = product.video_url
    payload['external_link'] = product.external_link

    # --- V&R Specific Flags & Commerce Fields ---
    show_vat = product.show_vat if getattr(product, "show_vat", None) is not None else True
    payload["vr_show_vat"] = bool(show_vat)
    payload["vr_call_for_price"] = False

    payload["vr_in_collective"] = bool(getattr(product, "in_collective", False))
    payload["vr_in_inventory"] = bool(getattr(product, "in_inventory", True))
    payload["vr_in_reseller"] = bool(getattr(product, "in_reseller", False))
    payload["vr_buy_now"] = bool(getattr(product, "buy_now", False))

    collective_discount_value = getattr(product, "collective_discount", None)
    if collective_discount_value is None:
        collective_discount_value = 0.0
    try:
        collective_discount_value = float(collective_discount_value)
    except (TypeError, ValueError):
        collective_discount_value = 0.0

    payload["vr_collective_discount"] = (
        f"{collective_discount_value:.2f}"
        if collective_discount_value
        else None
    )
    payload["collective_discount"] = collective_discount_value

    price_notax_value = getattr(product, "price_notax", None)
    if price_notax_value is None:
        price_notax_value = resolved_price
    payload["price_notax"] = price_notax_value

    processing_time_value = getattr(product, "processing_time", None)
    if processing_time_value is None:
        processing_time_value = 3
    payload["processing_time"] = str(processing_time_value)
    payload["time_unit"] = "Days"

    payload["available_for_shipment"] = bool(getattr(product, "available_for_shipment", True))
    payload["local_pickup"] = bool(getattr(product, "local_pickup", False))

    # --- Shipping Fees ---
    default_shipping = {
        "uk": "75",
        "europe": "50",
        "usa": "100",
        "world": "150",
    }

    shipping_rates = default_shipping.copy()

    if getattr(product, "shipping_profile_id", None):
        profile = None
        try:
            profile = getattr(product, "shipping_profile", None)
        except Exception:
            profile = None

        if profile is None:
            result = await db.execute(
                select(ShippingProfile).where(ShippingProfile.id == product.shipping_profile_id)
            )
            profile = result.scalar_one_or_none()

        if profile and profile.rates:
            def _format_rate(value: Any, fallback: str) -> str:
                try:
                    return (
                        f"{float(value):.2f}".rstrip("0").rstrip(".")
                        if value is not None
                        else fallback
                    )
                except (TypeError, ValueError):
                    return fallback

            shipping_rates = {
                "uk": _format_rate(profile.rates.get("uk"), shipping_rates["uk"]),
                "europe": _format_rate(profile.rates.get("europe"), shipping_rates["europe"]),
                "usa": _format_rate(profile.rates.get("usa"), shipping_rates["usa"]),
                "world": _format_rate(profile.rates.get("row"), shipping_rates["world"]),
            }

    payload["shipping_uk_fee"] = shipping_rates["uk"]
    payload["shipping_europe_fee"] = shipping_rates["europe"]
    payload["shipping_usa_fee"] = shipping_rates["usa"]
    payload["shipping_world_fee"] = shipping_rates["world"]
    payload["shipping_fees"] = shipping_rates

    logger_instance.info(
        "Prepared V&R payload shipping fees for %s: %s",
        product.sku,
        shipping_rates,
    )

    if not getattr(product, "shipping_profile_id", None):
        logger_instance.warning(
            f"No shipping profile ID for {product.sku}. Using default V&R shipping fees."
        )

    # Log the final payload before returning
    try:
        payload_json_for_log = json.dumps(payload, indent=2, default=str)
        logger_instance.debug(f"Prepared V&R payload for SKU '{product.sku}': {payload_json_for_log}")
    except TypeError: # In case something non-serializable is in payload (shouldn't be)
        logger_instance.debug(f"Prepared V&R payload for SKU '{product.sku}' (contains non-serializable elements, showing dict): {payload}")

    return payload, brand_was_defaulted


def _sanitize_path_component(value: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9._-]", "-", value or "")
    sanitized = sanitized.strip("-_")
    return sanitized or datetime.now().strftime("%Y%m%d%H%M%S")


def _sanitize_filename(filename: Optional[str]) -> str:
    name = Path(filename or "upload").name
    sanitized = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    return sanitized or "upload"


def _draft_media_subdir(draft_id: Optional[int], sku: Optional[str]) -> str:
    if draft_id is not None:
        return f"id-{_sanitize_path_component(str(draft_id))}"
    if sku:
        return f"sku-{_sanitize_path_component(sku)}"
    return f"draft-{datetime.now().strftime('%Y%m%d%H%M%S')}"


async def save_draft_upload_file(upload_file: UploadFile, subdir: str) -> str:
    """Save an uploaded draft file under the configured draft media directory."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    filename = f"{timestamp}_{_sanitize_filename(upload_file.filename)}"

    target_dir = DRAFT_UPLOAD_DIR / subdir
    target_dir.mkdir(parents=True, exist_ok=True)
    filepath = target_dir / filename

    async with aiofiles.open(filepath, "wb") as out_file:
        content = await upload_file.read()
        await out_file.write(content)

    return f"{DRAFT_UPLOAD_URL_PREFIX}/{subdir}/{filename}"


async def save_upload_file(upload_file: UploadFile) -> str:
    """Save an uploaded file and return its path"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{timestamp}_{_sanitize_filename(upload_file.filename)}"
    filepath = os.path.join(UPLOAD_DIR, filename)

    async with aiofiles.open(filepath, 'wb') as out_file:
        content = await upload_file.read()
        await out_file.write(content)

    return f"/static/uploads/{filename}"


def cleanup_draft_media(subdir: str, keep_urls: List[str]) -> None:
    """Remove orphaned files from a draft media directory."""
    directory = DRAFT_UPLOAD_DIR / subdir
    if not directory.exists() or not directory.is_dir():
        return

    keep_filenames: set[str] = set()
    for url in keep_urls:
        if not url:
            continue
        parsed = urlparse(url)
        path = parsed.path
        prefix = f"{DRAFT_UPLOAD_URL_PREFIX}/{subdir}/"
        if path.startswith(prefix):
            keep_filenames.add(Path(path).name)

    try:
        for file_path in directory.iterdir():
            if file_path.is_file() and file_path.name not in keep_filenames:
                file_path.unlink(missing_ok=True)

        if not any(directory.iterdir()):
            directory.rmdir()
    except Exception as cleanup_error:
        logger.warning(
            "Failed to tidy draft media directory %s: %s",
            subdir,
            cleanup_error,
        )

def process_platform_data(form_data: Dict[str, Any]) -> Dict[str, Any]:
    """Extract platform-specific data from form fields"""
    platform_data = {}
    
    # Process eBay data
    ebay_data = {}
    for key, value in form_data.items():
        if key.startswith("platform_data__ebay__"):
            field_name = key.replace("platform_data__ebay__", "")
            # Handle boolean values (checkboxes)
            if value in [True, 'true', 'True', 'on']:
                ebay_data[field_name] = True
            elif value in [False, 'false', 'False']:
                ebay_data[field_name] = False
            else:
                ebay_data[field_name] = value
    
    if ebay_data:
        platform_data["ebay"] = ebay_data
    
    # Process Reverb data
    reverb_data = {}
    for key, value in form_data.items():
        if key.startswith("platform_data__reverb__"):
            field_name = key.replace("platform_data__reverb__", "")
            # Handle boolean values (checkboxes)
            if value in [True, 'true', 'True', 'on']:
                reverb_data[field_name] = True
            elif value in [False, 'false', 'False']:
                reverb_data[field_name] = False
            else:
                reverb_data[field_name] = value
    
    if reverb_data:
        platform_data["reverb"] = reverb_data
    
    # Process V&R data
    vr_data = {}
    for key, value in form_data.items():
        if key.startswith("platform_data__vr__"):
            field_name = key.replace("platform_data__vr__", "")
            vr_data[field_name] = value
    
    if vr_data:
        platform_data["vr"] = vr_data
    
    # Process shopify data
    shopify_data = {}
    for key, value in form_data.items():
        if key.startswith("platform_data__shopify__"):
            field_name = key.replace("platform_data__shopify__", "")
            shopify_data[field_name] = value
    
    if shopify_data:
        platform_data["shopify"] = shopify_data
    
    return platform_data

@router.get("/api/products/{product_id}")
async def get_product_json(
    product_id: int,
    db: AsyncSession = Depends(get_db)
):
    """API endpoint to get product data for copy from existing feature"""
    query = select(Product).where(Product.id == product_id)
    result = await db.execute(query)
    product = result.scalar_one_or_none()
    
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    
    # Convert to dict and exclude sensitive fields
    product_dict = jsonable_encoder(product)
    
    # Return JSON response
    return product_dict

@router.get("/", response_class=HTMLResponse)
async def list_products(
    request: Request,
    page: int = 1,
    per_page: Union[int, str] = 100,  # Default to 100
    search: Optional[str] = None,
    category: Optional[str] = None,
    brand: Optional[str] = None,
    platform: Optional[str] = None,  
    status: Optional[str] = None,
    state: Optional[str] = None,
    sort: Optional[str] = None,      # NEW: Sort column
    order: Optional[str] = 'asc',    # NEW: Sort direction
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings)
):
    # Handle the case when per_page is 'all'
    if per_page == 'all':
        pagination_limit = None  # No limit
        pagination_offset = 0
    else:
        try:
            per_page = int(per_page)
        except (ValueError, TypeError):
            per_page = 100  # Default to 100 if conversion fails
            
        pagination_limit = per_page
        pagination_offset = (page - 1) * per_page
    
    # Handle status/state parameter (state is alias for status)
    status_query_param = request.query_params.get("status")
    state_query_param = request.query_params.get("state")
    filter_status = status or state

    if (
        status_query_param is None
        and state_query_param is None
        and not filter_status
    ):
        filter_status = "active"
        status_query_param = "active"

    status_query_value = (
        status_query_param
        if status_query_param is not None
        else state_query_param
    )
    
    # Build query using async style
    if platform:
        # If platform filter is specified, join with PlatformCommon to filter by platform
        from app.models.platform_common import PlatformCommon
        
        query = (
            select(Product)
            .join(PlatformCommon, Product.id == PlatformCommon.product_id)
            .where(PlatformCommon.platform_name.ilike(f"%{platform}%"))
        )
        
        # Add status filter if specified
        if filter_status:
            # Map common status values
            status_mapping = {
                'active': 'active',
                'live': 'active',
                'draft': 'draft',
                'sold': 'sold',
                'ended': 'ended',
                'pending': 'pending',
                'deleted': 'deleted',
            }
            
            mapped_status = status_mapping.get(filter_status.lower(), filter_status)
            query = query.where(PlatformCommon.status.ilike(f"%{mapped_status}%"))
            
    else:
        # No platform filter - query products directly
        query = select(Product)
        
        # Add status filter on Product table if specified
        if filter_status:
            # Convert string to enum for comparison
            from app.models.product import ProductStatus
            
            # Map frontend values to ProductStatus enum
            status_mapping = {
                'active': ProductStatus.ACTIVE,
                'live': ProductStatus.ACTIVE,     # Alias
                'draft': ProductStatus.DRAFT,
                'sold': ProductStatus.SOLD,
                'archived': ProductStatus.ARCHIVED,
                'ended': ProductStatus.ARCHIVED,  # Map "ended" to archived
                'pending': ProductStatus.DRAFT,   # Map "pending" to draft
                'deleted': ProductStatus.DELETED,
            }
            
            # Get the enum value
            enum_status = status_mapping.get(filter_status.lower())
            if enum_status:
                query = query.where(Product.status == enum_status)
    
    # Apply existing filters
    if search:
        search_term = f"%{search}%"
        query = query.filter(
            or_(
                Product.brand.ilike(search_term),
                Product.model.ilike(search_term),
                Product.sku.ilike(search_term),
                Product.description.ilike(search_term)
            )
        )
    
    if category:
        query = query.filter(Product.category == category)
    
    if brand:
        query = query.filter(Product.brand == brand)
    
    # Get total count before pagination
    count_query = select(func.count()).select_from(query.subquery())
    count_result = await db.execute(count_query)
    total = count_result.scalar_one()
    
    # Apply pagination and ordering
    # Add sorting logic BEFORE the default ordering
    if sort and sort in ['brand', 'model', 'category', 'price', 'status']:
        if sort == 'price':
            sort_column = Product.base_price
        elif sort == 'brand':
            sort_column = Product.brand
        elif sort == 'model':
            sort_column = Product.model
        elif sort == 'category':
            sort_column = Product.category
        elif sort == 'status':
            sort_column = Product.status
        
        # Apply sort direction
        if order == 'desc':
            query = query.order_by(desc(sort_column))
        else:
            query = query.order_by(sort_column)
    else:
        # Default ordering - newest first
        query = query.order_by(desc(Product.created_at))
    
    # Apply pagination and ordering
    # query = query.order_by(desc(Product.created_at))
    
    if pagination_limit:
        query = query.offset(pagination_offset).limit(pagination_limit)
    
    # Execute query
    result = await db.execute(query)
    products = result.scalars().all()
    
    # Get unique categories and brands for filters
    # Configuration for dropdown sort order - Options: 'alphabetical' or 'count'
    CATEGORY_DROPDOWN_SORT = 'count'  # Sort by most common first
    BRAND_DROPDOWN_SORT = 'alphabetical'  # Sort alphabetically
    
    # Build categories query
    categories_query = (
        select(Product.category, func.count(Product.id).label("count"))
        .filter(Product.category.isnot(None))
        .group_by(Product.category)
    )
    if CATEGORY_DROPDOWN_SORT == 'count':
        categories_query = categories_query.order_by(desc(func.count(Product.id)))
    else:  # 'alphabetical'
        categories_query = categories_query.order_by(Product.category)
    
    categories_result = await db.execute(categories_query)
    categories_with_counts = [(c[0], c[1]) for c in categories_result.all() if c[0]]
    
    # Build brands query
    brands_query = (
        select(Product.brand, func.count(Product.id).label("count"))
        .filter(Product.brand.isnot(None))
        .group_by(Product.brand)
    )
    if BRAND_DROPDOWN_SORT == 'count':
        brands_query = brands_query.order_by(desc(func.count(Product.id)))
    else:  # 'alphabetical'
        brands_query = brands_query.order_by(Product.brand)
    brands_result = await db.execute(brands_query)
    brands_with_counts = [(b[0], b[1]) for b in brands_result.all() if b[0]]
    
    # Calculate pagination info
    if per_page != 'all' and per_page > 0:
        total_pages = (total + per_page - 1) // per_page
        start_page = max(1, page - 2)
        end_page = min(total_pages, page + 2)
        
        # Calculate start and end items for display
        start_item = (page - 1) * per_page + 1 if total > 0 else 0
        end_item = min(page * per_page, total)
    else:
        total_pages = 1
        page = 1
        start_page = 1
        end_page = 1
        # For "all" pages
        start_item = 1 if total > 0 else 0
        end_item = total
    
    message = request.query_params.get("message")
    message_type = request.query_params.get("message_type", "info")
    selected_status_value = (
        filter_status.lower()
        if isinstance(filter_status, str) and filter_status
        else None
    )
    status_query_value = status_query_value if status_query_value is not None else ""

    return templates.TemplateResponse(
        "inventory/list.html",
        {
            "request": request,
            "products": products,
            "total_products": total,
            "page": page,
            "per_page": per_page,
            "total_pages": total_pages,
            "start_page": start_page,
            "end_page": end_page,
            "start_item": start_item,
            "end_item": end_item,
            "categories": categories_with_counts,
            "brands": brands_with_counts,
            "selected_category": category,
            "selected_brand": brand,
            "selected_platform": platform,    # NEW: Pass to template
            "selected_status": selected_status_value,
            "status_query_value": status_query_value,
            "search": search,
            "has_prev": page > 1,
            "has_next": page < total_pages,
            "current_sort": sort,          # NEW: Pass current sort
            "current_order": order,        # NEW: Pass current order
            "message": message,
            "message_type": message_type,
        }
    )

# Alias list_products to list_inventory_route for compatibility with tests
list_inventory_route = list_products

# Explicitly export the alias
__all__ = ["list_inventory_route", "router"]


async def get_sale_info(db: AsyncSession, product_id: int) -> Optional[Dict]:
    """
    Get sale information for a product by analyzing sync_events.

    Returns dict with:
    - sold_platform: platform where item was sold (or None if private sale)
    - sold_date: when it was sold
    - ended_platforms: list of platforms where it was ended
    - is_private_sale: True if ended on platforms but no platform shows 'sold'
    """
    # Query all status change events for this product that indicate sold/ended
    result = await db.execute(
        select(SyncEvent)
        .where(
            SyncEvent.product_id == product_id,
            SyncEvent.change_type == 'status_change',
        )
        .order_by(SyncEvent.detected_at.desc())
    )
    events = result.scalars().all()

    if not events:
        return None

    sold_platform = None
    sold_date = None
    ended_platforms = []

    for event in events:
        change_data = event.change_data or {}
        new_status = (change_data.get('new') or '').lower()

        if new_status == 'sold':
            # This platform shows a confirmed sale
            if not sold_platform:  # Take the most recent
                sold_platform = event.platform_name
                sold_date = event.detected_at
        elif new_status in ('ended', 'sold_out'):
            ended_platforms.append({
                'platform': event.platform_name,
                'date': event.detected_at
            })

    if not sold_platform and not ended_platforms:
        return None

    # If no platform shows 'sold' but we have 'ended' events, it's a private sale
    is_private_sale = sold_platform is None and len(ended_platforms) > 0

    # For private sales, use the most recent ended date
    if is_private_sale and ended_platforms:
        sold_date = ended_platforms[0]['date']  # Already sorted desc

    return {
        'sold_platform': sold_platform,
        'sold_date': sold_date,
        'ended_platforms': ended_platforms,
        'is_private_sale': is_private_sale,
    }


@router.get("/product/{product_id}", response_class=HTMLResponse)
async def product_detail(
    request: Request,
    product_id: int,
    db: AsyncSession = Depends(get_db)
):
    logger.info(f"Fetching details for product ID: {product_id}")
    try:
        # 1. Fetch Product
        product_query = select(Product).where(Product.id == product_id)
        product_result = await db.execute(product_query)
        product = product_result.scalar_one_or_none()

        if not product:
            logger.warning(f"Product with ID {product_id} not found.")
            return templates.TemplateResponse(
                "errors/404.html",
                {"request": request, "error_message": f"Product ID {product_id} not found."},
                status_code=404
            )

        # 2. Fetch Existing PlatformCommon Listings for this Product
        common_listings_query = (
            select(PlatformCommon)
            .options(selectinload(PlatformCommon.ebay_listing))
            .where(PlatformCommon.product_id == product_id)
        )
        common_listings_result = await db.execute(common_listings_query)
        existing_common_listings = common_listings_result.scalars().all()

        common_listings_map = {
            listing.platform_name.upper(): listing for listing in existing_common_listings
        }
        logger.debug(f"Fetched {len(existing_common_listings)} PlatformCommon records for product {product_id}.")

        # 3. Construct `all_platforms_status` for the template
        all_platforms_status = []

        for platform_enum in PlatformName:
            platform_display_name = platform_enum.value # This will be "EBAY", "REVERB", "VR", "SHOPIFY"
            platform_url_slug = platform_enum.slug # Uses the @property from your enum

            entry = {
                "name": platform_display_name, # For display in template
                "slug": platform_url_slug,     # For URL generation in template
                "is_listed": False,
                "details": None
            }

            # platform_enum.value (e.g., "VR") is used to check against keys in common_listings_map
            if platform_enum.value in common_listings_map:
                common_listing_record = common_listings_map[platform_enum.value]
                entry["is_listed"] = True

                sync_status_for_template = "Unknown"
                if common_listing_record.status:
                    status_upper = common_listing_record.status.upper()
                    if status_upper == "ACTIVE":
                        sync_status_for_template = "SYNCED"
                    elif status_upper == "DRAFT":
                        sync_status_for_template = "PENDING"
                    elif status_upper == "ERROR":
                        sync_status_for_template = "ERROR"
                    else:
                        sync_status_for_template = common_listing_record.status
                
                # Ensure these getattr calls use the correct attribute names from your PlatformCommon model
                entry["details"] = {
                    "external_id": getattr(common_listing_record, 'external_id', None) or \
                                    getattr(common_listing_record, 'platform_product_id', 'N/A'),
                    "status": getattr(common_listing_record, 'status', None),
                    "sync_status": sync_status_for_template,
                    "last_sync": getattr(common_listing_record, 'last_synced', None) or \
                                    getattr(common_listing_record, 'updated_at', None),
                    "message": getattr(common_listing_record, 'platform_message', None),
                    "listing_url": getattr(common_listing_record, 'listing_url', None)
                }

                if platform_enum.value == "EBAY":
                    ebay_listing = getattr(common_listing_record, "ebay_listing", None)
                    uses_crazylister = False
                    description_sources: List[str] = []

                    if ebay_listing and getattr(ebay_listing, "listing_data", None):
                        listing_data_raw = ebay_listing.listing_data
                        listing_data_obj = {}

                        if isinstance(listing_data_raw, dict):
                            listing_data_obj = listing_data_raw
                        elif isinstance(listing_data_raw, str):
                            try:
                                listing_data_obj = json.loads(listing_data_raw)
                            except json.JSONDecodeError:
                                listing_data_obj = {"Description": listing_data_raw}

                        if listing_data_obj:
                            if "uses_crazylister" in listing_data_obj:
                                uses_crazylister = bool(listing_data_obj.get("uses_crazylister"))
                            else:
                                potential_html = []

                                direct_desc = listing_data_obj.get("Description")
                                if isinstance(direct_desc, str):
                                    potential_html.append(direct_desc)

                                raw_block = listing_data_obj.get("Raw")
                                if isinstance(raw_block, dict):
                                    raw_desc = raw_block.get("Description")
                                    if isinstance(raw_desc, str):
                                        potential_html.append(raw_desc)

                                    item_block = raw_block.get("Item")
                                    if isinstance(item_block, dict):
                                        item_desc = item_block.get("Description")
                                        if isinstance(item_desc, str):
                                            potential_html.append(item_desc)

                                listing_section = listing_data_obj.get("listing_data")
                                if isinstance(listing_section, dict):
                                    section_desc = listing_section.get("Description")
                                    if isinstance(section_desc, str):
                                        potential_html.append(section_desc)

                                for html_snippet in potential_html:
                                    if html_snippet:
                                        description_sources.append(html_snippet)

                    if not uses_crazylister and product and product.description:
                        description_sources.append(product.description)

                    if not uses_crazylister:
                        for source_html in description_sources:
                            if source_html and "crazylister" in source_html.lower():
                                uses_crazylister = True
                                break

                    entry["details"]["uses_crazylister"] = uses_crazylister

            all_platforms_status.append(entry)
        
        logger.debug(f"Constructed all_platforms_status for product {product_id}: {all_platforms_status}")

        # 4. Load platform status messages from flash cookie (fallback to query string for legacy URLs)
        platform_messages: List[Dict[str, str]] = []
        flash_cookie = request.cookies.get("flash_status")
        if flash_cookie:
            try:
                parsed_messages = json.loads(flash_cookie)
                if isinstance(parsed_messages, list):
                    platform_messages = [msg for msg in parsed_messages if isinstance(msg, dict)]
            except json.JSONDecodeError:
                platform_messages = []

        if not platform_messages:
            from urllib.parse import unquote
            show_status = request.query_params.get("show_status") == "true"
            if show_status:
                for platform in ["reverb", "ebay", "shopify", "vr"]:
                    status = request.query_params.get(f"{platform}_status")
                    message = request.query_params.get(f"{platform}_message")

                    if status and message:
                        platform_messages.append({
                            "platform": platform.upper(),
                            "status": status,
                            "message": unquote(message),
                        })

        # 5. Prepare context for the template
        prev_product_row = await db.execute(
            select(Product.id, Product.title, Product.brand, Product.model)
            .where(Product.id < product_id)
            .order_by(Product.id.desc())
            .limit(1)
        )
        prev_product = None
        row = prev_product_row.first()
        if row is not None:
            mapping = row._mapping
            prev_product = {
                "id": mapping["id"],
                "title": mapping["title"],
                "brand": mapping["brand"],
                "model": mapping["model"],
            }

        next_product_row = await db.execute(
            select(Product.id, Product.title, Product.brand, Product.model)
            .where(Product.id > product_id)
            .order_by(Product.id.asc())
            .limit(1)
        )
        next_product = None
        row = next_product_row.first()
        if row is not None:
            mapping = row._mapping
            next_product = {
                "id": mapping["id"],
                "title": mapping["title"],
                "brand": mapping["brand"],
                "model": mapping["model"],
            }

        reverb_listing_id = None
        reverb_listing = common_listings_map.get("REVERB")
        if reverb_listing and reverb_listing.external_id:
            reverb_listing_id = reverb_listing.external_id

        # Get sale info for sold products
        sale_info = None
        if product.status and product.status.value.upper() == 'SOLD':
            sale_info = await get_sale_info(db, product_id)

        # Stale listing check for Flow 3 (Paid Feature)
        from app.core.utils import is_listing_stale, get_listing_age_months
        from app.core.config import get_settings
        stale_settings = get_settings()

        reverb_published_at = None
        if reverb_listing:
            # Get reverb_listings to check published date
            reverb_listing_query = select(ReverbListing).where(
                ReverbListing.platform_id == reverb_listing.id
            )
            reverb_listing_result = await db.execute(reverb_listing_query)
            reverb_listing_row = reverb_listing_result.scalar_one_or_none()
            if reverb_listing_row:
                reverb_published_at = reverb_listing_row.reverb_published_at

        listing_is_stale = is_listing_stale(
            reverb_published_at,
            product.created_at,
            stale_settings.STALE_LISTING_THRESHOLD_MONTHS
        )
        listing_age_months = get_listing_age_months(reverb_published_at, product.created_at)

        context = {
            "request": request,
            "product": product,
            "all_platforms_status": all_platforms_status,
            "platform_messages": platform_messages,
            "prev_product": prev_product,
            "next_product": next_product,
            "reverb_listing_id": reverb_listing_id,
            "sale_info": sale_info,
            "listing_is_stale": listing_is_stale,
            "listing_age_months": listing_age_months,
            "stale_threshold_months": stale_settings.STALE_LISTING_THRESHOLD_MONTHS,
        }

        response = templates.TemplateResponse("inventory/detail.html", context)
        if flash_cookie:
            response.delete_cookie("flash_status")

        return response

    except Exception as e:
        logger.error(f"Error in product_detail for product_id {product_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")


def _summarize_differences(results: List[Dict]) -> List[str]:
    lines: List[str] = []
    for result in results:
        if not result.get("available") or result.get("error"):
            continue
        if result.get("needs_fix"):
            base = f"{result['platform'].capitalize()}: {result.get('platform_count')} of {result.get('canonical_count')} images"
            live_count = result.get("live_count")
            if live_count is not None and live_count != result.get("platform_count"):
                base += f" (live: {live_count})"
            stored_count = result.get("stored_count")
            if stored_count is not None and stored_count != result.get("platform_count") and stored_count != live_count:
                base += f" (stored: {stored_count})"
            lines.append(base)
    return lines


@router.post("/product/{product_id}/refresh_images", response_class=JSONResponse)
async def refresh_product_images(
    product_id: int,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    product = await db.get(Product, product_id)
    if not product:
        return JSONResponse(
            {"status": "error", "message": "Product not found."},
            status_code=404,
        )

    canonical_gallery, canonical_updated = await refresh_canonical_gallery(db, settings, product, refresh_reverb=True)

    platform_results: List[Dict[str, Any]] = []

    shopify_result = await reconcile_shopify(db, settings, product, canonical_gallery, apply_fix=False)
    platform_results.append(shopify_result)

    ebay_result = await reconcile_ebay(db, settings, product, canonical_gallery, apply_fix=False)
    platform_results.append(ebay_result)

    errors = [res for res in platform_results if res.get("error")]
    if errors:
        message = "; ".join(res.get("message", "Unknown error") for res in errors)
        return JSONResponse(
            {
                "status": "error",
                "message": message,
                "message_type": "error",
                "needs_fix": True,
                "canonical_updated": canonical_updated,
                "platform_results": platform_results,
            },
            status_code=500,
        )

    actionable_results = [res for res in platform_results if res.get("available")]
    needs_fix = any(res.get("needs_fix") for res in actionable_results)
    summary_lines = _summarize_differences(platform_results)

    if needs_fix:
        base_message = "Detected image discrepancies."
        if summary_lines:
            base_message += " " + ", ".join(summary_lines)
        message_type = "warning"
    else:
        base_message = "Platform galleries already match the RIFF images."
        message_type = "success"

    return JSONResponse(
        {
            "status": "success",
            "message": base_message,
            "message_type": message_type,
            "needs_fix": needs_fix,
            "canonical_updated": canonical_updated,
            "platform_results": platform_results,
        }
    )


@router.post("/product/{product_id}/fix_images", response_class=JSONResponse)
async def fix_product_images(
    product_id: int,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    product = await db.get(Product, product_id)
    if not product:
        return JSONResponse(
            {"status": "error", "message": "Product not found."},
            status_code=404,
        )

    canonical_gallery, canonical_updated = await refresh_canonical_gallery(db, settings, product, refresh_reverb=True)

    platform_results: List[Dict[str, Any]] = []

    shopify_result = await reconcile_shopify(db, settings, product, canonical_gallery, apply_fix=True)
    platform_results.append(shopify_result)

    ebay_result = await reconcile_ebay(db, settings, product, canonical_gallery, apply_fix=True)
    platform_results.append(ebay_result)

    errors = [res for res in platform_results if res.get("error")]
    if errors:
        message = "; ".join(res.get("message", "Unable to update images") for res in errors)
        return JSONResponse(
            {
                "status": "error",
                "message": message,
                "message_type": "error",
                "needs_fix": True,
                "canonical_updated": canonical_updated,
                "platform_results": platform_results,
            },
            status_code=500,
        )

    actionable_results = [res for res in platform_results if res.get("available")]
    needs_fix = any(res.get("needs_fix") for res in actionable_results)
    summary_lines = _summarize_differences(platform_results)

    if needs_fix:
        base_message = "Some platforms still report mismatched image counts."
        if summary_lines:
            base_message += " " + ", ".join(summary_lines)
        message_type = "warning"
    else:
        base_message = "Shopify and eBay galleries now mirror the RIFF images."
        message_type = "success"

    return JSONResponse(
        {
            "status": "success",
            "message": base_message,
            "message_type": message_type,
            "needs_fix": needs_fix,
            "canonical_updated": canonical_updated,
            "platform_results": platform_results,
        }
    )


@router.post("/product/{product_id}/relist", response_class=JSONResponse)
async def relist_product(
    product_id: int,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """
    Flow 2: Proactive relist from RIFF UI.

    Relists a product on ALL platforms where it has existing listings.
    Use this when an order is cancelled and the user wants to relist on all platforms.

    Unlike Flow 1 (reactive from Reverb sync), this endpoint:
    - Also relists on Reverb (publishes an ended listing)
    - Can be triggered directly from the RIFF UI

    eBay Notes:
    - eBay relist generates a NEW ItemID
    - Old listing is orphaned (platform_id=NULL) with relist history in listing_data
    - New listing row is created and linked to platform_common
    """
    from app.services.ebay.trading import EbayTradingLegacyAPI
    from app.services.vr_service import VRService

    logger = logging.getLogger(__name__)
    logger.info(f"Relist request for product {product_id}")

    # Get product with platform listings
    stmt = select(Product).where(Product.id == product_id).options(
        selectinload(Product.platform_listings)
    )
    result = await db.execute(stmt)
    product = result.scalar_one_or_none()

    if not product:
        return JSONResponse(
            {"status": "error", "message": "Product not found."},
            status_code=404,
        )

    # Build a map of platform_common records
    platform_commons: Dict[str, PlatformCommon] = {}
    for pc in product.platform_listings:
        platform_commons[pc.platform_name] = pc

    if not platform_commons:
        return JSONResponse(
            {"status": "error", "message": "No platform listings found for this product."},
            status_code=400,
        )

    platform_results: List[Dict[str, Any]] = []
    now_utc = datetime.utcnow()  # Use naive datetime for TIMESTAMP WITHOUT TIME ZONE columns

    # --- Relist on Reverb ---
    if 'reverb' in platform_commons:
        reverb_pc = platform_commons['reverb']
        if reverb_pc.external_id:
            try:
                reverb_service = ReverbService(db, settings)
                # Use the underlying client to publish (relist) the listing
                await reverb_service.client.update_listing(
                    reverb_pc.external_id,
                    {"publish": True}
                )

                # Update local database
                reverb_pc.status = ListingStatus.ACTIVE.value
                reverb_pc.sync_status = SyncStatus.SYNCED.value
                reverb_pc.last_sync = now_utc
                db.add(reverb_pc)

                # Update reverb_listings table if exists
                reverb_listing_stmt = select(ReverbListing).where(
                    ReverbListing.platform_id == reverb_pc.id
                )
                reverb_listing_result = await db.execute(reverb_listing_stmt)
                reverb_listing = reverb_listing_result.scalar_one_or_none()
                if reverb_listing:
                    reverb_listing.reverb_state = "live"
                    db.add(reverb_listing)

                platform_results.append({
                    "platform": "reverb",
                    "success": True,
                    "message": f"Relisted on Reverb (ID: {reverb_pc.external_id})",
                })
                logger.info(f"Reverb relist successful for {product.sku}")
            except Exception as e:
                platform_results.append({
                    "platform": "reverb",
                    "success": False,
                    "message": f"Reverb error: {str(e)}",
                })
                logger.error(f"Reverb relist failed for {product.sku}: {e}")
        else:
            logger.info(f"Reverb listing has no external_id for {product.sku}, skipping")

    # --- Relist on eBay ---
    if 'ebay' in platform_commons:
        ebay_pc = platform_commons['ebay']
        if ebay_pc.external_id:
            try:
                ebay_api = EbayTradingLegacyAPI(sandbox=False)
                relist_response = await ebay_api.relist_fixed_price_item(ebay_pc.external_id)

                ack = relist_response.get('Ack', '')
                if ack in ['Success', 'Warning']:
                    new_item_id = relist_response.get('ItemID')
                    if new_item_id:
                        old_item_id = ebay_pc.external_id

                        # Step 1: Find and orphan the OLD ebay_listings row
                        old_listing_stmt = select(EbayListing).where(
                            EbayListing.ebay_item_id == old_item_id
                        )
                        old_listing_result = await db.execute(old_listing_stmt)
                        old_ebay_listing = old_listing_result.scalar_one_or_none()

                        if old_ebay_listing:
                            # Orphan the old listing
                            old_ebay_listing.platform_id = None
                            old_ebay_listing.listing_status = 'ENDED'
                            old_ebay_listing.updated_at = now_utc

                            # Add relist history to listing_data
                            listing_data = old_ebay_listing.listing_data or {}
                            listing_data['_relist_info'] = {
                                'reason': 'manual_relist_from_riff',
                                'relisted_to_item_id': new_item_id,
                                'relisted_at': now_utc.isoformat(),
                                'original_product_sku': product.sku,
                                'original_product_id': product.id
                            }
                            old_ebay_listing.listing_data = listing_data
                            db.add(old_ebay_listing)
                            logger.info(f"Orphaned old eBay listing {old_item_id} with relist history")

                        # Step 2: Create NEW ebay_listings row
                        new_ebay_listing = EbayListing(
                            ebay_item_id=new_item_id,
                            listing_status='ACTIVE',
                            platform_id=ebay_pc.id,
                            title=old_ebay_listing.title if old_ebay_listing else None,
                            price=old_ebay_listing.price if old_ebay_listing else None,
                            quantity=old_ebay_listing.quantity if old_ebay_listing else 1,
                            quantity_available=1,
                            ebay_category_id=old_ebay_listing.ebay_category_id if old_ebay_listing else None,
                            ebay_category_name=old_ebay_listing.ebay_category_name if old_ebay_listing else None,
                            ebay_condition_id=old_ebay_listing.ebay_condition_id if old_ebay_listing else None,
                            condition_display_name=old_ebay_listing.condition_display_name if old_ebay_listing else None,
                            picture_urls=old_ebay_listing.picture_urls if old_ebay_listing else None,
                            item_specifics=old_ebay_listing.item_specifics if old_ebay_listing else None,
                            payment_policy_id=old_ebay_listing.payment_policy_id if old_ebay_listing else None,
                            return_policy_id=old_ebay_listing.return_policy_id if old_ebay_listing else None,
                            shipping_policy_id=old_ebay_listing.shipping_policy_id if old_ebay_listing else None,
                            start_time=now_utc,
                            listing_data={
                                '_relisted_from': old_item_id,
                                '_relisted_at': now_utc.isoformat()
                            }
                        )
                        db.add(new_ebay_listing)

                        # Step 3: Update platform_common with new external_id and URL
                        ebay_pc.external_id = new_item_id
                        ebay_pc.listing_url = f"https://www.ebay.co.uk/itm/{new_item_id}"
                        ebay_pc.status = ListingStatus.ACTIVE.value
                        ebay_pc.sync_status = SyncStatus.SYNCED.value
                        ebay_pc.last_sync = now_utc
                        db.add(ebay_pc)

                        platform_results.append({
                            "platform": "ebay",
                            "success": True,
                            "message": f"Relisted on eBay: {old_item_id} → {new_item_id}",
                            "old_item_id": old_item_id,
                            "new_item_id": new_item_id,
                        })
                        logger.info(f"eBay relist successful for {product.sku}: {old_item_id} → {new_item_id}")
                    else:
                        platform_results.append({
                            "platform": "ebay",
                            "success": False,
                            "message": "eBay relist succeeded but no new ItemID returned",
                        })
                else:
                    errors = relist_response.get('Errors', [])
                    if not isinstance(errors, list):
                        errors = [errors]
                    error_msg = "; ".join([e.get('LongMessage', 'Unknown') for e in errors if isinstance(e, dict)])
                    platform_results.append({
                        "platform": "ebay",
                        "success": False,
                        "message": f"eBay relist failed: {error_msg}",
                    })
                    logger.error(f"eBay relist failed for {product.sku}: {error_msg}")
            except Exception as e:
                platform_results.append({
                    "platform": "ebay",
                    "success": False,
                    "message": f"eBay error: {str(e)}",
                })
                logger.error(f"eBay relist failed for {product.sku}: {e}")
        else:
            logger.info(f"eBay listing has no external_id for {product.sku}, skipping")

    # --- Relist on Shopify ---
    if 'shopify' in platform_commons:
        shopify_pc = platform_commons['shopify']
        if shopify_pc.external_id:
            try:
                shopify_service = ShopifyService(db)
                # Use days_since_sold=7 to handle both active and archived cases
                relist_result = await shopify_service.relist_listing(
                    shopify_pc.external_id,
                    days_since_sold=7
                )

                if relist_result.get('success'):
                    shopify_pc.status = ListingStatus.ACTIVE.value
                    shopify_pc.sync_status = SyncStatus.SYNCED.value
                    shopify_pc.last_sync = now_utc
                    db.add(shopify_pc)

                    platform_results.append({
                        "platform": "shopify",
                        "success": True,
                        "message": f"Relisted on Shopify (ID: {shopify_pc.external_id})",
                    })
                    logger.info(f"Shopify relist successful for {product.sku}")
                else:
                    platform_results.append({
                        "platform": "shopify",
                        "success": False,
                        "message": f"Shopify relist failed: {relist_result.get('error', 'Unknown error')}",
                    })
            except Exception as e:
                platform_results.append({
                    "platform": "shopify",
                    "success": False,
                    "message": f"Shopify error: {str(e)}",
                })
                logger.error(f"Shopify relist failed for {product.sku}: {e}")
        else:
            logger.info(f"Shopify listing has no external_id for {product.sku}, skipping")

    # --- Relist on V&R ---
    if 'vr' in platform_commons:
        vr_pc = platform_commons['vr']
        if vr_pc.external_id:
            try:
                vr_service = VRService(db)
                vr_success = await vr_service.restore_from_sold(vr_pc.external_id)

                if vr_success:
                    vr_pc.status = ListingStatus.ACTIVE.value
                    vr_pc.sync_status = SyncStatus.SYNCED.value
                    vr_pc.last_sync = now_utc
                    db.add(vr_pc)

                    platform_results.append({
                        "platform": "vr",
                        "success": True,
                        "message": f"Relisted on V&R (ID: {vr_pc.external_id})",
                    })
                    logger.info(f"V&R relist successful for {product.sku}")
                else:
                    platform_results.append({
                        "platform": "vr",
                        "success": False,
                        "message": "V&R restore_from_sold returned False",
                    })
            except Exception as e:
                platform_results.append({
                    "platform": "vr",
                    "success": False,
                    "message": f"V&R error: {str(e)}",
                })
                logger.error(f"V&R relist failed for {product.sku}: {e}")
        else:
            logger.info(f"V&R listing has no external_id for {product.sku}, skipping")

    # Update product status to ACTIVE if any platform succeeded
    successful_platforms = [r for r in platform_results if r.get('success')]
    if successful_platforms:
        product.status = ProductStatus.ACTIVE
        db.add(product)

    # Commit all changes
    await db.commit()

    # Summarize results
    successful = [r for r in platform_results if r.get('success')]
    failed = [r for r in platform_results if not r.get('success')]

    if not platform_results:
        return JSONResponse({
            "status": "warning",
            "message": "No platforms available for relist (no external IDs)",
            "message_type": "warning",
            "platform_results": [],
        })

    if failed and not successful:
        return JSONResponse({
            "status": "error",
            "message": f"Relist failed on all platforms",
            "message_type": "error",
            "platform_results": platform_results,
        }, status_code=500)

    if failed:
        return JSONResponse({
            "status": "partial",
            "message": f"Relisted on {len(successful)} platform(s), failed on {len(failed)}",
            "message_type": "warning",
            "platform_results": platform_results,
        })

    return JSONResponse({
        "status": "success",
        "message": f"Successfully relisted on {len(successful)} platform(s)",
        "message_type": "success",
        "platform_results": platform_results,
    })


@router.post("/product/{product_id}/refresh", response_class=JSONResponse)
async def refresh_stale_listing(
    product_id: int,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """
    Flow 3: Stale Listing Refresh (Paid Feature).

    Ends old listings on Reverb, eBay, V&R and creates new ones.
    Shopify is EXCLUDED (kept for SEO).

    This is different from relist (Flow 1/2) because:
    - Old listings are ENDED/DELETED, not just republished
    - NEW listing IDs are generated on all platforms
    - Old platform_common records are orphaned with status=REFRESHED
    - Fresh timestamps give better platform visibility

    Returns:
        JSON with status and per-platform results
    """
    from app.services.ebay_service import EbayService
    from app.services.vr_service import VRService
    from app.services.reverb_service import ReverbService
    from app.core.utils import is_listing_stale, get_listing_age_months

    logger.info(f"Stale refresh request for product {product_id}")

    # Get product with platform listings and reverb_listings for age check
    stmt = (
        select(Product)
        .where(Product.id == product_id)
        .options(
            selectinload(Product.platform_listings),
        )
    )
    result = await db.execute(stmt)
    product = result.scalar_one_or_none()

    if not product:
        return JSONResponse(
            {"status": "error", "message": "Product not found."},
            status_code=404,
        )

    # Build a map of platform_common records
    platform_commons: Dict[str, PlatformCommon] = {}
    for pc in product.platform_listings:
        platform_commons[pc.platform_name] = pc

    if not platform_commons:
        return JSONResponse(
            {"status": "error", "message": "No platform listings found for this product."},
            status_code=400,
        )

    # Get reverb_published_at for staleness check
    reverb_published_at = None
    if 'reverb' in platform_commons:
        reverb_pc = platform_commons['reverb']
        reverb_listing_stmt = select(ReverbListing).where(
            ReverbListing.platform_id == reverb_pc.id
        )
        reverb_listing_result = await db.execute(reverb_listing_stmt)
        reverb_listing = reverb_listing_result.scalar_one_or_none()
        if reverb_listing:
            reverb_published_at = reverb_listing.reverb_published_at

    # Check if listing qualifies as stale
    threshold = settings.STALE_LISTING_THRESHOLD_MONTHS
    if not is_listing_stale(reverb_published_at, product.created_at, threshold):
        age_months = get_listing_age_months(reverb_published_at, product.created_at)
        return JSONResponse({
            "status": "error",
            "message": f"Listing is only {age_months or 0} months old. Must be >{threshold} months for refresh.",
            "message_type": "warning",
        }, status_code=400)

    platform_results: List[Dict[str, Any]] = []
    now_utc = datetime.utcnow()

    # --- Refresh on Reverb (End old → Create new) ---
    if 'reverb' in platform_commons:
        reverb_pc = platform_commons['reverb']
        if reverb_pc.external_id:
            try:
                reverb_service = ReverbService(db, settings)
                old_reverb_id = reverb_pc.external_id

                # Step 1: End the old listing
                reverb_listing_stmt = select(ReverbListing).where(
                    ReverbListing.platform_id == reverb_pc.id
                )
                reverb_listing_result = await db.execute(reverb_listing_stmt)
                reverb_listing_record = reverb_listing_result.scalar_one_or_none()

                if reverb_listing_record:
                    await reverb_service.end_listing(reverb_listing_record.id, reason="not_sold")
                    logger.info(f"Ended old Reverb listing {old_reverb_id}")

                # Step 2: Orphan old platform_common (set product_id=NULL, status=REFRESHED)
                reverb_pc.product_id = None
                reverb_pc.status = ListingStatus.REFRESHED.value
                reverb_pc.sync_status = SyncStatus.SYNCED.value
                reverb_pc.updated_at = now_utc

                # Also update platform_specific_data with refresh info
                old_sku = product.sku
                psd = reverb_pc.platform_specific_data or {}
                psd['_refresh_info'] = {
                    'refreshed_at': now_utc.isoformat(),
                    'original_product_id': product.id,
                    'original_sku': old_sku,
                    'reason': 'stale_listing_refresh'
                }
                reverb_pc.platform_specific_data = psd
                db.add(reverb_pc)

                # Step 2b: Update product SKU with refresh suffix (Reverb requires unique SKUs)
                sku_match = re.match(r'^(.+?)(-R(\d+))?$', old_sku or '')
                if sku_match:
                    base_sku = sku_match.group(1)
                    existing_num = int(sku_match.group(3)) if sku_match.group(3) else 0
                    new_sku = f"{base_sku}-R{existing_num + 1}"
                else:
                    new_sku = f"{old_sku}-R1"

                product.sku = new_sku
                db.add(product)
                await db.flush()
                logger.info(f"Updated product SKU from {old_sku} to {new_sku} for Reverb refresh")

                # Step 3: Create new Reverb listing
                create_result = await reverb_service.create_listing_from_product(
                    product_id=product.id,
                    publish=True
                )

                if create_result.get('status') == 'success':
                    new_reverb_id = create_result.get('reverb_listing_id')
                    platform_results.append({
                        "platform": "reverb",
                        "success": True,
                        "message": f"Refreshed: {old_reverb_id} → {new_reverb_id}",
                        "old_id": old_reverb_id,
                        "new_id": new_reverb_id,
                    })
                    logger.info(f"Reverb refresh successful: {old_reverb_id} → {new_reverb_id}")
                else:
                    platform_results.append({
                        "platform": "reverb",
                        "success": False,
                        "message": f"Ended old listing but failed to create new: {create_result.get('error', 'Unknown')}",
                    })
            except Exception as e:
                platform_results.append({
                    "platform": "reverb",
                    "success": False,
                    "message": f"Reverb error: {str(e)}",
                })
                logger.error(f"Reverb refresh failed for {product.sku}: {e}")
        else:
            logger.info(f"Reverb listing has no external_id for {product.sku}, skipping")

    # --- Refresh on eBay (End old → Create new) ---
    if 'ebay' in platform_commons:
        ebay_pc = platform_commons['ebay']
        if ebay_pc.external_id:
            try:
                ebay_service = EbayService(db, settings)
                old_item_id = ebay_pc.external_id

                # Step 1: End the old listing
                await ebay_service.mark_item_as_sold(old_item_id)
                logger.info(f"Ended old eBay listing {old_item_id}")

                # Step 2: Orphan old ebay_listings row
                old_listing_stmt = select(EbayListing).where(
                    EbayListing.ebay_item_id == old_item_id
                )
                old_listing_result = await db.execute(old_listing_stmt)
                old_ebay_listing = old_listing_result.scalar_one_or_none()

                if old_ebay_listing:
                    old_ebay_listing.platform_id = None
                    old_ebay_listing.listing_status = 'ENDED'
                    old_ebay_listing.updated_at = now_utc
                    listing_data = old_ebay_listing.listing_data or {}
                    listing_data['_refresh_info'] = {
                        'reason': 'stale_listing_refresh',
                        'refreshed_at': now_utc.isoformat(),
                        'original_product_sku': product.sku,
                        'original_product_id': product.id
                    }
                    old_ebay_listing.listing_data = listing_data
                    db.add(old_ebay_listing)

                # Step 3: Orphan old platform_common
                ebay_pc.product_id = None
                ebay_pc.status = ListingStatus.REFRESHED.value
                ebay_pc.sync_status = SyncStatus.SYNCED.value
                ebay_pc.updated_at = now_utc
                psd = ebay_pc.platform_specific_data or {}
                psd['_refresh_info'] = {
                    'refreshed_at': now_utc.isoformat(),
                    'original_product_id': product.id,
                    'original_sku': product.sku,
                    'reason': 'stale_listing_refresh'
                }
                ebay_pc.platform_specific_data = psd
                db.add(ebay_pc)

                # Step 4: Create new eBay listing
                create_result = await ebay_service.create_listing_from_product(
                    product=product,
                    use_shipping_profile=True
                )

                if create_result.get('status') == 'success':
                    new_item_id = create_result.get('ebay_item_id')
                    platform_results.append({
                        "platform": "ebay",
                        "success": True,
                        "message": f"Refreshed: {old_item_id} → {new_item_id}",
                        "old_id": old_item_id,
                        "new_id": new_item_id,
                    })
                    logger.info(f"eBay refresh successful: {old_item_id} → {new_item_id}")
                else:
                    platform_results.append({
                        "platform": "ebay",
                        "success": False,
                        "message": f"Ended old listing but failed to create new: {create_result.get('error', 'Unknown')}",
                    })
            except Exception as e:
                platform_results.append({
                    "platform": "ebay",
                    "success": False,
                    "message": f"eBay error: {str(e)}",
                })
                logger.error(f"eBay refresh failed for {product.sku}: {e}")
        else:
            logger.info(f"eBay listing has no external_id for {product.sku}, skipping")

    # --- Refresh on V&R (Mark sold → Create new) ---
    if 'vr' in platform_commons:
        vr_pc = platform_commons['vr']
        if vr_pc.external_id:
            try:
                vr_service = VRService(db)
                old_vr_id = vr_pc.external_id

                # Step 1: Mark the old listing as sold (V&R doesn't have true delete)
                await vr_service.mark_item_as_sold(old_vr_id)
                logger.info(f"Marked old V&R listing {old_vr_id} as sold")

                # Step 2: Orphan old vr_listings row
                old_vr_listing_stmt = select(VRListing).where(
                    VRListing.vr_listing_id == old_vr_id
                )
                old_vr_listing_result = await db.execute(old_vr_listing_stmt)
                old_vr_listing = old_vr_listing_result.scalar_one_or_none()

                if old_vr_listing:
                    old_vr_listing.platform_id = None
                    old_vr_listing.vr_state = 'ended'
                    old_vr_listing.updated_at = now_utc
                    extended = old_vr_listing.extended_attributes or {}
                    extended['_refresh_info'] = {
                        'reason': 'stale_listing_refresh',
                        'refreshed_at': now_utc.isoformat(),
                        'original_product_sku': product.sku,
                        'original_product_id': product.id
                    }
                    old_vr_listing.extended_attributes = extended
                    db.add(old_vr_listing)

                # Step 3: Orphan old platform_common
                vr_pc.product_id = None
                vr_pc.status = ListingStatus.REFRESHED.value
                vr_pc.sync_status = SyncStatus.SYNCED.value
                vr_pc.updated_at = now_utc
                psd = vr_pc.platform_specific_data or {}
                psd['_refresh_info'] = {
                    'refreshed_at': now_utc.isoformat(),
                    'original_product_id': product.id,
                    'original_sku': product.sku,
                    'reason': 'stale_listing_refresh'
                }
                vr_pc.platform_specific_data = psd
                db.add(vr_pc)

                # Step 4: Create new V&R listing
                create_result = await vr_service.create_listing_from_product(
                    product=product
                )

                if create_result.get('status') == 'success':
                    new_vr_id = create_result.get('vr_listing_id')
                    platform_results.append({
                        "platform": "vr",
                        "success": True,
                        "message": f"Refreshed: {old_vr_id} → {new_vr_id}",
                        "old_id": old_vr_id,
                        "new_id": new_vr_id,
                    })
                    logger.info(f"V&R refresh successful: {old_vr_id} → {new_vr_id}")
                else:
                    platform_results.append({
                        "platform": "vr",
                        "success": False,
                        "message": f"Ended old listing but failed to create new: {create_result.get('error', 'Unknown')}",
                    })
            except Exception as e:
                platform_results.append({
                    "platform": "vr",
                    "success": False,
                    "message": f"V&R error: {str(e)}",
                })
                logger.error(f"V&R refresh failed for {product.sku}: {e}")
        else:
            logger.info(f"V&R listing has no external_id for {product.sku}, skipping")

    # Shopify is EXCLUDED from refresh (SEO preservation)
    if 'shopify' in platform_commons:
        platform_results.append({
            "platform": "shopify",
            "success": True,
            "message": "Shopify kept unchanged (SEO preservation)",
            "skipped": True,
        })

    # Commit all changes
    await db.commit()

    # Summarize results
    successful = [r for r in platform_results if r.get('success') and not r.get('skipped')]
    failed = [r for r in platform_results if not r.get('success')]
    skipped = [r for r in platform_results if r.get('skipped')]

    if not platform_results:
        return JSONResponse({
            "status": "warning",
            "message": "No platforms available for refresh (no external IDs)",
            "message_type": "warning",
            "platform_results": [],
        })

    if failed and not successful:
        return JSONResponse({
            "status": "error",
            "message": "Refresh failed on all platforms",
            "message_type": "error",
            "platform_results": platform_results,
        }, status_code=500)

    if failed:
        return JSONResponse({
            "status": "partial",
            "message": f"Refreshed {len(successful)} platform(s), failed on {len(failed)}, skipped {len(skipped)}",
            "message_type": "warning",
            "platform_results": platform_results,
        })

    return JSONResponse({
        "status": "success",
        "message": f"Successfully refreshed {len(successful)} platform(s), skipped {len(skipped)} (Shopify SEO)",
        "message_type": "success",
        "platform_results": platform_results,
    })


@router.post("/product/{product_id}/list_on/{platform_slug}", name="create_platform_listing_from_detail")
async def handle_create_platform_listing_from_detail(
    request: Request,
    product_id: int,
    platform_slug: str,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings) # Inject settings
  ):
        
    product_service = ProductService(db)
    product = await product_service.get_product_model_instance(product_id) # Using the new method name in ProductService Class

    if not product:
        logger.error(f"Product ID {product_id} not found for listing on {platform_slug}.")
        raise HTTPException(status_code=404, detail=f"Product {product_id} not found.")
    
    redirect_url = request.url_for('product_detail', product_id=product_id)
    message = f"An error occurred." # Default
    message_type = "error" # Default
    
    try:
        if platform_slug == "vr":
            logger.info(f"Processing Vintage & Rare listing for product {product.sku}.")

            # Prevent duplicate submissions from creating multiple VR listings
            existing_vr_stmt = await db.execute(
                select(PlatformCommon).where(
                    PlatformCommon.product_id == product.id,
                    PlatformCommon.platform_name == "vr"
                )
            )
            existing_vr_link = existing_vr_stmt.scalar_one_or_none()

            if existing_vr_link and existing_vr_link.external_id:
                active_states = {"active", "live", "pending"}
                existing_status = (existing_vr_link.status or "").lower()

                latest_vr_state = None
                if existing_vr_link.id:
                    vr_state_result = await db.execute(
                        select(VRListing.vr_state)
                        .where(VRListing.platform_id == existing_vr_link.id)
                        .order_by(VRListing.id.desc())
                        .limit(1)
                    )
                    vr_state_row = vr_state_result.first()
                    if vr_state_row:
                        latest_vr_state = (vr_state_row[0] or "").lower()

                if existing_status in active_states or (latest_vr_state and latest_vr_state in active_states):
                    message = (
                        f"Vintage & Rare listing already exists for SKU '{product.sku}' "
                        f"(ID: {existing_vr_link.external_id})."
                    )
                    logger.info(
                        "Skipping duplicate V&R listing for product %s - existing listing %s in state %s / %s",
                        product.sku,
                        existing_vr_link.external_id,
                        existing_status,
                        latest_vr_state,
                    )
                    return RedirectResponse(
                        url=f"{redirect_url}?message={quote_plus(message)}&message_type=warning",
                        status_code=303,
                    )

            vr_price_override = await _determine_vr_price(product, db, logger)

            saved_platform_options: Dict[str, Any] = {}
            package_blob = product.package_dimensions if isinstance(product.package_dimensions, dict) else {}
            if isinstance(package_blob, dict):
                platform_data_blob = package_blob.get("platform_data")
                if isinstance(platform_data_blob, dict):
                    vr_blob = platform_data_blob.get("vr")
                    if isinstance(vr_blob, dict):
                        saved_platform_options = vr_blob.copy()

            use_fallback = False

            # Fast AJAX brand validation BEFORE expensive Selenium process
            logger.info(f"Validating brand '{product.brand}' with V&R before listing...")
            validation = VRBrandValidator.validate_brand(product.brand)
            validation_error = validation.get("error_code")

            if validation_error in {"network", "unexpected", "unexpected_response"}:
                logger.warning(
                    "Vintage & Rare brand validation unavailable for '%s' (error: %s)",
                    product.brand,
                    validation_error,
                )
                downtime_message = (
                    "Vintage & Rare is currently responding very slowly, so we can't"
                    " list this product right now. Please try again in a few minutes."
                )
                return RedirectResponse(
                    url=f"{redirect_url}?message={quote_plus(downtime_message)}&message_type=error",
                    status_code=303,
                )

            if not validation["is_valid"]:
                # Brand not recognized by V&R - offer to proceed with fallback
                logger.warning(f"Brand '{product.brand}' not recognized by V&R for {product.sku}")
                
                # Check if user explicitly wants to use fallback (via query parameter)
                use_fallback = request.query_params.get('use_fallback_brand', 'false').lower() == 'true'
                
                if not use_fallback:
                    # First time - ask user if they want to proceed with fallback
                    error_message = f"Brand '{product.brand}' is not recognized by Vintage & Rare. Would you like to proceed using '{DEFAULT_VR_BRAND}' as the brand instead?"
                    fallback_url = f"{redirect_url}?use_fallback_brand=true"
                    
                    # You could render a confirmation template or redirect with options
                    return RedirectResponse(
                        url=f"{redirect_url}?message={error_message}&message_type=warning&fallback_url={fallback_url}", 
                        status_code=303
                    )
                else:
                    # User confirmed - proceed with fallback brand
                    logger.info(f"Using fallback brand '{DEFAULT_VR_BRAND}' for {product.sku} (original: '{product.brand}')")
            else:
                # Brand is valid - proceed normally
                logger.info(f"✅ Brand '{product.brand}' validated successfully (V&R ID: {validation['brand_id']})")

            payload: Dict[str, Any] = {
                "sync_source": "inventory_detail",
                "platform_options": saved_platform_options,
            }
            if use_fallback:
                payload["use_fallback_brand"] = True
            if vr_price_override is not None:
                payload["override_price"] = float(vr_price_override)

            try:
                job = await enqueue_vr_job(
                    db,
                    product_id=product.id,
                    payload=payload,
                )
                await db.commit()
            except Exception as exc:
                logger.error("Failed to enqueue V&R job for product %s: %s", product.sku, exc, exc_info=True)
                message = f"Unable to queue Vintage & Rare listing for SKU '{product.sku}': {exc}"
                return RedirectResponse(
                    url=f"{redirect_url}?message={quote_plus(message)}&message_type=error",
                    status_code=303,
                )

            message = f"Queued Vintage & Rare listing job #{job.id} for SKU '{product.sku}'."
            if use_fallback:
                message += f" Using fallback brand '{DEFAULT_VR_BRAND}'."
            message_type = "success"
            logger.info("Queued V&R job %s for product %s with payload %s", job.id, product.sku, payload)
        
        elif platform_slug == "shopify":
            logger.info(f"=== SINGLE PLATFORM LISTING: SHOPIFY ===")
            logger.info(f"Product ID: {product.id}, SKU: {product.sku}")
            logger.info(f"Product: {product.brand} {product.model}")

            # Check for existing Shopify listing to prevent duplicates
            existing_shopify_stmt = await db.execute(
                select(PlatformCommon).where(
                    PlatformCommon.product_id == product.id,
                    PlatformCommon.platform_name == "shopify"
                )
            )
            existing_shopify = existing_shopify_stmt.scalar_one_or_none()
            if existing_shopify and existing_shopify.external_id:
                existing_status = (existing_shopify.status or "").lower()
                if existing_status in {"active", "live", "draft"}:
                    message = f"Shopify listing already exists for SKU '{product.sku}' (ID: {existing_shopify.external_id})."
                    logger.info(f"Skipping duplicate Shopify listing for product {product.sku}")
                    return RedirectResponse(
                        url=f"{redirect_url}?message={quote_plus(message)}&message_type=warning",
                        status_code=303,
                    )

            try:
                # Initialize Shopify service
                shopify_service = ShopifyService(db, settings)
                
                description_with_footer = ensure_description_has_standard_footer(product.description or "")
                fallback_title = product.title or product.generate_title()
                shopify_generated_keywords = generate_shopify_keywords(
                    brand=product.brand,
                    model=product.model,
                    finish=product.finish,
                    year=product.year,
                    decade=product.decade,
                    category=product.category,
                    condition=product.condition.value if hasattr(product.condition, "value") else product.condition,
                    description_html=description_with_footer,
                )
                shopify_generated_short_description = generate_shopify_short_description(
                    description_with_footer,
                    fallback=fallback_title,
                )
                shopify_generated_seo_title = (fallback_title or "").strip()[:255] or None

                saved_platform_options: Dict[str, Any] = {}
                package_blob = product.package_dimensions if isinstance(product.package_dimensions, dict) else {}
                if isinstance(package_blob, dict):
                    platform_data_blob = package_blob.get("platform_data")
                    if isinstance(platform_data_blob, dict):
                        shopify_blob = platform_data_blob.get("shopify")
                        if isinstance(shopify_blob, dict):
                            saved_platform_options = shopify_blob.copy()

                if not saved_platform_options.get("category_gid"):
                    mapped_category = await _lookup_shopify_category(db, product.category)
                    if mapped_category:
                        logger.info(
                            "Shopify detail publish: mapped category for product %s (%s) -> %s",
                            product.id,
                            product.category,
                            mapped_category,
                        )
                        saved_platform_options.update(mapped_category)
                    else:
                        logger.warning(
                            "Shopify detail publish: no category mapping found for product %s (%s)",
                            product.id,
                            product.category,
                        )

                base_url = str(request.base_url).rstrip('/')
                local_photo_urls: List[str] = []
                if product.primary_image:
                    if product.primary_image.startswith('/static/'):
                        local_photo_urls.append(f"{base_url}{product.primary_image}")
                    else:
                        local_photo_urls.append(product.primary_image)
                if product.additional_images:
                    for img_url in product.additional_images:
                        if not img_url:
                            continue
                        full_url = (
                            f"{base_url}{img_url}" if img_url.startswith('/static/') else img_url
                        )
                        if full_url not in local_photo_urls:
                            local_photo_urls.append(full_url)

                # Prepare enriched data similar to what would come from Reverb
                # NOTE: Only use local_photos - do NOT also populate cloudinary_photos
                # as shopify_service processes both and would create duplicates
                enriched_data = {
                    "title": f"{product.year} {product.brand} {product.model}" if product.year else f"{product.brand} {product.model}",
                    "description": description_with_footer,
                    "photos": [],
                    "cloudinary_photos": [],  # Leave empty - using local_photos instead
                    "condition": {"display_name": product.condition},
                    "price": {"amount": str(product.base_price), "currency": "GBP"},
                    "inventory": product.quantity if product.quantity else 1,
                    "finish": product.finish,
                    "year": str(product.year) if product.year else None,
                    "model": product.model,
                    "brand": product.brand,
                    "local_photos": local_photo_urls,
                }
                
                result = await shopify_service.create_listing_from_product(
                    product,
                    enriched_data,
                    platform_options=saved_platform_options or None,
                )

                persist_response = await _persist_shopify_listing(
                    db,
                    settings,
                    product,
                    result,
                    shopify_options=saved_platform_options,
                    shopify_generated_keywords=shopify_generated_keywords,
                    shopify_generated_seo_title=shopify_generated_seo_title,
                    shopify_generated_short_description=shopify_generated_short_description,
                )

                if persist_response.get("status") == "success":
                    message = persist_response.get("message") or "Successfully created Shopify listing"
                    message_type = "success"
                else:
                    message = persist_response.get("message", "Failed to create Shopify listing")
                    message_type = "error"
                    
            except Exception as e:
                logger.error(f"Error creating Shopify listing: {str(e)}")
                message = f"Error creating Shopify listing: {str(e)}"
                message_type = "error"
        
        elif platform_slug == "ebay":
            logger.info(f"=== SINGLE PLATFORM LISTING: EBAY ===")
            logger.info(f"Product ID: {product.id}, SKU: {product.sku}")
            logger.info(f"Product: {product.brand} {product.model}")
            logger.warning("⚠️  NOTE: eBay requires proper shipping profiles to be configured")

            # Check for existing eBay listing to prevent duplicates
            existing_ebay_stmt = await db.execute(
                select(PlatformCommon).where(
                    PlatformCommon.product_id == product.id,
                    PlatformCommon.platform_name == "ebay"
                )
            )
            existing_ebay = existing_ebay_stmt.scalar_one_or_none()
            if existing_ebay and existing_ebay.external_id:
                existing_status = (existing_ebay.status or "").lower()
                if existing_status in {"active", "live"}:
                    message = f"eBay listing already exists for SKU '{product.sku}' (Item ID: {existing_ebay.external_id})."
                    logger.info(f"Skipping duplicate eBay listing for product {product.sku}")
                    return RedirectResponse(
                        url=f"{redirect_url}?message={quote_plus(message)}&message_type=warning",
                        status_code=303,
                    )

            try:
                # Initialize eBay service
                ebay_service = EbayService(db, settings)

                # Calculate proper eBay price (use Reverb price if available, otherwise calculate from base)
                ebay_price = _calculate_default_platform_price(
                    "ebay",
                    product.base_price,
                    float(product.price) if product.price else None
                )

                # Prepare enriched data
                enriched_data = {
                    "title": f"{product.year} {product.brand} {product.model}" if product.year else f"{product.brand} {product.model}",
                    "description": product.description,
                    "photos": [],
                    "condition": {"display_name": product.condition},
                    "categories": [],  # Will be populated with Reverb category UUID if available
                    "price": {"amount": str(ebay_price), "currency": "GBP"},
                    "inventory": product.quantity if product.quantity else 1,
                    "finish": product.finish,
                    "year": str(product.year) if product.year else None,
                    "model": product.model,
                    "brand": product.brand
                }
                
                # Add images
                if product.primary_image:
                    enriched_data["photos"].append({"url": product.primary_image})
                if product.additional_images:
                    for img_url in product.additional_images:
                        enriched_data["photos"].append({"url": img_url})
                
                # Get Reverb category UUID if the product has a Reverb listing
                reverb_uuid = None
                if product.sku.startswith('REV-'):
                    # Check if we have a Reverb listing with category info
                    reverb_listing_query = select(ReverbListing).join(
                        PlatformCommon
                    ).where(
                        PlatformCommon.product_id == product.id,
                        PlatformCommon.platform_name == 'reverb'
                    )
                    reverb_result = await db.execute(reverb_listing_query)
                    reverb_listing = reverb_result.scalar_one_or_none()
                    
                    if reverb_listing and reverb_listing.extended_attributes:
                        categories = reverb_listing.extended_attributes.get('categories', [])
                        if categories and len(categories) > 0:
                            reverb_uuid = categories[0].get('uuid')
                            logger.info(f"Found Reverb UUID from listing: {reverb_uuid}")
                
                # Add category UUID to enriched data if found
                if reverb_uuid:
                    enriched_data["categories"] = [{"uuid": reverb_uuid}]
                
                # Get policies from product's platform data if available
                # Default to Business Policies with the profile IDs from existing listings
                policies = {
                    'shipping_profile_id': '252277357017',
                    'payment_profile_id': '252544577017',
                    'return_profile_id': '252277356017'
                }
                if hasattr(product, 'platform_data') and product.platform_data and 'ebay' in product.platform_data:
                    ebay_data = product.platform_data['ebay']
                    # Override with product-specific policies if they exist
                    if ebay_data.get('shipping_policy'):
                        policies['shipping_profile_id'] = ebay_data.get('shipping_policy')
                    if ebay_data.get('payment_policy'):
                        policies['payment_profile_id'] = ebay_data.get('payment_policy')
                    if ebay_data.get('return_policy'):
                        policies['return_profile_id'] = ebay_data.get('return_policy')
                
                result = await ebay_service.create_listing_from_product(
                    product=product,
                    reverb_api_data=enriched_data,
                    use_shipping_profile=True,  # Always use Business Policies
                    **policies
                )
                
                if result.get("status") == "success":
                    message = f"Successfully created eBay listing with ID: {result.get('external_id', result.get('ItemID'))}"
                    message_type = "success"
                else:
                    message = f"Failed to create eBay listing: {result.get('message', result.get('error', 'Unknown error'))}"
                    message_type = "error"
                    
            except Exception as e:
                logger.error(f"Error creating eBay listing: {str(e)}")
                message = f"Error creating eBay listing: {str(e)}"
                message_type = "error"
        
        elif platform_slug == "reverb":
            logger.info(f"Processing Reverb listing for product {product.sku}")
            try:
                reverb_service = ReverbService(db, settings)

                # Check if already listed on Reverb
                existing_listing = await db.execute(
                    select(PlatformCommon)
                    .where(
                        and_(
                            PlatformCommon.product_id == product_id,
                            PlatformCommon.platform_name == "reverb"
                        )
                    )
                )
                if existing_listing.scalar_one_or_none():
                    message = "Product is already listed on Reverb"
                    message_type = "warning"
                else:
                    result = await reverb_service.create_listing_from_product(product_id)

                    if result.get("status") == "success":
                        message = f"Successfully created Reverb listing with ID: {result.get('reverb_listing_id')}"
                        sku_adjustment = result.get("sku_adjustment")
                        if sku_adjustment:
                            message += f" (SKU updated to {sku_adjustment.get('new_sku')})"
                        message_type = "success"

                        # Update product status to ACTIVE if it was DRAFT
                        if product.status == ProductStatus.DRAFT:
                            product.status = ProductStatus.ACTIVE
                            await db.commit()
                    else:
                        error_message = result.get('error', 'Unknown error')
                        if result.get("code") == "duplicate_sku" and result.get("conflict"):
                            conflict = result["conflict"]
                            error_message += f" (Reverb listing {conflict.get('id')} is still live with SKU {product.sku})"
                        message = f"Error creating Reverb listing: {error_message}"
                        message_type = "error"

            except Exception as e:
                logger.error(f"Error creating Reverb listing: {str(e)}")
                message = f"Error creating Reverb listing: {str(e)}"
                message_type = "error"
        
        else:
            message = f"Listing on platform '{platform_slug}' is not yet implemented."
            message_type = "info"
            logger.info(message)

    except ValueError as ve: # Catch data validation/mapping errors from our helper
        logger.error(f"Data error for {platform_slug} listing (product {product_id}): {str(ve)}", exc_info=True)
        message = f"Data error for {platform_slug}: {str(ve)}"
        message_type = "error"
    except HTTPException: # Re-raise HTTPExceptions to let FastAPI handle them
        raise
    except Exception as e:
        logger.error(f"Unexpected error listing product {product_id} on {platform_slug}: {str(e)}", exc_info=True)
        message = f"Server error listing on {platform_slug}. Check logs."
        message_type = "error"

    # Using quote_plus to safely encode the message for URL and avoid truncation at ampersand
    return RedirectResponse(
        url=f"{redirect_url}?message={quote_plus(message)}&message_type={message_type}", 
        status_code=303
    )

@router.get("/add", response_class=HTMLResponse)
async def add_product_form(
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    draft_id: Optional[int] = None,
):
    # Get existing brands for dropdown (alphabetically sorted)
    existing_brands = await db.execute(
        select(Product.brand)
        .distinct()
        .filter(Product.brand.isnot(None))
        .order_by(Product.brand)
    )
    existing_brands = [b[0] for b in existing_brands.all() if b[0]]

    # Canonical category suggestions (full Reverb taxonomy, alphabetically sorted)
    # Include UUID for frontend validation
    canonical_query = (
        select(ReverbCategory.full_path, ReverbCategory.uuid)
        .filter(ReverbCategory.full_path.isnot(None))
        .filter(ReverbCategory.uuid.isnot(None))
        .order_by(ReverbCategory.full_path)
    )
    canonical_result = await db.execute(canonical_query)
    canonical_categories: List[Dict[str, str]] = []
    seen_categories: set[str] = set()
    for full_path, uuid in canonical_result.all():
        if not full_path or not uuid:
            continue
        normalized = full_path.strip()
        if not normalized or normalized in seen_categories:
            continue
        canonical_categories.append({"full_path": normalized, "uuid": uuid})
        seen_categories.add(normalized)

    # Get existing products for "copy from" feature
    # Limit to 100 most recent products
    existing_products_result = await db.execute(
        select(Product)
        .order_by(desc(Product.created_at))
        .limit(100)
    )
    existing_products = existing_products_result.scalars().all()

    prefill_draft_id: Optional[int] = None
    form_data: Optional[Dict[str, Any]] = None
    if draft_id is not None:
        draft = await db.get(Product, draft_id)
        if draft and draft.status == ProductStatus.DRAFT:
            prefill_draft_id = draft.id
            form_data = _serialize_draft_product(draft)

    # Exclude OTHER from dropdown - Reverb doesn't accept it
    manufacturing_countries = [c for c in ManufacturingCountry if c != ManufacturingCountry.OTHER]
    handedness_options = list(Handedness)
    case_status_options = list(CaseStatus)
    body_type_options = SPEC_FIELD_MAP.get("body_type", {}).get("options", [])

    return templates.TemplateResponse(
        "inventory/add.html",
        {
            "request": request,
            "existing_brands": existing_brands,
            "canonical_categories": canonical_categories,
            "existing_products": existing_products,
            "ebay_status": "pending",
            "reverb_status": "pending",
            "vr_status": "pending",
            "shopify_status": "pending",
            "tinymce_api_key": settings.TINYMCE_API_KEY,  # This is important
            "form_data": form_data,
            "prefill_draft_id": prefill_draft_id,
            "manufacturing_countries": manufacturing_countries,
            "handedness_options": handedness_options,
            "case_status_options": case_status_options,
            "body_type_options": body_type_options,
            "spec_fields": SPEC_FIELDS,  # For Additional Specs UI
            # Platform pricing markups (from env vars)
            "ebay_markup_percent": settings.EBAY_PRICE_MARKUP_PERCENT,
            "vr_markup_percent": settings.VR_PRICE_MARKUP_PERCENT,
            "reverb_markup_percent": settings.REVERB_PRICE_MARKUP_PERCENT,
            "shopify_markup_percent": settings.SHOPIFY_PRICE_MARKUP_PERCENT,
        }
    )

@router.post("/add")
async def add_product(
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    brand: str = Form(...),
    model: str = Form(...),
    sku: str = Form(...),
    category: str = Form(...),
    condition: str = Form(...),
    base_price: float = Form(...),
    cost_price: Optional[float] = Form(None),
    description: Optional[str] = Form(None),
    year: Optional[int] = Form(None),
    decade: Optional[int] = Form(None),
    finish: Optional[str] = Form(None),
    status: str = Form("DRAFT"),
    title: Optional[str] = Form(None),
    processing_time: Optional[str] = Form(None),
    price: Optional[str] = Form(None),
    price_notax: Optional[str] = Form(None),
    collective_discount: Optional[str] = Form(None),
    offer_discount: Optional[str] = Form(None),
    # Checkbox fields
    in_collective: Optional[bool] = Form(False),
    in_inventory: Optional[bool] = Form(True),
    in_reseller: Optional[bool] = Form(False),
    free_shipping: Optional[bool] = Form(False),
    buy_now: Optional[bool] = Form(True),
    show_vat: Optional[bool] = Form(True),
    local_pickup: Optional[bool] = Form(False),
    available_for_shipment: Optional[bool] = Form(True),
    is_stocked_item: Optional[bool] = Form(False),
    quantity: Optional[str] = Form(None),
    # Media fields
    primary_image_file: Optional[UploadFile] = File(None),
    primary_image_url: Optional[str] = Form(None),
    additional_images_files: List[UploadFile] = File([]),
    additional_images_urls: Optional[str] = Form(None),
    video_url: Optional[str] = Form(None),
    external_link: Optional[str] = Form(None),
    storefront: Optional[str] = Form(None),
    # Platform sync fields
    sync_all: Optional[str] = Form("true"),
    sync_platforms: Optional[List[str]] = Form(None)
):
    """
    Creates a new product from form data and optionally sets up platform listings.

    1. Removed duplicated code: The route is now structured in a clear, logical flow with no duplicate processing.
    2. Better error handling:
        - Added specific error handling for different types of errors
        - Separated validation errors from processing errors
        - Added proper platform service error handling
    3. Improved structure:
        - Clear step-by-step process: validate → process → create → redirect
        - Non-critical errors in platform operations don't fail the whole request
        - Clear separation of concerns
    4. Added proper exception classes:
        - Created a comprehensive exception hierarchy
        - Each module has its own exception types
        - Allows more targeted error handling

    25.02.25: Enhanced product creation endpoint that handles the comprehensive form.

    This implementation:

    1. Properly processes all fields including platform-specific data
    2. Handles image uploads more robustly
    3. Integrates with multiple platforms in parallel
    4. Provides detailed feedback on each platform's status

    """

    # Debug logging
    print("===== POST REQUEST TO /add =====")
    print("Method:", request.method)
    form_data = await request.form()

    # Normalise basic numeric fields from simple form values (allow blank strings)
    BLANK_SENTINELS = {None, "", " ", "null", "undefined"}

    if quantity in BLANK_SENTINELS:
        parsed_quantity = None
    else:
        try:
            parsed_quantity = int(str(quantity).strip())
        except ValueError:
            raise HTTPException(status_code=422, detail="Quantity must be a valid integer")

    def _parse_float(value: Optional[str], default: Optional[float] = None, field_name: str = "value") -> Optional[float]:
        if value in BLANK_SENTINELS:
            return default
        try:
            return float(str(value).replace(",", ""))
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail=f"{field_name} must be a valid number")

    def _strip_text(value: Optional[str]) -> Optional[str]:
        if value in BLANK_SENTINELS or value is None:
            return None
        text = str(value).strip()
        return text or None


    processed_processing_time: Optional[int] = None
    if processing_time not in BLANK_SENTINELS:
        try:
            processed_processing_time = int(str(processing_time).strip())
        except ValueError:
            raise HTTPException(status_code=422, detail="Processing time must be a valid integer")

    parsed_price = _parse_float(price, field_name="price")
    parsed_price_notax = _parse_float(price_notax, field_name="price_notax")
    parsed_collective_discount = _parse_float(collective_discount, 0.0, field_name="collective_discount")
    parsed_offer_discount = _parse_float(offer_discount, 0.0, field_name="offer_discount")

    # Ensure decade derives from year when not explicitly supplied
    if decade is None and year is not None:
        try:
            decade = (int(year) // 10) * 10
        except (TypeError, ValueError):
            decade = None

    # Sanitize form data for logging (remove base64 image data)
    log_form_data = {}
    for key, value in form_data.items():
        if isinstance(value, str) and value.startswith('data:image'):
            log_form_data[key] = f"[base64 image data - {len(value)} chars]"
        elif key == 'image_files' and hasattr(value, 'filename'):
            log_form_data[key] = f"[file upload: {value.filename}]"
        else:
            log_form_data[key] = value

    print("Form data received:", log_form_data)

    # Get existing brands - needed for error responses (alphabetically sorted)
    existing_brands = await db.execute(
        select(Product.brand)
        .distinct()
        .filter(Product.brand.isnot(None))
        .order_by(Product.brand)
    )
    existing_brands = [b[0] for b in existing_brands.all() if b[0]]

    categories_result = await db.execute(
        select(Product.category)
        .distinct()
        .filter(Product.category.isnot(None))
        .order_by(Product.category)
    )
    categories = [c[0] for c in categories_result.all() if c[0]]
    
    existing_products_result = await db.execute(
        select(Product)
        .order_by(desc(Product.created_at))
        .limit(100)
    )
    existing_products = existing_products_result.scalars().all()

    # Platform statuses to track integration results
    platform_statuses = {
        "ebay": {"status": "pending", "message": "Waiting for sync"},
        "reverb": {"status": "pending", "message": "Waiting for sync"},
        "vr": {"status": "pending", "message": "Waiting for sync"},
        "shopify": {"status": "pending", "message": "Waiting for sync"}
    }

    pending_reverb_refresh: List[Tuple[str, Optional[int]]] = []

    try:
        # Initialize services
        product_service = ProductService(db)
        ebay_service = EbayService(db, settings)
        reverb_service = ReverbService(db, settings)
        shopify_service = ShopifyService(db, settings)

        # Process brand
        brand = brand.title()
        is_new_brand = brand not in existing_brands

        # Validate status
        try:
            status_enum = ProductStatus[status.upper()]
        except KeyError:
            return templates.TemplateResponse(
                "inventory/add.html",
                {
                    "request": request,
                    "error": f"Invalid status value: {status}. Must be one of: {', '.join(ProductStatus.__members__.keys())}",
                    "form_data": request.form,
                    "existing_brands": existing_brands,
                    "categories": categories,
                    "existing_products": existing_products,
                    "ebay_status": "error",
                    "reverb_status": "error",
                    "vr_status": "error",
                    "shopify_status": "error",
                    "manufacturing_countries": manufacturing_countries,
                    "handedness_options": handedness_options,
                    "case_status_options": case_status_options,
                    "body_type_options": body_type_options,
                },
                status_code=400
            )

        # Validate condition
        try:
            condition_enum = ProductCondition(condition)
        except ValueError:
            return templates.TemplateResponse(
                "inventory/add.html",
                {
                    "request": request,
                    "error": f"Invalid condition value: {condition}",
                    "form_data": request.form,
                    "existing_brands": existing_brands,
                    "categories": categories,
                    "existing_products": existing_products,
                    "ebay_status": "error",
                    "reverb_status": "error",
                    "vr_status": "error",
                    "shopify_status": "error",
                    "manufacturing_countries": manufacturing_countries,
                    "handedness_options": handedness_options,
                    "case_status_options": case_status_options,
                    "body_type_options": body_type_options,
                },
                status_code=400
            )

        # Handle images
        primary_image = None
        if primary_image_file and primary_image_file.filename:
            primary_image = await save_upload_file(primary_image_file)
        elif primary_image_url:
            primary_image = primary_image_url

        additional_images = []
        if additional_images_files:
            for file in additional_images_files:
                if file.filename:
                    path = await save_upload_file(file)
                    additional_images.append(path)

        if additional_images_urls:
            parsed_urls: List[str] = []
            stripped = additional_images_urls.strip()
            if stripped.startswith('['):
                try:
                    maybe_list = json.loads(stripped)
                    if isinstance(maybe_list, list):
                        parsed_urls = [str(u).strip() for u in maybe_list if str(u).strip()]
                except json.JSONDecodeError:
                    parsed_urls = []
            if not parsed_urls:
                parsed_urls = [url.strip() for url in additional_images_urls.split('\n') if url.strip()]
            additional_images.extend(parsed_urls)

        # Convert local static paths to full URLs for external platforms
        def make_full_url(path):
            if path and path.startswith('/static/'):
                # Get the base URL from the request
                base_url = str(request.base_url).rstrip('/')
                return f"{base_url}{path}"
            return path

        # Apply URL conversion
        primary_image, additional_images = await ensure_remote_media_urls(
            primary_image,
            additional_images,
            sku,
            settings,
        )

        initial_gallery_expected_count = int(bool(primary_image))
        if additional_images:
            initial_gallery_expected_count += len([img for img in additional_images if img])

        if primary_image:
            primary_image = make_full_url(primary_image)
        additional_images = [make_full_url(img) for img in additional_images]

        local_gallery_full_urls: List[str] = []
        if primary_image:
            local_gallery_full_urls.append(primary_image)
        if additional_images:
            for img in additional_images:
                if img and img not in local_gallery_full_urls:
                    local_gallery_full_urls.append(img)

        # Process platform-specific data from form
        platform_data = {}
        for key, value in form_data.items():
            if key.startswith("platform_data__"):
                parts = key.split("__")
                if len(parts) >= 3:
                    platform = parts[1]
                    field = parts[2]
                    
                    if platform not in platform_data:
                        platform_data[platform] = {}
                    
                    # Handle boolean values properly
                    if isinstance(value, str) and value.lower() in ['true', 'on']:
                        platform_data[platform][field] = True
                    elif isinstance(value, str) and value.lower() == 'false':
                        platform_data[platform][field] = False
                    else:
                        platform_data[platform][field] = value

        # Map shipping profile to Reverb ID if needed
        selected_shipping_profile_id: Optional[int] = None
        logger.info("Raw shipping_profile from form: %s", form_data.get("shipping_profile"))
        reverb_options = platform_data.get("reverb")
        if reverb_options and reverb_options.get("shipping_profile"):
            logger.info(
                "Reverb platform shipping_profile value before resolution: %s",
                reverb_options.get("shipping_profile"),
            )
            shipping_value = reverb_options.get("shipping_profile")
            profile_id = None
            try:
                profile_id = int(shipping_value)
            except (TypeError, ValueError):
                profile_id = None

            profile_record = None
            if profile_id is not None:
                profile_result = await db.execute(
                    select(ShippingProfile).where(ShippingProfile.id == profile_id)
                )
                profile_record = profile_result.scalar_one_or_none()

            if profile_record is None:
                profile_result = await db.execute(
                    select(ShippingProfile).where(ShippingProfile.reverb_profile_id == str(shipping_value))
                )
                profile_record = profile_result.scalar_one_or_none()

            if profile_record and profile_record.reverb_profile_id:
                reverb_options["shipping_profile"] = profile_record.reverb_profile_id
                selected_shipping_profile_id = profile_record.id
                logger.info(
                    "Resolved shipping profile '%s' to local id %s / reverb id %s",
                    shipping_value,
                    profile_record.id,
                    profile_record.reverb_profile_id,
                )
            else:
                logger.warning(
                    "Could not resolve shipping profile '%s' to a known record; leaving value unchanged",
                    shipping_value,
                )

        if selected_shipping_profile_id is None:
            raw_profile = form_data.get("shipping_profile_id") or form_data.get("shipping_profile")
            if raw_profile not in (None, ""):
                try:
                    selected_shipping_profile_id = int(str(raw_profile).strip())
                    logger.info("Using raw shipping_profile value %s", selected_shipping_profile_id)
                except (TypeError, ValueError):
                    logger.warning("Invalid shipping_profile value '%s'", raw_profile)

        manufacturing_country_enum: Optional[ManufacturingCountry] = None
        raw_manufacturing_country = _strip_text(form_data.get("manufacturing_country"))
        if raw_manufacturing_country:
            try:
                manufacturing_country_enum = ManufacturingCountry(raw_manufacturing_country)
            except ValueError:
                logger.warning("Invalid manufacturing country '%s' provided; defaulting to None", raw_manufacturing_country)

        serial_number_value = _strip_text(form_data.get("serial_number"))

        handedness_enum = Handedness.UNSPECIFIED
        raw_handedness = _strip_text(form_data.get("handedness"))
        if raw_handedness:
            try:
                handedness_enum = Handedness[raw_handedness.upper()]
            except KeyError:
                try:
                    handedness_enum = Handedness(raw_handedness.upper())
                except ValueError:
                    logger.warning("Invalid handedness '%s' provided; defaulting to UNSPECIFIED", raw_handedness)

        artist_owned_flag = form_data.get("artist_owned") == "on"
        artist_names_raw = form_data.get("artist_names") or ""
        artist_names_list = [
            name.strip()
            for name in re.split(r"[,\n]", artist_names_raw)
            if name and name.strip()
        ]

        inventory_location_enum = InventoryLocation.HANKS
        raw_inventory_location = _strip_text(form_data.get("inventory_location"))
        if raw_inventory_location:
            lookup = raw_inventory_location.upper()
            try:
                inventory_location_enum = InventoryLocation[lookup]
            except KeyError:
                try:
                    inventory_location_enum = InventoryLocation(lookup)
                except ValueError:
                    logger.warning("Invalid inventory location '%s'; defaulting to %s", raw_inventory_location, inventory_location_enum.value)

        case_status_enum = CaseStatus.UNSPECIFIED
        raw_case_status = _strip_text(form_data.get("case_status"))
        if raw_case_status:
            lookup = raw_case_status.upper()
            try:
                case_status_enum = CaseStatus[lookup]
            except KeyError:
                try:
                    case_status_enum = CaseStatus(lookup)
                except ValueError:
                    logger.warning("Invalid case status '%s'; defaulting to %s", raw_case_status, case_status_enum.value)

        case_details_value = _strip_text(form_data.get("case_details"))

        extra_handmade_flag = form_data.get("extra_handmade") == "on"
        body_type_value = _strip_text(form_data.get("body_type"))
        number_of_strings_value = _strip_text(form_data.get("number_of_strings"))
        extra_attributes: Dict[str, Any] = {"handmade": extra_handmade_flag}
        if body_type_value:
            extra_attributes["body_type"] = body_type_value
        if number_of_strings_value:
            extra_attributes["number_of_strings"] = number_of_strings_value

        # eBay category-specific attributes (e.g., Form Factor for Microphones)
        ebay_form_factor = _strip_text(form_data.get("platform_data__ebay__form_factor"))
        if ebay_form_factor:
            extra_attributes["ebay_form_factor"] = ebay_form_factor

        # Merge additional specs from the Additional Specs UI section
        additional_specs_json = form_data.get("additional_specs_json", "{}")
        try:
            additional_specs = json.loads(additional_specs_json) if additional_specs_json else {}
            if isinstance(additional_specs, dict):
                extra_attributes.update(additional_specs)
        except json.JSONDecodeError:
            logger.warning("Failed to parse additional_specs_json: %s", additional_specs_json)

        # Create product data
        storefront_value = _normalize_storefront_input(form_data.get("storefront"), Storefront.HANKS) or Storefront.HANKS

        product_data = ProductCreate(
            brand=brand,
            model=model,
            sku=sku,
            category=category,
            condition=condition_enum.value,
            base_price=base_price,
            cost_price=cost_price,
            description=description,
            year=year,
            decade=decade,
            finish=finish,
            status=status_enum.value,
            price=parsed_price,
            price_notax=parsed_price_notax,
            collective_discount=parsed_collective_discount,
            offer_discount=parsed_offer_discount,
            in_collective=in_collective,
            in_inventory=in_inventory,
            in_reseller=in_reseller,
            free_shipping=free_shipping,
            buy_now=buy_now,
            show_vat=show_vat,
            local_pickup=local_pickup,
            available_for_shipment=available_for_shipment,
            is_stocked_item=is_stocked_item,
            quantity=parsed_quantity if is_stocked_item else None,
            processing_time=processed_processing_time,
            primary_image=primary_image,
            additional_images=additional_images,
            video_url=video_url,
            external_link=external_link,
            shipping_profile_id=selected_shipping_profile_id,
            storefront=storefront_value,
            manufacturing_country=manufacturing_country_enum,
            serial_number=serial_number_value,
            handedness=handedness_enum,
            artist_owned=artist_owned_flag,
            artist_names=artist_names_list,
            inventory_location=inventory_location_enum,
            case_status=case_status_enum,
            case_details=case_details_value,
            extra_attributes=extra_attributes,
        )

        logger.info(
            "Creating product %s with shipping_profile_id=%s",
            sku,
            selected_shipping_profile_id,
        )

        # Step 1: Create the product
        product_read = await product_service.create_product(product_data)
        print(f"Product created successfully: {product_read.id}")

        # Get the actual SQLAlchemy model instance for platform services
        product = await product_service.get_product_model_instance(product_read.id)
        if not product:
            raise ValueError(f"Could not retrieve created product with ID {product_read.id}")

        # Persist manually supplied title/decade/quantity values if provided
        updated = False
        shipping_profile_changed = False

        if title:
            cleaned_title = title.strip()
            if cleaned_title and product.title != cleaned_title:
                product.title = cleaned_title
                updated = True
        elif not product.title:
            # Ensure we at least store the generated title so downstream consumers see it
            generated_title = product.generate_title()
            if generated_title:
                product.title = generated_title
                updated = True

        if decade is not None and product.decade != decade:
            product.decade = decade
            updated = True

        if parsed_quantity is not None:
            # For stocked items we store the explicit quantity; for unique items we keep as provided
            if product.quantity != parsed_quantity:
                product.quantity = parsed_quantity
                updated = True

        if selected_shipping_profile_id and getattr(product, "shipping_profile_id", None) != selected_shipping_profile_id:
            logger.info(
                "Persisting shipping_profile_id %s on product %s (%s)",
                selected_shipping_profile_id,
                product.id,
                product.sku,
            )
            product.shipping_profile_id = selected_shipping_profile_id
            shipping_profile_changed = True

        if updated or shipping_profile_changed:
            await db.commit()
            await db.refresh(product)

        logger.info(
            "Product %s saved with shipping_profile_id=%s",
            product.id,
            product.shipping_profile_id,
        )

        # Step 2: Determine which platforms to sync
        platforms_to_sync = []
        if sync_all == "true":
            platforms_to_sync = ["shopify", "ebay", "vr", "reverb"]
        elif sync_platforms:
            platforms_to_sync = sync_platforms
        
        logger.info(f"=== PLATFORM SYNC CONFIGURATION ===")
        logger.info(f"Sync all: {sync_all}")
        logger.info(f"Selected platforms: {platforms_to_sync}")
        logger.info(f"Product created: ID={product.id}, SKU={product.sku}")
        
        # Step 3: Create platform listings based on selection

        # Initialize enriched_data - will be populated from Reverb if creating there first
        enriched_data = None

        # If Reverb is selected, create it FIRST to get enriched data
        if "reverb" in platforms_to_sync:
            logger.info("=== CREATING REVERB LISTING FIRST ===")
            logger.info(f"Product: {product.sku} - {product.brand} {product.model}")

            if initial_gallery_expected_count == 0:
                message = "Cannot publish to Reverb without at least one image"
                logger.error("%s; skipping platform sync", message)
                platform_statuses["reverb"] = {
                    "status": "error",
                    "message": message,
                }
                for platform in ["ebay", "shopify", "vr"]:
                    if platform in platforms_to_sync:
                        platform_statuses[platform] = {
                            "status": "info",
                            "message": "Skipped - Reverb listing aborted due to missing images",
                        }
                platforms_to_sync = []
            else:
                try:
                    reverb_options = platform_data.get("reverb", {})
                    result = await reverb_service.create_listing_from_product(
                        product_id=product.id,
                        platform_options=reverb_options,
                        publish=True,
                    )

                    if result.get("status") == "success":
                        sku_adjustment = result.get("sku_adjustment")
                        platform_statuses["reverb"] = {
                            "status": "success",
                            "message": f"Listed on Reverb with ID: {result.get('reverb_listing_id')}"
                        }
                        if sku_adjustment:
                            platform_statuses["reverb"]["message"] += (
                                f" (SKU updated to {sku_adjustment.get('new_sku')})"
                            )

                        reverb_listing_id = result.get("reverb_listing_id")
                        if reverb_listing_id:
                            pending_reverb_refresh.append(
                                (
                                    str(reverb_listing_id),
                                    initial_gallery_expected_count or None,
                                )
                            )

                        enriched_data = result.get("listing_data") or {}
                        if local_gallery_full_urls:
                            enriched_data["local_photos"] = local_gallery_full_urls
                        platforms_to_sync = [p for p in platforms_to_sync if p != "reverb"]
                    else:
                        duplicate_sku = result.get("code") == "duplicate_sku"
                        conflict_message = result.get("error", "Failed to create Reverb listing")
                        platform_statuses["reverb"] = {
                            "status": "error",
                            "message": conflict_message,
                            "sku_conflict": result.get("code") == "duplicate_sku",
                        }

                        logger.warning("❌ Reverb creation failed - skipping other platforms")
                        for platform in ["ebay", "shopify", "vr"]:
                            if platform in platforms_to_sync:
                                platform_statuses[platform] = {
                                    "status": "info",
                                    "message": "Skipped - Reverb creation failed",
                                    "sku_conflict": duplicate_sku,
                                }
                        platforms_to_sync = []
                        enriched_data = None

                        if duplicate_sku:
                            logger.error(
                                "Reverb rejected SKU %s because it already exists. Prompting user to resolve conflict.",
                                product.sku,
                            )
                            return JSONResponse(
                                status_code=400,
                                content={
                                    "status": "error",
                                    "error": (
                                        "Reverb reports this SKU already exists in your shop. "
                                        "Please end the existing listing on Reverb or change the SKU before retrying."
                                    ),
                                    "sku_conflict": True,
                                },
                            )

                except Exception as e:
                    logger.error(f"Reverb listing error: {str(e)}", exc_info=True)
                    platform_statuses["reverb"] = {
                        "status": "error",
                        "message": f"Error: {str(e)}"
                    }

                    logger.warning("❌ Reverb creation failed - skipping other platforms")
                    for platform in ["ebay", "shopify", "vr"]:
                        if platform in platforms_to_sync:
                            platform_statuses[platform] = {
                                "status": "info",
                                "message": "Skipped - Reverb creation failed"
                            }
                    platforms_to_sync = []
                    enriched_data = None

        # If no enriched data from Reverb, create from product data
        if not enriched_data and platforms_to_sync:
            logger.info("No Reverb data available - creating enriched data from product")

            # Ensure product attributes are loaded after any rollback in downstream services
            try:
                await db.refresh(product)
            except Exception:
                # If refresh fails (e.g. product already expired), fall back to re-querying
                product = await product_service.get_product_model_instance(product.id)
                if not product:
                    raise ValueError(f"Could not re-load product with ID {product_read.id} after platform failure")

            # NOTE: Only use local_photos - do NOT also populate photos/cloudinary_photos
            # as shopify_service processes all sources and would create duplicates
            enriched_data = {
                "title": f"{product.year} {product.brand} {product.model}" if product.year else f"{product.brand} {product.model}",
                "description": product.description,
                "photos": [],  # Leave empty - using local_photos instead
                "cloudinary_photos": [],  # Leave empty - using local_photos instead
                "condition": {"display_name": product.condition},
                "categories": [{"uuid": platform_data.get("reverb", {}).get("primary_category")}] if platform_data.get("reverb") else [],
                "price": {"amount": str(product.base_price), "currency": "GBP"},
                "inventory": product.quantity if product.is_stocked_item else 1,
                "shipping": {},
                "finish": product.finish,
                "year": str(product.year) if product.year else None,
                "model": product.model,
                "brand": product.brand,
                "local_photos": local_gallery_full_urls,
            }
        
        # Create listings on each selected platform
        if "shopify" in platforms_to_sync:
            logger.info(f"=== CREATING SHOPIFY LISTING ===")
            logger.info(f"Product: {product.sku} - {product.brand} {product.model}")
            try:
                # Initialize Shopify service if not already done
                if 'shopify_service' not in locals():
                    shopify_service = ShopifyService(db, settings)

                description_with_footer = ensure_description_has_standard_footer(product.description or "")
                fallback_title = product.title or product.generate_title()
                shopify_generated_keywords = generate_shopify_keywords(
                    brand=product.brand,
                    model=product.model,
                    finish=product.finish,
                    year=product.year,
                    decade=product.decade,
                    category=product.category,
                    condition=product.condition.value if getattr(product.condition, "value", None) else product.condition,
                    description_html=description_with_footer,
                )
                shopify_generated_short_description = generate_shopify_short_description(
                    description_with_footer,
                    fallback=fallback_title,
                )
                shopify_generated_seo_title = (fallback_title or "").strip()[:255] or None

                shopify_options = platform_data.get("shopify", {})
                logger.info("Calling shopify_service.create_listing_from_product()...")
                result = await shopify_service.create_listing_from_product(
                    product=product,
                    reverb_data=enriched_data,
                    platform_options=shopify_options
                )
                logger.info(f"Shopify result: {result}")

                persist_response = await _persist_shopify_listing(
                    db,
                    settings,
                    product,
                    result,
                    shopify_options=shopify_options,
                    shopify_generated_keywords=shopify_generated_keywords,
                    shopify_generated_seo_title=shopify_generated_seo_title,
                    shopify_generated_short_description=shopify_generated_short_description,
                )

                platform_statuses["shopify"] = persist_response
                if persist_response.get("status") == "success":
                    logger.info(
                        "✅ Shopify listing created successfully: ID=%s",
                        persist_response.get("external_id"),
                    )
                else:
                    logger.warning(
                        "❌ Shopify listing failed to persist: %s",
                        persist_response.get("message"),
                    )
            except Exception as e:
                logger.error(f"Shopify listing error: {str(e)}", exc_info=True)
                platform_statuses["shopify"] = {
                    "status": "error",
                    "message": f"Error: {str(e)}"
                }
        
        if "ebay" in platforms_to_sync:
            logger.info(f"=== CREATING EBAY LISTING ===")
            logger.info(f"Product: {product.sku} - {product.brand} {product.model}")
            logger.warning("⚠️  NOTE: eBay listing creation may fail due to shipping profile requirements")
            logger.warning("⚠️  eBay requires business policies to be configured properly")
            try:
                # Get policies from platform data
                ebay_options = platform_data.get("ebay", {})
                DEFAULT_EBAY_SHIPPING_PROFILE_ID = "254638064017"
                ebay_policies = {
                    "shipping_profile_id": ebay_options.get("shipping_policy") or DEFAULT_EBAY_SHIPPING_PROFILE_ID,
                    "payment_profile_id": ebay_options.get("payment_policy"),
                    "return_profile_id": ebay_options.get("return_policy")
                }
                price_override = _parse_price_to_decimal(
                    ebay_options.get("price") or ebay_options.get("price_display")
                )
                logger.info(f"eBay policies: {ebay_policies}")
                
                logger.info("Calling ebay_service.create_listing_from_product()...")
                result = await ebay_service.create_listing_from_product(
                    product=product,
                    reverb_api_data=enriched_data,
                    use_shipping_profile=bool(ebay_policies.get("shipping_profile_id")),
                    price_override=price_override,
                    **ebay_policies
                )
                logger.info(f"eBay result: {result}")
                
                if result.get("status") == "success":
                    platform_statuses["ebay"] = {
                        "status": "success",
                        "message": f"Listed on eBay with ID: {result.get('external_id') or result.get('ItemID')}"
                    }
                    logger.info(f"✅ eBay listing created successfully: ID={result.get('external_id') or result.get('ItemID')}")
                else:
                    platform_statuses["ebay"] = {
                        "status": "error",
                        "message": result.get("error", "Failed to create eBay listing")
                    }
                    logger.warning(f"❌ eBay listing failed: {result.get('error')}")
            except Exception as e:
                logger.error(f"eBay listing error: {str(e)}", exc_info=True)
                platform_statuses["ebay"] = {
                    "status": "error",
                    "message": f"Error: {str(e)}"
                }
        
        if "vr" in platforms_to_sync:
            logger.info("=== QUEUING V&R LISTING JOB ===")
            try:
                payload = {
                    "platform_options": platform_data.get("vr") or {},
                    "sync_source": "multi_create",
                    "enriched_data": enriched_data or {},
                }
                job = await enqueue_vr_job(
                    db,
                    product_id=product.id,
                    payload=payload,
                )
                await db.commit()
                platform_statuses["vr"] = {
                    "status": "success",
                    "message": f"Queued V&R job #{job.id}",
                }
                logger.info(
                    "Queued V&R job %s for product %s (%s)",
                    job.id,
                    product.sku,
                    payload,
                )
            except Exception as exc:
                logger.error("Failed to enqueue V&R job: %s", exc, exc_info=True)
                platform_statuses["vr"] = {
                    "status": "error",
                    "message": f"Queue error: {exc}",
                }
        
        # Reverb is already handled above if it was selected
        
        # Log final summary
        for listing_id, expected in pending_reverb_refresh:
            logger.info(
                "Scheduling background Reverb image refresh for listing %s (expected %s images)",
                listing_id,
                expected,
            )
            schedule_reverb_image_refresh(
                listing_id,
                expected_count=expected,
                settings=settings,
            )

        logger.info(f"=== PLATFORM SYNC SUMMARY ===")
        for platform, status in platform_statuses.items():
            if status["status"] == "success":
                logger.info(f"✅ {platform}: {status['message']}")
            elif status["status"] == "error":
                logger.error(f"❌ {platform}: {status['message']}")
            else:
                logger.info(f"ℹ️  {platform}: {status['message']}")

        # Step 4: Check if we need to rollback due to failures
        # Count successes and failures
        successful_platforms = [p for p, s in platform_statuses.items() if s["status"] == "success"]
        failed_platforms = [p for p, s in platform_statuses.items() if s["status"] == "error"]

        # Only rollback if Reverb failed (since it's the primary platform)
        # If other platforms fail, we keep the successful ones
        if "reverb" in failed_platforms:
            logger.warning(f"🔄 ROLLBACK INITIATED - Failed platforms: {failed_platforms}")
            logger.warning(f"Rolling back successful platforms: {successful_platforms}")

            # Rollback each successful platform
            for platform in successful_platforms:
                try:
                    logger.info(f"Rolling back {platform} listing...")

                    if platform == "reverb":
                        # Delete from Reverb API
                        reverb_listing = await db.execute(
                            select(ReverbListing).join(PlatformCommon).where(
                                PlatformCommon.product_id == product.id,
                                PlatformCommon.platform_name == "reverb"
                            )
                        )
                        reverb_listing = reverb_listing.scalar_one_or_none()
                        if reverb_listing and reverb_listing.reverb_listing_id:
                            try:
                                reverb_client = ReverbClient(api_key=settings.REVERB_API_KEY)
                                await reverb_client.delete_listing(reverb_listing.reverb_listing_id)
                                logger.info(f"✅ Deleted Reverb listing {reverb_listing.reverb_listing_id}")
                            except Exception as e:
                                logger.error(f"Failed to delete Reverb listing: {e}")

                    elif platform == "ebay":
                        # End eBay listing
                        ebay_listing = await db.execute(
                            select(EbayListing).join(PlatformCommon).where(
                                PlatformCommon.product_id == product.id,
                                PlatformCommon.platform_name == "ebay"
                            )
                        )
                        ebay_listing = ebay_listing.scalar_one_or_none()
                        if ebay_listing and ebay_listing.ebay_item_id:
                            try:
                                await ebay_service.end_listing(ebay_listing.ebay_item_id)
                                logger.info(f"✅ Ended eBay listing {ebay_listing.ebay_item_id}")
                            except Exception as e:
                                logger.error(f"Failed to end eBay listing: {e}")

                    elif platform == "shopify":
                        # Delete Shopify product
                        shopify_listing = await db.execute(
                            select(ShopifyListing).join(PlatformCommon).where(
                                PlatformCommon.product_id == product.id,
                                PlatformCommon.platform_name == "shopify"
                            )
                        )
                        shopify_listing = shopify_listing.scalar_one_or_none()
                        if shopify_listing and shopify_listing.shopify_product_id:
                            try:
                                await shopify_service.delete_product(shopify_listing.shopify_product_id)
                                logger.info(f"✅ Deleted Shopify product {shopify_listing.shopify_product_id}")
                            except Exception as e:
                                logger.error(f"Failed to delete Shopify product: {e}")

                    elif platform == "vr":
                        # V&R doesn't have API delete, just mark as deleted in our DB
                        logger.info("V&R listings cannot be deleted via API - will be cleaned up in database")

                except Exception as e:
                    logger.error(f"Error during {platform} rollback: {e}")

            # Delete all platform_common and related listing entries
            await db.execute(
                delete(PlatformCommon).where(PlatformCommon.product_id == product.id)
            )

            # Update product status to DRAFT
            product.status = ProductStatus.DRAFT
            await db.commit()

            logger.info("✅ Rollback complete - Product reverted to DRAFT status")

            # Update platform statuses for response
            for platform in successful_platforms:
                platform_statuses[platform] = {
                    "status": "rolled_back",
                    "message": "Rolled back due to other platform failures"
                }

        # Step 4.5: Update product status to ACTIVE if any platform creation succeeded
        if successful_platforms and product.status == ProductStatus.DRAFT:
            logger.info(f"✅ Updating product status to ACTIVE - successful platforms: {successful_platforms}")
            product.status = ProductStatus.ACTIVE
            await db.commit()

        # Step 5: Queue for platform sync (if stock manager is available)
        try:
            print("About to queue product")
            if hasattr(request.app.state, 'stock_manager') and hasattr(request.app.state.stock_manager, 'queue_product'):
                print("queue_product method exists, calling it")
                await request.app.state.stock_manager.queue_product(product.id)
                print("Product queued successfully")
            else:
                print("queue_product method doesn't exist - skipping")
        except Exception as e:
            print(f"Queue error (non-critical): {type(e).__name__}: {str(e)}")

        print("About to return redirect response")

        # Step 5: Prepare flash messages for redirect and return JSON response
        redirect_url = f"/inventory/product/{product.id}"
        flash_messages: List[Dict[str, str]] = []
        for platform, status_info in platform_statuses.items():
            if status_info["status"] != "pending":
                flash_messages.append({
                    "platform": platform.upper(),
                    "status": status_info["status"],
                    "message": status_info["message"],
                })

        response = JSONResponse({
            "status": "success",
            "product_id": product.id,
            "redirect_url": redirect_url,
            "platform_statuses": platform_statuses,
        })

        if flash_messages:
            try:
                response.set_cookie(
                    "flash_status",
                    json.dumps(flash_messages),
                    max_age=60,
                    httponly=True,
                    samesite="lax",
                )
            except Exception as cookie_error:
                logger.debug("Failed to set flash_status cookie: %s", cookie_error)

        return response

    except ProductCreationError as e:
        # Handle specific product creation errors
        await db.rollback()
        error_message = str(e)
        if "Failed to create product:" in error_message:
            inner_message = error_message.split("Failed to create product:", 1)[1].strip()
            error_message = f"Failed to create product: {inner_message}"

        # Check if this is a duplicate SKU error
        if "already exists" in error_message and "SKU" in error_message:
            # Get next available SKU suggestion
            query = select(func.max(Product.sku)).where(Product.sku.like('RIFF-%'))
            result = await db.execute(query)
            highest_sku = result.scalar_one_or_none()

            if highest_sku and highest_sku.startswith('RIFF-'):
                try:
                    numeric_part = highest_sku.replace('RIFF-', '')
                    next_sku = f"RIFF-{int(numeric_part) + 1:08d}"
                    error_message += f". Suggested next SKU: {next_sku}"
                except:
                    pass

        return JSONResponse({
            "status": "error",
            "error": error_message,
            "platform_statuses": platform_statuses
        }, status_code=400)
    except PlatformIntegrationError as e:
        # Product was created but platform integration failed
        error_message = f"Product created but platform integration failed: {str(e)}"
        print(error_message)
        
        # Don't rollback the transaction since the product was created
        return JSONResponse({
            "status": "warning",
            "warning": error_message,
                "ebay_status": platform_statuses["ebay"]["status"],
                "ebay_message": platform_statuses["ebay"]["message"],
                "reverb_status": platform_statuses["reverb"]["status"],
                "reverb_message": platform_statuses["reverb"]["message"],
                "vr_status": platform_statuses["vr"]["status"],
                "vr_message": platform_statuses["vr"]["message"],
                "shopify_status": platform_statuses["shopify"]["status"],
                "shopify_message": platform_statuses["shopify"]["message"]
            },
            status_code=400
        )
    except HTTPException as exc:
        raise exc
    except Exception as e:
        logger.exception("Unhandled error while creating product")
        await db.rollback()

        return JSONResponse(
            {
                "status": "error",
                "error": f"Failed to create product: {str(e)}",
            },
            status_code=400,
        )


@router.post("/inspect-payload")
async def inspect_payload(
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    brand: str = Form(...),
    model: str = Form(...),
    sku: str = Form(...),
    category: str = Form(...),
    condition: str = Form(...),
    base_price: float = Form(...),
    quantity: int = Form(1),
    description: str = Form(""),
    decade: Optional[int] = Form(None),
    year: Optional[int] = Form(None),
    finish: Optional[str] = Form(None),
    processing_time: int = Form(3),
    primary_image: Optional[str] = Form(None),
    additional_images: Optional[str] = Form(None),
    # Platform-specific fields - accept strings and convert to bool
    sync_ebay: str = Form("false"),
    sync_reverb: str = Form("false"),
    sync_vr: str = Form("false"),
    sync_shopify: str = Form("false"),
    # eBay fields
    ebay_category: Optional[str] = Form(None),
    ebay_category_name: Optional[str] = Form(None),
    ebay_price: Optional[float] = Form(None),
    ebay_payment_policy: Optional[str] = Form(None),
    ebay_return_policy: Optional[str] = Form(None),
    ebay_shipping_policy: Optional[str] = Form(None),
    ebay_location: Optional[str] = Form(None),
    ebay_country: Optional[str] = Form("GB"),
    ebay_postal_code: Optional[str] = Form(None),
    # Reverb fields
    reverb_product_type: Optional[str] = Form(None),
    reverb_primary_category: Optional[str] = Form(None),
    reverb_price: Optional[float] = Form(None),
    shipping_profile: Optional[str] = Form(None),
    # V&R fields
    vr_category_id: Optional[str] = Form(None),
    vr_subcategory_id: Optional[str] = Form(None),
    vr_sub_subcategory_id: Optional[str] = Form(None),
    vr_sub_sub_subcategory_id: Optional[str] = Form(None),
    vr_price: Optional[float] = Form(None),
    # Shopify fields
    shopify_category_gid: Optional[str] = Form(None),
    shopify_price: Optional[float] = Form(None),
    shopify_product_type: Optional[str] = Form(None)
):
    """Generate platform payloads without creating the product"""
    
    # Log all received form data
    print("=== INSPECT PAYLOAD FORM DATA ===")
    print(f"Brand: {brand}")
    print(f"Model: {model}")
    print(f"SKU: {sku}")
    print(f"Category: {category}")
    print(f"Condition: {condition}")
    print(f"Base Price: {base_price}")
    print(f"Quantity: {quantity}")
    print(f"Description: {description[:100] if description else 'None'}...")
    print(f"Sync Shopify: {sync_shopify}")
    print(f"Sync eBay: {sync_ebay}")
    print(f"Sync V&R: {sync_vr}")
    print(f"Sync Reverb: {sync_reverb}")
    print(f"Reverb Primary Category: {reverb_primary_category}")
    print(f"eBay Category: {ebay_category}")
    print(f"Primary Image: {primary_image}")
    print(f"Additional Images: {additional_images}")
    print("=================================")
    
    # Convert string booleans to actual booleans
    sync_shopify = sync_shopify.lower() == 'true'
    sync_ebay = sync_ebay.lower() == 'true'
    sync_vr = sync_vr.lower() == 'true'
    sync_reverb = sync_reverb.lower() == 'true'
    
    # Process images
    images_array = []
    if primary_image:
        images_array.append(primary_image)
    if additional_images:
        try:
            additional = json.loads(additional_images)
            images_array.extend(additional)
        except:
            pass

    condition_mapping_service = ConditionMappingService(db)

    # Ensure the standard footer is present when we have body copy
    description = ensure_description_has_standard_footer(description)
    description_with_footer = description or ""
    
    # Map condition to Reverb condition UUID via DB-backed mappings
    reverb_condition_uuid = None
    condition_enum = None
    try:
        condition_enum = ProductCondition(condition)
    except Exception:
        logger.warning("inspect_payload received invalid condition value: %s", condition)

    if condition_enum:
        mapping = await condition_mapping_service.get_mapping(
            PlatformName.REVERB,
            condition_enum,
        )
        if mapping:
            reverb_condition_uuid = mapping.platform_condition_id

    if not reverb_condition_uuid:
        reverb_condition_uuid = "df268ad1-c462-4ba6-b6db-e007e23922ea"
    
    # Build response with payloads for each platform
    payloads = {}
    
    shopify_generated_keywords: List[str] = []
    shopify_generated_short_description: Optional[str] = None
    shopify_generated_seo_title: Optional[str] = None

    # Shopify payload
    if sync_shopify:
        # Build title with year if available
        title_parts = []
        if year:
            title_parts.append(str(year))
        title_parts.extend([brand, model])
        if finish:
            title_parts.append(finish)
        title = " ".join(filter(None, title_parts))

        shopify_generated_keywords = generate_shopify_keywords(
            brand=brand,
            model=model,
            finish=finish,
            year=year,
            decade=decade,
            category=shopify_product_type or category,
            condition=condition,
            description_html=description_with_footer,
        )

        fallback_title = title or f"{brand} {model}".strip()
        shopify_generated_seo_title = (fallback_title or "").strip()[:255] or None
        shopify_generated_short_description = generate_shopify_short_description(
            description_with_footer,
            fallback=fallback_title,
        )

        shopify_payload = {
            "platform": "shopify",
            "product_data": {
                "title": title,
                "descriptionHtml": description_with_footer,  # Changed from body_html
                "vendor": brand,
                "productType": shopify_product_type or category,  # Changed from product_type
                "status": "ACTIVE",  # Changed from "active" to uppercase
                "tags": shopify_generated_keywords,
                # Note: variants and images are added via separate API calls in the actual service
                "images": [{"src": url} for url in images_array],
            },
            "category_gid": shopify_category_gid
        }

        if shopify_generated_seo_title or shopify_generated_short_description:
            seo_block: Dict[str, str] = {}
            if shopify_generated_seo_title:
                seo_block["title"] = shopify_generated_seo_title
            if shopify_generated_short_description:
                seo_block["description"] = shopify_generated_short_description
            if seo_block:
                shopify_payload["product_data"]["seo"] = seo_block

        # Add metafields if needed (these are added via separate API calls in the actual service)
        metafields = []
        if decade:
            metafields.append({
                "namespace": "custom",
                "key": "decade",
                "value": decade,
                "type": "single_line_text_field"
            })
        if year:
            metafields.append({
                "namespace": "custom",
                "key": "year",
                "value": str(year),
                "type": "number_integer"
            })
        if shopify_generated_short_description:
            metafields.append({
                "namespace": "custom",
                "key": "short_description",
                "value": shopify_generated_short_description,
                "type": "multi_line_text_field",
            })
        if metafields:
            shopify_payload["product_data"]["metafields"] = metafields

        payloads["shopify"] = shopify_payload
    
    # eBay payload
    if sync_ebay:
        # Build title with year if available
        title_parts = []
        if year:
            title_parts.append(str(year))
        title_parts.extend([brand, model])
        if finish:
            title_parts.append(finish)
        title = " ".join(filter(None, title_parts))
        
        ebay_payload = {
            "platform": "ebay",
            "listing_data": {
                "Title": title,
                "Description": description_with_footer,
                "CategoryID": ebay_category,  # Changed from nested PrimaryCategory
                "Price": str(ebay_price or base_price),  # Changed from StartPrice
                "Currency": "GBP",
                "CurrencyID": "GBP",  # Added CurrencyID
                "Country": ebay_country,
                "Location": ebay_location or "United Kingdom",
                "PostalCode": ebay_postal_code,
                "Quantity": str(quantity),
                "ConditionID": "3000",  # Used condition
                "PictureDetails": {
                    "PictureURL": images_array[:12]  # eBay supports max 12 images
                },
                "ListingType": "FixedPriceItem",
                "ListingDuration": "GTC",
                "DispatchTimeMax": str(processing_time),
                "SKU": sku
            },
            "policies": {
                "payment": ebay_payment_policy if ebay_payment_policy else None,
                "return": ebay_return_policy if ebay_return_policy else None,
                "shipping": ebay_shipping_policy if ebay_shipping_policy else None
            }
        }
        
        # Add item specifics in the format expected by the trading API
        item_specifics = {}
        if brand:
            item_specifics["Brand"] = brand
        if model:
            item_specifics["Model"] = model
        if year:
            item_specifics["Year"] = str(year)
        if finish:
            item_specifics["Finish"] = finish
        
        if item_specifics:
            ebay_payload["listing_data"]["ItemSpecifics"] = item_specifics
        
        payloads["ebay"] = ebay_payload
    
    # V&R payload
    if sync_vr:
        # Build title with year if available
        title_parts = []
        if year:
            title_parts.append(str(year))
        title_parts.extend([brand, model])
        if finish:
            title_parts.append(finish)
        title = " ".join(filter(None, title_parts))
        
        vr_payload = {
            "platform": "vr",
            "listing_data": {
                # Category mapping - using the expected field names
                "Category": vr_category_id,
                "SubCategory1": vr_subcategory_id,
                "SubCategory2": vr_sub_subcategory_id,
                "SubCategory3": vr_sub_sub_subcategory_id,
                
                # Product details
                "title": title,
                "description": description_with_footer,
                "price": vr_price or base_price,
                "brand": brand,
                "model": model,
                "year": str(year) if year else "",  # V&R expects string
                "finish": finish or "",
                "condition": condition,
                
                # Images in the correct format
                "primary_image": images_array[0] if images_array else "",
                "additional_images": images_array[1:] if len(images_array) > 1 else [],
                
                # Shipping fees
                "shipping_fees": {
                    "uk": "45",
                    "europe": "50",
                    "usa": "100",
                    "world": "150"
                },
                
                # Options
                "in_collective": False,
                "in_inventory": True,
                "buy_now": False,
                "processing_time": str(processing_time),
                "time_unit": "Days",
                "shipping": True,
                "local_pickup": False,
                "quantity": quantity
            }
        }
        payloads["vr"] = vr_payload
    
    # Reverb payload (more complex, needs more fields)
    if sync_reverb:
        reverb_payload = {
            "platform": "reverb",
            "listing_data": {
                "title": f"{brand} {model}",
                "description": description_with_footer,
                "condition": {
                    "uuid": reverb_condition_uuid
                },
                "price": {
                    "amount": str(reverb_price or base_price),
                    "currency": "GBP"
                },
                "categories": [{"uuid": reverb_primary_category}] if reverb_primary_category else [],
                "make": brand,
                "model": model,
                "year": year,
                "finish": finish,
                "has_inventory": True,
                "inventory": quantity,
                "shipping": {
                    "local": True,
                    "rates": []
                },
                "photos": images_array,
                "sku": sku,
                "upc_does_not_apply": True,
                "publish": True,
                "state": {
                    "slug": "live"
                }
            }
        }
        
        # Add shipping profile if provided
        if shipping_profile:
            reverb_payload["shipping_profile_id"] = shipping_profile
        payloads["reverb"] = reverb_payload
    
    return {
        "status": "success",
        "message": "Payloads generated successfully",
        "payloads": payloads,
        "summary": {
            "product": {
                "brand": brand,
                "model": model,
                "sku": sku,
                "price": base_price,
                "quantity": quantity
            },
            "platforms_selected": {
                "shopify": sync_shopify,
                "ebay": sync_ebay,
                "vr": sync_vr,
                "reverb": sync_reverb
            }
        }
    }


@router.post("/save-draft")
async def save_draft(
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    # Basic product fields
    brand: str = Form(...),
    model: str = Form(...),
    sku: str = Form(...),
    title: Optional[str] = Form(None),
    category: str = Form(...),
    condition: str = Form(...),
    base_price: float = Form(...),
    quantity: int = Form(1),
    description: str = Form(""),
    # Optional fields
    decade: Optional[int] = Form(None),
    year: Optional[int] = Form(None),
    finish: Optional[str] = Form(None),
    processing_time: int = Form(3),
    cost_price: Optional[float] = Form(None),
    collective_discount: Optional[float] = Form(None),
    artist_names: Optional[str] = Form(None),
    # Inventory fields
    location: Optional[str] = Form(None),
    stock_warning_level: Optional[int] = Form(None),
    offer_price: Optional[float] = Form(None),
    offer_discount: Optional[float] = Form(None),
    # Checkbox fields
    in_collective: Optional[bool] = Form(False),
    in_inventory: Optional[bool] = Form(True),
    in_reseller: Optional[bool] = Form(False),
    free_shipping: Optional[bool] = Form(False),
    buy_now: Optional[bool] = Form(True),
    show_vat: Optional[bool] = Form(True),
    local_pickup: Optional[bool] = Form(False),
    available_for_shipment: Optional[bool] = Form(True),
    is_stocked_item: Optional[bool] = Form(False),
    # Media fields
    primary_image_file: Optional[UploadFile] = File(None),
    primary_image_url: Optional[str] = Form(None),
    additional_images_files: List[UploadFile] = File([]),
    additional_images_urls: Optional[str] = Form(None),
    video_url: Optional[str] = Form(None),
    external_link: Optional[str] = Form(None),
    storefront_input: Optional[str] = Form(None),
    # Platform sync fields
    sync_all: Optional[str] = Form("true"),
    sync_platforms: Optional[List[str]] = Form(None),
    # Platform-specific fields (for generating payloads)
    # eBay fields
    ebay_category: Optional[str] = Form(None),
    ebay_category_name: Optional[str] = Form(None),
    ebay_price: Optional[float] = Form(None),
    ebay_payment_policy: Optional[str] = Form(None),
    ebay_return_policy: Optional[str] = Form(None),
    ebay_shipping_policy: Optional[str] = Form(None),
    ebay_location: Optional[str] = Form(None),
    ebay_country: Optional[str] = Form("GB"),
    ebay_postal_code: Optional[str] = Form(None),
    # Reverb fields
    reverb_product_type: Optional[str] = Form(None),
    reverb_primary_category: Optional[str] = Form(None),
    reverb_price: Optional[float] = Form(None),
    shipping_profile: Optional[str] = Form(None),
    # V&R fields
    vr_category_id: Optional[str] = Form(None),
    vr_subcategory_id: Optional[str] = Form(None),
    vr_sub_subcategory_id: Optional[str] = Form(None),
    vr_sub_sub_subcategory_id: Optional[str] = Form(None),
    vr_price: Optional[float] = Form(None),
    # Shopify fields
    shopify_category_gid: Optional[str] = Form(None),
    shopify_price: Optional[float] = Form(None),
    shopify_product_type: Optional[str] = Form(None),
    # Additional product fields
    manufacturing_country: Optional[str] = Form(None),
    shipping_profile_id: Optional[int] = Form(None),
    handedness: Optional[str] = Form(None),
    serial_number: Optional[str] = Form(None),
    artist_owned: Optional[bool] = Form(False),
    inventory_location: Optional[str] = Form(None),
    case_status: Optional[str] = Form(None),
    case_details: Optional[str] = Form(None),
    extra_handmade: Optional[str] = Form(None),
    body_type: Optional[str] = Form(None),
    number_of_strings: Optional[str] = Form(None),
    # eBay category-specific fields
    ebay_form_factor: Optional[str] = Form(None),
    ebay_bass_type: Optional[str] = Form(None),
    ebay_amplifier_type: Optional[str] = Form(None),
    ebay_synth_type: Optional[str] = Form(None),
    ebay_keyboard_type: Optional[str] = Form(None),
    ebay_piano_type: Optional[str] = Form(None),
    ebay_piano_keys: Optional[str] = Form(None),
    ebay_headphones_connectivity: Optional[str] = Form(None),
    ebay_headphones_earpiece: Optional[str] = Form(None),
    ebay_headphones_form_factor: Optional[str] = Form(None),
    ebay_headphones_features: Optional[str] = Form(None),
    # Draft ID for updating existing draft
    draft_id: Optional[int] = Form(None)
):
    """Save product as draft without creating platform listings"""

    try:
        # Debug logging
        print(f"[SAVE DRAFT] Received description: {description[:100] if description else 'NONE'}...")
        print(f"[SAVE DRAFT] Description length: {len(description) if description else 0}")

        description = ensure_description_has_standard_footer(description)

        # Initialize product service
        product_service = ProductService(db)

        # Auto-derive decade from year when the dropdown was left unset
        if decade is None and year is not None:
            try:
                decade = (int(year) // 10) * 10
            except (TypeError, ValueError):
                decade = None

        # Process images
        primary_image = None
        additional_images = []

        draft_subdir = _draft_media_subdir(draft_id, sku)

        # Handle primary image
        if primary_image_file and primary_image_file.filename:
            primary_image = await save_draft_upload_file(primary_image_file, draft_subdir)
        elif primary_image_url:
            primary_image = primary_image_url

        # Handle additional images - files
        for img_file in additional_images_files:
            if img_file.filename:
                image_url = await save_draft_upload_file(img_file, draft_subdir)
                additional_images.append(image_url)

        # Handle additional images - URLs
        if additional_images_urls:
            try:
                urls = json.loads(additional_images_urls)
                additional_images.extend(urls)
            except:
                pass

        local_media_urls: List[str] = []
        if primary_image:
            local_media_urls.append(primary_image)
        local_media_urls.extend(additional_images)
        cleanup_draft_media(draft_subdir, local_media_urls)

        storefront_value = _normalize_storefront_input(storefront_input, Storefront.HANKS) or Storefront.HANKS

        # Process manufacturing_country enum
        manufacturing_country_enum = None
        if manufacturing_country and manufacturing_country.strip():
            try:
                manufacturing_country_enum = ManufacturingCountry(manufacturing_country.strip())
            except ValueError:
                try:
                    manufacturing_country_enum = ManufacturingCountry[manufacturing_country.strip().upper()]
                except KeyError:
                    pass

        # Process handedness enum
        handedness_enum = None
        if handedness and handedness.strip():
            try:
                handedness_enum = Handedness(handedness.strip())
            except ValueError:
                try:
                    handedness_enum = Handedness[handedness.strip().upper()]
                except KeyError:
                    pass

        # Process inventory_location enum - default to UNSPECIFIED (NOT NULL constraint)
        inventory_location_enum = InventoryLocation.UNSPECIFIED
        if inventory_location and inventory_location.strip() and inventory_location.strip().lower() not in ('none', ''):
            try:
                inventory_location_enum = InventoryLocation(inventory_location.strip())
            except ValueError:
                try:
                    inventory_location_enum = InventoryLocation[inventory_location.strip().upper()]
                except KeyError:
                    inventory_location_enum = InventoryLocation.UNSPECIFIED

        # Process case_status enum - default to UNSPECIFIED
        case_status_enum = CaseStatus.UNSPECIFIED
        if case_status and case_status.strip() and case_status.strip().lower() not in ('none', ''):
            try:
                case_status_enum = CaseStatus(case_status.strip())
            except ValueError:
                try:
                    case_status_enum = CaseStatus[case_status.strip().upper()]
                except KeyError:
                    case_status_enum = CaseStatus.UNSPECIFIED

        # Build extra_attributes
        extra_attributes: Dict[str, Any] = {"handmade": extra_handmade == "on"}
        if body_type and body_type.strip():
            extra_attributes["body_type"] = body_type.strip()
        if number_of_strings and number_of_strings.strip():
            extra_attributes["number_of_strings"] = number_of_strings.strip()

        # Get ebay_form_factor - check both direct parameter and form field name
        form_data = await request.form()
        form_factor_from_form = form_data.get("platform_data__ebay__form_factor")
        print(f"[SAVE DRAFT] ebay_form_factor param: {ebay_form_factor}")
        print(f"[SAVE DRAFT] platform_data__ebay__form_factor from form: {form_factor_from_form}")
        ebay_form_factor_value = ebay_form_factor or form_factor_from_form
        print(f"[SAVE DRAFT] Final ebay_form_factor_value: {ebay_form_factor_value}")
        if ebay_form_factor_value and str(ebay_form_factor_value).strip():
            extra_attributes["ebay_form_factor"] = str(ebay_form_factor_value).strip()
            print(f"[SAVE DRAFT] Added to extra_attributes: {extra_attributes}")

        # Get ebay_bass_type - check both direct parameter and form field name
        bass_type_from_form = form_data.get("platform_data__ebay__bass_type")
        print(f"[SAVE DRAFT] ebay_bass_type param: {ebay_bass_type}")
        print(f"[SAVE DRAFT] platform_data__ebay__bass_type from form: {bass_type_from_form}")
        ebay_bass_type_value = ebay_bass_type or bass_type_from_form
        print(f"[SAVE DRAFT] Final ebay_bass_type_value: {ebay_bass_type_value}")
        if ebay_bass_type_value and str(ebay_bass_type_value).strip():
            extra_attributes["ebay_bass_type"] = str(ebay_bass_type_value).strip()
            print(f"[SAVE DRAFT] Added bass_type to extra_attributes: {extra_attributes}")

        # Get ebay_amplifier_type - check both direct parameter and form field name
        amplifier_type_from_form = form_data.get("platform_data__ebay__amplifier_type")
        ebay_amplifier_type_value = ebay_amplifier_type or amplifier_type_from_form
        if ebay_amplifier_type_value and str(ebay_amplifier_type_value).strip():
            extra_attributes["ebay_amplifier_type"] = str(ebay_amplifier_type_value).strip()

        # Get ebay_synth_type
        synth_type_from_form = form_data.get("platform_data__ebay__synth_type")
        ebay_synth_type_value = ebay_synth_type or synth_type_from_form
        if ebay_synth_type_value and str(ebay_synth_type_value).strip():
            extra_attributes["ebay_synth_type"] = str(ebay_synth_type_value).strip()

        # Get ebay_keyboard_type
        keyboard_type_from_form = form_data.get("platform_data__ebay__keyboard_type")
        ebay_keyboard_type_value = ebay_keyboard_type or keyboard_type_from_form
        if ebay_keyboard_type_value and str(ebay_keyboard_type_value).strip():
            extra_attributes["ebay_keyboard_type"] = str(ebay_keyboard_type_value).strip()

        # Get Digital Piano fields
        piano_type_from_form = form_data.get("platform_data__ebay__piano_type")
        ebay_piano_type_value = ebay_piano_type or piano_type_from_form
        if ebay_piano_type_value and str(ebay_piano_type_value).strip():
            extra_attributes["ebay_piano_type"] = str(ebay_piano_type_value).strip()

        piano_keys_from_form = form_data.get("platform_data__ebay__piano_keys")
        ebay_piano_keys_value = ebay_piano_keys or piano_keys_from_form
        if ebay_piano_keys_value and str(ebay_piano_keys_value).strip():
            extra_attributes["ebay_piano_keys"] = str(ebay_piano_keys_value).strip()

        # Get Headphones fields
        hp_connectivity_from_form = form_data.get("platform_data__ebay__headphones_connectivity")
        ebay_hp_connectivity_value = ebay_headphones_connectivity or hp_connectivity_from_form
        if ebay_hp_connectivity_value and str(ebay_hp_connectivity_value).strip():
            extra_attributes["ebay_headphones_connectivity"] = str(ebay_hp_connectivity_value).strip()

        hp_earpiece_from_form = form_data.get("platform_data__ebay__headphones_earpiece")
        ebay_hp_earpiece_value = ebay_headphones_earpiece or hp_earpiece_from_form
        if ebay_hp_earpiece_value and str(ebay_hp_earpiece_value).strip():
            extra_attributes["ebay_headphones_earpiece"] = str(ebay_hp_earpiece_value).strip()

        hp_form_factor_from_form = form_data.get("platform_data__ebay__headphones_form_factor")
        ebay_hp_form_factor_value = ebay_headphones_form_factor or hp_form_factor_from_form
        if ebay_hp_form_factor_value and str(ebay_hp_form_factor_value).strip():
            extra_attributes["ebay_headphones_form_factor"] = str(ebay_hp_form_factor_value).strip()

        hp_features_from_form = form_data.get("platform_data__ebay__headphones_features")
        ebay_hp_features_value = ebay_headphones_features or hp_features_from_form
        if ebay_hp_features_value and str(ebay_hp_features_value).strip():
            extra_attributes["ebay_headphones_features"] = str(ebay_hp_features_value).strip()

        # Merge additional specs from the Additional Specs UI section
        additional_specs_json = form_data.get("additional_specs_json", "{}")
        try:
            additional_specs = json.loads(additional_specs_json) if additional_specs_json else {}
            if isinstance(additional_specs, dict):
                extra_attributes.update(additional_specs)
        except json.JSONDecodeError:
            logger.warning("[SAVE DRAFT] Failed to parse additional_specs_json: %s", additional_specs_json)

        # Create or update product data - only include fields that exist in Product model
        product_data = {
            "sku": sku,
            "brand": brand.title(),
            "model": model,
            "title": title,
            "category": category,
            "condition": condition,
            "base_price": base_price,
            "quantity": quantity,
            "description": description,
            "decade": decade,
            "year": year,
            "finish": finish,
            "processing_time": processing_time,
            "cost_price": cost_price,
            "collective_discount": collective_discount or 0.0,
            "offer_discount": offer_discount,
            "in_collective": in_collective,
            "in_inventory": in_inventory,
            "in_reseller": in_reseller,
            "free_shipping": free_shipping,
            "buy_now": buy_now,
            "show_vat": show_vat,
            "local_pickup": local_pickup,
            "available_for_shipment": available_for_shipment,
            "is_stocked_item": is_stocked_item,
            "primary_image": primary_image,
            "additional_images": additional_images,
            "video_url": video_url,
            "external_link": external_link,
            "storefront": storefront_value,
            "manufacturing_country": manufacturing_country_enum,
            "shipping_profile_id": shipping_profile_id,
            "handedness": handedness_enum,
            "serial_number": serial_number.strip() if serial_number and serial_number.strip().lower() not in ('none', '') else None,
            "artist_owned": artist_owned,
            "artist_names": [name.strip() for name in re.split(r"[,\n]", artist_names or "") if name.strip()] if artist_names else [],
            "inventory_location": inventory_location_enum,
            "case_status": case_status_enum,
            "case_details": case_details.strip() if case_details and case_details.strip().lower() not in ('none', '') else None,
            "extra_attributes": extra_attributes,
            "status": "DRAFT"  # Always save as DRAFT
        }

        # Store platform data as JSON for later use
        platform_data = {
            "sync_all": sync_all == "true",
            "sync_platforms": sync_platforms or [],
            "ebay": {
                "category": ebay_category or form_data.get("ebay_category"),
                "category_name": ebay_category_name,
                "price": ebay_price,
                "payment_policy": ebay_payment_policy,
                "return_policy": ebay_return_policy,
                "shipping_policy": ebay_shipping_policy,
                "location": ebay_location,
                "country": ebay_country,
                "postal_code": ebay_postal_code,
                "form_factor": ebay_form_factor_value,
                "bass_type": ebay_bass_type_value,
                "amplifier_type": ebay_amplifier_type_value
            },
            "reverb": {
                "product_type": reverb_product_type,
                "primary_category": reverb_primary_category,
                "price": reverb_price,
                "shipping_profile": shipping_profile
            },
            "vr": {
                "category_id": vr_category_id,
                "subcategory_id": vr_subcategory_id,
                "sub_subcategory_id": vr_sub_subcategory_id,
                "sub_sub_subcategory_id": vr_sub_sub_subcategory_id,
                "price": vr_price
            },
            "shopify": {
                "category_gid": shopify_category_gid,
                "price": shopify_price,
                "product_type": shopify_product_type
            }
        }

        # Store platform data in package_dimensions temporarily (since attributes field doesn't exist)
        # This is a temporary solution - ideally we'd add a proper platform_data JSONB field
        product_data["package_dimensions"] = {"platform_data": platform_data}

        if draft_id:
            # Update existing draft
            product = await db.get(Product, draft_id)
            if not product:
                raise HTTPException(status_code=404, detail="Draft not found")

            # Update product fields
            for key, value in product_data.items():
                setattr(product, key, value)

            await db.commit()
            await db.refresh(product)
        else:
            # Create new draft
            product = Product(**product_data)
            db.add(product)
            await db.commit()
            await db.refresh(product)

        # Return JSON response for AJAX request
        return JSONResponse({
            "status": "success",
            "message": f"Draft saved successfully with SKU: {product.sku}",
            "product_id": product.id,
            "redirect_url": f"/inventory?message=Draft saved successfully&message_type=success"
        })

    except Exception as e:
        await db.rollback()
        logger.error(f"Error saving draft: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "message": f"Failed to save draft: {str(e)}"
            }
        )


@router.get("/drafts", response_class=JSONResponse)
async def get_drafts(
    db: AsyncSession = Depends(get_db)
):
    """Get all draft products for resuming editing"""
    drafts = await db.execute(
        select(Product)
        .where(Product.status == "DRAFT")
        .order_by(desc(Product.updated_at))
    )
    drafts = drafts.scalars().all()

    return {
        "drafts": [
            {
                "id": d.id,
                "sku": d.sku,
                "brand": d.brand,
                "model": d.model,
                "created_at": d.created_at.isoformat(),
                "updated_at": d.updated_at.isoformat()
            }
            for d in drafts
        ]
    }


@router.post("/drafts/{draft_id}/delete")
async def delete_draft(
    draft_id: int,
    db: AsyncSession = Depends(get_db)
):
    draft = await db.get(Product, draft_id)
    if not draft or draft.status != ProductStatus.DRAFT:
        raise HTTPException(status_code=404, detail="Draft not found")

    sku = draft.sku or f"Draft-{draft_id}"
    await db.delete(draft)
    await db.commit()

    message = f"{sku} deleted"
    return RedirectResponse(
        url=f"/inventory?message={quote_plus(message)}&message_type=error",
        status_code=303,
    )


@router.get("/api/ebay/category-aspects", response_class=JSONResponse)
async def get_ebay_category_aspects(
    category_id: Optional[str] = None,
):
    """
    Get eBay category-specific aspects (like Form Factor for Microphones).
    Returns cached data from JSON file.

    Args:
        category_id: Optional eBay category ID to filter results
    """
    cache_file = Path(__file__).parent.parent / "static" / "data" / "ebay_category_aspects.json"

    try:
        async with aiofiles.open(cache_file, 'r') as f:
            content = await f.read()
            data = json.loads(content)

        if category_id:
            # Return aspects for specific category
            category_data = data.get("categories", {}).get(category_id)
            if category_data:
                return JSONResponse({
                    "success": True,
                    "category_id": category_id,
                    "category_name": category_data.get("name"),
                    "required_aspects": category_data.get("required_aspects", {})
                })
            else:
                return JSONResponse({
                    "success": True,
                    "category_id": category_id,
                    "category_name": None,
                    "required_aspects": {}
                })
        else:
            # Return all categories
            return JSONResponse({
                "success": True,
                "last_updated": data.get("last_updated"),
                "categories": data.get("categories", {})
            })
    except FileNotFoundError:
        return JSONResponse({
            "success": False,
            "error": "Category aspects cache file not found"
        }, status_code=500)
    except json.JSONDecodeError:
        return JSONResponse({
            "success": False,
            "error": "Invalid cache file format"
        }, status_code=500)


def _serialize_draft_product(draft: Product) -> Dict[str, Any]:
    """Produce a serialisable representation of a draft product."""
    additional_images: Any = draft.additional_images or []
    if isinstance(additional_images, str):
        try:
            parsed = json.loads(additional_images)
            if isinstance(parsed, list):
                additional_images = parsed
            elif parsed:
                additional_images = [parsed]
            else:
                additional_images = []
        except json.JSONDecodeError:
            additional_images = [additional_images]

    status_value = None
    if hasattr(draft.status, "value"):
        status_value = draft.status.value
    elif draft.status is not None:
        status_value = draft.status

    base_price = None
    if draft.base_price is not None:
        try:
            base_price = float(draft.base_price)
        except (TypeError, ValueError):
            base_price = draft.base_price

    offer_discount = None
    if draft.offer_discount is not None:
        try:
            offer_discount = float(draft.offer_discount)
        except (TypeError, ValueError):
            offer_discount = draft.offer_discount

    quantity = None
    if draft.quantity is not None:
        try:
            quantity = int(draft.quantity)
        except (TypeError, ValueError):
            quantity = draft.quantity

    processing_time = None
    if draft.processing_time is not None:
        try:
            processing_time = int(draft.processing_time)
        except (TypeError, ValueError):
            processing_time = draft.processing_time

    draft_data: Dict[str, Any] = {
        "id": draft.id,
        "sku": draft.sku,
        "brand": draft.brand,
        "model": draft.model,
        "title": draft.title,
        "category": draft.category,
        "condition": draft.condition,
        "status": status_value,
        "base_price": base_price,
        "quantity": quantity,
        "description": draft.description,
        "decade": draft.decade,
        "year": draft.year,
        "finish": draft.finish,
        "processing_time": processing_time,
        "cost_price": float(draft.cost_price) if draft.cost_price is not None else None,
        "collective_discount": float(draft.collective_discount) if draft.collective_discount is not None else 0.0,
        "offer_discount": offer_discount,
        "in_collective": draft.in_collective,
        "in_inventory": draft.in_inventory,
        "in_reseller": draft.in_reseller,
        "free_shipping": draft.free_shipping,
        "buy_now": draft.buy_now,
        "show_vat": draft.show_vat,
        "local_pickup": draft.local_pickup,
        "available_for_shipment": draft.available_for_shipment,
        "is_stocked_item": draft.is_stocked_item,
        "primary_image": draft.primary_image,
        "additional_images": additional_images,
        "video_url": draft.video_url,
        "external_link": draft.external_link,
    }

    artist_names = draft.artist_names or []
    if isinstance(artist_names, str):
        try:
            parsed_names = json.loads(artist_names)
            if isinstance(parsed_names, list):
                artist_names = parsed_names
            elif parsed_names:
                artist_names = [parsed_names]
            else:
                artist_names = []
        except json.JSONDecodeError:
            artist_names = [artist_names]

    extra_attributes: Dict[str, Any] = draft.extra_attributes or {}
    if isinstance(extra_attributes, str):
        try:
            maybe_attrs = json.loads(extra_attributes)
            if isinstance(maybe_attrs, dict):
                extra_attributes = maybe_attrs
        except json.JSONDecodeError:
            extra_attributes = {}

    handedness_value = None
    if draft.handedness:
        handedness_value = getattr(draft.handedness, "name", draft.handedness)

    case_status_value = None
    if draft.case_status:
        case_status_value = getattr(draft.case_status, "name", draft.case_status)

    manufacturing_country_value = None
    if draft.manufacturing_country:
        manufacturing_country_value = getattr(draft.manufacturing_country, "value", draft.manufacturing_country)

    draft_data.update(
        {
            "handedness": handedness_value,
            "serial_number": draft.serial_number,
            "case_status": case_status_value,
            "case_details": draft.case_details,
            "artist_owned": draft.artist_owned,
            "artist_names": artist_names,
            "extra_attributes": extra_attributes,
            "manufacturing_country": manufacturing_country_value,
            "shipping_profile_id": draft.shipping_profile_id,
        }
    )

    package_dimensions = draft.package_dimensions or {}
    if isinstance(package_dimensions, dict) and "platform_data" in package_dimensions:
        draft_data["platform_data"] = package_dimensions["platform_data"]

    return draft_data


@router.get("/drafts/{draft_id}", response_class=JSONResponse)
async def get_draft_details(
    draft_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Get details of a specific draft for editing"""
    draft = await db.get(Product, draft_id)
    if not draft or draft.status != "DRAFT":
        raise HTTPException(status_code=404, detail="Draft not found")

    return _serialize_draft_product(draft)


@router.get("/products/{product_id}/edit")
async def edit_product_form(
    request: Request,
    product_id: int,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Show product edit form"""
    product = await db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    
    # Get platform statuses and specialist pricing
    platform_links_result = await db.execute(
        select(PlatformCommon).where(PlatformCommon.product_id == product_id)
    )
    platform_links = platform_links_result.scalars().all()
    categories_result = await db.execute(
        select(ReverbCategory.full_path)
        .where(ReverbCategory.full_path.isnot(None))
        .order_by(ReverbCategory.full_path)
    )
    canonical_categories: List[str] = []
    seen_categories: set[str] = set()
    for (full_path,) in categories_result.all():
        if not full_path:
            continue
        normalized = full_path.strip()
        if not normalized or normalized in seen_categories:
            continue
        canonical_categories.append(normalized)
        seen_categories.add(normalized)

    base_price_value = float(product.base_price or 0)
    reverb_price_value = float(product.price or 0) if product.price else None
    platforms: Dict[str, Dict[str, Any]] = {
        name: _build_platform_stub(name, base_price_value, reverb_price_value)
        for name in ["shopify", "reverb", "ebay", "vr"]
    }
    brand_result = await db.execute(select(Product.brand).distinct().order_by(Product.brand))
    brand_options = [row[0] for row in brand_result.fetchall() if row[0]]

    shipping_profiles_result = await db.execute(
        select(ShippingProfile).order_by(ShippingProfile.name)
    )
    shipping_profiles = shipping_profiles_result.scalars().all()

    for link in platform_links:
        platform_key = (link.platform_name or "").lower()
        if not platform_key:
            continue

        entry = platforms.get(platform_key)
        if entry is None:
            entry = _build_platform_stub(platform_key, base_price_value, reverb_price_value)
            platforms[platform_key] = entry

        entry["status"] = (link.status or entry.get("status") or "inactive").lower()
        entry["external_id"] = link.external_id
        entry["url"] = link.listing_url

        price_value: Optional[float] = None

        if platform_key == "shopify":
            listing_stmt = select(ShopifyListing).where(ShopifyListing.platform_id == link.id)
            listing = (await db.execute(listing_stmt)).scalar_one_or_none()
            if listing and listing.price is not None:
                price_value = float(listing.price)
        elif platform_key == "reverb":
            listing_stmt = select(ReverbListing).where(ReverbListing.platform_id == link.id)
            listing = (await db.execute(listing_stmt)).scalar_one_or_none()
            if listing and listing.list_price is not None:
                price_value = float(listing.list_price)
        elif platform_key == "ebay":
            listing_stmt = select(EbayListing).where(EbayListing.platform_id == link.id)
            listing = (await db.execute(listing_stmt)).scalar_one_or_none()
            if listing and listing.price is not None:
                price_value = float(listing.price)
        elif platform_key == "vr":
            listing_stmt = select(VRListing).where(VRListing.platform_id == link.id)
            listing = (await db.execute(listing_stmt)).scalar_one_or_none()
            if listing and listing.price_notax is not None:
                price_value = float(listing.price_notax)

        if price_value is None:
            platform_specific = link.platform_specific_data or {}
            raw_price = platform_specific.get("price") if isinstance(platform_specific, dict) else None
            try:
                price_value = float(raw_price) if raw_price is not None else None
            except (TypeError, ValueError):
                price_value = None

        if price_value is None:
            price_value = _calculate_default_platform_price(platform_key, base_price_value, reverb_price_value)

        entry["price"] = price_value
    
    return templates.TemplateResponse(
        "inventory/edit.html",
        {
            "request": request,
            "product": product,
            "platforms": platforms,
            "conditions": ProductCondition,
            "statuses": ProductStatus,
            "handedness_options": list(Handedness),
            "manufacturing_countries": [c for c in ManufacturingCountry if c != ManufacturingCountry.OTHER],
            "case_status_options": list(CaseStatus),
            "inventory_locations": list(InventoryLocation),
            "storefront_options": list(Storefront),
            "brand_options": brand_options,
            "canonical_categories": canonical_categories,
            "shipping_profiles": shipping_profiles,
            "body_type_options": SPEC_FIELD_MAP.get("body_type", {}).get("options", []),
            "tinymce_api_key": settings.TINYMCE_API_KEY,
        }
    )

@router.post("/products/{product_id}/edit")
async def update_product(
    request: Request,
    product_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Update product details"""
    form_data = await request.form()
    
    product = await db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    current_platform_prices = await _fetch_current_platform_prices(db, product_id)
    
    original_values = {
        "title": product.title,
        "brand": product.brand,
        "model": product.model,
        "description": product.description,
        "quantity": product.quantity,
        "base_price": product.base_price,
        "category": product.category,
        "serial_number": product.serial_number,
        "handedness": product.handedness,
        "manufacturing_country": product.manufacturing_country,
        "artist_owned": product.artist_owned,
        "artist_names": list(product.artist_names) if product.artist_names else [],
        "extra_attributes": json.loads(json.dumps(product.extra_attributes or {})),
        "condition": product.condition,
        "year": product.year,
        "finish": product.finish,
    }
    
    # Update product fields with validation
    product.title = form_data.get('title') or product.title
    product.brand = form_data.get('brand') or product.brand
    product.model = form_data.get('model') or product.model
    
    # Handle year - can be empty
    year_str = form_data.get('year', '').strip()
    if year_str:
        try:
            product.year = int(year_str)
        except ValueError:
            pass  # Keep existing year if invalid

    decade_value = form_data.get("decade")
    if decade_value is not None:
        decade_value = decade_value.strip()
        if decade_value == "":
            product.decade = None
        else:
            if decade_value.lower().endswith("s"):
                decade_value = decade_value[:-1]
            try:
                product.decade = int(decade_value)
            except ValueError:
                pass
    
    product.finish = form_data.get('finish') or product.finish
    product.category = form_data.get('category') or product.category
    product.description = form_data.get('description') or product.description

    product.serial_number = form_data.get("serial_number") or None

    handedness_value = form_data.get("handedness")
    if handedness_value:
        try:
            product.handedness = Handedness[handedness_value]
        except KeyError:
            pass

    product.artist_owned = form_data.get("artist_owned") == "on"
    artist_names_raw = form_data.get("artist_names", "")
    if artist_names_raw:
        parsed_names = [
            name.strip()
            for name in re.split(r"[,\n]", artist_names_raw)
            if name.strip()
        ]
        product.artist_names = parsed_names
    else:
        product.artist_names = []

    manufacturing_country_value = (form_data.get("manufacturing_country") or "").strip()
    if manufacturing_country_value:
        try:
            product.manufacturing_country = ManufacturingCountry(manufacturing_country_value)
        except ValueError:
            pass
    else:
        product.manufacturing_country = None

    inventory_location_value = form_data.get("inventory_location")
    if inventory_location_value:
        try:
            product.inventory_location = InventoryLocation[inventory_location_value]
        except KeyError:
            pass

    storefront_option = _normalize_storefront_input(form_data.get("storefront"), product.storefront)
    if storefront_option:
        product.storefront = storefront_option

    case_status_value = form_data.get("case_status")
    if case_status_value:
        try:
            product.case_status = CaseStatus[case_status_value]
        except KeyError:
            pass

    product.case_details = form_data.get("case_details") or None

    extra_attributes = dict(product.extra_attributes or {})
    extra_attributes["handmade"] = form_data.get("extra_handmade") == "on"
    body_type_value = (form_data.get("body_type") or "").strip()
    if body_type_value:
        extra_attributes["body_type"] = body_type_value
    else:
        extra_attributes.pop("body_type", None)
    number_of_strings_value = (form_data.get("number_of_strings") or "").strip()
    if number_of_strings_value:
        extra_attributes["number_of_strings"] = number_of_strings_value
    else:
        extra_attributes.pop("number_of_strings", None)
    product.extra_attributes = extra_attributes

    shipping_profile_value = form_data.get("shipping_profile_id") or form_data.get("shipping_profile")
    if shipping_profile_value is not None:
        shipping_profile_value = str(shipping_profile_value).strip()
        if shipping_profile_value == "":
            product.shipping_profile_id = None
        else:
            try:
                product.shipping_profile_id = int(shipping_profile_value)
            except ValueError:
                logger.warning("Invalid shipping profile value '%s' ignored", shipping_profile_value)
    
    # Handle price with validation
    try:
        product.base_price = float(form_data.get('base_price', product.base_price))
    except (ValueError, TypeError):
        pass  # Keep existing price if invalid
    
    # Handle quantity with validation
    try:
        product.quantity = int(form_data.get('quantity', product.quantity))
    except (ValueError, TypeError):
        pass  # Keep existing quantity if invalid
    
    product.is_stocked_item = form_data.get('is_stocked_item') == 'on'
    
    # Update condition if changed
    if form_data.get('condition'):
        try:
            product.condition = ProductCondition(form_data.get('condition'))
        except ValueError:
            # If invalid condition value, keep existing
            pass
    
    await db.commit()

    changed_fields = {
        field
        for field, original in original_values.items()
        if getattr(product, field) != original
    }

    platform_price_overrides: Dict[str, float] = {}
    for platform_key in ("reverb", "ebay", "vr"):
        raw_value = form_data.get(f"platform_price_{platform_key}")
        if raw_value is None or raw_value == "":
            continue
        try:
            desired_price = float(raw_value)
        except (TypeError, ValueError):
            continue

        current_price = current_platform_prices.get(platform_key)
        if current_price is None or abs(desired_price - current_price) > PRICE_CHANGE_EPSILON:
            platform_price_overrides[platform_key] = desired_price

    message = "Product updated successfully."

    if changed_fields or platform_price_overrides:
        vr_executor = getattr(request.app.state, "vr_executor", None)
        sync_service = SyncService(db, vr_executor=vr_executor)
        try:
            propagation_result = await sync_service.propagate_product_edit(
                product_id,
                original_values,
                changed_fields,
                platform_price_overrides=platform_price_overrides,
            )
            logger.info("Edit propagation result for product %s: %s", product.sku, propagation_result)
        except Exception as exc:
            logger.error("Error propagating product edits: %s", exc, exc_info=True)
            message += " (Warning: some platform updates may have failed)"

    # Check if any platforms were selected for sync
    sync_platforms = []
    for platform in ['reverb', 'ebay', 'shopify', 'vr']:
        if form_data.get(f'sync_{platform}'):
            sync_platforms.append(platform)
    
    if sync_platforms:
        message += f" (Note: Platform sync for {', '.join(sync_platforms)} is pending implementation)"
    
    # Redirect back to detail page
    return RedirectResponse(
        url=f"/inventory/product/{product_id}",
        status_code=303
    )

@router.put("/products/{product_id}/stock")
async def update_product_stock(
    product_id: int,
    quantity: int,
    request: Request
):
    try:
        event = StockUpdateEvent(
            product_id=product_id,
            platform="local",
            new_quantity=quantity,
            timestamp=datetime.now()
        )
        await request.app.state.stock_manager.process_stock_update(event)
        return {"status": "success", "new_quantity": quantity}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/api/next-sku", response_model=dict)
async def get_next_sku(db: AsyncSession = Depends(get_db)):
    """Generate the next available SKU in format RIFF-1xxxxxxx (8 digit number starting with 1)"""
    try:
        from app.services.sku_service import generate_next_riff_sku

        new_sku = await generate_next_riff_sku(db)
        return {"sku": new_sku}
    except Exception as e:
        import traceback

        print(traceback.format_exc())
        return {"error": str(e)}

@router.get("/export/vintageandrare", response_class=StreamingResponse)
async def export_vintageandrare(
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
):
    try:
        export_service = VRExportService(db)
        csv_content = await export_service.generate_csv()
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        filename = f"vintageandrare_export_{timestamp}.csv"
        
        headers = {
            'Content-Disposition': f'attachment; filename="{filename}"',
            'Content-Type': 'text/csv'
        }
        
        return StreamingResponse(
            iter([csv_content.getvalue()]),
            headers=headers
        )
        
    except Exception as e:
        print(f"Export error: {str(e)}")
        return templates.TemplateResponse(
            "errors/500.html",
            {
                "request": request,
                "error_message": "Error generating export file"
            },
            status_code=500
        )

@router.get("/metrics")
async def get_metrics(request: Request):
    """Get current metrics for all platforms and queue status"""
    return request.app.state.stock_manager.get_metrics()

@router.get("/test")
async def test_route():
    return {"message": "Test route working"}

@router.get("/sync/vintageandrare", response_class=HTMLResponse)
async def sync_vintageandrare_form(
    request: Request,
    db: AsyncSession = Depends(get_db),
    search: Optional[str] = None,
    category: Optional[str] = None,
    brand: Optional[str] = None
):
    """Show form for selecting products to sync to VintageAndRare"""
    # Base query for products
    query = select(Product).outerjoin(
        PlatformCommon, 
        and_(
            PlatformCommon.product_id == Product.id,
            PlatformCommon.platform_name == 'vintageandrare'
        )
    ).where(PlatformCommon.id == None)  # Only products not yet on V&R
    
    # Apply filters
    if search:
        search = f"%{search}%"
        query = query.filter(
            or_(
                Product.brand.ilike(search),
                Product.model.ilike(search),
                Product.category.ilike(search)
            )
        )
    if category:
        query = query.filter(Product.category == category)
    if brand:
        query = query.filter(Product.brand == brand)
    
    # Execute query
    result = await db.execute(query)
    products = result.scalars().all()
    
    # Get categories and brands for filters
    categories_result = await db.execute(select(Product.category).distinct())
    categories = [c[0] for c in categories_result.all() if c[0]]
    
    brands_result = await db.execute(select(Product.brand).distinct())
    brands = [b[0] for b in brands_result.all() if b[0]]
    
    return templates.TemplateResponse(
        "inventory/sync_vr.html",
        {
            "request": request,
            "products": products,
            "categories": categories,
            "brands": brands,
            "selected_category": category,
            "selected_brand": brand,
            "search": search
        }
    )

@router.post("/sync/vintageandrare", response_class=HTMLResponse)
async def sync_vintageandrare_submit(
    request: Request,
    product_ids: List[int] = Form(...),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings)
):
    """Process selected products and sync to VintageAndRare"""
    results = {
        "success": 0,
        "errors": 0,
        "messages": []
    }
    
    from app.services.vintageandrare.client import VintageAndRareClient
    from app.services.category_mapping_service import CategoryMappingService
    
    # Initialize services
    mapping_service = CategoryMappingService(db)
    vr_client = VintageAndRareClient(
        settings.VINTAGE_AND_RARE_USERNAME,
        settings.VINTAGE_AND_RARE_PASSWORD,
        db_session=db
    )
    
    # Authenticate first
    is_authenticated = await vr_client.authenticate()
    if not is_authenticated:
        results["errors"] += len(product_ids)
        results["messages"].append("Failed to authenticate with Vintage & Rare")
        return templates.TemplateResponse(
            "inventory/sync_vr_results.html",
            {
                "request": request,
                "results": results
            }
        )
    
    # Process each product
    for product_id in product_ids:
        try:
            # Get product
            query = select(Product).where(Product.id == product_id)
            result = await db.execute(query)
            product = result.scalar_one_or_none()
            
            if not product:
                results["errors"] += 1
                results["messages"].append(f"Product {product_id} not found")
                continue
            
            # Check for existing platform listing
            query = select(PlatformCommon).where(
                PlatformCommon.product_id == product.id,
                PlatformCommon.platform_name == "vintageandrare"
            )
            platform_result = await db.execute(query)
            platform_common = platform_result.scalar_one_or_none()
            
            # Create new platform listing if needed
            if not platform_common:
                platform_common = PlatformCommon(
                    product_id=product.id,
                    platform_name="vintageandrare",
                    status=ListingStatus.DRAFT.value,
                    sync_status=SyncStatus.PENDING.value,
                    last_sync=datetime.now(timezone.utc)()
                )
                db.add(platform_common)
                await db.flush()
            
            # Check VR permissions first before attempting to create VRListing
            try:
                # Try to create a VRListing record
                vr_listing = VRListing(
                    platform_id=platform_common.id,
                    in_collective=product.in_collective or False,
                    in_inventory=product.in_inventory or True,
                    in_reseller=product.in_reseller or False,
                    collective_discount=product.collective_discount,
                    price_notax=product.price_notax,
                    show_vat=product.show_vat or True,
                    processing_time=product.processing_time,
                    inventory_quantity=1,
                    vr_state="draft",
                    created_at=datetime.now(timezone.utc)(),
                    updated_at=datetime.now(timezone.utc)(),
                    last_synced_at=datetime.now(timezone.utc)()
                )
                db.add(vr_listing)
                await db.flush()
            except Exception as e:
                # If permissions error, continue without VRListing
                logger.warning(f"Unable to create VRListing: {str(e)}")
                # For demo, continue without VRListing
            
            # Prepare data for V&R client
            product_data = {
                "id": product.id,  # Include ID for mapping lookup
                "brand": product.brand,
                "model": product.model,
                "year": product.year,
                "decade": product.decade,
                "finish": product.finish,
                "description": product.description,
                "price": product.base_price,
                "price_notax": product.price_notax,
                "category": product.category,
                "in_collective": product.in_collective,
                "in_inventory": product.in_inventory,
                "in_reseller": product.in_reseller,
                "collective_discount": product.collective_discount,
                "show_vat": product.show_vat,
                "local_pickup": product.local_pickup,
                "available_for_shipment": product.available_for_shipment,
                "processing_time": product.processing_time,
                "primary_image": product.primary_image,
                "additional_images": product.additional_images,
                "video_url": product.video_url,
                "external_link": product.external_link
            }
            
            # Call V&R client to create listing (test mode for now)
            vr_response = await vr_client.create_listing(product_data, test_mode=False)
            
            # Update platform_common with response data
            if vr_response.get("status") == "success":
                if vr_response.get("external_id"):
                    platform_common.external_id = vr_response["external_id"]
                platform_common.sync_status = SyncStatus.SYNCED.value
                platform_common.last_sync = datetime.now(timezone.utc)()
                
                results["success"] += 1
                results["messages"].append(f"Created draft for {product.brand} {product.model}")
            else:
                platform_common.sync_status = SyncStatus.FAILED.value
                platform_common.last_sync = datetime.now(timezone.utc)()
                
                results["errors"] += 1
                results["messages"].append(f"Error creating draft for {product.brand} {product.model}: {vr_response.get('message', 'Unknown error')}")
            
        except Exception as e:
            results["errors"] += 1
            results["messages"].append(f"Error syncing product {product_id}: {str(e)}")
            import traceback
            print(traceback.format_exc())
    
    await db.commit()
    
    return templates.TemplateResponse(
        "inventory/sync_vr_results.html",
        {
            "request": request,
            "results": results
        }
    )

@router.get("/sync/ebay", response_class=HTMLResponse)
async def sync_ebay_form(
    request: Request,
    db: AsyncSession = Depends(get_db),
    search: Optional[str] = None,
    category: Optional[str] = None,
    brand: Optional[str] = None
):
    """Show form for selecting products to sync to eBay"""
    # Base query for products
    query = select(Product).outerjoin(
        PlatformCommon, 
        and_(
            PlatformCommon.product_id == Product.id,
            PlatformCommon.platform_name == 'ebay'
        )
    ).where(PlatformCommon.id == None)  # Only products not yet on eBay
    
    # Apply filters
    if search:
        search = f"%{search}%"
        query = query.filter(
            or_(
                Product.brand.ilike(search),
                Product.model.ilike(search),
                Product.category.ilike(search)
            )
        )
    if category:
        query = query.filter(Product.category == category)
    if brand:
        query = query.filter(Product.brand == brand)
    
    # Execute query
    result = await db.execute(query)
    products = result.scalars().all()
    
    # Get categories and brands for filters
    categories_result = await db.execute(select(Product.category).distinct())
    categories = [c[0] for c in categories_result.all() if c[0]]
    
    brands_result = await db.execute(select(Product.brand).distinct())
    brands = [b[0] for b in brands_result.all() if b[0]]
    
    return templates.TemplateResponse(
        "inventory/sync_ebay.html",  # You'll need to create this template
        {
            "request": request,
            "products": products,
            "categories": categories,
            "brands": brands,
            "selected_category": category,
            "selected_brand": brand,
            "search": search
        }
    )

@router.post("/sync/ebay", response_class=HTMLResponse)
async def sync_ebay_submit(
    request: Request,
    product_ids: List[int] = Form(...),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings)
):
    """Process selected products and sync to eBay"""
    results = {
        "success": 0,
        "errors": 0,
        "messages": []
    }
    
    # Initialize services
    mapping_service = CategoryMappingService(db)
    condition_mapping_service = ConditionMappingService(db)
    ebay_service = EbayService(db, settings)
    
    # Process each product
    for product_id in product_ids:
        try:
            # Get product
            query = select(Product).where(Product.id == product_id)
            result = await db.execute(query)
            product = result.scalar_one_or_none()
            
            if not product:
                results["errors"] += 1
                results["messages"].append(f"Product {product_id} not found")
                continue
            
            # Check for existing platform listing
            query = select(PlatformCommon).where(
                PlatformCommon.product_id == product.id,
                PlatformCommon.platform_name == "ebay"
            )
            platform_result = await db.execute(query)
            platform_common = platform_result.scalar_one_or_none()
            
            # Create new platform listing if needed
            if not platform_common:
                platform_common = PlatformCommon(
                    product_id=product.id,
                    platform_name="ebay",
                    status=ListingStatus.DRAFT.value,
                    sync_status=SyncStatus.PENDING.value,
                    last_sync=datetime.now(timezone.utc)()
                )
                db.add(platform_common)
                await db.flush()
            
            # Map category from our system to eBay category ID
            category_mapping = await mapping_service.get_mapping(
                "internal", 
                str(product.category) if product.category else "default",
                "ebay"
            )
            
            if not category_mapping:
                # Try by name if ID mapping failed
                category_mapping = await mapping_service.get_mapping_by_name(
                    "internal",
                    product.category,
                    "ebay"
                )
            
            if not category_mapping:
                # Use default if no mapping found
                category_mapping = await mapping_service.get_default_mapping("ebay")
                if not category_mapping:
                    results["errors"] += 1
                    results["messages"].append(f"No category mapping found for {product.category}")
                    continue
            
            # Prepare data for eBay listing
            ebay_item_specifics = {
                "Brand": product.brand,
                "Model": product.model,
                "Year": str(product.year) if product.year else "",
                "MPN": product.sku or "Does Not Apply",
                "Type": product.category or "",
                "Condition": product.condition or "Used"
            }
            
            # Add any other product attributes that might be relevant
            if product.finish:
                ebay_item_specifics["Finish"] = product.finish
            
            scope = (
                "musical_instruments"
                if category_mapping.target_id in MUSICAL_INSTRUMENT_CATEGORY_IDS
                else "default"
            )
            condition_id = await condition_mapping_service.get_condition_id(
                PlatformName.EBAY,
                product.condition or ProductCondition.GOOD,
                scope=scope,
                fallbacks=("default",),
            )
            if not condition_id:
                condition_id = "3000"

            # Create eBay listing data
            ebay_data = {
                "category_id": category_mapping.target_id,
                "condition_id": condition_id,
                "price": float(product.base_price) if product.base_price else 0.0,
                "duration": "GTC",  # Good Till Cancelled
                "item_specifics": ebay_item_specifics
            }
            
            # Create eBay listing
            try:
                ebay_listing = await ebay_service.create_draft_listing(
                    platform_common.id,
                    ebay_data
                )
                
                results["success"] += 1
                results["messages"].append(f"Created eBay draft for {product.brand} {product.model}")
                
            except Exception as e:
                platform_common.sync_status = SyncStatus.FAILED.value
                platform_common.last_sync = datetime.now(timezone.utc)()
                
                results["errors"] += 1
                results["messages"].append(f"Error creating eBay draft for {product.brand} {product.model}: {str(e)}")
            
        except Exception as e:
            results["errors"] += 1
            results["messages"].append(f"Error syncing product {product_id} to eBay: {str(e)}")
            import traceback
            print(traceback.format_exc())
    
    await db.commit()
    
    return templates.TemplateResponse(
        "inventory/sync_ebay_results.html",  # You'll need to create this template based on sync_vr_results.html
        {
            "request": request,
            "results": results
        }
    )

@router.get("/api/dropbox/folders", response_class=JSONResponse)
async def get_dropbox_folders(
    request: Request,
    background_tasks: BackgroundTasks,
    path: str = "",
    settings: Settings = Depends(get_settings)
):
    """
    API endpoint to get Dropbox folders for navigation with token refresh support.
    
    This endpoint:
    1. Handles token refresh if needed
    2. Uses the cached folder structure when available
    3. Returns folder and file information for UI navigation
    4. Initializes a background scan if needed
    """
    try:
        # Check if scan is already in progress
        if hasattr(request.app.state, 'dropbox_scan_in_progress') and request.app.state.dropbox_scan_in_progress:
            progress = getattr(request.app.state, 'dropbox_scan_progress', {'status': 'scanning', 'progress': 0})
            return JSONResponse(
                status_code=202,  # Accepted but processing
                content={
                    "status": "processing", 
                    "message": "Dropbox scan in progress", 
                    "progress": progress
                }
            )
        
        # Get credentials
        access_token = getattr(settings, 'DROPBOX_ACCESS_TOKEN', None) or os.environ.get('DROPBOX_ACCESS_TOKEN')
        refresh_token = getattr(settings, 'DROPBOX_REFRESH_TOKEN', None) or os.environ.get('DROPBOX_REFRESH_TOKEN')
        app_key = getattr(settings, 'DROPBOX_APP_KEY', None) or os.environ.get('DROPBOX_APP_KEY')
        app_secret = getattr(settings, 'DROPBOX_APP_SECRET', None) or os.environ.get('DROPBOX_APP_SECRET')
        
        # Direct fallback to environment variables if not in settings
        if not access_token:
            access_token = os.environ.get('DROPBOX_ACCESS_TOKEN')
            print(f"Loading access token directly from environment: {bool(access_token)}")
        
        if not refresh_token:
            refresh_token = os.environ.get('DROPBOX_REFRESH_TOKEN')
            print(f"Loading refresh token directly from environment: {bool(refresh_token)}")
            
        if not app_key:
            app_key = os.environ.get('DROPBOX_APP_KEY')
            print(f"Loading app key directly from environment: {bool(app_key)}")
            
        if not app_secret:
            app_secret = os.environ.get('DROPBOX_APP_SECRET')
            print(f"Loading app secret directly from environment: {bool(app_secret)}")
        
        # Check if all credentials are available now
        if not access_token and not refresh_token:
            return JSONResponse(
                status_code=503,
                content={
                    "status": "error",
                    "message": "Dropbox credentials not available. Please configure DROPBOX_ACCESS_TOKEN or DROPBOX_REFRESH_TOKEN in .env file."
                }
            )

        # Use shared client with token persistence to avoid 401 on every request
        client = await get_dropbox_client(request, settings)

        # Check if we need to initialize a scan
        if (not hasattr(request.app.state, 'dropbox_map') or
            request.app.state.dropbox_map is None):

            # Check if the service has cached folder structure
            logger.info(f"Checking client folder structure: {bool(client.folder_structure)}, entries: {len(client.folder_structure) if client.folder_structure else 0}")
            if client.folder_structure:
                logger.info("Found cached folder structure in service, using it")

                # Also update app state for consistency
                request.app.state.dropbox_map = {
                    'folder_structure': client.folder_structure,
                    'temp_links': {}
                }
                request.app.state.dropbox_last_updated = datetime.now()

                # Use the service's cached data
                folder_contents = await client.get_folder_contents(path)

                # For root path, extract top-level folders from the structure
                if not path:
                    folders = []
                    logger.info(f"Extracting folders from structure with {len(client.folder_structure)} entries")
                    for folder_path, folder_data in client.folder_structure.items():
                        logger.debug(f"Checking {folder_path}: is_dict={isinstance(folder_data, dict)}, starts_with_slash={folder_path.startswith('/')}, slash_count={folder_path.count('/')}")
                        if isinstance(folder_data, dict) and folder_path.startswith('/') and folder_path.count('/') == 1:
                            folder_entry = {
                                'name': folder_path.strip('/'),
                                'path': folder_path,
                                'is_folder': True
                            }
                            folders.append(folder_entry)
                            logger.debug(f"Added folder: {folder_entry}")

                    logger.info(f"Found {len(folders)} folders to return")
                    return JSONResponse(
                        content={
                            "folders": sorted(folders, key=lambda x: x['name'].lower()),
                            "files": [],
                            "current_path": path,
                            "cached": True
                        }
                    )
                else:
                    return JSONResponse(
                        content={
                            "folders": folder_contents.get("folders", []),
                            "files": folder_contents.get("images", []),
                            "current_path": path,
                            "cached": True
                        }
                    )

            # No cache available anywhere
            return JSONResponse(
                content={
                    "folders": [],
                    "files": [],
                    "current_path": path,
                    "message": "No Dropbox data cached. Please use the sync button to load data."
                }
            )

        # Get cached data
        dropbox_map = request.app.state.dropbox_map
        logger.info(f"App state dropbox_map exists: {dropbox_map is not None}, has structure: {'folder_structure' in dropbox_map if dropbox_map else False}")

        # If the token might be expired, verify it
        last_updated = getattr(request.app.state, 'dropbox_last_updated', None)
        token_age_hours = ((datetime.now() - last_updated).total_seconds() / 3600) if last_updated else None
        
        if token_age_hours and token_age_hours > 3:  # Check if token is older than 3 hours
            # Test connection and refresh if needed
            test_result = await client.test_connection()
            if not test_result:
                # Connection failed - token might be expired
                # This function handles refresh internally
                print("Token may be expired, getting fresh folder data")
                
                # Get specific folder contents
                if path:
                    folder_data = await client.get_folder_contents(path)
                    return folder_data
                else:
                    # For root, just list top-level folders
                    entries = await client.list_folder_recursive(path="", max_depth=1)
                    folders = []
                    for entry in entries:
                        if entry.get('.tag') == 'folder':
                            folder_path = entry.get('path_lower', '')
                            folder_name = os.path.basename(folder_path)
                            folders.append({
                                'name': folder_name,
                                'path': folder_path,
                                'is_folder': True
                            })
                    return {"folders": sorted(folders, key=lambda x: x['name'])}
            
        # If we get here, we can use the cached structure
        folder_structure = dropbox_map['folder_structure']
        
        # If first request, return top-level folders
        if not path:
            # Return top-level folders
            folders = []
            for folder_name, folder_data in folder_structure.items():
                if isinstance(folder_data, dict) and folder_name.startswith('/'):
                    folders.append({
                        'name': folder_name.strip('/'),
                        'path': folder_name,
                        'is_folder': True
                    })
            
            return {"folders": sorted(folders, key=lambda x: x['name'].lower())}
        else:
            # Navigate to the requested path
            current_level = folder_structure
            current_path = ""
            path_parts = path.strip('/').split('/')
            
            for part in path_parts:
                if part:
                    current_path = f"/{part}" if current_path == "" else f"{current_path}/{part}"
                    if current_path in current_level:
                        current_level = current_level[current_path]
                    else:
                        # Path not found
                        return {"items": [], "current_path": path, "error": f"Path {path} not found"}
            
            # Get folders and files at this level
            items = []
            
            # Process each key in the current level
            for key, value in current_level.items():
                # Skip non-string keys or special keys
                if not isinstance(key, str):
                    continue
                
                if key.startswith('/'):
                    # This is a subfolder
                    name = os.path.basename(key)
                    items.append({
                        'name': name,
                        'path': key,
                        'is_folder': True
                    })
                elif key == 'files' and isinstance(value, list):
                    # This is the files list
                    for file in value:
                        if not isinstance(file, dict) or 'path' not in file:
                            continue
                            
                        # Only include image files
                        if any(file['path'].lower().endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif']):
                            # Get temp link from the map if available
                            temp_link = None
                            if 'temp_links' in dropbox_map and file['path'] in dropbox_map['temp_links']:
                                temp_link = dropbox_map['temp_links'][file['path']]
                            
                            items.append({
                                'name': file.get('name', os.path.basename(file['path'])),
                                'path': file['path'],
                                'is_folder': False,
                                'temp_link': temp_link
                            })
            
            # Sort items (folders first, then files)
            items.sort(key=lambda x: (not x['is_folder'], x['name'].lower()))
            
            return {"items": items, "current_path": path}
            
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return JSONResponse(
            status_code=500,
            content={"error": f"Error accessing Dropbox: {str(e)}"}
        )

@router.get("/api/dropbox/images", response_class=JSONResponse)
async def get_dropbox_images(
    request: Request,
    folder_path: str
):
    """
    API endpoint to get images from a Dropbox folder.
    
    This function uses two approaches to find images:
    1. First it directly searches for images in the temp_links cache with matching paths
    2. Then it tries to navigate the folder structure if no direct matches are found
    
    Args:
        request: The FastAPI request object
        folder_path: The Dropbox folder path to get images from
        
    Returns:
        JSON response with list of images and their temporary links
    """
    try:
        # Check for cached structure
        dropbox_map = getattr(request.app.state, 'dropbox_map', None)
        if not dropbox_map:
            return {"images": [], "error": "No Dropbox cache found. Please refresh the page."}
        
        # Normalize the folder path for consistent comparisons
        normalized_folder_path = folder_path.lower().rstrip('/')
        
        # APPROACH 1: First directly look in temp_links for images in this folder
        images = []
        temp_links = dropbox_map.get('temp_links', {})
        
        # Search for images directly in the requested folder
        for path, link_data in temp_links.items():
            path_lower = path.lower()

            # Match files directly in this folder (not in subfolders)
            folder_part = os.path.dirname(path_lower)

            if folder_part == normalized_folder_path:
                if any(path_lower.endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif']):
                    # Handle new format with thumbnail and full URLs
                    if isinstance(link_data, dict):
                        images.append({
                            'name': os.path.basename(path),
                            'path': path,
                            'url': link_data.get('thumbnail', link_data.get('full')),  # Use thumbnail for display
                            'full_url': link_data.get('full'),  # Include full URL for when image is selected
                            'thumbnail_url': link_data.get('thumbnail')
                        })
                    else:
                        # Old format compatibility
                        images.append({
                            'name': os.path.basename(path),
                            'path': path,
                            'url': link_data,
                            'full_url': link_data,
                            'thumbnail_url': link_data
                        })
        
        # If images found directly, return them
        if images:
            print(f"Found {len(images)} images directly in folder {folder_path}")
            # Sort images by name for consistent ordering
            images.sort(key=lambda x: x.get('name', ''))
            return {"images": images}
            
        # APPROACH 2: If no images found directly, try navigating the folder structure
        folder_structure = dropbox_map.get('folder_structure', {})
        path_parts = folder_path.strip('/').split('/')
        current = folder_structure
        current_path = ""
        
        # Navigate to the folder
        for part in path_parts:
            if part:
                current_path = f"/{part}" if current_path == "" else f"{current_path}/{part}"
                if current_path in current:
                    current = current[current_path]
                else:
                    # Try a more flexible path search in temp_links as a fallback
                    fallback_images = []
                    search_prefix = f"{normalized_folder_path}/"
                    
                    for path, link_data in temp_links.items():
                        if path.lower().startswith(search_prefix) and any(path.lower().endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif']):
                            # Handle new format with thumbnail and full URLs
                            if isinstance(link_data, dict):
                                fallback_images.append({
                                    'name': os.path.basename(path),
                                    'path': path,
                                    'url': link_data.get('thumbnail', link_data.get('full')),
                                    'full_url': link_data.get('full'),
                                    'thumbnail_url': link_data.get('thumbnail')
                                })
                            else:
                                # Old format compatibility
                                fallback_images.append({
                                    'name': os.path.basename(path),
                                    'path': path,
                                    'url': link_data,
                                    'full_url': link_data,
                                    'thumbnail_url': link_data
                                })
                    
                    if fallback_images:
                        print(f"Found {len(fallback_images)} images using fallback search for {folder_path}")
                        fallback_images.sort(key=lambda x: x.get('name', ''))
                        return {"images": fallback_images}
                    
                    # If no fallback images found either, return empty list
                    print(f"Folder {folder_path} not found in structure")
                    return {"images": [], "error": f"Folder {folder_path} not found"}
        
        # Extract images from specified folder using recursive helper function
        def extract_images_from_folder(folder_data, prefix=""):
            result = []
            
            # Check if folder contains files array
            if isinstance(folder_data, dict) and 'files' in folder_data and isinstance(folder_data['files'], list):
                for file in folder_data['files']:
                    if (file.get('path') and any(file['path'].lower().endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif'])):
                        # Get temp link from the map
                        temp_link = None
                        if 'temp_links' in dropbox_map and file['path'] in dropbox_map['temp_links']:
                            temp_link = dropbox_map['temp_links'][file['path']]
                            
                        if temp_link:
                            # Handle both old format (string URL) and new format (dict with thumbnail/full)
                            if isinstance(temp_link, dict):
                                result.append({
                                    'name': file.get('name', os.path.basename(file['path'])),
                                    'path': file['path'],
                                    'thumbnail_url': temp_link.get('thumbnail'),
                                    'url': temp_link.get('full') or temp_link.get('thumbnail'),  # Full may be None (lazy fetch)
                                })
                            else:
                                # Legacy string format
                                result.append({
                                    'name': file.get('name', os.path.basename(file['path'])),
                                    'path': file['path'],
                                    'thumbnail_url': temp_link,
                                    'url': temp_link
                                })
            
            # Look through subfolders with a priority for specific resolution folders
            resolution_folders = []
            other_folders = []
            
            for key, value in folder_data.items():
                if isinstance(key, str) and key.startswith('/') and isinstance(value, dict):
                    folder_name = os.path.basename(key.rstrip('/'))
                    # Prioritize resolution folders
                    if any(res in folder_name.lower() for res in ['1500px', 'hi-res', '640px']):
                        resolution_folders.append((key, value))
                    else:
                        other_folders.append((key, value))
            
            # Check resolution folders first
            for key, subfolder in resolution_folders:
                result.extend(extract_images_from_folder(subfolder, f"{prefix}{os.path.basename(key)}/"))
            
            # If no images found in resolution folders, check other folders
            if not result and other_folders:
                for key, subfolder in other_folders:
                    result.extend(extract_images_from_folder(subfolder, f"{prefix}{os.path.basename(key)}/"))
            
            return result
        
        # Extract images from the current folder and its subfolders
        images = extract_images_from_folder(current)
        
        # APPROACH 3: Final fallback - if still no images found, search entire temp_links
        if not images and 'temp_links' in dropbox_map:
            search_prefix = f"{normalized_folder_path}/"

            for path, link in dropbox_map['temp_links'].items():
                path_lower = path.lower()
                if path_lower.startswith(search_prefix) and any(path_lower.endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif']):
                    # Handle both old format (string URL) and new format (dict with thumbnail/full)
                    if isinstance(link, dict):
                        images.append({
                            'name': os.path.basename(path),
                            'path': path,
                            'thumbnail_url': link.get('thumbnail'),
                            'url': link.get('full') or link.get('thumbnail'),
                        })
                    else:
                        images.append({
                            'name': os.path.basename(path),
                            'path': path,
                            'thumbnail_url': link,
                            'url': link
                        })
        
        # Sort images by name for consistent ordering
        images.sort(key=lambda x: x.get('name', ''))
        
        print(f"Found {len(images)} images in folder {folder_path}")
        return {"images": images}
        
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return JSONResponse(
            status_code=500,
            content={"error": f"Error getting Dropbox images: {str(e)}"}
        )

@router.get("/api/dropbox/init", response_class=JSONResponse)
async def init_dropbox_scan(
    request: Request,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings)
):
    """Initialize Dropbox scan in the background and report progress"""
    
    # Check if already scanning
    if hasattr(request.app.state, 'dropbox_scan_in_progress') and request.app.state.dropbox_scan_in_progress:
        # Get progress if available
        progress = getattr(request.app.state, 'dropbox_scan_progress', {'status': 'scanning', 'progress': 0})
        return JSONResponse(content=progress)
    
    # Check if already scanned
    if hasattr(request.app.state, 'dropbox_map') and request.app.state.dropbox_map:
        return JSONResponse(content={
            'status': 'complete', 
            'last_updated': request.app.state.dropbox_last_updated.isoformat()
        })
    
    # Start scan in background
    request.app.state.dropbox_scan_in_progress = True
    request.app.state.dropbox_scan_progress = {'status': 'starting', 'progress': 0}
    
    background_tasks.add_task(perform_dropbox_scan, request.app, settings.DROPBOX_ACCESS_TOKEN)
    
    return JSONResponse(content={
        'status': 'started',
        'message': 'Dropbox scan initiated in background'
    })

@router.get("/api/dropbox/debug-scan")
async def debug_dropbox_scan(
    request: Request,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings)
):
    """Debug endpoint to trigger Dropbox scan"""
    # Reset scan state
    request.app.state.dropbox_scan_in_progress = False
    
    # Check token
    token = settings.DROPBOX_ACCESS_TOKEN
    if not token:
        return {"status": "error", "message": "No Dropbox access token configured"}
    
    # Start scan
    print(f"Manually starting Dropbox scan with token (length: {len(token)})")
    request.app.state.dropbox_scan_in_progress = True
    request.app.state.dropbox_scan_progress = {'status': 'starting', 'progress': 0}
    
    # Add to background tasks
    background_tasks.add_task(perform_dropbox_scan, request.app, token)
    
    return {
        "status": "started", 
        "message": "Dropbox scan initiated in background", 
        "token_available": bool(token)
    }

@router.get("/api/dropbox/debug-token")
async def debug_dropbox_token(
    request: Request,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings)
):
    """Debug endpoint to check Dropbox tokens and refresh if needed"""
    try:
        # Get tokens from settings and environment
        access_token = getattr(settings, 'DROPBOX_ACCESS_TOKEN', None) or os.environ.get('DROPBOX_ACCESS_TOKEN')
        refresh_token = getattr(settings, 'DROPBOX_REFRESH_TOKEN', None) or os.environ.get('DROPBOX_REFRESH_TOKEN')
        app_key = getattr(settings, 'DROPBOX_APP_KEY', None) or os.environ.get('DROPBOX_APP_KEY')
        app_secret = getattr(settings, 'DROPBOX_APP_SECRET', None) or os.environ.get('DROPBOX_APP_SECRET')
        
        # Create detailed response with token info
        response = {
            "access_token": {
                "available": bool(access_token),
                "preview": f"{access_token[:5]}...{access_token[-5:]}" if access_token and len(access_token) > 10 else None,
                "length": len(access_token) if access_token else 0,
                "source": "settings" if hasattr(settings, 'DROPBOX_ACCESS_TOKEN') and settings.DROPBOX_ACCESS_TOKEN else "environment" if access_token else None
            },
            "refresh_token": {
                "available": bool(refresh_token),
                "preview": f"{refresh_token[:5]}...{refresh_token[-5:]}" if refresh_token and len(refresh_token) > 10 else None,
                "length": len(refresh_token) if refresh_token else 0,
                "source": "settings" if hasattr(settings, 'DROPBOX_REFRESH_TOKEN') and settings.DROPBOX_REFRESH_TOKEN else "environment" if refresh_token else None
            },
            "app_credentials": {
                "app_key_available": bool(app_key),
                "app_secret_available": bool(app_secret),
                "source": "settings" if hasattr(settings, 'DROPBOX_APP_KEY') and settings.DROPBOX_APP_KEY else "environment" if app_key else None
            }
        }
        
        # Test current access token if available
        if access_token:
            from app.services.dropbox.dropbox_async_service import AsyncDropboxClient
            client = AsyncDropboxClient(access_token=access_token)
            test_result = await client.test_connection()
            response["token_status"] = "valid" if test_result else "invalid"
        else:
            response["token_status"] = "missing"
        
        # Try to refresh token if invalid and we have refresh credentials
        if (response["token_status"] in ["invalid", "missing"] and 
            refresh_token and app_key and app_secret):
            
            print("Attempting to refresh token...")
            from app.services.dropbox.dropbox_async_service import AsyncDropboxClient
            refresh_client = AsyncDropboxClient(
                refresh_token=refresh_token,
                app_key=app_key,
                app_secret=app_secret
            )
            
            refresh_success = await refresh_client.refresh_access_token()
            
            if refresh_success:
                # We got a new token
                new_token = refresh_client.access_token
                
                # Save it to use in future requests
                if hasattr(request.app.state, 'settings'):
                    request.app.state.settings.DROPBOX_ACCESS_TOKEN = new_token
                
                # Update environment variable
                os.environ["DROPBOX_ACCESS_TOKEN"] = new_token
                
                # Start background scan with new token
                request.app.state.dropbox_scan_in_progress = True
                request.app.state.dropbox_scan_progress = {'status': 'starting', 'progress': 0}
                background_tasks.add_task(perform_dropbox_scan, request.app, new_token)
                
                response["refresh_result"] = {
                    "success": True,
                    "new_token_preview": f"{new_token[:5]}...{new_token[-5:]}",
                    "new_token_length": len(new_token),
                    "scan_initiated": True
                }
            else:
                response["refresh_result"] = {
                    "success": False,
                    "error": "Failed to refresh token"
                }
        
        return response
    except Exception as e:
        import traceback
        print(f"Debug token error: {str(e)}")
        print(traceback.format_exc())
        return {
            "status": "error",
            "error": str(e),
            "error_type": type(e).__name__
        }

@router.get("/api/dropbox/direct-scan")
async def direct_dropbox_scan(
    request: Request,
    settings: Settings = Depends(get_settings)
):
    """
    Direct scan endpoint for debugging - attempts to scan a folder directly
    without using background tasks for immediate feedback
    """
    try:
        from app.services.dropbox.dropbox_async_service import AsyncDropboxClient
        
        # Get tokens from settings and environment
        access_token = getattr(settings, 'DROPBOX_ACCESS_TOKEN', None) or os.environ.get('DROPBOX_ACCESS_TOKEN')
        refresh_token = getattr(settings, 'DROPBOX_REFRESH_TOKEN', None) or os.environ.get('DROPBOX_REFRESH_TOKEN')
        app_key = getattr(settings, 'DROPBOX_APP_KEY', None) or os.environ.get('DROPBOX_APP_KEY')
        app_secret = getattr(settings, 'DROPBOX_APP_SECRET', None) or os.environ.get('DROPBOX_APP_SECRET')
        
        if not access_token and not refresh_token:
            return {
                "status": "error", 
                "message": "No Dropbox access token or refresh token configured"
            }
            
        # Create the client with all credentials
        client = AsyncDropboxClient(
            access_token=access_token,
            refresh_token=refresh_token,
            app_key=app_key,
            app_secret=app_secret
        )
        
        # Try to refresh token if we have refresh credentials but no access token
        if refresh_token and app_key and app_secret and not access_token:
            print("Attempting to refresh token before direct scan...")
            refresh_success = await client.refresh_access_token()
            if refresh_success:
                # We got a new token
                access_token = client.access_token
                # Update in app state if settings exist
                if hasattr(request.app.state, 'settings'):
                    request.app.state.settings.DROPBOX_ACCESS_TOKEN = access_token
                # Update in environment
                os.environ['DROPBOX_ACCESS_TOKEN'] = access_token
                print("Successfully refreshed access token for direct scan")
            else:
                return {
                    "status": "error",
                    "message": "Failed to refresh access token"
                }
        
        # Test connection first
        test_result = await client.test_connection()
        if not test_result:
            return {
                "status": "error", 
                "message": "Failed to connect to Dropbox API - invalid token"
            }
            
        # Start scan of top-level folders for quick test
        print("Starting direct scan of top-level folders...")
        
        # Just list top folders with max_depth=1 for quicker results
        entries = await client.list_folder_recursive(path="", max_depth=1)
        
        # Collect folder information
        folders = []
        files = []
        
        for entry in entries:
            entry_type = entry.get('.tag', '')
            path = entry.get('path_lower', '')
            name = os.path.basename(path)
            
            if entry_type == 'folder':
                folders.append({
                    "name": name, 
                    "path": path
                })
            elif entry_type == 'file' and client._is_image_file(path):
                files.append({
                    "name": name, 
                    "path": path,
                    "size": entry.get('size', 0),
                })
        
        # Get a sample of temp links for quick testing (max 5 files)
        sample_files = files[:5]
        temp_links = {}
        
        if sample_files:
            sample_paths = [f['path'] for f in sample_files]
            temp_links = await client.get_temporary_links_async(sample_paths)
        
        return {
            "status": "success", 
            "message": f"Directly scanned {len(folders)} top-level folders and {len(files)} files", 
            "folders": folders[:10],  # Limit to first 10
            "files": files[:10],      # Limit to first 10
            "temp_links_sample": len(temp_links),
            "token_refreshed": access_token != getattr(settings, 'DROPBOX_ACCESS_TOKEN', None)
        }
        
    except Exception as e:
        import traceback
        traceback_str = traceback.format_exc()
        print(f"Error in direct scan: {str(e)}")
        print(traceback_str)
        return {
            "status": "error", 
            "message": f"Error in direct scan: {str(e)}",
            "traceback": traceback_str.split("\n")[-10:] if len(traceback_str) > 0 else []
        }

@router.get("/api/dropbox/sync-status")
async def get_dropbox_sync_status(request: Request):
    """Get current Dropbox sync status and statistics"""
    try:
        from app.services.dropbox.scheduled_sync import DropboxSyncScheduler
        
        if not hasattr(request.app.state, 'dropbox_scheduler'):
            request.app.state.dropbox_scheduler = DropboxSyncScheduler(request.app.state)
        
        scheduler = request.app.state.dropbox_scheduler
        return scheduler.get_sync_status()
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.post("/api/dropbox/sync-now")
async def trigger_dropbox_sync(
    request: Request,
    force: bool = False,
    background_tasks: BackgroundTasks = None
):
    """Manually trigger a Dropbox sync"""
    try:
        from app.services.dropbox.scheduled_sync import DropboxSyncScheduler
        
        if not hasattr(request.app.state, 'dropbox_scheduler'):
            request.app.state.dropbox_scheduler = DropboxSyncScheduler(request.app.state)
        
        scheduler = request.app.state.dropbox_scheduler
        
        # Run sync in background
        if background_tasks:
            background_tasks.add_task(scheduler.full_sync, force=force)
            return {
                "status": "started",
                "message": "Sync started in background"
            }
        else:
            # Run sync directly
            result = await scheduler.full_sync(force=force)
            return result
            
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.get("/api/dropbox/refresh-token")
async def force_refresh_dropbox_token(
    request: Request,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings)
):
    """Force refresh of the Dropbox access token using refresh token"""
    try:
        # Get refresh credentials
        refresh_token = getattr(settings, 'DROPBOX_REFRESH_TOKEN', None) or os.environ.get('DROPBOX_REFRESH_TOKEN')
        app_key = getattr(settings, 'DROPBOX_APP_KEY', None) or os.environ.get('DROPBOX_APP_KEY')
        app_secret = getattr(settings, 'DROPBOX_APP_SECRET', None) or os.environ.get('DROPBOX_APP_SECRET')
        
        if not refresh_token or not app_key or not app_secret:
            return {
                "status": "error",
                "message": "Missing required refresh credentials",
                "refresh_token_available": bool(refresh_token),
                "app_key_available": bool(app_key),
                "app_secret_available": bool(app_secret)
            }
        
        # Create client for token refresh
        from app.services.dropbox.dropbox_async_service import AsyncDropboxClient
        client = AsyncDropboxClient(
            refresh_token=refresh_token,
            app_key=app_key,
            app_secret=app_secret
        )
        
        # Attempt to refresh the token
        print("Forcing Dropbox token refresh...")
        refresh_success = await client.refresh_access_token()
        
        if refresh_success:
            # We got a new token
            new_token = client.access_token
            
            # Update in app state if settings exist
            if hasattr(request.app.state, 'settings'):
                request.app.state.settings.DROPBOX_ACCESS_TOKEN = new_token
            
            # Update in environment
            os.environ['DROPBOX_ACCESS_TOKEN'] = new_token
            
            # Start background scan with new token if requested
            start_scan = request.query_params.get('start_scan', 'false').lower() == 'true'
            if start_scan:
                request.app.state.dropbox_scan_in_progress = True
                request.app.state.dropbox_scan_progress = {'status': 'starting', 'progress': 0}
                background_tasks.add_task(perform_dropbox_scan, request.app, new_token)
                
            return {
                "status": "success",
                "message": "Successfully refreshed access token",
                "new_token_preview": f"{new_token[:5]}...{new_token[-5:]}",
                "new_token_length": len(new_token),
                "scan_initiated": start_scan
            }
        else:
            return {
                "status": "error",
                "message": "Failed to refresh access token",
                "refresh_token_preview": f"{refresh_token[:5]}...{refresh_token[-5:]}" if len(refresh_token) > 10 else None
            }
    
    except Exception as e:
        import traceback
        print(f"Error in token refresh: {str(e)}")
        print(traceback.format_exc())
        return {
            "status": "error",
            "message": f"Exception during token refresh: {str(e)}",
            "error_type": type(e).__name__
        }

@router.get("/api/dropbox/test-credentials", response_class=JSONResponse)
async def test_dropbox_credentials(
    settings: Settings = Depends(get_settings)
):
    """Test that Dropbox credentials are being loaded correctly"""
    return {
        "app_key_available": bool(settings.DROPBOX_APP_KEY),
        "app_secret_available": bool(settings.DROPBOX_APP_SECRET),
        "refresh_token_available": bool(settings.DROPBOX_REFRESH_TOKEN),
        "access_token_available": bool(settings.DROPBOX_ACCESS_TOKEN),
        "app_key_preview": settings.DROPBOX_APP_KEY[:5] + "..." if settings.DROPBOX_APP_KEY else None,
        "refresh_token_preview": settings.DROPBOX_REFRESH_TOKEN[:5] + "..." if settings.DROPBOX_REFRESH_TOKEN else None
    }

@router.get("/api/dropbox/debug-cache")
async def debug_dropbox_cache(request: Request):
    """Debug endpoint to see what's in the Dropbox cache"""
    dropbox_map = getattr(request.app.state, 'dropbox_map', None)
    
    if not dropbox_map:
        return {"status": "no_cache", "message": "No Dropbox cache found"}
    
    # Count temporary links
    temp_links_count = len(dropbox_map.get('temp_links', {}))
    
    # Get some sample paths with temporary links
    sample_links = {}
    for i, (path, link) in enumerate(dropbox_map.get('temp_links', {}).items()):
        if i >= 5:  # Just get 5 samples
            break
        sample_links[path] = link[:50] + "..." if link else None
    
    return {
        "status": "ok",
        "last_updated": getattr(request.app.state, 'dropbox_last_updated', None),
        "has_folder_structure": "folder_structure" in dropbox_map,
        "temp_links_count": temp_links_count,
        "sample_links": sample_links,
        "sample_folder_paths": list(dropbox_map.get('folder_structure', {}).keys())[:5]
    }

@router.get("/api/dropbox/debug-credentials")
async def debug_dropbox_credentials(
    settings: Settings = Depends(get_settings)
):
    """Debug endpoint to check how credentials are loaded"""
    
    # Check settings first
    settings_creds = {
        "settings_access_token": bool(getattr(settings, 'DROPBOX_ACCESS_TOKEN', None)),
        "settings_refresh_token": bool(getattr(settings, 'DROPBOX_REFRESH_TOKEN', None)),
        "settings_app_key": bool(getattr(settings, 'DROPBOX_APP_KEY', None)),
        "settings_app_secret": bool(getattr(settings, 'DROPBOX_APP_SECRET', None))
    }
    
    # Check environment variables directly
    env_creds = {
        "env_access_token": bool(os.environ.get('DROPBOX_ACCESS_TOKEN')),
        "env_refresh_token": bool(os.environ.get('DROPBOX_REFRESH_TOKEN')),
        "env_app_key": bool(os.environ.get('DROPBOX_APP_KEY')),
        "env_app_secret": bool(os.environ.get('DROPBOX_APP_SECRET'))
    }
    
    # Sample values (first 5 chars only)
    samples = {
        "access_token_sample": os.environ.get('DROPBOX_ACCESS_TOKEN', '')[:5] + "..." if os.environ.get('DROPBOX_ACCESS_TOKEN') else None,
        "refresh_token_sample": os.environ.get('DROPBOX_REFRESH_TOKEN', '')[:5] + "..." if os.environ.get('DROPBOX_REFRESH_TOKEN') else None
    }
    
    return {
        "settings_loaded": settings_creds,
        "environment_loaded": env_creds,
        "samples": samples
    }

@router.get("/api/dropbox/debug-folder-images")
async def debug_folder_images(
    request: Request,
    folder_path: str
):
    """Debug endpoint to check what images exist for a specific folder"""
    dropbox_map = getattr(request.app.state, 'dropbox_map', None)
    
    if not dropbox_map:
        return {"status": "no_cache", "message": "No Dropbox cache found"}
    
    # Count all temporary links
    all_temp_links = dropbox_map.get('temp_links', {})
    
    # Find images in this folder from temp_links
    folder_images = []
    for path, link in all_temp_links.items():
        normalized_path = path.lower()
        normalized_folder = folder_path.lower()
        
        # Check if this path is in the requested folder
        if normalized_path.startswith(normalized_folder + '/') or normalized_path == normalized_folder:
            if any(path.lower().endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif']):
                folder_images.append({
                    'path': path,
                    'link': link[:50] + "..." if link else None
                })
    
    # Get folder structure info
    folder_structure = dropbox_map.get('folder_structure', {})
    current = folder_structure
    
    # Try to navigate to the folder (if it exists in structure)
    path_parts = folder_path.strip('/').split('/')
    current_path = ""
    for part in path_parts:
        if not part:
            continue
        current_path = f"/{part}" if current_path == "" else f"{current_path}/{part}"
        if current_path in current:
            current = current[current_path]
        else:
            current = None
            break
    
    return {
        "status": "ok",
        "folder_path": folder_path,
        "folder_exists_in_structure": current is not None,
        "folder_structure_details": current if isinstance(current, dict) and len(str(current)) < 1000 else "(too large to display)",
        "images_found_in_temp_links": len(folder_images),
        "sample_images": folder_images[:5]
    }

@router.get("/api/dropbox/generate-links", response_class=JSONResponse)
async def generate_folder_links(
    request: Request,
    folder_path: str,
    settings: Settings = Depends(get_settings)
):
    """
    Generate thumbnails for all images in a specific folder.

    Uses the Dropbox thumbnail API to fetch small base64 thumbnails (~12KB each)
    instead of full temporary links. This is MUCH faster and uses less bandwidth.
    Full-res links are fetched on-demand when user selects an image.
    """
    try:
        # Use shared client with token persistence
        client = await get_dropbox_client(request, settings)

        # Get the folder structure from cache if available
        dropbox_map = getattr(request.app.state, 'dropbox_map', None)
        if not dropbox_map:
            return {"status": "error", "message": "No Dropbox cache available"}

        # First, list the folder to get image paths
        import aiohttp
        async with aiohttp.ClientSession() as session:
            # List folder contents
            entries = await client.list_folder(folder_path)

            # Filter for images
            image_paths = []
            for entry in entries:
                if entry.get('.tag') == 'file':
                    path = entry.get('path_lower', '')
                    if any(path.endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif']):
                        image_paths.append(path)

            print(f"Found {len(image_paths)} images in folder {folder_path}")

            if not image_paths:
                return {
                    "status": "success",
                    "message": "No images found in folder",
                    "images": []
                }

            # Get thumbnails for all images (FAST - ~12KB each vs ~600KB for full-res)
            # Run ALL thumbnail fetches in parallel for speed
            thumbnails = {}

            # Create all tasks at once
            tasks = [client.get_image_links_with_thumbnails(session, path) for path in image_paths]

            # Run all in parallel (Dropbox API can handle concurrent requests)
            print(f"Fetching {len(tasks)} thumbnails in parallel...")
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for result in results:
                if isinstance(result, Exception):
                    continue  # Skip failed fetches
                path, links = result
                if links.get('thumbnail'):
                    thumbnails[path] = links

            print(f"Generated {len(thumbnails)} thumbnails for folder {folder_path}")

            # Update the cache with thumbnails
            if dropbox_map and 'temp_links' in dropbox_map:
                dropbox_map['temp_links'].update(thumbnails)
                print(f"Updated cache with {len(thumbnails)} thumbnails")

            # Return images with thumbnail data URLs for UI
            images = []
            for path, links in thumbnails.items():
                images.append({
                    'name': os.path.basename(path),
                    'path': path,
                    'url': links.get('thumbnail'),  # Base64 data URL for display
                    'thumbnail_url': links.get('thumbnail'),
                    'full_url': None  # Will be fetched on-demand
                })

            return {
                "status": "success",
                "message": f"Generated {len(thumbnails)} thumbnails",
                "images": images
            }

    except Exception as e:
        import traceback
        print(f"Error generating thumbnails: {str(e)}")
        print(traceback.format_exc())
        return {
            "status": "error",
            "message": f"Error generating thumbnails: {str(e)}"
        }


@router.get("/api/dropbox/full-res-link", response_class=JSONResponse)
async def get_dropbox_full_res_link(
    request: Request,
    file_path: str,
    settings: Settings = Depends(get_settings)
):
    """
    Get a full-resolution temporary link for a single image.
    Called on-demand when user selects/clicks an image.

    This is the "lazy fetch" approach - thumbnails are shown in browser,
    full-res is only fetched when actually needed.
    """
    try:
        # Use shared client with token persistence
        client = await get_dropbox_client(request, settings)

        # Get full-res link for this specific file
        full_link = await client.get_full_res_link(file_path)

        if full_link:
            return {
                "status": "success",
                "path": file_path,
                "url": full_link
            }
        else:
            return {
                "status": "error",
                "message": f"Could not get link for {file_path}"
            }

    except Exception as e:
        import traceback
        logger.error(f"Error getting full-res link: {str(e)}")
        logger.error(traceback.format_exc())
        return {
            "status": "error",
            "message": f"Error: {str(e)}"
        }


@router.get("/shipping-profiles")
async def get_shipping_profiles(
    db: AsyncSession = Depends(get_db)
):
    """Get all shipping profiles."""
    from app.models.shipping import ShippingProfile
    
    profiles = await db.execute(select(ShippingProfile).order_by(ShippingProfile.name))
    result = profiles.scalars().all()
    
    # Convert to dict for JSON response compatible with your frontend
    return [
        {
            "id": profile.id,
            "reverb_profile_id": profile.reverb_profile_id,
            "ebay_profile_id": profile.ebay_profile_id,
            "name": profile.name,
            "display_name": f"{profile.name} ({profile.reverb_profile_id})" if profile.reverb_profile_id else profile.name,
            "description": profile.description,
            "package_type": profile.package_type,
            "dimensions": profile.dimensions,  # Return dimensions as JSONB 
            "weight": profile.weight,
            "carriers": profile.carriers,
            "options": profile.options,
            "rates": profile.rates,
            "is_default": profile.is_default
        }
        for profile in result
    ]

@router.get("/platform-categories/{platform}")
async def get_platform_categories(
    platform: str,
    db: AsyncSession = Depends(get_db)
):
    """Get all available categories for a specific platform."""
    from sqlalchemy import text
    
    if platform == "ebay":
        # Get eBay categories from mappings table
        query = text("""
            SELECT DISTINCT target_category_id, target_category_name
            FROM platform_category_mappings
            WHERE target_platform = 'ebay'
            AND target_category_id IS NOT NULL
            ORDER BY target_category_name
        """)
        
        result = await db.execute(query)
        categories = [
            {"id": row[0], "name": row[1]}
            for row in result.fetchall()
        ]
        
    elif platform == "shopify":
        # Get Shopify categories from mappings table
        query = text("""
            SELECT DISTINCT shopify_gid, merchant_type, target_category_name
            FROM platform_category_mappings
            WHERE target_platform = 'shopify'
            AND shopify_gid IS NOT NULL
            ORDER BY merchant_type
        """)
        
        result = await db.execute(query)
        categories = [
            {
                "id": row[0],
                "name": row[1] or row[2] or row[0],  # prefer merchant_type, fallback to full name or gid
                "full_name": row[2] or row[1] or row[0],
            }
            for row in result.fetchall()
        ]
        
    elif platform == "vr":
        # Load V&R category names
        import json
        from pathlib import Path
        vr_names_file = Path(__file__).parent.parent.parent / "scripts" / "mapping_work" / "vr_category_map.json"
        vr_names = {}
        if vr_names_file.exists():
            with open(vr_names_file, 'r') as f:
                vr_names = json.load(f)
        
        # Get V&R categories - need to build hierarchy
        query = text("""
            SELECT DISTINCT 
                vr_category_id,
                vr_subcategory_id,
                vr_sub_subcategory_id,
                vr_sub_sub_subcategory_id
            FROM platform_category_mappings
            WHERE target_platform = 'vintageandrare'
            AND vr_category_id IS NOT NULL
            ORDER BY vr_category_id, vr_subcategory_id
        """)
        
        result = await db.execute(query)
        categories = []
        for row in result.fetchall():
            # Build the ID path and name
            id_parts = [str(row[0])]
            name_parts = []
            
            # Get category name
            if str(row[0]) in vr_names:
                name_parts.append(vr_names[str(row[0])].get('name', f'Category {row[0]}'))
                
                # Get subcategory name
                if row[1] and str(row[1]) in vr_names[str(row[0])].get('subcategories', {}):
                    id_parts.append(str(row[1]))
                    name_parts.append(vr_names[str(row[0])]['subcategories'][str(row[1])].get('name', f'Subcategory {row[1]}'))
                    
                    # Get sub-subcategory name if exists
                    if row[2] and str(row[2]) in vr_names[str(row[0])]['subcategories'][str(row[1])].get('subcategories', {}):
                        id_parts.append(str(row[2]))
                        name_parts.append(vr_names[str(row[0])]['subcategories'][str(row[1])]['subcategories'][str(row[2])].get('name', f'Sub-subcategory {row[2]}'))
                elif row[1]:
                    id_parts.append(str(row[1]))
                    name_parts.append(f'Subcategory {row[1]}')
            else:
                name_parts.append(f'Category {row[0]}')
                if row[1]:
                    id_parts.append(str(row[1]))
                    name_parts.append(f'Subcategory {row[1]}')
            
            categories.append({
                "id": "/".join(id_parts),
                "name": " > ".join(name_parts) if name_parts else f"Category {'/'.join(id_parts)}"
            })
    else:
        return {"error": f"Unknown platform: {platform}"}
    
    return {"categories": categories}

@router.get("/category-search")
async def search_reverb_categories(
    q: str = Query("", min_length=1, description="Search term for Reverb categories"),
    limit: int = Query(20, ge=1, le=100, description="Maximum number of categories to return"),
    db: AsyncSession = Depends(get_db),
):
    term = (q or "").strip()
    if not term:
        return {"categories": []}

    pattern = f"%{term}%"

    stmt = (
        select(ReverbCategory.uuid, ReverbCategory.name, ReverbCategory.full_path)
        .where(
            or_(
                ReverbCategory.full_path.ilike(pattern),
                ReverbCategory.name.ilike(pattern),
            )
        )
        .order_by(func.length(ReverbCategory.full_path), ReverbCategory.full_path)
        .limit(limit)
    )

    result = await db.execute(stmt)
    rows = result.all()

    categories = [
        {
            "uuid": uuid,
            "name": name,
            "full_path": full_path or name,
        }
        for uuid, name, full_path in rows
        if (full_path or name)
    ]

    return {"categories": categories}


@router.get("/category-mappings/{reverb_category:path}")
async def get_category_mappings(
    reverb_category: str,
    sku: Optional[str] = None,
    uuid: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """
    Get platform category mappings for a Reverb category.
    
    Can be called with either:
    1. A category name (legacy support)
    2. A SKU parameter to look up the UUID from reverb_listings
    """
    from sqlalchemy import text
    
    # URL decode the category name
    from urllib.parse import unquote
    reverb_category = unquote(reverb_category)
    
    print(f"Looking up category: {reverb_category}, SKU: {sku}, UUID: {uuid}")
    
    # If we have a UUID directly, use it
    reverb_uuid = uuid
    
    # If no direct UUID but we have a SKU, try to get UUID from database
    if not reverb_uuid and sku and sku.upper().startswith('REV-'):
        # Extract reverb ID from SKU
        reverb_id = sku.upper().replace('REV-', '')
        
        # Look up the UUID from reverb_listings
        uuid_query = text("""
            SELECT rl.reverb_category_uuid
            FROM products p
            JOIN platform_common pc ON p.id = pc.product_id
            JOIN reverb_listings rl ON pc.id = rl.platform_id
            WHERE p.sku = :sku
        """)
        
        result = await db.execute(uuid_query, {"sku": sku})
        row = result.fetchone()
        if row and row.reverb_category_uuid:
            reverb_uuid = row.reverb_category_uuid
            print(f"Found UUID from SKU: {reverb_uuid}")
    
    # Query using the new normalized tables
    if reverb_uuid:
        # Use UUID for precise lookup
        query = text("""
            SELECT
                rc.id as reverb_cat_id,
                rc.name as reverb_cat_name,
                rc.uuid as reverb_cat_uuid,
                -- eBay mapping
                ec.ebay_category_id,
                ec.ebay_category_name,
                -- Shopify mapping
                sc.shopify_gid,
                sc.shopify_category_name,
                sc.merchant_type,
                -- VR mapping
                vc.vr_category_id,
                vc.vr_category_name,
                vc.vr_subcategory_id,
                vc.vr_subcategory_name,
                vc.vr_sub_subcategory_id,
                vc.vr_sub_sub_subcategory_id
            FROM reverb_categories rc
            LEFT JOIN ebay_category_mappings ec ON rc.id = ec.reverb_category_id
            LEFT JOIN shopify_category_mappings sc ON rc.id = sc.reverb_category_id
            LEFT JOIN vr_category_mappings vc ON rc.id = vc.reverb_category_id
            WHERE rc.uuid = :uuid
        """)
        
        result = await db.execute(query, {"uuid": reverb_uuid})
        row = result.fetchone()
    else:
        # Fallback: Try exact match on reverb category name
        query = text("""
            SELECT
                rc.id as reverb_cat_id,
                rc.name as reverb_cat_name,
                rc.uuid as reverb_cat_uuid,
                -- eBay mapping
                ec.ebay_category_id,
                ec.ebay_category_name,
                -- Shopify mapping
                sc.shopify_gid,
                sc.shopify_category_name,
                sc.merchant_type,
                -- VR mapping
                vc.vr_category_id,
                vc.vr_category_name,
                vc.vr_subcategory_id,
                vc.vr_subcategory_name,
                vc.vr_sub_subcategory_id,
                vc.vr_sub_sub_subcategory_id
            FROM reverb_categories rc
            LEFT JOIN ebay_category_mappings ec ON rc.id = ec.reverb_category_id
            LEFT JOIN shopify_category_mappings sc ON rc.id = sc.reverb_category_id
            LEFT JOIN vr_category_mappings vc ON rc.id = vc.reverb_category_id
            WHERE rc.name = :category
        """)
        
        result = await db.execute(query, {"category": reverb_category})
        row = result.fetchone()
    
    if row:
        print(f"Found mappings for Reverb category: {row.reverb_cat_name} (ID: {row.reverb_cat_id})")
        if row.ebay_category_id:
            print(f"  eBay: {row.ebay_category_id} - {row.ebay_category_name}")
        if row.shopify_gid:
            print(f"  Shopify: {row.shopify_gid} - {row.merchant_type}")
        if row.vr_category_id:
            print(f"  VR: {row.vr_category_id}/{row.vr_subcategory_id}")
    
    # Build response with mappings for each platform
    mappings = {
        "reverb_uuid": None,
        "ebay": None,
        "shopify": None,
        "vr": None
    }

    if row:
        # Add Reverb UUID
        if hasattr(row, 'reverb_cat_uuid'):
            mappings['reverb_uuid'] = row.reverb_cat_uuid
        # eBay mapping
        if row.ebay_category_id:
            mappings['ebay'] = {
                "id": row.ebay_category_id,
                "name": row.ebay_category_name
            }
        
        # Shopify mapping
        if row.shopify_gid:
            mappings['shopify'] = {
                "gid": row.shopify_gid,
                "name": row.merchant_type or row.shopify_category_name,  # Prefer merchant_type
                "full_name": row.shopify_category_name
            }
        
        # VR mapping
        if row.vr_category_id:
            # Build the V&R category hierarchy
            vr_ids = []
            vr_ids.append(row.vr_category_id)
            if row.vr_subcategory_id:
                vr_ids.append(row.vr_subcategory_id)
            if row.vr_sub_subcategory_id:
                vr_ids.append(row.vr_sub_subcategory_id)
            if row.vr_sub_sub_subcategory_id:
                vr_ids.append(row.vr_sub_sub_subcategory_id)
            
            # Get VR names if available
            vr_name = row.vr_category_name
            if row.vr_subcategory_name:
                vr_name = f"{vr_name} / {row.vr_subcategory_name}"
            
            mappings['vr'] = {
                "id": "/".join(vr_ids),
                "category_id": row.vr_category_id,
                "subcategory_id": row.vr_subcategory_id,
                "sub_subcategory_id": row.vr_sub_subcategory_id,
                "sub_sub_subcategory_id": row.vr_sub_sub_subcategory_id,
                "name": vr_name
            }
    
    print(f"Returning mappings: {mappings}")
    return {"mappings": mappings}

async def perform_dropbox_scan(app, access_token=None):
    """Background task to scan Dropbox with token refresh support"""
    try:
        print("Starting Dropbox scan background task...")
        
        # Mark scan as in progress
        app.state.dropbox_scan_in_progress = True
        app.state.dropbox_scan_progress = {'status': 'scanning', 'progress': 0}
        
        # Get tokens and credentials from settings
        settings = getattr(app.state, 'settings', None)
        
        # Fallback to environment variables if settings not available
        if settings:
            refresh_token = getattr(settings, 'DROPBOX_REFRESH_TOKEN', None)
            app_key = getattr(settings, 'DROPBOX_APP_KEY', None)
            app_secret = getattr(settings, 'DROPBOX_APP_SECRET', None)
        else:
            # Get from environment
            refresh_token = os.environ.get('DROPBOX_REFRESH_TOKEN')
            app_key = os.environ.get('DROPBOX_APP_KEY')
            app_secret = os.environ.get('DROPBOX_APP_SECRET')
            
        print(f"Access token available: {bool(access_token)}")
        print(f"Refresh token available: {bool(refresh_token)}{' (starts with: ' + refresh_token[:5] + '...)' if refresh_token else ''}")
        print(f"App key available: {bool(app_key)}{' (starts with: ' + app_key[:5] + '...)' if app_key else ''}")
        print(f"App secret available: {bool(app_secret)}{' (starts with: ' + app_secret[:5] + '...)' if app_secret else ''}")
        
        if not access_token and not refresh_token:
            print("ERROR: No access token or refresh token provided")
            app.state.dropbox_scan_progress = {'status': 'error', 'message': 'No token available', 'progress': 0}
            app.state.dropbox_scan_in_progress = False
            return
        
        # Create the async client
        print("Creating client instance...")
        
        # Initialize with all available credentials
        from app.services.dropbox.dropbox_async_service import AsyncDropboxClient
        client = AsyncDropboxClient(
            access_token=access_token,
            refresh_token=refresh_token,
            app_key=app_key,
            app_secret=app_secret
        )
        
        # Try to refresh token first if we have refresh credentials
        if refresh_token and app_key and app_secret:
            print("Attempting to refresh token before scan...")
            try:
                refresh_success = await client.refresh_access_token()
                if refresh_success:
                    print("Successfully refreshed access token")
                    # Save the new token
                    access_token = client.access_token
                    # Update in environment
                    os.environ['DROPBOX_ACCESS_TOKEN'] = access_token
                    # Update in app state if settings exist
                    if hasattr(app.state, 'settings'):
                        app.state.settings.DROPBOX_ACCESS_TOKEN = access_token
                else:
                    print("Failed to refresh access token")
                    app.state.dropbox_scan_progress = {
                        'status': 'error', 
                        'message': 'Failed to refresh access token', 
                        'progress': 0
                    }
                    app.state.dropbox_scan_in_progress = False
                    return
            except Exception as refresh_error:
                print(f"Error refreshing token: {str(refresh_error)}")
                app.state.dropbox_scan_progress = {
                    'status': 'error', 
                    'message': f'Error refreshing token: {str(refresh_error)}', 
                    'progress': 0
                }
                app.state.dropbox_scan_in_progress = False
                return
                
        # Try a simple operation first to test the token
        print("Testing connection...")
        test_result = await client.test_connection()
        if not test_result:
            print("ERROR: Could not connect to Dropbox API")
            app.state.dropbox_scan_progress = {
                'status': 'error', 
                'message': 'Could not connect to Dropbox API', 
                'progress': 0
            }
            app.state.dropbox_scan_in_progress = False
            return
            
        print("Connection successful, starting full scan...")
        app.state.dropbox_scan_progress = {'status': 'scanning', 'progress': 10}
        
        # Perform the scan with cache support
        dropbox_map = await client.scan_and_map_folder()
        
        # Store results
        print("Scan complete, saving results...")
        app.state.dropbox_map = dropbox_map
        app.state.dropbox_last_updated = datetime.now()
        app.state.dropbox_scan_progress = {'status': 'complete', 'progress': 100}
        
        # If we got a new token via refresh, store it
        if client.access_token != access_token:
            # Update in environment
            os.environ['DROPBOX_ACCESS_TOKEN'] = client.access_token
            # Update in app state if settings exist
            if hasattr(app.state, 'settings'):
                app.state.settings.DROPBOX_ACCESS_TOKEN = client.access_token
            print("Updated access token from refresh")
        
        print(f"Dropbox background scan completed successfully. Mapped {len(dropbox_map.get('all_entries', []))} entries and {len(dropbox_map.get('temp_links', {}))} temporary links.")
    except Exception as e:
        print(f"ERROR in Dropbox scan: {str(e)}")
        import traceback
        print(traceback.format_exc())
        app.state.dropbox_scan_progress = {'status': 'error', 'message': f"Error: {str(e)}", 'progress': 0}
    finally:
        app.state.dropbox_scan_in_progress = False
        print("Background scan task finished")
