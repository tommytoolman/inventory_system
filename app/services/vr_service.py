# app/services/vintageandrare_service.py
import asyncio
import logging
import uuid
import pandas as pd
import json
from datetime import datetime, timezone
from typing import Optional, Dict, List, Any, Tuple
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.services.vintageandrare.client import VintageAndRareClient
from app.models.product import Product
from app.models.platform_common import PlatformCommon, ListingStatus
from app.models.vr import VRListing
from app.models.sync_event import SyncEvent

logger = logging.getLogger(__name__)

class VRService:
    """
    Service for handling the full Vintage & Rare inventory import and differential sync process.
    """
    
    # =========================================================================
    # 1. INITIALIZATION & HELPERS
    # =========================================================================
    def __init__(self, db: AsyncSession):
        self.db = db

    def _sanitize_for_json(self, obj: Any) -> Any:
        """Recursively check through a dictionary and replace NaN values with None."""
        if isinstance(obj, dict):
            return {k: self._sanitize_for_json(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._sanitize_for_json(i) for i in obj]
        elif pd.isna(obj):
            return None
        else:
            return obj
        

    # =========================================================================
    # 2. MAIN SYNC ENTRY POINT (DETECTION PHASE)
    # =========================================================================
    async def run_import_process(self, username: str, password: str, sync_run_id: uuid.UUID, save_only: bool = False):
        """Run the V&R inventory import process."""
        try:
            logger.info("Starting VRService.run_import_process")
            client = VintageAndRareClient(username, password, db_session=self.db)
            
            # Clean up any existing temp files before starting
            client.cleanup_temp_files()
            logger.info("Cleaned up any existing temp files before import process")
            
            logger.info("Attempting authentication with V&R...")
            if not await client.authenticate():
                logger.error("V&R authentication failed")
                return {"status": "error", "message": "V&R authentication failed"}
            
            logger.info("Authentication successful. Downloading inventory...")
            inventory_result = await client.download_inventory_dataframe(save_to_file=True)
            
            # Check if download needs retry (check type first to avoid DataFrame comparison error)
            if isinstance(inventory_result, str) and inventory_result == "RETRY_NEEDED":
                logger.warning("V&R inventory download exceeded timeout - needs retry during off-peak hours")
                return {"status": "retry_needed", "message": "V&R inventory download timeout - please retry during off-peak hours"}
            
            if inventory_result is None or (isinstance(inventory_result, pd.DataFrame) and inventory_result.empty):
                logger.error("V&R inventory download failed or returned empty.")
                return {"status": "error", "message": "No V&R inventory data received."}
            
            # At this point we know it's a DataFrame
            inventory_df = inventory_result
            
            logger.info(f"Successfully downloaded inventory with {len(inventory_df)} items")
            if save_only:
                return {"status": "success", "message": f"V&R inventory saved with {len(inventory_df)} records", "count": len(inventory_df)}
            
            logger.info("Processing inventory updates using differential sync...")
            sync_stats = await self.sync_vr_inventory(inventory_df, sync_run_id)

            logger.info(f"Inventory sync process complete: {sync_stats}")
            return {"status": "success", "message": "V&R inventory synced successfully.", **sync_stats}
        
        except Exception as e:
            logger.error(f"Exception in VintageAndRareService.run_import_process: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}


    # =========================================================================
    # 3. DIFFERENTIAL SYNC LOGIC
    # =========================================================================
    async def sync_vr_inventory(self, df: pd.DataFrame, sync_run_id: uuid.UUID) -> Dict[str, int]:
        """Main sync method - compares API data with DB and logs necessary changes."""
        stats = {"total_from_vr": len(df), "events_logged": 0, "created": 0, "updated": 0, "removed": 0, "unchanged": 0, "errors": 0}
        
        try:
            logger.info("Fetching existing V&R inventory from database...")
            existing_data = await self._fetch_existing_vr_data()
            
            api_items = self._prepare_api_data(df)
            db_items = self._prepare_db_data(existing_data)
            
            changes = self._calculate_changes(api_items, db_items)
            
            logger.info(f"Applying changes: {len(changes['create'])} new, {len(changes['update'])} updates, {len(changes['remove'])} removals")
            
            if changes['create']:
                stats['created'], events_created = await self._batch_create_products(changes['create'], sync_run_id)
                stats['events_logged'] += events_created
            if changes['update']:
                stats['updated'], events_updated = await self._batch_update_products(changes['update'], sync_run_id)
                stats['events_logged'] += events_updated
            if changes['remove']:
                stats['removed'], events_removed = await self._batch_mark_removed(changes['remove'], sync_run_id)
                stats['events_logged'] += events_removed
        
            stats['unchanged'] = len(api_items) - stats['created'] - stats['updated']
            logger.info(f"Sync complete: {stats}")
            
        except Exception as e:
            logger.error(f"Sync failed: {str(e)}", exc_info=True)
            stats['errors'] += 1
            raise
            
        return stats

    def _calculate_changes(self, api_items: Dict, db_items: Dict) -> Dict[str, List]:
        """Calculates create, update, and remove operations based on business rules."""
        changes = {'create': [], 'update': [], 'remove': []}
        api_ids = set(api_items.keys())
        db_ids = set(db_items.keys())
        
        for vr_id in api_ids - db_ids:
            api_item = api_items[vr_id]
            # Use the new 'status' field instead of the old 'is_sold' boolean
            if api_item.get('status') == 'active':
                changes['create'].append(api_item)

        for vr_id in api_ids & db_ids:
            if self._has_changed(api_items[vr_id], db_items[vr_id]):
                changes['update'].append({'api_data': api_items[vr_id], 'db_data': db_items[vr_id]})
        
        for vr_id in db_ids - api_ids:
            db_item = db_items[vr_id]
            # ONLY flag for removal if our database thinks the listing is currently active.
            if (db_item.get('platform_common_status') or '').lower() == 'active':
                changes['remove'].append(db_item)
            
        return changes
    
    def _has_changed_old(self, api_item: Dict, db_item: Dict) -> bool:
        """Check if an item has meaningful changes."""
        api_price = api_item['price']
        db_price = float(db_item.get('base_price') or 0)
        if abs(api_price - db_price) > 0.01:
            return True

        api_status = 'sold' if api_item['is_sold'] else 'active'
        db_vr_state = str(db_item.get('vr_state', '')).lower()
        if api_status != db_vr_state:
            return True
        
        return False

    def _has_changed(self, api_item: Dict, db_item: Dict) -> bool:
        """Compares API data against the new, correct fields from our database query."""
        api_status = (api_item.get('status') or '').lower()
        db_status = (db_item.get('platform_common_status') or '').lower()

        # Since V&R only has 'active' or 'sold', a simple comparison is enough.
        # if api_status != db_status:
        #     return True
        # BUT ... ended and sold need to be treated as equivalent for change detection.

        # --- ADD THIS NUANCED CHECK ---
        # Treat all 'off-market' statuses (sold, ended) as equivalent for detection.
        off_market_statuses = ['sold', 'ended', 'removed', 'deleted']
        statuses_match = (api_status in off_market_statuses and db_status in off_market_statuses) or \
                        (api_status == db_status)

        if not statuses_match:
            return True
        # --- END NUANCED CHECK ---
            
        db_price = float(db_item.get('base_price') or 0.0)
        if abs(api_item['price'] - db_price) > 0.01:
            return True

        return False

    # =========================================================================
    # 4. BATCH PROCESSING / EVENT LOGGING
    # =========================================================================
    async def _batch_create_products(self, items: List[Dict], sync_run_id: uuid.UUID) -> Tuple[int, int]:
        """Log rogue listings to sync_events only."""
        created_count, events_logged = 0, 0
        events_to_create = []
        for item in items:
            raw_data = item.get('_raw', {})
            event_data = {
                'sync_run_id': sync_run_id, 'platform_name': 'vr', 'product_id': None,
                'platform_common_id': None, 'external_id': item['external_id'], 'change_type': 'new_listing',
                'change_data': {
                    'title': f"{raw_data.get('brand_name', '')} {raw_data.get('product_model_name', '')}".strip(),
                    'price': item['price'],
                    'sku': f"VR-{item['external_id']}",
                    'is_sold': item['status'] == 'sold',
                    'listing_url': raw_data.get('external_link'),
                    'extended_attributes': raw_data},
                'status': 'pending'}
            events_to_create.append(event_data)
            created_count += 1
        
        if events_to_create:
            try:
                stmt = insert(SyncEvent).values(events_to_create)
                stmt = stmt.on_conflict_do_nothing(
                    index_elements=['platform_name', 'external_id', 'change_type'],
                    index_where=(SyncEvent.status == 'pending'))
                await self.db.execute(stmt)
                events_logged = len(events_to_create)
                logger.info(f"Attempted to log {len(events_to_create)} new listing events (duplicates ignored)")
            except Exception as e:
                logger.error(f"Failed to bulk insert new listing events: {e}", exc_info=True)
        return created_count, events_logged

    async def _batch_update_products_old(self, items: List[Dict], sync_run_id: uuid.UUID) -> Tuple[int, int]:
        """Log price and status changes to sync_events."""
        updated_count, events_logged = 0, 0
        all_events = []
        for item in items:
            api_data, db_data = item['api_data'], item['db_data']
            
            db_price_for_compare = float(db_data.get('base_price') or 0.0)
            if abs(api_data['price'] - db_price_for_compare) > 0.01:
                all_events.append({
                    'sync_run_id': sync_run_id, 'platform_name': 'vr', 'product_id': db_data['product_id'],
                    'platform_common_id': db_data['platform_common_id'], 'external_id': api_data['vr_id'],
                    'change_type': 'price', 'change_data': {'old': db_data.get('base_price'), 'new': api_data['price'], 'vr_id': api_data['vr_id']},
                    'status': 'pending'})
            
            api_status = 'sold' if api_data['is_sold'] else 'active'
            db_vr_state = str(db_data.get('vr_state', '')).lower()
            if api_status != db_vr_state:
                all_events.append({
                    'sync_run_id': sync_run_id, 'platform_name': 'vr', 'product_id': db_data['product_id'],
                    'platform_common_id': db_data['platform_common_id'], 'external_id': api_data['vr_id'],
                    'change_type': 'status_change', 'change_data': {'old': db_vr_state, 'new': api_status, 'vr_id': api_data['vr_id'], 'is_sold': api_data['is_sold']},
                    'status': 'pending'})
            updated_count += 1
        
        if all_events:
            try:
                stmt = insert(SyncEvent).values(all_events)
                stmt = stmt.on_conflict_do_nothing(
                    index_elements=['platform_name', 'external_id', 'change_type'],
                    index_where=(SyncEvent.status == 'pending'))
                await self.db.execute(stmt)
                events_logged = len(all_events)
                logger.info(f"Attempted to log {len(all_events)} update events (duplicates ignored)")
            except Exception as e:
                logger.error(f"Failed to bulk insert update events: {e}", exc_info=True)
        return updated_count, events_logged

    async def _batch_update_products(self, items: List[Dict], sync_run_id: uuid.UUID) -> Tuple[int, int]:
        """Logs price and status changes, prioritizing the 'sold' status."""
        updated_count, events_logged = 0, 0
        all_events = []
        
        for item in items:
            try:
                api_data, db_data = item['api_data'], item['db_data']

                api_status = (api_data.get('status') or '').lower()
                db_status = (db_data.get('platform_common_status') or '').lower()

                # --- NEW PRIORITIZATION LOGIC ---

                # First, check for a status change.
                off_market_statuses = ['sold', 'ended']
                statuses_match = (api_status in off_market_statuses and db_status in off_market_statuses) or (api_status == db_status)

                has_status_change = not statuses_match
                new_status_is_sold = (api_status == 'sold')

                if has_status_change:
                    all_events.append({
                        'sync_run_id': sync_run_id, 'platform_name': 'vr',
                        'product_id': db_data['product_id'], 'platform_common_id': db_data['platform_common_id'],
                        'external_id': api_data['external_id'], 'change_type': 'status_change',
                        'change_data': {'old': db_status, 'new': api_status},
                        'status': 'pending'
                    })

                # Only check for a price change if the item has NOT just been marked as sold.
                if not new_status_is_sold:
                    db_price_for_compare = float(db_data.get('base_price') or 0.0)
                    if abs(api_data['price'] - db_price_for_compare) > 0.01:
                        all_events.append({
                            'sync_run_id': sync_run_id, 'platform_name': 'vr',
                            'product_id': db_data['product_id'], 'platform_common_id': db_data['platform_common_id'],
                            'external_id': api_data['external_id'], 'change_type': 'price',
                            'change_data': {'old': db_data.get('base_price'), 'new': api_data['price']},
                            'status': 'pending'
                        })
                # --- END NEW LOGIC ---

                updated_count += 1
            except Exception as e:
                logger.error(f"Failed to prepare events for V&R item {item['api_data']['external_id']}: {e}", exc_info=True)
        
        # Bulk insert logic remains the same
        if all_events:
            stmt = insert(SyncEvent).values(all_events)
            stmt = stmt.on_conflict_do_nothing(
                index_elements=['platform_name', 'external_id', 'change_type'],
                index_where=(SyncEvent.status == 'pending')
            )
            await self.db.execute(stmt)
            events_logged = len(all_events)

        return updated_count, events_logged

    async def _batch_mark_removed(self, items: List[Dict], sync_run_id: uuid.UUID) -> Tuple[int, int]:
        """Log removal events to sync_events."""
        removed_count, events_logged = 0, 0
        events_to_create = []
        for item in items:
            events_to_create.append({
                'sync_run_id': sync_run_id, 'platform_name': 'vr', 'product_id': item['product_id'],
                'platform_common_id': item['platform_common_id'], 'external_id': item['external_id'],
                'change_type': 'removed_listing', 'change_data': {'sku': item['sku'], 'vr_id': item['external_id'], 'reason': 'not_found_in_api'},
                'status': 'pending'})
            removed_count += 1
        
        if events_to_create:
            try:
                stmt = insert(SyncEvent).values(events_to_create)
                stmt = stmt.on_conflict_do_nothing(
                    index_elements=['platform_name', 'external_id', 'change_type'],
                    index_where=(SyncEvent.status == 'pending'))
                await self.db.execute(stmt)
                events_logged = len(events_to_create)
                logger.info(f"Attempted to log {len(events_to_create)} removal events (duplicates ignored)")
            except Exception as e:
                logger.error(f"Failed to bulk insert removal events: {e}", exc_info=True)
        return removed_count, events_logged

    # =========================================================================
    # 5. OUTBOUND ACTIONS (ACTION PHASE)
    # =========================================================================
    async def mark_item_as_sold(self, external_id: str) -> bool:
        """Marks an item as sold on the V&R platform via an AJAX call."""
        logger.info(f"Received request to mark V&R item {external_id} as sold.")
        settings = get_settings()
        client = VintageAndRareClient(settings.VINTAGE_AND_RARE_USERNAME, settings.VINTAGE_AND_RARE_PASSWORD, db_session=self.db)
        
        try:
            if not await client.authenticate():
                logger.error(f"Authentication failed for marking item {external_id} as sold.")
                return False
            result = await client.mark_item_as_sold(external_id)
            if result:
                return result.get("success", False)
            return False
        except Exception as e:
            logger.error(f"Exception while marking V&R item {external_id} as sold: {e}", exc_info=True)
            return False

    async def create_listing_from_product(self, product: Product, reverb_data: Dict[str, Any] = None) -> Dict[str, Any]:
        """Creates a Vintage & Rare listing from a local master Product object."""
        logger.info(f"Creating V&R listing for Product ID: {product.id}, SKU: {product.sku}")
        try:
            settings = get_settings()
            # Initialize client WITHOUT db_session like the working script
            client = VintageAndRareClient(
                username=settings.VINTAGE_AND_RARE_USERNAME, 
                password=settings.VINTAGE_AND_RARE_PASSWORD
            )
            
            # Authenticate with V&R - no timeout, just like the working script
            if not await client.authenticate():
                logger.error("Failed to authenticate with V&R")
                return {"status": "error", "message": "V&R authentication failed"}
            
            # Prepare product data for V&R (similar to CSV uploader)
            product_data = {
                'sku': product.sku,
                'brand': product.brand or '',
                'model': product.model or '',
                'price': str(product.base_price) if product.base_price else '0',
                'year': str(product.year) if product.year else None,  # Pass None not empty string for Selenium check
                'finish': product.finish if product.finish else None,  # Pass None not empty string for Selenium check
                'description': product.description or '',
                'external_id': product.sku,  # Use SKU as external ID for V&R
                
                # V&R specific fields with defaults
                'show_vat': True,
                'call_for_price': False,
                'in_collective': False,
                'in_inventory': True,
                'in_reseller': False,
                'buy_now': False,
                'processing_time': '3',
                'time_unit': 'Days',
                'shipping': True,
                'local_pickup': False,
            }
            
            # Add shipping fees (use defaults or extract from reverb_data if available)
            if reverb_data and 'shipping' in reverb_data:
                # Try to extract shipping from Reverb data
                shipping_rates = reverb_data.get('shipping', {}).get('rates', [])
                shipping_fees = {
                    'europe': '50',
                    'usa': '100', 
                    'uk': '45',
                    'world': '150'
                }
                
                for rate in shipping_rates:
                    region = rate.get('region_code', '')
                    amount = rate.get('rate', {}).get('amount', '')
                    if region == 'GB' and amount:
                        shipping_fees['uk'] = str(int(float(amount)))
                    elif region == 'US' and amount:
                        shipping_fees['usa'] = str(int(float(amount)))
                    elif region in ['EUR_EU', 'EU'] and amount:
                        shipping_fees['europe'] = str(int(float(amount)))
                    elif region == 'XX' and amount:
                        shipping_fees['world'] = str(int(float(amount)))
                
                product_data['shipping_fees'] = shipping_fees
            else:
                # Default shipping fees
                product_data['shipping_fees'] = {
                    'europe': '50',
                    'usa': '100',
                    'uk': '45',
                    'world': '150'
                }
            
            # Extract images from Reverb API data and transform to MAX_RES
            all_images = []
            
            # Import image transformation utilities
            from app.core.utils import ImageTransformer, ImageQuality
            
            # First try to get images from reverb_data (preferred source)
            if reverb_data:
                # Check for cloudinary_photos (high quality images)
                cloudinary_photos = reverb_data.get('cloudinary_photos', [])
                if cloudinary_photos:
                    logger.info(f"Found {len(cloudinary_photos)} Cloudinary photos from Reverb")
                    for photo in cloudinary_photos[:20]:  # V&R limit is 20 images
                        image_url = None
                        if 'preview_url' in photo:
                            # Use preview_url which is typically higher resolution
                            image_url = photo['preview_url']
                        elif 'url' in photo:
                            image_url = photo['url']
                        
                        if image_url:
                            # Transform to MAX_RES for V&R
                            max_res_url = ImageTransformer.transform_reverb_url(image_url, ImageQuality.MAX_RES)
                            all_images.append(max_res_url)
                            logger.info(f"Transformed image: {image_url[:50]}... -> {max_res_url[:50]}...")
                
                # Fallback to regular photos if no cloudinary photos
                if not all_images:
                    photos = reverb_data.get('photos', [])
                    if photos:
                        logger.info(f"Found {len(photos)} regular photos from Reverb")
                        for photo in photos[:20]:  # V&R limit is 20 images
                            image_url = None
                            if isinstance(photo, dict) and '_links' in photo:
                                # Extract the large version if available
                                if 'large_crop' in photo['_links']:
                                    image_url = photo['_links']['large_crop']['href']
                                elif 'full' in photo['_links']:
                                    image_url = photo['_links']['full']['href']
                            elif isinstance(photo, str):
                                image_url = photo
                            
                            if image_url:
                                # Transform to MAX_RES for V&R
                                max_res_url = ImageTransformer.transform_reverb_url(image_url, ImageQuality.MAX_RES)
                                all_images.append(max_res_url)
                                logger.info(f"Transformed image: {image_url[:50]}... -> {max_res_url[:50]}...")
                
                logger.info(f"Extracted and transformed {len(all_images)} images from Reverb data")
            
            # Fallback to product's stored images if no Reverb data
            if not all_images:
                if product.primary_image:
                    # Transform stored image to MAX_RES
                    max_res_url = ImageTransformer.transform_reverb_url(product.primary_image, ImageQuality.MAX_RES)
                    all_images.append(max_res_url)
                if hasattr(product, 'additional_images') and product.additional_images:
                    # Transform all additional images to MAX_RES
                    for img_url in product.additional_images:
                        max_res_url = ImageTransformer.transform_reverb_url(img_url, ImageQuality.MAX_RES)
                        all_images.append(max_res_url)
                logger.info(f"Using and transformed {len(all_images)} images from product record")
            
            # Set primary_image and additional_images in the format expected by VR client
            if all_images:
                product_data['primary_image'] = all_images[0]
                product_data['additional_images'] = all_images[1:] if len(all_images) > 1 else []
                logger.info(f"Set primary_image and {len(product_data['additional_images'])} additional_images")
            else:
                product_data['primary_image'] = ''
                product_data['additional_images'] = []
                logger.warning("No images available for VR listing")
            
            # Map category using database lookups from platform_category_mappings
            # Get Reverb category UUID from reverb_data if available
            reverb_category_uuid = None
            if reverb_data:
                categories = reverb_data.get('categories', [])
                if categories and len(categories) > 0:
                    reverb_category_uuid = categories[0].get('uuid')
            
            # Default category IDs (as fallback)
            category_ids = {
                'Category': '51',  # Default to Guitars
                'SubCategory1': '83',  # Default to Electric solid body
                'SubCategory2': None,
                'SubCategory3': None
            }
            
            # If we have a Reverb category UUID, look up the VR category IDs
            if reverb_category_uuid:
                logger.info(f"Looking up V&R category IDs for Reverb UUID: {reverb_category_uuid}")
                
                # Query platform_category_mappings for VR category IDs
                # Use the specific VR category columns instead of parsing a string
                query = text("""
                    SELECT vr_category_id, vr_subcategory_id, 
                           vr_sub_subcategory_id, vr_sub_sub_subcategory_id
                    FROM platform_category_mappings
                    WHERE source_platform = 'reverb'
                      AND target_platform = 'vintageandrare'
                      AND source_category_id = :reverb_uuid
                    LIMIT 1
                """)
                
                result = await self.db.execute(query, {"reverb_uuid": reverb_category_uuid})
                mapping = result.fetchone()
                
                if mapping:
                    logger.info(f"Found V&R mapping: cat={mapping.vr_category_id}, "
                              f"subcat={mapping.vr_subcategory_id}, "
                              f"sub_subcat={mapping.vr_sub_subcategory_id}, "
                              f"sub_sub_subcat={mapping.vr_sub_sub_subcategory_id}")
                    
                    # Use the specific category IDs from the mapping
                    if mapping.vr_category_id:
                        category_ids['Category'] = str(mapping.vr_category_id)
                    if mapping.vr_subcategory_id:
                        category_ids['SubCategory1'] = str(mapping.vr_subcategory_id)
                    # These are optional - only set if they exist
                    if mapping.vr_sub_subcategory_id:
                        category_ids['SubCategory2'] = str(mapping.vr_sub_subcategory_id)
                    else:
                        category_ids['SubCategory2'] = None
                    if mapping.vr_sub_sub_subcategory_id:
                        category_ids['SubCategory3'] = str(mapping.vr_sub_sub_subcategory_id)
                    else:
                        category_ids['SubCategory3'] = None
                    
                    logger.info(f"Mapped V&R category IDs: {category_ids}")
                else:
                    logger.warning(f"No V&R category mapping found for Reverb UUID: {reverb_category_uuid}")
            else:
                logger.warning("No Reverb category UUID available, using default V&R categories")
            
            # Set the category IDs in product_data
            product_data['Category'] = category_ids['Category']
            product_data['SubCategory1'] = category_ids['SubCategory1']
            product_data['SubCategory2'] = category_ids['SubCategory2']
            product_data['SubCategory3'] = category_ids['SubCategory3']
            
            # Create the listing using Selenium
            # Check for test mode from environment variable
            import os
            test_mode = os.getenv('VR_TEST_MODE', 'false').lower() == 'true'
            
            logger.info(f"Creating V&R listing via Selenium for SKU: {product.sku} (test_mode={test_mode})")
            result = await client.create_listing_selenium(
                product_data=product_data,
                test_mode=test_mode,
                from_scratch=False,  # Using category strings, not IDs
                db_session=None  # Same as working script
            )
            
            logger.info(f"V&R creation result: {result}")
            return result
            
        except Exception as e:
            logger.error(f"Exception while creating V&R listing for SKU {product.sku}: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}

    async def update_listing_price(self, external_id: str, new_price: float) -> bool:
        """Outbound action to update the price of a listing on the V&R platform."""
        logger.info(f"Received request to update V&R listing {external_id} to price £{new_price:.2f}.")
        settings = get_settings()
        # Note: The db_session is now passed during client initialization
        client = VintageAndRareClient(settings.VINTAGE_AND_RARE_USERNAME, settings.VINTAGE_AND_RARE_PASSWORD, db_session=self.db)
        
        try:
            update_data = {'product_price': f"{new_price:.2f}"}
            result = await client.update_item_details(external_id, update_data)

            return result.get("success", False)
        except Exception as e:
            logger.error(f"Exception while updating price for V&R item {external_id}: {e}", exc_info=True)
            return False

    # =========================================================================
    # 6. DATA PREPARATION & FETCHING HELPERS
    # =========================================================================
    async def _fetch_existing_vr_data_old(self) -> List[Dict]:
        """Fetches all V&R-related data from the local database."""
        query = text("""
            WITH vr_data AS (
                SELECT DISTINCT ON (vl.vr_listing_id)
                    p.id as product_id, p.sku, p.base_price, p.description, p.status as product_status,
                    pc.id as platform_common_id, pc.external_id, pc.status as platform_common_status,
                    vl.id as vr_listing_id, vl.vr_state, vl.price_notax
                FROM vr_listings vl
                JOIN platform_common pc ON pc.id = vl.platform_id AND pc.platform_name = 'vr'
                LEFT JOIN products p ON p.id = pc.product_id
                ORDER BY vl.vr_listing_id, vl.id DESC
            )
            SELECT product_id, sku, base_price, description, product_status,
                   platform_common_id, external_id, platform_common_status,
                   vr_listing_id, vr_state, price_notax
            FROM vr_data
            UNION ALL
            SELECT p.id as product_id, p.sku, p.base_price, p.description, p.status as product_status,
                   pc.id as platform_common_id, pc.external_id, pc.status as platform_common_status,
                   NULL as vr_listing_id, NULL as vr_state, NULL as price_notax
            FROM platform_common pc
            LEFT JOIN products p ON p.id = pc.product_id
            WHERE pc.platform_name = 'vr' AND NOT EXISTS (SELECT 1 FROM vr_listings vl WHERE vl.platform_id = pc.id)
        """)
        result = await self.db.execute(query)
        return [row._asdict() for row in result.fetchall()]
    
    async def _fetch_existing_vr_data(self) -> List[Dict]:
        """Fetches all V&R-related data from the local database, focusing on the source of truth."""
        query = text("""
            SELECT 
                p.id as product_id, 
                p.sku, 
                p.base_price, -- For price comparison
                pc.id as platform_common_id, 
                pc.external_id, 
                pc.status as platform_common_status -- This is our source of truth
            FROM platform_common pc
            LEFT JOIN products p ON p.id = pc.product_id
            WHERE pc.platform_name = 'vr'
        """)
        result = await self.db.execute(query)
        return [row._asdict() for row in result.fetchall()]    
    
    def _prepare_api_data_old(self, df: pd.DataFrame) -> Dict[str, Dict]:
        """Convert API DataFrame to a clean lookup dict by VR ID."""
        api_items = {}
        for _, row in df.iterrows():
            vr_id = str(row.get('product_id', ''))
            if not vr_id:
                continue
            
            clean_row = self._sanitize_for_json(row.to_dict())
            api_items[vr_id] = {
                'vr_id': vr_id, 'sku': f"VR-{vr_id}",
                'price': float(clean_row.get('product_price', 0) or 0),
                'is_sold': str(clean_row.get('product_sold', '')).lower() == 'yes',
                'brand': clean_row.get('brand_name') or 'Unknown',
                'model': clean_row.get('product_model_name') or 'Unknown',
                'description': clean_row.get('product_description') or '',
                'category': clean_row.get('category_name'),
                'year': int(clean_row['product_year']) if clean_row.get('product_year') else None,
                'image_url': clean_row.get('image_url'),
                'listing_url': clean_row.get('external_link'),
                'extended_attributes': clean_row}
        return api_items
    
    def _prepare_api_data(self, df: pd.DataFrame) -> Dict[str, Dict]:
        """Convert API DataFrame to a clean lookup dict and translate status."""
        api_items = {}
        for _, row in df.iterrows():
            vr_id = str(row.get('product_id', ''))
            if not vr_id:
                continue
            
            clean_row = self._sanitize_for_json(row.to_dict())
            
            # Translate V&R's 'yes'/'no' for sold into our universal status
            is_sold = str(clean_row.get('product_sold', '')).lower() == 'yes'
            universal_status = 'sold' if is_sold else 'active'

            api_items[vr_id] = {
                'external_id': vr_id,
                'status': universal_status, # Use the translated status
                'price': float(clean_row.get('product_price', 0) or 0),
                '_raw': clean_row
            }
        return api_items
    
    def _prepare_db_data(self, existing_data: List[Dict]) -> Dict[str, Dict]:
        """Convert DB data to lookup dict by external ID."""
        return {str(row['external_id']): row for row in existing_data if row.get('external_id')}
