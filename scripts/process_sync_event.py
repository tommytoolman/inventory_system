#!/usr/bin/env python3
"""
Process a sync event for real - creates listings across all platforms.

Usage:
    python scripts/process_sync_event.py --event-id 12065
"""

import asyncio
import argparse
import sys
from pathlib import Path
from datetime import datetime, timezone
import json

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import async_session
from app.services.reverb_service import ReverbService
from app.services.ebay_service import EbayService
from app.services.shopify_service import ShopifyService
from app.services.vr_service import VRService
from app.core.config import get_settings
from app.models.sync_event import SyncEvent
from app.models.product import Product, ProductCondition
from app.models.reverb import ReverbListing
from app.models.platform_common import PlatformCommon
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


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
        
        # Check if download needs retry (check type first to avoid DataFrame comparison error)
        if isinstance(inventory_result, str) and inventory_result == "RETRY_NEEDED":
            logger.warning("  VR inventory download exceeded timeout - skipping reconciliation")
            logger.info("  Reconciliation will be attempted during next scheduled batch run")
            return False
        
        if inventory_result is None or (isinstance(inventory_result, pd.DataFrame) and inventory_result.empty):
            logger.error("  Failed to download VR inventory")
            return False
        
        # At this point we know it's a DataFrame
        inventory_df = inventory_result
        
        # Filter for active listings (use underscore column name from processed CSV)
        active_df = inventory_df[inventory_df['product_sold'] != 'yes'].copy()
        
        # Get existing VR IDs to exclude
        from app.models import VRListing as VrListing
        stmt = select(VrListing.vr_listing_id).where(VrListing.vr_listing_id.isnot(None))
        result = await session.execute(stmt)
        existing_ids = {str(row[0]) for row in result if row[0]}
        
        # Find new VR listings (use underscore column names)
        df_ids = set(active_df['product_id'].astype(str))
        new_ids = df_ids - existing_ids
        new_listings_df = active_df[active_df['product_id'].astype(str).isin(new_ids)]
        
        logger.info(f"  Found {len(new_listings_df)} new VR listings to check")
        
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
            vr_id = str(best_match['product_id'])  # Fixed: use underscore column name
            # Handle potential NaN in external_link
            external_link = best_match.get('external_link')
            if pd.isna(external_link) or not external_link:
                vr_url = f"https://www.vintageandrare.com/product/{vr_id}"
            else:
                vr_url = str(external_link)
            
            logger.info(f"  ✅ Matched to VR ID: {vr_id} (score: {best_score})")
            
            # Update platform_common
            pc_stmt = select(PlatformCommon).where(
                PlatformCommon.product_id == product.id,
                PlatformCommon.platform_name == 'vr'
            )
            pc_result = await session.execute(pc_stmt)
            platform_common = pc_result.scalar_one_or_none()
            
            if platform_common:
                logger.info(f"  Updating platform_common: external_id {platform_common.external_id} → {vr_id}")
                platform_common.external_id = vr_id
                platform_common.listing_url = vr_url
                
                # Sanitize NaN values in extended_attributes
                row_dict = best_match.to_dict() if hasattr(best_match, 'to_dict') else dict(best_match)
                sanitized_dict = {}
                for key, value in row_dict.items():
                    if pd.isna(value):
                        sanitized_dict[key] = None
                    else:
                        sanitized_dict[key] = value
                
                # Create vr_listings entry with underscore column names (as processed by CSV)
                vr_listing = VrListing(
                    platform_id=platform_common.id,
                    vr_listing_id=vr_id,
                    vr_state='active',
                    inventory_quantity=1,
                    in_collective=best_match.get('product_in_collective', '') == 'yes',
                    in_inventory=best_match.get('product_in_inventory', '') == 'yes',
                    in_reseller=best_match.get('product_in_reseller', '') == 'yes',
                    collective_discount=float(best_match.get('collective_discount', 0) or 0),
                    price_notax=float(best_match.get('product_price', 0) or 0),  # Using product_price as price_notax doesn't exist
                    show_vat=best_match.get('show_vat', '') == 'yes',
                    processing_time=int(best_match.get('processing_time', '3 Days').split()[0]) if isinstance(best_match.get('processing_time'), str) else 3,
                    last_synced_at=datetime.now(timezone.utc).replace(tzinfo=None),
                    extended_attributes=sanitized_dict  # Use sanitized dict
                )
                session.add(vr_listing)
                logger.info(f"  ✅ Created vr_listings entry for VR ID: {vr_id}")
                
                # Commit the reconciliation
                await session.commit()
                logger.info(f"  ✅ Reconciliation committed to database")
                return True
        else:
            logger.warning(f"  ❌ No VR match found (best score: {best_score})")
            logger.info("  Will need manual reconciliation or wait for next batch reconciliation")
            
    except Exception as e:
        logger.error(f"  Error during VR reconciliation: {e}")
        return False
    
    return False


