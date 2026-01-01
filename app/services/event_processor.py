"""
Event processor service that handles all types of sync events.
This is the core logic extracted from scripts/process_sync_event.py
to be reusable by both CLI and web UI.
"""
import logging
import json as json_module
import os
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy import select

from app.models.sync_event import SyncEvent
from app.models.product import Product, ProductCondition, ProductStatus
from app.models.platform_common import PlatformCommon, ListingStatus, SyncStatus
from app.core.enums import Storefront, InventoryLocation, Handedness
from app.models.reverb import ReverbListing
from app.models.shopify import ShopifyListing
from app.models.ebay import EbayListing
from app.models.vr import VRListing
from app.models.shipping import ShippingProfile

from app.services.reverb_service import ReverbService
from app.services.reverb.client import ReverbClient
from app.services.ebay_service import EbayService
from app.services.shopify_service import ShopifyService
from app.services.vr_service import VRService
from app.core.config import get_settings
from app.services.vr_job_queue import enqueue_vr_job

logger = logging.getLogger(__name__)

class EventProcessingResult:
    """Result of processing a sync event"""
    def __init__(self):
        self.success: bool = False
        self.message: str = ""
        self.product_id: Optional[int] = None
        self.platforms_created: List[str] = []
        self.platforms_failed: List[str] = []
        self.errors: List[str] = []
        self.details: Dict[str, Any] = {}

async def process_sync_event(
    session: AsyncSession,
    event_id: int,
    platforms: Optional[List[str]] = None,
    sandbox: bool = False
) -> EventProcessingResult:
    """
    Process a single sync event - handles all event types.

    This is the main entry point that routes to specific handlers based on event type.
    Currently handles:
    - new_listing: Creates product and listings on other platforms
    - status_change: Updates status across platforms
    - price_change: Updates price across platforms
    - removed_listing: Removes from all platforms

    Args:
        session: Database session
        event_id: The sync event ID to process
        platforms: Optional list of platforms to process (default: all)
        sandbox: Use sandbox mode for eBay

    Returns:
        EventProcessingResult with success status and details
    """
    result = EventProcessingResult()

    try:
        # Get the sync event with all related data
        stmt = select(SyncEvent).where(SyncEvent.id == event_id)
        db_result = await session.execute(stmt)
        event = db_result.scalar_one_or_none()

        if not event:
            result.message = f"Sync event {event_id} not found"
            logger.error(result.message)
            return result

        logger.info(f"Processing sync event {event_id}: {event.change_type} for {event.platform_name} {event.external_id}")

        # Check if already processed
        if event.status == 'processed' and event.change_type != 'price_change':
            result.message = f"Event {event_id} already processed"
            logger.warning(result.message)
            return result

        if event.status == 'error':
            logger.warning(f"Processing event {event_id} with error status")

        # Route to appropriate handler based on event type
        if event.change_type == 'new_listing':
            result = await _process_new_listing(session, event, platforms, sandbox)
        elif event.change_type in ['status_change', 'removed_listing']:
            result = await _process_status_change(session, event, platforms)
        elif event.change_type in ['price_change', 'price']:
            result = await _process_price_change(session, event, platforms)
        elif event.change_type == 'quantity_change':
            result = await _process_quantity_change(session, event)
        else:
            result.message = f"Unknown event type: {event.change_type}"
            logger.error(result.message)
            return result

        # Update event status based on result
        if result.success:
            event.status = 'processed'
            event.processed_at = datetime.utcnow()
            if result.platforms_failed:
                event.status = 'partial'
                event.notes = json_module.dumps({
                    "successful_platforms": result.platforms_created,
                    "failed_platforms": result.platforms_failed,
                    "errors": result.errors
                })
        else:
            event.status = 'error'
            event.notes = json_module.dumps({
                "error": result.message,
                "details": result.errors
            })

        await session.commit()

    except Exception as e:
        logger.error(f"Error processing sync event {event_id}: {e}", exc_info=True)
        result.message = f"Error: {str(e)}"
        result.errors.append(str(e))

    return result

