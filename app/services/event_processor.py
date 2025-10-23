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
        # Only process Reverb new listings for now
        if event.platform_name != 'reverb':
            result.message = f"New listing processing only supported for Reverb, not {event.platform_name}"
            return result

        # Check if product already exists with this SKU
        sku = f"REV-{event.external_id}"
        stmt = select(Product).where(Product.sku == sku)
        db_result = await session.execute(stmt)
        existing_product = db_result.scalar_one_or_none()

        if existing_product:
            logger.info(f"Found existing product {existing_product.id}: {existing_product.title}")
            product = existing_product
            result.product_id = product.id
        else:
            # Fetch Reverb listing data
            logger.info(f"Fetching Reverb listing {event.external_id}...")
            settings = get_settings()

            # Use the client directly for fetching data (matching original script)
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

        # Create platform_common entry for Reverb
        await _ensure_platform_common_reverb(session, product, reverb_listing_dict)

        # Determine which platforms to create listings on
        if platforms:
            platforms_to_create = [p for p in platforms if p != 'reverb']
        else:
            platforms_to_create = ['ebay', 'shopify', 'vr']

        logger.info(f"Creating listings on platforms: {platforms_to_create}")

        # Create listings on each platform
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

    # Get price amount
    price_amount = reverb_data.get('price', {}).get('amount', 0)
    if isinstance(price_amount, str):
        price_amount = float(price_amount)
    else:
        price_amount = float(price_amount)

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
        base_price=price_amount,  # Now guaranteed to be float
        price=price_amount,  # Also populate price field
        status='ACTIVE',
        is_stocked_item=False,  # Single items, not stock
        quantity=1,  # Default quantity of 1
        primary_image=primary_image,  # Store primary image
        additional_images=additional_images,  # Store additional images as list (will be JSONB)
        processing_time=processing_time
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
        sync_status='synced',
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
                sync_status='synced',
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
    """Create V&R listing with reconciliation"""
    try:
        vr_service = VRService(session)

        vr_result = await vr_service.create_listing_from_product(
            product=product,
            reverb_data=reverb_data
        )

        if vr_result.get('status') == 'success':
            logger.info("  ✅ VR listing created on website successfully")

            platform_common_id = vr_result.get('platform_common_id')
            if platform_common_id:
                if vr_result.get('needs_id_resolution'):
                    return {
                        'success': True,
                        'needs_reconciliation': True,
                        'platform_common_id': platform_common_id
                    }
                return {
                    'success': True,
                    'vr_id': vr_result.get('vr_listing_id')
                }

            # Fallback for legacy behaviour if service didn't persist data
            platform_common = PlatformCommon(
                product_id=product.id,
                platform_name='vr',
                external_id=product.sku,
                status='active',
                sync_status='pending',
                last_sync=datetime.utcnow()
            )
            session.add(platform_common)
            await session.flush()

            if vr_result.get('needs_id_resolution'):
                logger.info("  ⚠️  VR doesn't return listing ID immediately - will reconcile later")
                return {
                    'success': True,
                    'needs_reconciliation': True,
                    'platform_common_id': platform_common.id
                }
            else:
                return {
                    'success': True,
                    'vr_id': vr_result.get('vr_listing_id')
                }
        else:
            return {
                'success': False,
                'error': vr_result.get('message', 'Unknown VR error')
            }

    except Exception as e:
        logger.error(f"VR creation error: {e}", exc_info=True)
        return {
            'success': False,
            'error': str(e)
        }

async def _process_status_change(
    session: AsyncSession,
    event: SyncEvent,
    platforms: Optional[List[str]]
) -> EventProcessingResult:
    """Process status change events (sold, ended, removed)"""
    result = EventProcessingResult()
    result.message = "Status change processing not yet implemented in event_processor"
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
                    vr_listing.vr_state = 'live'
                    logger.info(f"  ✅ Updated VR listing with real ID: {vr_id}")
                else:
                    # Create vr_listings entry if missing
                    vr_listing = VRListing(
                        platform_id=platform_common.id,
                        vr_listing_id=vr_id,
                        price_notax=product.base_price,
                        processing_time=product.processing_time or 3,
                        vr_state='live'
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