async def process_event(event_id: int, retry_errors: bool = False, platforms: list = None, sandbox: bool = False):
    """Process a single sync event for real
    
    Args:
        event_id: The sync event ID to process
        retry_errors: If True, will retry events with 'error' status
        platforms: List of platforms to process (e.g., ['shopify', 'vr', 'ebay']). If None, process all.
        sandbox: If True, use eBay sandbox environment for testing
    """
    
    async with async_session() as session:
        # Get the sync event
        stmt = select(SyncEvent).where(SyncEvent.id == event_id)
        result = await session.execute(stmt)
        event = result.scalar_one_or_none()
        
        if not event:
            logger.error(f"Sync event {event_id} not found")
            return False
            
        # Check if we should process this event
        valid_statuses = ['pending']
        if retry_errors:
            valid_statuses.extend(['error', 'partial'])  # Allow retrying both error and partial
            
        if event.status not in valid_statuses:
            logger.warning(f"Sync event {event_id} has status '{event.status}' - skipping")
            return False
            
        # Extract retry count from notes if it exists
        retry_count = 0
        if event.notes:
            try:
                notes_data = json.loads(event.notes) if isinstance(event.notes, str) else event.notes
                retry_count = notes_data.get('retry_count', 0)
            except:
                pass
        
        if retry_count >= 3:
            logger.error(f"Sync event {event_id} has been retried {retry_count} times - marking as failed")
            event.status = 'failed'
            event.notes = json.dumps({
                'retry_count': retry_count,
                'last_error': 'Max retries exceeded'
            })
            await session.commit()
            return False
            
        logger.info(f"Processing sync event {event_id}: {event.change_type} for {event.platform_name} {event.external_id}")
        
        # Initialize services with db session and settings
        settings = get_settings()
        reverb_service = ReverbService(session, settings)
        ebay_service = EbayService(session, settings)
        shopify_service = ShopifyService(session, settings)
        vr_service = VRService(session)  # VRService only takes db
        
        try:
            # Step 1: Fetch Reverb API data
            logger.info(f"Fetching Reverb listing {event.external_id}...")
            # Use the client directly for fetching data
            from app.services.reverb.client import ReverbClient
            reverb_client = ReverbClient(
                api_key=settings.REVERB_API_KEY,
                use_sandbox=settings.REVERB_USE_SANDBOX
            )
            reverb_data = await reverb_client.get_listing_details(event.external_id)
            
            if not reverb_data:
                logger.error(f"Failed to fetch Reverb listing {event.external_id}")
                event.status = 'error'
                event.notes = "Failed to fetch Reverb listing data"
                await session.commit()
                return False
            
            # Step 2: Get or create product
            stmt = select(Product).where(Product.sku == f"REV-{event.external_id}")
            result = await session.execute(stmt)
            product = result.scalar_one_or_none()
            
            if product:
                logger.info(f"Found existing product {product.id}: {product.title}")
            else:
                # Create new product from Reverb data
                logger.info("Creating new product from Reverb data...")
                
                # Map condition
                condition_map = {
                    'excellent': ProductCondition.EXCELLENT,
                    'very_good': ProductCondition.VERYGOOD,  # Fixed: VERYGOOD not VERY_GOOD
                    'good': ProductCondition.GOOD,
                    'fair': ProductCondition.FAIR,
                    'poor': ProductCondition.POOR
                }
                condition_slug = reverb_data.get('condition', {}).get('slug', 'good')
                condition = condition_map.get(condition_slug, ProductCondition.GOOD)
                
                # Extract images from Reverb data and transform to MAX_RES
                from app.core.utils import ImageTransformer, ImageQuality
                photos = reverb_data.get('photos', [])
                logger.info(f"📸 Found {len(photos)} photos in Reverb data")
                primary_image = None
                additional_images = []
                if photos:
                    # Get the best quality version of each photo
                    for idx, photo in enumerate(photos):
                        links = photo.get('_links', {})
                        # Log available link types for first photo
                        if idx == 0:
                            logger.info(f"  Available link types in first photo: {list(links.keys())}")
                        # Try to get any available image URL - prefer 'full', fall back to others
                        image_url = (links.get('full', {}).get('href') or 
                                    links.get('large_crop', {}).get('href') or
                                    links.get('large', {}).get('href'))  # Keep 'large' as fallback
                        if image_url:
                            # Transform to MAX_RES for highest quality
                            max_res_url = ImageTransformer.transform_reverb_url(image_url, ImageQuality.MAX_RES)
                            if idx == 0:
                                primary_image = max_res_url
                                logger.info(f"  Primary image: {primary_image[:80]}...")
                            else:
                                additional_images.append(max_res_url)
                    logger.info(f"  Extracted {len(additional_images)} additional images")
                
                # Get price and ensure it's a float
                price_amount = reverb_data.get('price', {}).get('amount', 0)
                if isinstance(price_amount, str):
                    price_amount = float(price_amount)
                
                # Extract year and finish from Reverb data
                year_str = reverb_data.get('year', '')
                year = None
                if year_str:
                    # Try to extract a 4-digit year from strings like "1940s" or "1965"
                    import re
                    year_match = re.search(r'(\d{4})', str(year_str))
                    if year_match:
                        year = int(year_match.group(1))
                
                finish = reverb_data.get('finish', '')
                
                logger.info(f"📦 Creating product with:")
                logger.info(f"  SKU: REV-{event.external_id}")
                logger.info(f"  Brand: {reverb_data.get('make', '')}")
                logger.info(f"  Model: {reverb_data.get('model', '')}")
                logger.info(f"  Year: {year_str} -> {year}")
                logger.info(f"  Finish: {finish}")
                logger.info(f"  Price: {price_amount}")
                logger.info(f"  Primary image: {'Yes' if primary_image else 'No'}")
                logger.info(f"  Additional images: {len(additional_images)}")
                
                # Get category from reverb_data
                categories = reverb_data.get('categories', [])
                category_name = ' / '.join([cat.get('full_name', '') for cat in categories]) if categories else ''
                logger.info(f"  Category: {category_name if category_name else 'None'}")
                logger.info(f"  Quantity: 1 (default for single items)")
                
                # Calculate decade from year
                decade = None
                if year:
                    try:
                        decade = (int(year) // 10) * 10
                        logger.info(f"  Calculated decade: {decade}s from year {year}")
                    except (ValueError, TypeError):
                        logger.warning(f"  Could not calculate decade from year: {year}")
                
                product = Product(
                    sku=f"REV-{event.external_id}",
                    brand=reverb_data.get('make', ''),
                    model=reverb_data.get('model', ''),
                    year=year,  # Add year
                    decade=decade,  # Add calculated decade
                    finish=finish,  # Add finish
                    category=category_name,  # Add category
                    title=reverb_data.get('title', ''),
                    description=reverb_data.get('description', ''),
                    condition=condition,
                    base_price=price_amount,  # Now guaranteed to be float
                    price=price_amount,  # Also populate price field
                    status='ACTIVE',
                    is_stocked_item=False,  # Single items, not stock
                    quantity=1,  # Default quantity of 1
                    primary_image=primary_image,  # Store primary image
                    additional_images=additional_images  # Store additional images as list (will be JSONB)
                )
                logger.info("  Adding product to session...")
                session.add(product)
                logger.info("  Flushing session to get product ID...")
                await session.flush()
                logger.info(f"✅ Created new product with ID {product.id}")
                logger.info(f"  Product in DB - Primary: {product.primary_image[:50] if product.primary_image else 'None'}, Additional count: {len(product.additional_images) if product.additional_images else 0}")
            
            # Step 2b: Get or create platform_common entry for Reverb
            stmt = select(PlatformCommon).where(
                PlatformCommon.platform_name == 'reverb',
                PlatformCommon.external_id == event.external_id
            )
            result = await session.execute(stmt)
            reverb_common = result.scalar_one_or_none()
            
            if reverb_common:
                logger.info(f"Found existing platform_common entry for Reverb")
            else:
                # Construct Reverb listing URL
                reverb_url = f"https://reverb.com/item/{event.external_id}"
                
                reverb_common = PlatformCommon(
                    product_id=product.id,
                    platform_name='reverb',
                    external_id=event.external_id,
                    status='active',
                    last_sync=datetime.utcnow(),  # Fixed: last_sync not last_sync_at
                    sync_status='SYNCED',
                    listing_url=reverb_url,  # Add the Reverb URL
                    platform_specific_data=reverb_data  # Fixed: platform_specific_data not raw_data
                )
                session.add(reverb_common)
                await session.flush()
                logger.info("Created platform_common entry for Reverb")
            
            # Step 3: Create reverb_listings entry
            logger.info("Creating reverb_listings entry...")
            
            # Check if reverb_listings entry already exists
            stmt = select(ReverbListing).where(ReverbListing.reverb_listing_id == event.external_id)
            result = await session.execute(stmt)
            reverb_listing = result.scalar_one_or_none()
            
            if not reverb_listing:
                # Get platform_common id for this reverb listing
                stmt_pc = select(PlatformCommon).where(
                    PlatformCommon.platform_name == 'reverb',
                    PlatformCommon.external_id == event.external_id
                )
                result_pc = await session.execute(stmt_pc)
                platform_common = result_pc.scalar_one_or_none()
                
                if not platform_common:
                    logger.error(f"Platform common entry not found for Reverb listing {event.external_id}")
                    return False
                
                # Extract data matching the ReverbListing model structure
                categories = reverb_data.get('categories', [])
                category_uuid = categories[0].get('uuid', '') if categories else ''
                
                stats = reverb_data.get('stats', {})
                state_data = reverb_data.get('state', {})
                
                # Prepare extended attributes for additional data
                extended_attrs = {
                    'title': reverb_data.get('title', ''),
                    'make': reverb_data.get('make', ''),
                    'model': reverb_data.get('model', ''),
                    'finish': reverb_data.get('finish', ''),
                    'year': reverb_data.get('year', ''),
                    'serial_number': reverb_data.get('serial_number', ''),
                    'description': reverb_data.get('description', ''),
                    'shop_name': reverb_data.get('shop_name', ''),
                    'origin_country_code': reverb_data.get('origin_country_code', 'GB')
                }
                
                # Parse datetime strings
                import iso8601
                reverb_created_at = None
                reverb_published_at = None
                
                if reverb_data.get('created_at'):
                    reverb_created_at = iso8601.parse_date(reverb_data['created_at']).replace(tzinfo=None)
                if reverb_data.get('published_at'):
                    reverb_published_at = iso8601.parse_date(reverb_data['published_at']).replace(tzinfo=None)
                
                # Extract slug from web URL since API doesn't return slug field directly
                reverb_slug = ''
                web_href = reverb_data.get('_links', {}).get('web', {}).get('href', '')
                if web_href and '/item/' in web_href:
                    reverb_slug = web_href.split('/item/')[-1]
                    logger.info(f"  Extracted slug from URL: {reverb_slug}")
                
                # Map condition display_name to rating since API doesn't return rating
                condition_display = reverb_data.get('condition', {}).get('display_name', '').lower()
                condition_rating_map = {
                    'brand new': 5.0,
                    'mint': 5.0,
                    'near mint': 4.5,
                    'excellent': 4.5,
                    'very good': 4.0,
                    'very good plus': 4.0,
                    'good': 3.5,
                    'good plus': 3.5,
                    'fair': 3.0,
                    'poor': 2.5,
                    'non functioning': 1.0
                }
                condition_rating = condition_rating_map.get(condition_display, 3.5)  # Default to 3.5 (Good) if unknown
                logger.info(f"  Condition: {condition_display} -> Rating: {condition_rating}")
                
                reverb_listing = ReverbListing(
                    platform_id=platform_common.id,
                    reverb_listing_id=event.external_id,
                    reverb_slug=reverb_slug,
                    reverb_category_uuid=category_uuid,
                    condition_rating=condition_rating,
                    inventory_quantity=reverb_data.get('inventory', 1),
                    has_inventory=reverb_data.get('has_inventory', True),
                    offers_enabled=reverb_data.get('offers_enabled', True),
                    is_auction=reverb_data.get('auction', False),
                    list_price=float(reverb_data.get('price', {}).get('amount', 0)),
                    listing_currency=reverb_data.get('listing_currency', 'GBP'),
                    shipping_profile_id=reverb_data.get('shipping_profile', {}).get('id', '') if isinstance(reverb_data.get('shipping_profile'), dict) else '',
                    reverb_state=state_data.get('slug', 'live') if isinstance(state_data, dict) else 'live',
                    view_count=stats.get('views', 0) if isinstance(stats, dict) else 0,
                    watch_count=stats.get('watches', 0) if isinstance(stats, dict) else 0,
                    reverb_created_at=reverb_created_at,
                    reverb_published_at=reverb_published_at,
                    last_synced_at=datetime.now(timezone.utc).replace(tzinfo=None),
                    handmade=reverb_data.get('handmade', False),
                    extended_attributes=extended_attrs
                )
                session.add(reverb_listing)
                await session.flush()
                logger.info(f"Created reverb_listings entry with ID {reverb_listing.id}")
            else:
                logger.info(f"Reverb listing already exists with ID {reverb_listing.id}")
            
            # Step 4: Create listings on other platforms
            results = {
                'ebay': None,
                'shopify': None,
                'vr': None,
                'vr_reconciliation': None  # Track reconciliation separately
            }
            
            # Determine which platforms to process
            if platforms is None:
                platforms = ['ebay', 'shopify', 'vr']  # Default to all platforms
            else:
                # Normalize platform names to lowercase
                platforms = [p.lower() for p in platforms]
                logger.info(f"Processing only specified platforms: {platforms}")
            
            # Create eBay listing
            if 'ebay' in platforms:
                logger.info("\n=== Creating eBay listing ===")
                logger.info(f"  Sandbox mode: {sandbox}")
                try:
                    # Use the same logic as sync service and inventory route
                    policies = {
                        'shipping_profile_id': '252277357017',  # Default shipping profile (corrected)
                        'payment_profile_id': '252544577017',   # Default payment profile (corrected)
                        'return_profile_id': '252277356017'     # Default return profile
                    }
                    
                    # Check if product has specific eBay policies in platform_data
                    if hasattr(product, 'platform_data') and product.platform_data and 'ebay' in product.platform_data:
                        ebay_data = product.platform_data['ebay']
                        logger.info(f"  Found eBay platform data: {ebay_data}")
                        # Override with product-specific policies if they exist
                        if ebay_data.get('shipping_policy'):
                            policies['shipping_profile_id'] = ebay_data.get('shipping_policy')
                        if ebay_data.get('payment_policy'):
                            policies['payment_profile_id'] = ebay_data.get('payment_policy')
                        if ebay_data.get('return_policy'):
                            policies['return_profile_id'] = ebay_data.get('return_policy')
                    
                    logger.info(f"  Using eBay policies: {policies}")
                    
                    ebay_result = await ebay_service.create_listing_from_product(
                        product=product,
                        reverb_api_data=reverb_data,
                        sandbox=sandbox,
                        use_shipping_profile=True,  # Use Business Policies like inventory route
                        **policies  # Pass the policies
                    )
                    if ebay_result and ebay_result.get('ItemID'):
                        results['ebay'] = ebay_result['ItemID']
                        logger.info(f"✅ eBay listing created: {results['ebay']}")
                        
                        # Create platform_common entry for eBay
                        ebay_common = PlatformCommon(
                            product_id=product.id,
                            platform_name='ebay',
                            external_id=results['ebay'],
                            status='active',
                            last_sync=datetime.utcnow(),  # Fixed: last_sync not last_sync_at
                            sync_status='SYNCED',
                            platform_specific_data=ebay_result  # Fixed: platform_specific_data not raw_data
                        )
                        session.add(ebay_common)
                    else:
                        logger.error(f"❌ Failed to create eBay listing: {ebay_result}")
                except Exception as e:
                    logger.error(f"❌ Error creating eBay listing: {e}")
            else:
                logger.info("Skipping eBay (not in platforms list)")
                
            # Create Shopify listing
            if 'shopify' in platforms:
                logger.info("\n=== Creating Shopify listing ===")
                try:
                    shopify_result = await shopify_service.create_listing_from_product(
                        product=product,
                        reverb_data=reverb_data  # Pass Reverb data for image extraction
                    )
                    if shopify_result and shopify_result.get('status') == 'success':
                        results['shopify'] = str(shopify_result.get('external_id', ''))
                        logger.info(f"✅ Shopify product created: {results['shopify']}")
                        
                        # Generate handle for the product first (needed for listing_url)
                        import re
                        def generate_shopify_handle(brand: str, model: str, sku: str) -> str:
                            parts = [str(part) for part in [brand, model, sku] if part and str(part).lower() != 'nan']
                            text = '-'.join(parts).lower()
                            text = re.sub(r'[^a-z0-9\-]+', '-', text)
                            return text.strip('-')
                        
                        handle = generate_shopify_handle(
                            product.brand or '',
                            product.model if hasattr(product, 'model') else reverb_data.get('model', ''),
                            product.sku
                        )
                        
                        # Build the listing URL
                        listing_url = f"https://londonvintageguitars.myshopify.com/products/{handle}" if handle else None
                        
                        # Create platform_common entry for Shopify
                        shopify_common = PlatformCommon(
                            product_id=product.id,
                            platform_name='shopify',
                            external_id=results['shopify'],
                            status='active',
                            last_sync=datetime.utcnow(),  # Fixed: last_sync not last_sync_at
                            sync_status='SYNCED',
                            listing_url=listing_url,  # Add the listing URL
                            platform_specific_data=shopify_result  # Fixed: platform_specific_data not raw_data
                        )
                        session.add(shopify_common)
                        await session.flush()  # Flush to get the ID for the shopify_listings record
                        await session.refresh(shopify_common)  # Refresh to get the generated ID
                        
                        logger.info(f"Created platform_common record with ID: {shopify_common.id}, URL: {listing_url}")
                        
                        # Create shopify_listings entry
                        from app.models import ShopifyListing
                        
                        # Get category info from reverb_data if available
                        category_gid = None
                        category_name = None
                        if reverb_data:
                            categories = reverb_data.get('categories', [])
                            if categories and categories[0].get('uuid'):
                                category_uuid = categories[0]['uuid']
                                # Load category mappings
                                import json
                                try:
                                    with open('app/services/category_mappings/reverb_to_shopify.json', 'r') as f:
                                        mappings_data = json.load(f)
                                        mappings = mappings_data.get('mappings', {})
                                        if category_uuid in mappings:
                                            category_gid = mappings[category_uuid].get('shopify_gid')
                                            category_name = mappings[category_uuid].get('merchant_type')
                                except Exception:
                                    pass
                        
                        # Fetch full product data from Shopify for extended_attributes
                        extended_attrs = {}
                        try:
                            from app.services.shopify.client import ShopifyGraphQLClient
                            shopify_client = ShopifyGraphQLClient()
                            product_gid = f"gid://shopify/Product/{results['shopify']}"
                            full_product = shopify_client.get_product_snapshot_by_id(product_gid)
                            if full_product:
                                # get_product_snapshot_by_id returns the product directly, not wrapped
                                extended_attrs = full_product
                                # Add explicit URL fields
                                extended_attrs['url'] = full_product.get('onlineStorePreviewUrl')
                                extended_attrs['online_store_url'] = full_product.get('onlineStoreUrl')
                                extended_attrs['online_store_preview_url'] = full_product.get('onlineStorePreviewUrl')
                                logger.info(f"Fetched full product data for extended_attributes, URL: {extended_attrs.get('url')}")
                                
                                # Update listing_url in platform_common if we got a better URL
                                if full_product.get('onlineStorePreviewUrl'):
                                    shopify_common.listing_url = full_product.get('onlineStorePreviewUrl')
                                    logger.info(f"Updated platform_common URL to: {shopify_common.listing_url}")
                        except Exception as e:
                            logger.warning(f"Could not fetch full product data: {e}")
                        
                        # Extract category and SEO from Shopify API response if available
                        if extended_attrs:
                            shopify_category = extended_attrs.get('category', {})
                            if shopify_category:
                                category_gid = shopify_category.get('id') or category_gid
                                category_name = shopify_category.get('name') or category_name
                                category_full_name = shopify_category.get('fullName')
                            else:
                                category_full_name = None
                                
                            seo_data = extended_attrs.get('seo', {})
                            seo_title = seo_data.get('title')
                            seo_description = seo_data.get('description')
                        else:
                            category_full_name = None
                            seo_title = None
                            seo_description = None
                        
                        shopify_listing = ShopifyListing(
                            platform_id=shopify_common.id,  # This should now have the ID
                            shopify_product_id=f"gid://shopify/Product/{results['shopify']}",  # Full GID format
                            shopify_legacy_id=results['shopify'],
                            handle=handle,
                            title=product.title or f"{product.year or ''} {product.brand} {product.model}".strip(),
                            status='active',
                            vendor=product.brand,
                            price=float(product.base_price) if product.base_price else None,
                            category_gid=category_gid,
                            category_name=category_name,
                            category_full_name=category_full_name,
                            seo_title=seo_title,
                            seo_description=seo_description,
                            category_assigned_at=datetime.utcnow() if category_gid else None,
                            category_assignment_status='ASSIGNED' if category_gid else 'PENDING',
                            extended_attributes=extended_attrs,
                            last_synced_at=datetime.utcnow()
                        )
                        session.add(shopify_listing)
                    else:
                        logger.error(f"❌ Failed to create Shopify product: {shopify_result}")
                except Exception as e:
                    logger.error(f"❌ Error creating Shopify product: {e}")
            else:
                logger.info("Skipping Shopify (not in platforms list)")
                
            # Create VR listing
            if 'vr' in platforms:
                logger.info("\n=== Creating VR listing ===")
                try:
                    logger.info("📤 Step 1: Calling VR API to create listing on website...")
                    vr_result = await vr_service.create_listing_from_product(
                        product=product,
                        reverb_data=reverb_data
                    )
                    # Check for success status instead of id field
                    if vr_result and vr_result.get('status') == 'success':
                        # VR doesn't return ID immediately, but listing was created
                        results['vr'] = 'created'
                        logger.info(f"  ✅ VR listing created on website successfully")
                        
                        logger.info("💾 Step 2: Creating platform_common entry for VR...")
                        # Create platform_common entry for VR
                        # Use SKU as external_id since VR doesn't return ID immediately
                        vr_common = PlatformCommon(
                            product_id=product.id,
                            platform_name='vr',
                            external_id=product.sku,  # Use SKU temporarily
                            status='active',
                            last_sync=datetime.utcnow(),  # Fixed: last_sync not last_sync_at
                            sync_status='SYNCED',
                            platform_specific_data=vr_result  # Fixed: platform_specific_data not raw_data
                        )
                        session.add(vr_common)
                        await session.flush()  # Ensure it's saved
                        logger.info(f"  ✅ platform_common created with id={vr_common.id}")
                        
                        logger.info("⚠️  Step 3: VR doesn't return listing ID immediately - will reconcile later")
                    else:
                        logger.error(f"❌ Failed to create VR listing on website: {vr_result}")
                        results['vr'] = None
                except Exception as e:
                    logger.error(f"❌ Error creating VR listing: {e}")
                    results['vr'] = None
            else:
                logger.info("Skipping VR (not in platforms list)")
            
            # Step 5: Update sync event status based on results
            if sandbox:
                logger.info("\n🏖️ SANDBOX MODE - NOT updating sync_event status")
                logger.info(f"Would have set status based on results: {results}")
                return True  # Return success but don't update database
            
            # Step 5b: Update sync event status (only in production)
            # Only count platforms that were actually processed
            processed_platforms = [p for p in platforms if p in ['ebay', 'shopify', 'vr']]
            success_count = sum(1 for k, v in results.items() if k in processed_platforms and v)
            total_platforms = len(processed_platforms)
            
            # Check if VR reconciliation failed (which means VR is not fully complete)
            vr_fully_complete = True
            if 'vr' in processed_platforms and results.get('vr') == 'created':
                # If VR was created but reconciliation failed, it's not fully complete
                if results.get('vr_reconciliation') in ['failed', 'error', None]:
                    vr_fully_complete = False
                    success_count -= 1  # Reduce success count since VR isn't fully done
                    logger.warning("VR listing created but reconciliation failed - counting as incomplete")
            
            # Determine status based on success rate
            if success_count == total_platforms and vr_fully_complete:
                event.status = 'processed'
                logger.info(f"All {total_platforms} platforms succeeded - marking as processed")
            elif success_count > 0:
                event.status = 'partial'
                logger.warning(f"Only {success_count}/{total_platforms} platforms fully succeeded - marking as partial")
            else:
                event.status = 'error'
                logger.error(f"All platform creations failed - marking as error")
            
            event.processed_at = datetime.utcnow()
            notes_data = {
                'results': results,
                'success_count': success_count,
                'total_platforms': total_platforms,
                'retry_count': retry_count
            }
            # Only add reverb_listing_id if we have it
            if 'reverb_listing' in locals() and reverb_listing:
                notes_data['reverb_listing_id'] = reverb_listing.id
            
            event.notes = json.dumps(notes_data)
            
            # Commit all changes
            logger.info("💾 Committing all changes to database...")
            await session.commit()
            logger.info("✅ Transaction committed successfully")
            
            # Refresh product to verify images persisted
            logger.info("🔄 Refreshing product from database to verify data...")
            await session.refresh(product)
            logger.info(f"After refresh - Primary image: {product.primary_image[:50] if product.primary_image else 'None'}, Additional images: {len(product.additional_images) if product.additional_images else 0}")
            
            # Double check product exists in DB
            verify_stmt = select(Product).where(Product.id == product.id)
            verify_result = await session.execute(verify_stmt)
            verified_product = verify_result.scalar_one_or_none()
            if verified_product:
                logger.info(f"✅ Verified: Product {verified_product.id} with SKU {verified_product.sku} exists in database")
                logger.info(f"  Images: Primary={'Yes' if verified_product.primary_image else 'No'}, Additional={len(verified_product.additional_images) if verified_product.additional_images else 0}")
            else:
                logger.error(f"❌ ERROR: Product {product.id} not found in database after commit!")
            
            # Verify platform_common entries
            logger.info("\n📊 Verifying platform_common entries:")
            pc_stmt = select(PlatformCommon).where(PlatformCommon.product_id == product.id)
            pc_result = await session.execute(pc_stmt)
            platform_commons = pc_result.scalars().all()
            for pc in platform_commons:
                logger.info(f"  {pc.platform_name}: ID={pc.id}, external_id={pc.external_id}, status={pc.status}, sync_status={pc.sync_status}")
            
            # Verify platform-specific listing tables
            logger.info("\n📋 Verifying platform-specific listings:")
            # Check reverb_listings
            from app.models import ShopifyListing, VRListing as VrListing
            reverb_stmt = select(ReverbListing).join(PlatformCommon).where(PlatformCommon.product_id == product.id)
            reverb_result = await session.execute(reverb_stmt)
            reverb_listing_check = reverb_result.scalar_one_or_none()
            if reverb_listing_check:
                logger.info(f"  ✅ reverb_listings: ID={reverb_listing_check.id}, reverb_listing_id={reverb_listing_check.reverb_listing_id}")
            else:
                logger.info(f"  ❌ reverb_listings: NOT FOUND")
                
            # Check shopify_listings  
            shopify_stmt = select(ShopifyListing).join(PlatformCommon).where(PlatformCommon.product_id == product.id)
            shopify_result = await session.execute(shopify_stmt)
            shopify_listing_check = shopify_result.scalar_one_or_none()
            if shopify_listing_check:
                logger.info(f"  ✅ shopify_listings: ID={shopify_listing_check.id}, shopify_product_id={shopify_listing_check.shopify_product_id}")
            else:
                logger.info(f"  ❌ shopify_listings: NOT FOUND")
                
            # Check vr_listings
            vr_stmt = select(VrListing).join(PlatformCommon).where(PlatformCommon.product_id == product.id)
            vr_result = await session.execute(vr_stmt)
            vr_listing_check = vr_result.scalar_one_or_none()
            if vr_listing_check:
                logger.info(f"  ✅ vr_listings: ID={vr_listing_check.id}, vr_listing_id={vr_listing_check.vr_listing_id}")
            else:
                logger.info(f"  ❌ vr_listings: NOT FOUND (Known issue - needs fixing)")
            
            # Check sync_event status
            logger.info(f"\n🔄 Sync event {event.id} final status: {event.status}")
            
            # Step 8: VR Reconciliation - Match VR listing to get real ID
            if 'vr' in platforms and results.get('vr') == 'created':
                logger.info("\n=== VR Reconciliation (2nd API Call) ===")
                logger.info("🔍 Starting VR reconciliation to get real VR ID...")
                try:
                    reconciliation_success = await reconcile_vr_listing_for_product(session, product)
                    results['vr_reconciliation'] = 'success' if reconciliation_success else 'failed'
                    if reconciliation_success:
                        logger.info("✅ VR reconciliation completed successfully")
                    else:
                        logger.error("❌ VR reconciliation failed - will retry in next batch")
                except Exception as e:
                    logger.error(f"❌ VR reconciliation error: {e}")
                    results['vr_reconciliation'] = 'error'
            
            # Summary
            logger.info("\n" + "=" * 60)
            logger.info("PROCESSING COMPLETE")
            logger.info("=" * 60)
            logger.info(f"Product ID: {product.id}")
            logger.info(f"SKU: {product.sku}")
            logger.info(f"Reverb Listing: {reverb_listing.id}")
            logger.info(f"eBay: {'✅ ' + results['ebay'] if results['ebay'] else '❌ Failed'}")
            logger.info(f"Shopify: {'✅ ' + results['shopify'] if results['shopify'] else '❌ Failed'}")
            logger.info(f"VR: {'✅ ' + results['vr'] if results['vr'] else '❌ Failed'}")
            
            return True
            
        except Exception as e:
            logger.error(f"Error processing sync event: {e}", exc_info=True)
            
            # Update retry count
            retry_count += 1
            
            # Determine if this should be retryable or permanent failure
            if retry_count >= 3:
                event.status = 'failed'
                logger.error(f"Marking event {event_id} as failed after {retry_count} attempts")
            else:
                event.status = 'error'
                logger.warning(f"Marking event {event_id} as error (attempt {retry_count}/3)")
            
            import json  # Ensure json is imported
            event.notes = json.dumps({
                'retry_count': retry_count,
                'last_error': str(e),
                'last_error_time': datetime.now(timezone.utc).isoformat()
            })
            await session.commit()
            return False


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description='Process a sync event for real')
    parser.add_argument('--event-id', type=int, required=True, help='Sync event ID to process')
    parser.add_argument('--retry-errors', action='store_true', help='Retry events with error status')
    parser.add_argument('--vr-test-mode', action='store_true', help='Run V&R in test mode (fill form but do not submit)')
    parser.add_argument('--vr-no-headless', action='store_true', help='Run V&R browser in visible mode for debugging (default: headless)')
    parser.add_argument('--platforms', nargs='+', choices=['ebay', 'shopify', 'vr'], 
                        help='Specify which platforms to process (default: all)')
    parser.add_argument('--sandbox', action='store_true', 
                        help='Use eBay sandbox environment for testing')
    args = parser.parse_args()
    
    # Set the VR test mode environment variable if flag is passed
    if args.vr_test_mode:
        import os
        os.environ['VR_TEST_MODE'] = 'true'
    
    # Set the VR headless mode environment variable
    if args.vr_no_headless:
        import os
        os.environ['VR_HEADLESS'] = 'false'
    else:
        import os
        os.environ['VR_HEADLESS'] = 'true'
    
    success = asyncio.run(process_event(
        args.event_id, 
        retry_errors=args.retry_errors,
        platforms=args.platforms,
        sandbox=args.sandbox
    ))
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()