async def _process_new_listing(
    session: AsyncSession,
    event: SyncEvent,
    platforms: Optional[List[str]],
    sandbox: bool
) -> EventProcessingResult:
    """
    Process a new_listing event - creates product and listings on all platforms.

    This contains the core logic from process_sync_event.py for handling new listings.
    """
    result = EventProcessingResult()

    try:
        change_data = event.change_data or {}

        product: Optional[Product] = None
        if event.product_id:
            product = await session.get(Product, event.product_id)

        candidate = change_data.get('match_candidate') if isinstance(change_data, dict) else None
        if not product and candidate and candidate.get('product_id'):
            candidate_product = await session.get(Product, candidate['product_id'])
            if candidate_product:
                product = candidate_product
                event.product_id = candidate_product.id

        if event.platform_name != 'reverb':
            if not product:
                result.message = "No product selected to match this listing."
                return result

            message = await _attach_existing_listing(session, event, product)
            result.success = True
            result.product_id = product.id
            result.message = message
            result.platforms_created.append(event.platform_name)
            return result

        # Reverb-specific handling below

        # Check if product already exists with this SKU
        reverb_listing_dict = change_data.get('raw_data') if isinstance(change_data, dict) else None

        if not product:
            sku = f"REV-{event.external_id}"
            stmt = select(Product).where(Product.sku == sku)
            db_result = await session.execute(stmt)
            existing_product = db_result.scalar_one_or_none()

            if existing_product:
                logger.info(f"Found existing product {existing_product.id}: {existing_product.title}")
                product = existing_product
                result.product_id = product.id
            else:
                # Fetch Reverb listing data if not already available
                if not reverb_listing_dict:
                    logger.info(f"Fetching Reverb listing {event.external_id}...")
                    settings = get_settings()
                    reverb_client = ReverbClient(
                        api_key=settings.REVERB_API_KEY,
                        use_sandbox=settings.REVERB_USE_SANDBOX
                    )
                    reverb_listing_dict = await reverb_client.get_listing_details(event.external_id)

                if not reverb_listing_dict:
                    result.message = f"Failed to fetch Reverb listing {event.external_id}"
                    return result

                # Create new product
                logger.info("Creating new product from Reverb data...")
                product = await _create_product_from_reverb(session, reverb_listing_dict)
                result.product_id = product.id

                # Update sync event with product_id
                event.product_id = product.id
                logger.info(f"Updated sync event {event.id} with product_id {product.id}")

        if not reverb_listing_dict:
            # Ensure we have listing data for downstream use
            settings = get_settings()
            reverb_client = ReverbClient(
                api_key=settings.REVERB_API_KEY,
                use_sandbox=settings.REVERB_USE_SANDBOX
            )
            reverb_listing_dict = await reverb_client.get_listing_details(event.external_id)
            if not reverb_listing_dict:
                result.message = f"Failed to fetch Reverb listing {event.external_id}"
                return result

        # Create platform_common entry for Reverb
        await _ensure_platform_common_reverb(session, product, reverb_listing_dict)

        # Determine which platforms to create listings on
        # Default: create local record only (no auto-push to other platforms)
        # User can manually list on other platforms from the product detail page
        if platforms:
            platforms_to_create = [p for p in platforms if p != 'reverb']
        else:
            platforms_to_create = []  # No auto-push - just import to RIFF

        if platforms_to_create:
            logger.info(f"Creating listings on platforms: {platforms_to_create}")
        else:
            logger.info("Importing to RIFF only (no auto-push to other platforms)")
            result.success = True
            result.message = f"Imported to RIFF as {product.sku}. Use product detail page to list on other platforms."
            result.platforms_created = ['reverb']  # Local record created
            return result

        # Create listings on each platform (only if explicitly requested)
        if 'ebay' in platforms_to_create:
            try:
                logger.info("\n=== Creating eBay listing ===")
                ebay_result = await _create_ebay_listing(session, product, reverb_listing_dict, sandbox)
                if ebay_result['success']:
                    result.platforms_created.append('ebay')
                    result.details['ebay'] = ebay_result
                else:
                    result.platforms_failed.append('ebay')
                    result.errors.append(f"eBay: {ebay_result.get('error', 'Unknown error')}")
            except Exception as e:
                logger.error(f"eBay creation failed: {e}")
                result.platforms_failed.append('ebay')
                result.errors.append(f"eBay: {str(e)}")

        if 'shopify' in platforms_to_create:
            try:
                logger.info("\n=== Creating Shopify listing ===")
                shopify_result = await _create_shopify_listing(session, product, reverb_listing_dict)
                if shopify_result['success']:
                    result.platforms_created.append('shopify')
                    result.details['shopify'] = shopify_result
                    # Commit Shopify changes immediately to ensure persistence
                    await session.commit()
                    logger.info("✅ Shopify records committed successfully")
                else:
                    result.platforms_failed.append('shopify')
                    result.errors.append(f"Shopify: {shopify_result.get('error', 'Unknown error')}")
            except Exception as e:
                logger.error(f"Shopify creation failed: {e}")
                result.platforms_failed.append('shopify')
                result.errors.append(f"Shopify: {str(e)}")

        if 'vr' in platforms_to_create:
            try:
                logger.info("\n=== Creating VR listing ===")
                vr_result = await _create_vr_listing(session, product, reverb_listing_dict)
                if vr_result['success']:
                    result.platforms_created.append('vr')
                    result.details['vr'] = vr_result
                else:
                    result.platforms_failed.append('vr')
                    result.errors.append(f"VR: {vr_result.get('error', 'Unknown error')}")
            except Exception as e:
                logger.error(f"VR creation failed: {e}")
                result.platforms_failed.append('vr')
                result.errors.append(f"VR: {str(e)}")

        # VR Reconciliation - Match VR listing to get real ID
        if 'vr' in result.platforms_created and result.details.get('vr', {}).get('needs_reconciliation'):
            logger.info("\n=== VR Reconciliation (2nd API Call) ===")
            logger.info("🔍 Starting VR reconciliation to get real VR ID...")
            try:
                reconciliation_success = await reconcile_vr_listing_for_product(session, product)
                if reconciliation_success:
                    logger.info("✅ VR reconciliation completed successfully")
                    result.details['vr_reconciliation'] = 'success'
                else:
                    logger.error("❌ VR reconciliation failed - will retry in next batch")
                    result.details['vr_reconciliation'] = 'failed'
            except Exception as e:
                logger.error(f"❌ VR reconciliation error: {e}")
                result.details['vr_reconciliation'] = 'error'

        # Set overall success
        result.success = len(result.platforms_created) > 0
        if result.success:
            result.message = f"Created listings on {len(result.platforms_created)} platforms"
            if result.platforms_failed:
                result.message += f", failed on {len(result.platforms_failed)} platforms"
        else:
            result.message = "Failed to create listings on any platform"

    except Exception as e:
        logger.error(f"Error in _process_new_listing: {e}", exc_info=True)
        result.message = f"Error: {str(e)}"
        result.errors.append(str(e))

    return result

async def _create_product_from_reverb(session: AsyncSession, reverb_data: dict) -> Product:
    """Create a Product from Reverb listing data"""
    # Extract images
    photos = reverb_data.get('photos', [])
    primary_image = None
    additional_images = []

    if photos:
        primary_photo = photos[0]
        primary_image = primary_photo.get('_links', {}).get('full', {}).get('href', '')

        for photo in photos[1:]:
            img_url = photo.get('_links', {}).get('full', {}).get('href', '')
            if img_url:
                additional_images.append(img_url)

    # Extract year and finish from Reverb data - matching original script EXACTLY
    year_str = reverb_data.get('year', '')
    year = None
    if year_str:
        # Try to extract a 4-digit year from strings like "1940s" or "1965"
        import re
        year_match = re.search(r'(\d{4})', str(year_str))
        if year_match:
            year = int(year_match.group(1))

    # Calculate decade from year
    decade = None
    if year:
        try:
            decade = (year // 10) * 10
        except (ValueError, TypeError):
            logger.warning(f"  Could not calculate decade from year: {year}")

    # Map condition - matching the original script and actual enum values
    condition_map = {
        'new': ProductCondition.NEW,
        'excellent': ProductCondition.EXCELLENT,
        'very_good': ProductCondition.VERYGOOD,  # Fixed: VERYGOOD not VERY_GOOD
        'good': ProductCondition.GOOD,
        'fair': ProductCondition.FAIR,
        'poor': ProductCondition.POOR
    }
    condition_slug = reverb_data.get('condition', {}).get('slug', 'good')
    product_condition = condition_map.get(condition_slug, ProductCondition.GOOD)

    # Extract processing time from shipping profile and keep reference
    processing_time = 3  # default
    shipping_profile = reverb_data.get('shipping_profile', {})
    shipping_profile_id = None
    if shipping_profile and isinstance(shipping_profile, dict):
        shipping_profile_id = shipping_profile.get('id')
        free_expedited_shipping = shipping_profile.get('free_expedited_shipping', False)
        processing_time = 1 if free_expedited_shipping else 3

    # Get category from reverb_data - matching original script
    categories = reverb_data.get('categories', [])
    category = ' / '.join([cat.get('full_name', '') for cat in categories]) if categories else ''

    # Get price amount from Reverb
    reverb_price = reverb_data.get('price', {}).get('amount', 0)
    if isinstance(reverb_price, str):
        reverb_price = float(reverb_price)
    else:
        reverb_price = float(reverb_price)

    # Reverse-engineer base price from Reverb price
    # Reverb price formula: ceil(base * 1.05 / 100) * 100 - 1
    # Reverse: (reverb_price + 1) / 1.05, then round down to nearest £9
    # e.g., Reverb £1399 → (1399+1)/1.05 = 1333.33 → base £1329
    if reverb_price > 0:
        raw_base = (reverb_price + 1) / 1.05
        # Round down to nearest value ending in 9 (e.g., 1329, 1339, 1349...)
        base_price = float(int(raw_base / 10) * 10 - 1)
        if base_price < 0:
            base_price = float(int(raw_base))
    else:
        base_price = 0.0

    logger.info(f"  Reverb price: £{reverb_price:.0f} → Base price: £{base_price:.0f}")

    # Create product - matching original script exactly
    product = Product(
        sku=f"REV-{reverb_data['id']}",
        brand=reverb_data.get('make', ''),
        model=reverb_data.get('model', ''),
        year=year,  # Add year
        decade=decade,  # Add calculated decade
        finish=reverb_data.get('finish', ''),  # Add finish
        category=category,  # Add category
        title=reverb_data.get('title', ''),
        description=reverb_data.get('description', ''),
        condition=product_condition,
        base_price=base_price,  # Calculated from Reverb price
        price=reverb_price,  # Store original Reverb price in price field
        status=ProductStatus.ACTIVE,
        is_stocked_item=False,  # Single items, not stock
        quantity=1,  # Default quantity of 1
        primary_image=primary_image,  # Store primary image
        additional_images=additional_images,  # Store additional images as list (will be JSONB)
        processing_time=processing_time,
        # Explicit enum defaults to avoid case sensitivity issues
        storefront=Storefront.HANKS,
        inventory_location=InventoryLocation.HANKS,
        handedness=Handedness.RIGHT,
    )

    # Link local shipping profile if we have a Reverb profile id
    if shipping_profile_id:
        stmt = select(ShippingProfile).where(ShippingProfile.reverb_profile_id == str(shipping_profile_id))
        profile_result = await session.execute(stmt)
        profile_record = profile_result.scalar_one_or_none()
        if profile_record:
            product.shipping_profile_id = profile_record.id

    # Capture first video if available
    videos = reverb_data.get('videos') or []
    if videos and isinstance(videos, list):
        first_video = videos[0] or {}
        product.video_url = first_video.get('url') or product.video_url

    ReverbService.apply_metadata_from_reverb(product, reverb_data)

    session.add(product)
    await session.flush()

    logger.info(f"✅ Created new product with ID {product.id}")
    return product

async def _ensure_platform_common_reverb(session: AsyncSession, product: Product, reverb_data: dict) -> PlatformCommon:
    """Ensure platform_common entry exists for Reverb"""
    # Check if already exists
    stmt = select(PlatformCommon).where(
        PlatformCommon.product_id == product.id,
        PlatformCommon.platform_name == 'reverb'
    )
    result = await session.execute(stmt)
    platform_common = result.scalar_one_or_none()

    if platform_common:
        logger.info("Found existing platform_common entry for Reverb")
        return platform_common

    # Create new platform_common
    reverb_url = f"https://reverb.com/item/{reverb_data['id']}"
    platform_common = PlatformCommon(
        product_id=product.id,
        platform_name='reverb',
        external_id=str(reverb_data['id']),
        status='active',
        sync_status=SyncStatus.SYNCED.value,
        last_sync=datetime.utcnow(),
        listing_url=reverb_url,
        platform_specific_data=reverb_data
    )
    session.add(platform_common)
    await session.flush()

    logger.info("Created platform_common entry for Reverb")

    # Create reverb_listings entry
    await _create_reverb_listing(session, platform_common, reverb_data)

    return platform_common

async def _create_reverb_listing(session: AsyncSession, platform_common: PlatformCommon, reverb_data: dict):
    """Create reverb_listings entry"""
    # Check if already exists
    stmt = select(ReverbListing).where(ReverbListing.platform_id == platform_common.id)
    result = await session.execute(stmt)
    if result.scalar_one_or_none():
        logger.info("Reverb listing already exists")
        return

    # Extract data
    slug = reverb_data.get('_links', {}).get('web', {}).get('href', '')
    if '/' in slug:
        slug = slug.split('/')[-1]

    condition = reverb_data.get('condition', {})
    if isinstance(condition, dict):
        condition_display = condition.get('display_name', 'Good')
        # Map to rating
        condition_map = {
            'New': 5.0, 'Mint': 5.0, 'Excellent': 4.5,
            'Very Good': 4.0, 'Good': 3.5, 'Fair': 3.0, 'Poor': 2.0
        }
        rating = condition_map.get(condition_display, 3.5)
    else:
        condition_display = str(condition)
        rating = 3.5

    reverb_listing = ReverbListing(
        platform_id=platform_common.id,
        reverb_listing_id=str(reverb_data['id']),
        reverb_slug=slug,
        condition_rating=rating,
        inventory_quantity=reverb_data.get('inventory', 1),
        has_inventory=reverb_data.get('has_inventory', True),
        offers_enabled=reverb_data.get('offers_enabled', False),
        is_auction=reverb_data.get('auction', False),
        list_price=float(reverb_data.get('price', {}).get('amount', 0)),
        listing_currency=reverb_data.get('listing_currency', 'GBP'),
        reverb_state=reverb_data.get('state', {}).get('slug', 'live'),
        extended_attributes=reverb_data
    )

    shipping_profile = reverb_data.get('shipping_profile') or {}
    if isinstance(shipping_profile, dict) and shipping_profile.get('id'):
        reverb_listing.shipping_profile_id = str(shipping_profile.get('id'))

    categories = reverb_data.get('categories') or []
    if categories:
        first_category = categories[0] or {}
        reverb_listing.reverb_category_uuid = first_category.get('uuid') or reverb_listing.reverb_category_uuid

    created_at = reverb_data.get('created_at')
    if created_at:
        try:
            dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            reverb_listing.reverb_created_at = dt.astimezone(timezone.utc).replace(tzinfo=None)
        except ValueError:
            logger.debug("Unable to parse reverb created_at %s", created_at)

    published_at = reverb_data.get('published_at')
    if published_at:
        try:
            dt = datetime.fromisoformat(published_at.replace('Z', '+00:00'))
            reverb_listing.reverb_published_at = dt.astimezone(timezone.utc).replace(tzinfo=None)
        except ValueError:
            logger.debug("Unable to parse reverb published_at %s", published_at)

    session.add(reverb_listing)
    await session.flush()
    logger.info(f"Created reverb_listings entry with ID {reverb_listing.id}")


async def _attach_existing_listing(session: AsyncSession, event: SyncEvent, product: Product) -> str:
    """Attach an externally created listing to an existing product."""

    change_data = event.change_data or {}
    raw_data = change_data.get('raw_data') or change_data.get('extended_attributes') or {}
    listing_url = change_data.get('listing_url') or change_data.get('external_link')

    status_value = change_data.get('status') or change_data.get('state')
    if change_data.get('is_sold'):
        status_value = 'sold'

    platform_payload = {
        'source': 'manual_match',
        'matched_at': datetime.utcnow().isoformat(),
        'raw_data': raw_data,
        'change_snapshot': change_data,
    }

    platform_common = await _ensure_platform_common_generic(
        session=session,
        product=product,
        platform=event.platform_name,
        external_id=str(event.external_id),
        status=status_value,
        listing_url=listing_url,
        platform_payload=platform_payload,
    )

    if event.platform_name == 'ebay':
        await _upsert_ebay_listing_from_change(session, platform_common, change_data)
    elif event.platform_name == 'shopify':
        await _upsert_shopify_listing_from_change(session, platform_common, change_data)
    elif event.platform_name == 'vr':
        await _upsert_vr_listing_from_change(session, platform_common, change_data)
    else:
        raise ValueError(f"Unsupported platform for manual match: {event.platform_name}")

    return f"Linked {event.platform_name.title()} listing to product {product.sku}"


def _default_listing_url(platform: str, external_id: str) -> Optional[str]:
    if not external_id:
        return None
    if platform == 'ebay':
        return f"https://www.ebay.co.uk/itm/{external_id}"
    if platform == 'shopify':
        return f"https://londonvintageguitars.myshopify.com/products/{external_id}"
    if platform == 'vr':
        return f"https://www.vintageandrare.com/product/{external_id}"
    if platform == 'reverb':
        return f"https://reverb.com/item/{external_id}"
    return None


async def _ensure_platform_common_generic(
    session: AsyncSession,
    product: Product,
    platform: str,
    external_id: str,
    status: Optional[str],
    listing_url: Optional[str],
    platform_payload: Dict[str, Any],
) -> PlatformCommon:
    """Create or update a platform_common entry for manual matches."""

    stmt = select(PlatformCommon).where(
        PlatformCommon.product_id == product.id,
        PlatformCommon.platform_name == platform,
    )
    existing = (await session.execute(stmt)).scalar_one_or_none()

    normalised_status = (status or 'active').lower()
    listing_url = listing_url or _default_listing_url(platform, external_id)

    if existing:
        existing.external_id = external_id
        existing.status = normalised_status
        existing.listing_url = listing_url or existing.listing_url
        existing.sync_status = SyncStatus.SYNCED.value.upper()
        existing.last_sync = datetime.utcnow()
        existing.platform_specific_data = platform_payload
        platform_common = existing
    else:
        platform_common = PlatformCommon(
            product_id=product.id,
            platform_name=platform,
            external_id=external_id,
            status=normalised_status,
            listing_url=listing_url,
            sync_status=SyncStatus.SYNCED.value.upper(),
            last_sync=datetime.utcnow(),
            platform_specific_data=platform_payload,
        )
        session.add(platform_common)
        await session.flush()

    return platform_common


async def _upsert_ebay_listing_from_change(
    session: AsyncSession,
    platform_common: PlatformCommon,
    change_data: Dict[str, Any],
) -> None:
    raw_data = change_data.get('raw_data') or {}

    stmt = select(EbayListing).where(EbayListing.platform_id == platform_common.id)
    listing = (await session.execute(stmt)).scalar_one_or_none()

    listing_status = (change_data.get('status') or 'active').upper()
    price = change_data.get('price')
    listing_url = change_data.get('listing_url') or platform_common.listing_url

    # eBay API returns quantities as strings - convert to int
    quantity_total_raw = raw_data.get('Quantity') or raw_data.get('quantity_total')
    quantity_available_raw = raw_data.get('QuantityAvailable') or change_data.get('quantity_available')
    quantity_sold_raw = raw_data.get('SellingStatus', {}).get('QuantitySold') if isinstance(raw_data, dict) else None

    try:
        quantity_total = int(quantity_total_raw) if quantity_total_raw is not None else None
    except (ValueError, TypeError):
        quantity_total = None
    try:
        quantity_available = int(quantity_available_raw) if quantity_available_raw is not None else None
    except (ValueError, TypeError):
        quantity_available = None
    try:
        quantity_sold = int(quantity_sold_raw) if quantity_sold_raw is not None else None
    except (ValueError, TypeError):
        quantity_sold = None

    picture_urls = []
    if isinstance(raw_data, dict):
        details = raw_data.get('PictureDetails') or {}
        urls = details.get('PictureURL')
        if isinstance(urls, list):
            picture_urls = urls
        elif urls:
            picture_urls = [urls]

    if listing:
        listing.listing_status = listing_status
        listing.title = change_data.get('title') or listing.title
        listing.price = float(price) if price is not None else listing.price
        listing.quantity = quantity_total or listing.quantity
        listing.quantity_available = quantity_available if quantity_available is not None else listing.quantity_available
        listing.quantity_sold = quantity_sold if quantity_sold is not None else listing.quantity_sold
        listing.listing_url = listing_url or listing.listing_url
        if picture_urls:
            listing.picture_urls = picture_urls
        listing.gallery_url = raw_data.get('GalleryURL') or listing.gallery_url
        listing.listing_data = raw_data or listing.listing_data
        listing.last_synced_at = datetime.utcnow()
    else:
        listing = EbayListing(
            platform_id=platform_common.id,
            ebay_item_id=platform_common.external_id,
            listing_status=listing_status,
            title=change_data.get('title'),
            price=float(price) if price is not None else None,
            listing_url=listing_url,
            quantity=quantity_total,
            quantity_available=quantity_available,
            quantity_sold=quantity_sold,
            picture_urls=picture_urls or None,
            gallery_url=raw_data.get('GalleryURL') if isinstance(raw_data, dict) else None,
            listing_data=raw_data,
        )
        session.add(listing)

    await session.flush()


async def _upsert_shopify_listing_from_change(
    session: AsyncSession,
    platform_common: PlatformCommon,
    change_data: Dict[str, Any],
) -> None:
    raw_data = change_data.get('raw_data') or {}

    stmt = select(ShopifyListing).where(ShopifyListing.platform_id == platform_common.id)
    listing = (await session.execute(stmt)).scalar_one_or_none()

    variants = raw_data.get('variants', {})
    if isinstance(variants, dict):
        variant_nodes = variants.get('nodes', [])
    elif isinstance(variants, list):
        variant_nodes = variants
    else:
        variant_nodes = []

    price = change_data.get('price')
    if price is None and variant_nodes:
        try:
            price = float(variant_nodes[0].get('price'))
        except (TypeError, ValueError):
            price = None

    shopify_product_id = raw_data.get('id') or change_data.get('full_gid')
    shopify_legacy_id = raw_data.get('legacyResourceId') or change_data.get('external_id')
    handle = raw_data.get('handle')
    vendor = raw_data.get('vendor') or change_data.get('vendor')
    status = (raw_data.get('status') or change_data.get('status') or 'active').lower()

    category_gid = None
    category_name = None
    category_full_name = None
    product_category = raw_data.get('productCategory') if isinstance(raw_data, dict) else None
    if isinstance(product_category, dict):
        taxonomy = product_category.get('productTaxonomyNode') or {}
        category_gid = taxonomy.get('id')
        category_name = taxonomy.get('name')
        category_full_name = taxonomy.get('fullName')

    seo_data = raw_data.get('seo') if isinstance(raw_data, dict) else {}

    generated_keywords = generate_shopify_keywords(
        brand=product.brand,
        model=product.model,
        finish=product.finish,
        year=product.year,
        decade=product.decade,
        category=category_name,
        condition=product.condition.value if product.condition else None,
        description_html=change_data.get('description'),
    ) if product else []

    short_description = generate_shopify_short_description(
        change_data.get('description'),
        fallback=product.title if product else None,
    )

    if listing:
        listing.shopify_product_id = shopify_product_id or listing.shopify_product_id
        listing.shopify_legacy_id = shopify_legacy_id or listing.shopify_legacy_id
        listing.handle = handle or listing.handle
        listing.title = change_data.get('title') or listing.title
        listing.vendor = vendor or listing.vendor
        listing.status = status
        listing.price = price if price is not None else listing.price
        listing.category_gid = category_gid or listing.category_gid
        listing.category_name = category_name or listing.category_name
        listing.category_full_name = category_full_name or listing.category_full_name
        listing.seo_title = seo_data.get('title') or listing.seo_title
        listing.seo_description = seo_data.get('description') or listing.seo_description or short_description or listing.seo_description
        listing.seo_keywords = generated_keywords or listing.seo_keywords
        listing.extended_attributes = raw_data or listing.extended_attributes
        listing.last_synced_at = datetime.utcnow()
    else:
        listing = ShopifyListing(
            platform_id=platform_common.id,
            shopify_product_id=shopify_product_id,
            shopify_legacy_id=str(shopify_legacy_id) if shopify_legacy_id else None,
            handle=handle,
            title=change_data.get('title'),
            vendor=vendor,
            status=status,
            price=price,
            category_gid=category_gid,
            category_name=category_name,
            category_full_name=category_full_name,
            category_assignment_status='ASSIGNED' if category_gid else None,
            category_assigned_at=datetime.utcnow() if category_gid else None,
            seo_title=seo_data.get('title'),
            seo_description=seo_data.get('description') or short_description,
            seo_keywords=generated_keywords,
            extended_attributes=raw_data,
            last_synced_at=datetime.utcnow(),
        )
        session.add(listing)

    await session.flush()


async def _upsert_vr_listing_from_change(
    session: AsyncSession,
    platform_common: PlatformCommon,
    change_data: Dict[str, Any],
) -> None:
    raw_data = change_data.get('extended_attributes') or change_data.get('raw_data') or {}

    stmt = select(VRListing).where(VRListing.platform_id == platform_common.id)
    listing = (await session.execute(stmt)).scalar_one_or_none()

    vr_state = 'sold' if change_data.get('is_sold') else (change_data.get('state') or 'active')
    price = change_data.get('price')

    collective_discount = change_data.get('collective_discount')
    try:
        collective_discount = float(collective_discount)
    except (TypeError, ValueError):
        collective_discount = 0.0

    processing_time = change_data.get('processing_time') or raw_data.get('processing_time')
    try:
        processing_time = int(str(processing_time).split()[0]) if processing_time else 3
    except (TypeError, ValueError):
        processing_time = 3

    extended_attributes = {
        'source': 'manual_match',
        'raw_data': raw_data,
        'change_data': change_data,
    }

    if listing:
        listing.vr_listing_id = str(platform_common.external_id)
        listing.vr_state = vr_state
        listing.price_notax = price if price is not None else listing.price_notax
        listing.inventory_quantity = raw_data.get('inventory') if isinstance(raw_data, dict) else listing.inventory_quantity
        listing.collective_discount = collective_discount
        listing.processing_time = processing_time
        listing.extended_attributes = extended_attributes
        listing.last_synced_at = datetime.utcnow()
    else:
        listing = VRListing(
            platform_id=platform_common.id,
            vr_listing_id=str(platform_common.external_id),
            vr_state=vr_state,
            price_notax=price,
            inventory_quantity=raw_data.get('inventory') if isinstance(raw_data, dict) else 1,
            collective_discount=collective_discount,
            processing_time=processing_time,
            extended_attributes=extended_attributes,
            last_synced_at=datetime.utcnow(),
        )
        session.add(listing)

    await session.flush()

async def _create_ebay_listing(session: AsyncSession, product: Product, reverb_data: dict, sandbox: bool) -> dict:
    """Create eBay listing"""
    try:
        settings = get_settings()
        ebay_service = EbayService(session, settings)

        # Get business policy IDs from environment
        policies = {
            'shipping_profile_id': os.environ.get('EBAY_SHIPPING_PROFILE_ID', '252277357017'),
            'payment_profile_id': os.environ.get('EBAY_PAYMENT_PROFILE_ID', '252544577017'),
            'return_profile_id': os.environ.get('EBAY_RETURN_PROFILE_ID', '252277356017')
        }

        # Override shipping policy if product is tied to a mapped profile
        if product.shipping_profile_id:
            shipping_profile = await session.get(ShippingProfile, product.shipping_profile_id)
            if shipping_profile and shipping_profile.ebay_profile_id:
                policies['shipping_profile_id'] = shipping_profile.ebay_profile_id

        logger.info(f"  Sandbox mode: {sandbox}")
        logger.info(f"  Using eBay policies: {policies}")

        ebay_result = await ebay_service.create_listing_from_product(
            product=product,
            reverb_api_data=reverb_data,
            sandbox=sandbox,
            use_shipping_profile=True,
            **policies  # Pass the policies
        )

        if ebay_result and ebay_result.get('ItemID'):
            logger.info(f"✅ eBay listing created: {ebay_result['ItemID']}")
            return {
                'success': True,
                'item_id': ebay_result['ItemID'],
                'listing_url': ebay_result.get('listing_url')
            }
        else:
            return {
                'success': False,
                'error': ebay_result.get('error', 'Unknown eBay error')
            }

    except Exception as e:
        logger.error(f"eBay creation error: {e}", exc_info=True)
        return {
            'success': False,
            'error': str(e)
        }

async def _create_shopify_listing(session: AsyncSession, product: Product, reverb_data: dict) -> dict:
    """Create Shopify listing"""
    try:
        settings = get_settings()
        shopify_service = ShopifyService(session, settings)

        shopify_result = await shopify_service.create_listing_from_product(
            product=product,
            reverb_data=reverb_data
        )

        if shopify_result and shopify_result.get('status') == 'success':
            logger.info(f"✅ Shopify product created: {shopify_result.get('external_id')}")

            # Generate handle for the product URL
            import re
            def generate_shopify_handle(brand: str, model: str, sku: str) -> str:
                parts = [str(part) for part in [brand, model, sku] if part and str(part).lower() != 'nan']
                text = '-'.join(parts).lower()
                text = re.sub(r'[^a-z0-9\-]+', '-', text)
                return text.strip('-')

            handle = generate_shopify_handle(
                product.brand or '',
                product.model or '',
                product.sku
            )

            # Build the listing URL
            listing_url = f"https://londonvintageguitars.myshopify.com/products/{handle}" if handle else None

            # Create platform_common entry for Shopify
            platform_common = PlatformCommon(
                product_id=product.id,
                platform_name='shopify',
                external_id=str(shopify_result.get('external_id', '')),
                status='active',
                last_sync=datetime.utcnow(),
                sync_status=SyncStatus.SYNCED.value,
                listing_url=listing_url,
                platform_specific_data=shopify_result
            )
            session.add(platform_common)
            await session.flush()

            logger.info(f"Created platform_common record with ID: {platform_common.id}, URL: {listing_url}")

            # Create shopify_listings entry
            shopify_listing = ShopifyListing(
                platform_id=platform_common.id,
                shopify_product_id=f"gid://shopify/Product/{shopify_result.get('external_id', '')}",
                shopify_legacy_id=str(shopify_result.get('external_id', '')),
                handle=handle,
                title=product.title or f"{product.year or ''} {product.brand} {product.model}".strip(),
                status='active',
                vendor=product.brand,
                price=float(product.base_price) if product.base_price else None,
                category_gid=None,  # Will be set later from extended_attrs
                category_name=None,
                category_full_name=None,
                seo_title=None,
                seo_description=None,
                category_assigned_at=None,
                category_assignment_status='PENDING',
                extended_attributes=shopify_result,
                last_synced_at=datetime.utcnow()
            )
            session.add(shopify_listing)

            # Enrich SEO metadata
            seo_title = (product.title or f"{product.year or ''} {product.brand} {product.model}".strip()).strip()
            if seo_title:
                shopify_listing.seo_title = seo_title[:255]

            description_source = product.description or (reverb_data.get('description') if reverb_data else '')
            plain_description = ShopifyService.strip_html_to_plain_text(description_source)
            if plain_description:
                shopify_listing.seo_description = plain_description[:320]

            # Category enrichment
            category_gid = shopify_result.get('category_gid')
            category_full_name = shopify_result.get('category_full_name')
            category_name = shopify_result.get('category_name') or (
                category_full_name.split(' > ')[-1] if category_full_name else None
            )

            if category_gid:
                shopify_listing.category_gid = category_gid
                shopify_listing.category_name = category_name
                shopify_listing.category_full_name = category_full_name
                shopify_listing.category_assignment_status = 'ASSIGNED'
                shopify_listing.category_assigned_at = datetime.utcnow()

            await session.flush()

            logger.info(f"Created shopify_listings entry with ID {shopify_listing.id}")

            # Fetch full product data from Shopify to get the preview URL
            try:
                from app.services.shopify.client import ShopifyGraphQLClient
                shopify_client = ShopifyGraphQLClient()
                product_gid = f"gid://shopify/Product/{shopify_result.get('external_id')}"
                full_product = shopify_client.get_product_snapshot_by_id(product_gid)
                if full_product:
                    # Log all URL fields to see what Shopify returns
                    logger.info(f"Shopify API returned URLs:")
                    logger.info(f"  handle: {full_product.get('handle')}")
                    logger.info(f"  onlineStoreUrl: {full_product.get('onlineStoreUrl')}")
                    logger.info(f"  onlineStorePreviewUrl: {full_product.get('onlineStorePreviewUrl')}")

                    # Check which URL matches the expected format
                    if full_product.get('onlineStoreUrl'):
                        logger.info(f"  Using onlineStoreUrl for listing_url")
                        platform_common.listing_url = full_product.get('onlineStoreUrl')
                    elif full_product.get('onlineStorePreviewUrl'):
                        logger.info(f"  Using onlineStorePreviewUrl for listing_url")
                        platform_common.listing_url = full_product.get('onlineStorePreviewUrl')

                    logger.info(f"Final platform_common URL: {platform_common.listing_url}")
            except Exception as e:
                logger.warning(f"Could not fetch full product data: {e}")

            return {
                'success': True,
                'external_id': str(shopify_result.get('external_id', '')),
                'product_id': shopify_result.get('product_id'),
                'legacy_id': shopify_result.get('legacy_id')
            }
        else:
            return {
                'success': False,
                'error': shopify_result.get('error', 'Unknown Shopify error')
            }

    except Exception as e:
        logger.error(f"Shopify creation error: {e}", exc_info=True)
        return {
            'success': False,
            'error': str(e)
        }

async def _create_vr_listing(session: AsyncSession, product: Product, reverb_data: dict) -> dict:
    """Queue a V&R listing job for asynchronous processing."""
    try:
        payload = {
            "sync_source": "event_processor",
            "reverb_data": reverb_data or {},
        }
        job = await enqueue_vr_job(
            session,
            product_id=product.id,
            payload=payload,
        )
        await session.commit()
        logger.info("  ✅ Queued V&R job %s for product %s", job.id, product.sku)
        return {
            "success": True,
            "queued": True,
            "job_id": job.id,
            "needs_reconciliation": False,
        }
    except Exception as e:
        await session.rollback()
        logger.error(f"VR queueing error: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
        }

async def _process_status_change(
    session: AsyncSession,
    event: SyncEvent,
    platforms: Optional[List[str]]
) -> EventProcessingResult:
    """Process status change events - handles both sold/ended AND relist (live/active) scenarios.

    For relist scenarios (sold → live/active):
    - Updates local Reverb status to 'live'
    - Propagates relist to other platforms:
      - V&R: calls restore_from_sold()
      - eBay: calls relist_item() (returns new ItemID)
      - Shopify: sets status to ACTIVE and inventory to 1
    """
    result = EventProcessingResult()
    settings = get_settings()

    try:
        change_data = event.change_data or {}
        old_status = str(change_data.get('old', '')).lower()
        new_status = str(change_data.get('new', '')).lower()
        source_platform = (event.platform_name or '').lower()

        logger.info(f"Processing status_change event {event.id}: {old_status} → {new_status} (source: {source_platform})")

        # Determine if this is a RELIST scenario (sold/ended → live/active)
        off_market = ['sold', 'ended', 'removed', 'archived']
        on_market = ['live', 'active']

        is_relist = old_status in off_market and new_status in on_market
        is_ending = old_status in on_market and new_status in off_market

        if not is_relist and not is_ending:
            result.message = f"Status change {old_status} → {new_status} does not require cross-platform action"
            result.success = True
            return result

        # Get the product
        product = None
        if event.product_id:
            product = await session.get(Product, event.product_id)

        if not product:
            result.message = "No product associated with this event"
            result.success = False
            return result

        result.product_id = product.id

        # === RELIST SCENARIO ===
        if is_relist:
            logger.info(f"RELIST detected for product {product.sku}: {old_status} → {new_status}")

            # Calculate days since sold for Shopify logic
            days_since_sold = 0
            if event.detected_at:
                now_utc = datetime.now(timezone.utc)
                detected_at = event.detected_at
                # Handle timezone-naive datetimes from DB
                if detected_at.tzinfo is None:
                    detected_at = detected_at.replace(tzinfo=timezone.utc)
                days_since_sold = (now_utc - detected_at).days

            # Determine which platforms to update
            target_platforms = platforms or ['reverb', 'ebay', 'shopify', 'vr']
            # Remove the source platform - it's already relisted there
            target_platforms = [p for p in target_platforms if p.lower() != source_platform]

            # Get all platform listings for this product
            pc_query = select(PlatformCommon).where(PlatformCommon.product_id == product.id)
            pc_result = await session.execute(pc_query)
            platform_commons = {pc.platform_name: pc for pc in pc_result.scalars().all()}

            # --- Update source platform (Reverb) local status ---
            if source_platform == 'reverb' and 'reverb' not in target_platforms:
                reverb_pc = platform_commons.get('reverb')
                if reverb_pc:
                    reverb_pc.status = ListingStatus.ACTIVE.value
                    reverb_pc.sync_status = SyncStatus.SYNCED.value
                    reverb_pc.last_sync = datetime.utcnow()
                    session.add(reverb_pc)

                    # Update reverb_listings table
                    rl_query = select(ReverbListing).where(ReverbListing.platform_id == reverb_pc.id)
                    rl_result = await session.execute(rl_query)
                    reverb_listing = rl_result.scalar_one_or_none()
                    if reverb_listing:
                        reverb_listing.reverb_state = 'live'
                        reverb_listing.last_synced_at = datetime.utcnow()
                        session.add(reverb_listing)

                    result.platforms_created.append('reverb')
                    logger.info(f"Updated local Reverb status to 'live' for {product.sku}")

            # --- Propagate to V&R ---
            if 'vr' in target_platforms:
                vr_pc = platform_commons.get('vr')
                if vr_pc and vr_pc.external_id:
                    try:
                        vr_service = VRService(session)
                        vr_success = await vr_service.restore_from_sold(vr_pc.external_id)
                        if vr_success:
                            # Update platform_common status
                            vr_pc.status = ListingStatus.ACTIVE.value
                            vr_pc.sync_status = SyncStatus.SYNCED.value
                            vr_pc.last_sync = datetime.utcnow()
                            session.add(vr_pc)
                            result.platforms_created.append('vr')
                            logger.info(f"V&R relist successful for {product.sku}")
                        else:
                            result.platforms_failed.append('vr')
                            result.errors.append("V&R restore_from_sold returned False")
                    except Exception as e:
                        result.platforms_failed.append('vr')
                        result.errors.append(f"V&R error: {str(e)}")
                        logger.error(f"V&R relist failed for {product.sku}: {e}")
                else:
                    logger.info(f"No V&R listing found for {product.sku}, skipping")

            # --- Propagate to eBay ---
            if 'ebay' in target_platforms:
                ebay_pc = platform_commons.get('ebay')
                if ebay_pc and ebay_pc.external_id:
                    try:
                        from app.services.ebay.trading import EbayTradingLegacyAPI
                        ebay_api = EbayTradingLegacyAPI(sandbox=False)

                        # Use RelistFixedPriceItem for fixed-price listings (not RelistItem which is for auctions)
                        relist_response = await ebay_api.relist_fixed_price_item(ebay_pc.external_id)

                        ack = relist_response.get('Ack', '')
                        if ack in ['Success', 'Warning']:
                            # Get the new ItemID from response
                            new_item_id = relist_response.get('ItemID')
                            if new_item_id:
                                old_item_id = ebay_pc.external_id
                                now_utc = datetime.utcnow()

                                # Step 1: Find and orphan the OLD ebay_listings row
                                old_listing_query = select(EbayListing).where(
                                    EbayListing.ebay_item_id == old_item_id
                                )
                                old_listing_result = await session.execute(old_listing_query)
                                old_ebay_listing = old_listing_result.scalar_one_or_none()

                                if old_ebay_listing:
                                    # Orphan the old listing - remove link to platform_common
                                    old_ebay_listing.platform_id = None
                                    old_ebay_listing.listing_status = 'ENDED'
                                    old_ebay_listing.updated_at = now_utc

                                    # Add relist history to listing_data
                                    listing_data = old_ebay_listing.listing_data or {}
                                    listing_data['_relist_info'] = {
                                        'reason': 'cancelled_order',
                                        'relisted_to_item_id': new_item_id,
                                        'relisted_at': now_utc.isoformat(),
                                        'original_product_sku': product.sku,
                                        'original_product_id': product.id
                                    }
                                    old_ebay_listing.listing_data = listing_data
                                    session.add(old_ebay_listing)
                                    logger.info(f"Orphaned old eBay listing {old_item_id} with relist history")

                                # Step 2: Create NEW ebay_listings row linked to platform_common
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
                                session.add(new_ebay_listing)
                                logger.info(f"Created new eBay listing row for {new_item_id}")

                                # Step 3: Update platform_common with new external_id and URL
                                ebay_pc.external_id = new_item_id
                                ebay_pc.listing_url = f"https://www.ebay.co.uk/itm/{new_item_id}"
                                ebay_pc.status = ListingStatus.ACTIVE.value
                                ebay_pc.sync_status = SyncStatus.SYNCED.value
                                ebay_pc.last_sync = now_utc
                                session.add(ebay_pc)

                                result.platforms_created.append('ebay')
                                result.details['ebay_old_item_id'] = old_item_id
                                result.details['ebay_new_item_id'] = new_item_id
                                logger.info(f"eBay relist successful for {product.sku}: {old_item_id} → {new_item_id}")
                            else:
                                result.platforms_failed.append('ebay')
                                result.errors.append("eBay relist succeeded but no new ItemID returned")
                        else:
                            errors = relist_response.get('Errors', [])
                            error_msg = "; ".join([e.get('LongMessage', 'Unknown') for e in (errors if isinstance(errors, list) else [errors])])
                            result.platforms_failed.append('ebay')
                            result.errors.append(f"eBay relist failed: {error_msg}")
                            logger.error(f"eBay relist failed for {product.sku}: {error_msg}")
                    except Exception as e:
                        result.platforms_failed.append('ebay')
                        result.errors.append(f"eBay error: {str(e)}")
                        logger.error(f"eBay relist failed for {product.sku}: {e}")
                else:
                    logger.info(f"No eBay listing found for {product.sku}, skipping")

            # --- Propagate to Shopify ---
            if 'shopify' in target_platforms:
                shopify_pc = platform_commons.get('shopify')
                if shopify_pc and shopify_pc.external_id:
                    try:
                        shopify_service = ShopifyService(session)
                        shopify_result = await shopify_service.relist_listing(
                            shopify_pc.external_id,
                            days_since_sold=days_since_sold
                        )
                        if shopify_result.get('success'):
                            # Note: shopify_service.relist_listing() already updates platform_common internally
                            result.platforms_created.append('shopify')
                            result.details['shopify_status_updated'] = shopify_result.get('status_updated')
                            result.details['shopify_inventory_updated'] = shopify_result.get('inventory_updated')
                            logger.info(f"Shopify relist successful for {product.sku}")
                        else:
                            result.platforms_failed.append('shopify')
                            result.errors.append(f"Shopify relist failed: {shopify_result.get('message', 'Unknown')}")
                    except Exception as e:
                        result.platforms_failed.append('shopify')
                        result.errors.append(f"Shopify error: {str(e)}")
                        logger.error(f"Shopify relist failed for {product.sku}: {e}")
                else:
                    logger.info(f"No Shopify listing found for {product.sku}, skipping")

            # Update product status
            product.status = ProductStatus.ACTIVE
            session.add(product)

            # Mark event as processed
            event.status = 'processed'
            event.processed_at = datetime.utcnow()
            event.notes = f"Relist propagated to: {', '.join(result.platforms_created)}" if result.platforms_created else "No platforms updated"
            if result.platforms_failed:
                event.notes += f" | Failed: {', '.join(result.platforms_failed)}"
            session.add(event)

            await session.commit()

            result.success = len(result.platforms_failed) == 0
            result.message = f"Relist processed: {len(result.platforms_created)} platforms updated"
            if result.platforms_failed:
                result.message += f", {len(result.platforms_failed)} failed"

        # === ENDING SCENARIO (sold/ended) ===
        elif is_ending:
            # This is handled by other parts of the sync system
            # Just mark locally for now
            logger.info(f"ENDING detected for product {product.sku}: {old_status} → {new_status}")
            result.message = "Ending events are handled by the sync detection process"
            result.success = True

        return result

    except Exception as e:
        logger.error(f"Error processing status_change event {event.id}: {e}", exc_info=True)
        result.message = f"Error: {str(e)}"
        result.errors.append(str(e))
        result.success = False
        return result

async def _process_price_change(
    session: AsyncSession,
    event: SyncEvent,
    platforms: Optional[List[str]]
) -> EventProcessingResult:
    """Process price change events"""
    result = EventProcessingResult()
    result.message = "Price change processing not yet implemented in event_processor"
    result.success = False
    return result


async def _process_quantity_change(
    session: AsyncSession,
    event: SyncEvent
) -> EventProcessingResult:
    """Handle quantity_change events for platforms such as eBay."""
    result = EventProcessingResult()

    try:
        if not event.product_id:
            result.message = "Event is missing product_id, cannot adjust quantity."
            return result

        product = await session.get(Product, event.product_id)
        if not product:
            result.message = f"Product with ID {event.product_id} not found."
            return result

        change_data = event.change_data or {}
        new_quantity = change_data.get('new_quantity')
        if new_quantity is None:
            result.message = "Quantity change event missing new_quantity value."
            return result

        try:
            new_quantity_int = int(new_quantity)
        except (TypeError, ValueError):
            result.message = f"Invalid new quantity value: {new_quantity}"
            return result

        old_quantity = change_data.get('old_quantity')
        try:
            old_quantity_int = int(old_quantity) if old_quantity is not None else None
        except (TypeError, ValueError):
            old_quantity_int = None

        is_stocked_item = change_data.get('is_stocked_item', product.is_stocked_item)

        if is_stocked_item:
            product.quantity = new_quantity_int
            if new_quantity_int > 0 and product.status == ProductStatus.SOLD:
                product.status = ProductStatus.ACTIVE
            if new_quantity_int == 0:
                product.status = ProductStatus.SOLD
        else:
            if new_quantity_int == 0:
                product.status = ProductStatus.SOLD

        session.add(product)

        if event.platform_common_id:
            platform_link = await session.get(PlatformCommon, event.platform_common_id)
            if platform_link:
                platform_link.status = ListingStatus.ACTIVE.value if new_quantity_int > 0 else ListingStatus.ENDED.value
                platform_link.sync_status = SyncStatus.SYNCED.value
                session.add(platform_link)

            listing_stmt = select(EbayListing).where(EbayListing.platform_id == event.platform_common_id)
            listing = (await session.execute(listing_stmt)).scalar_one_or_none()
            if listing:
                listing.quantity_available = new_quantity_int
                total_quantity = change_data.get('total_quantity')
                if total_quantity is not None:
                    try:
                        listing.quantity = int(total_quantity)
                    except (TypeError, ValueError):
                        pass
                session.add(listing)

        result.success = True
        result.product_id = product.id
        result.details['old_quantity'] = old_quantity_int
        result.details['new_quantity'] = new_quantity_int
        result.message = f"Quantity updated to {new_quantity_int}"

    except Exception as e:
        await session.rollback()
        result.message = f"Error processing quantity change: {e}"
        logger.error(result.message, exc_info=True)
        result.errors.append(result.message)

    return result


async def reconcile_vr_listing_for_product(session: AsyncSession, product: Product):
    """
    Reconcile a single VR listing after creation.
    Fetches VR inventory and matches to find the real VR ID.
    """
    import pandas as pd
    from app.services.vintageandrare.client import VintageAndRareClient

    try:
        logger.info(f"  Attempting to reconcile VR listing for {product.sku}")

        # Get settings
        settings = get_settings()

        # Initialize VR client
        client = VintageAndRareClient(
            username=settings.VINTAGE_AND_RARE_USERNAME,
            password=settings.VINTAGE_AND_RARE_PASSWORD
        )

        # Clean up any existing temp files before starting
        client.cleanup_temp_files()

        # Authenticate
        if not await client.authenticate():
            logger.error("  VR authentication failed for reconciliation")
            return False

        # Download VR inventory
        logger.info("  Downloading VR inventory to find matching listing...")
        inventory_result = await client.download_inventory_dataframe(save_to_file=False)

        # Check if download needs retry
        if isinstance(inventory_result, str) and inventory_result == "RETRY_NEEDED":
            logger.warning("  VR inventory download exceeded timeout - skipping reconciliation")
            logger.info("  Reconciliation will be attempted during next scheduled batch run")
            return False

        if inventory_result is None or (isinstance(inventory_result, pd.DataFrame) and inventory_result.empty):
            logger.error("  Failed to download VR inventory")
            return False

        # At this point we know it's a DataFrame
        inventory_df = inventory_result

        # Filter for active listings
        active_df = inventory_df[inventory_df['product_sold'] != 'yes'].copy()

        # Get existing VR IDs to exclude
        stmt = select(VRListing.vr_listing_id).where(VRListing.vr_listing_id.isnot(None))
        result = await session.execute(stmt)
        existing_vr_ids = {str(row[0]) for row in result.fetchall()}

        # Look for new listings not in our database
        active_df['product_id'] = active_df['product_id'].astype(str)
        new_listings_df = active_df[~active_df['product_id'].isin(existing_vr_ids)]

        # Search for our product by matching title/brand/model
        matched = False
        vr_id = None

        # Try to match based on brand, model, price
        product_brand = (product.brand or '').lower().strip()
        product_model = (product.model or '').lower().strip()
        product_price = product.base_price or product.price

        best_match = None
        best_score = 0

        for idx, vr_row in new_listings_df.iterrows():
            vr_brand = str(vr_row.get('brand_name', '')).lower().strip()
            vr_model = str(vr_row.get('product_model_name', '')).lower().strip()
            vr_price = float(vr_row.get('product_price', 0))

            score = 0

            # Brand match (required)
            if product_brand and vr_brand and product_brand == vr_brand:
                score += 40
            else:
                continue

            # Model match
            if product_model and vr_model and product_model == vr_model:
                score += 40

            # Price match (within 5%)
            if product_price and vr_price:
                price_ratio = abs(vr_price - product_price) / max(vr_price, product_price)
                if price_ratio < 0.05:
                    score += 20

            if score > best_score:
                best_score = score
                best_match = vr_row

        if best_match is not None and best_score >= 60:
            vr_id = str(best_match['product_id'])
            matched = True
            logger.info(f"  ✅ Found matching VR listing: ID={vr_id}, Score={best_score}")
        else:
            logger.warning(f"  ❌ No matching VR listing found for: {product.title}")
            return False

        if matched and vr_id:
            # Update the platform_common and vr_listings with the real VR ID
            pc_stmt = select(PlatformCommon).where(
                PlatformCommon.product_id == product.id,
                PlatformCommon.platform_name == 'vr'
            )
            result = await session.execute(pc_stmt)
            platform_common = result.scalar_one_or_none()

            if platform_common:
                # Update external_id
                platform_common.external_id = vr_id

                # Update listing URL
                external_link = best_match.get('external_link')
                if pd.isna(external_link) or not external_link:
                    vr_url = f"https://www.vintageandrare.com/product/{vr_id}"
                else:
                    vr_url = str(external_link)
                platform_common.listing_url = vr_url
                platform_common.status = ListingStatus.ACTIVE.value
                platform_common.sync_status = SyncStatus.SYNCED.value

                # Update or create vr_listings entry
                vr_stmt = select(VRListing).where(VRListing.platform_id == platform_common.id)
                result = await session.execute(vr_stmt)
                vr_listing = result.scalar_one_or_none()

                if vr_listing:
                    vr_listing.vr_listing_id = vr_id
                    vr_listing.vr_state = 'active'
                    logger.info(f"  ✅ Updated VR listing with real ID: {vr_id}")
                else:
                    # Create vr_listings entry if missing
                    vr_listing = VRListing(
                        platform_id=platform_common.id,
                        vr_listing_id=vr_id,
                        price_notax=product.base_price,
                        processing_time=product.processing_time or 3,
                        vr_state='active'
                    )
                    session.add(vr_listing)
                    logger.info(f"  ✅ Created VR listing record with ID: {vr_id}")

                await session.flush()
                return True
            else:
                logger.error("  ❌ Platform common entry not found for VR")
                return False

        return False

    except Exception as e:
        logger.error(f"  ❌ VR reconciliation error: {e}", exc_info=True)
        return False


class EventProcessor:
    """Event processor class that wraps the standalone function for compatibility"""
    def __init__(self, session: AsyncSession, dry_run: bool = False):
        self.session = session
        self.dry_run = dry_run

    async def process_sync_event(self, event: SyncEvent) -> EventProcessingResult:
        """Process a sync event using the session from initialization"""
        # Call the standalone function with the event's ID
        return await process_sync_event(
            session=self.session,
            event_id=event.id,
            platforms=None,  # Process all platforms
            sandbox=self.dry_run
        )
