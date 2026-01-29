# app/services/vintageandrare_service.py
import asyncio
import logging
import os
import uuid
import pandas as pd
import json
from datetime import datetime, timezone
from typing import Optional, Dict, List, Any, Tuple, Set
from sqlalchemy import text, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.services.vintageandrare.client import VintageAndRareClient
from app.models.product import Product
from app.models.platform_common import PlatformCommon, ListingStatus, SyncStatus
from app.models.vr import VRListing
from app.services.match_utils import suggest_product_match
from app.models.sync_event import SyncEvent
from app.models.shipping import ShippingProfile

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
        self.settings = get_settings()

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

    async def _get_platform_status(self, product_id: int, platform_name: str) -> Optional[str]:
        """Fetch the current status for a given platform listing from platform_common."""
        query = text(
            "SELECT status FROM platform_common "
            "WHERE product_id = :product_id AND platform_name = :platform LIMIT 1"
        )
        result = await self.db.execute(query, {"product_id": product_id, "platform": platform_name})
        row = result.fetchone()
        if not row:
            return None
        mapping = getattr(row, "_mapping", None)
        return mapping["status"] if mapping else row[0]

    async def _remove_vr_association(self, platform_common_id: Optional[int]) -> None:
        """Remove local VR platform linkage (vr_listing only, keep platform_common for sync history)."""
        if not platform_common_id:
            return

        # Delete the VR-specific listing data
        await self.db.execute(
            text("DELETE FROM vr_listings WHERE platform_id = :pid"),
            {"pid": platform_common_id}
        )

        # NOTE: We DON'T delete platform_common because:
        # 1. It's referenced by sync_events (foreign key constraint)
        # 2. We need it for sync history
        # 3. The listing is just no longer on V&R, but may still exist on other platforms
        

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
                    'extended_attributes': raw_data
                },
                'status': 'pending'}

            match = await suggest_product_match(
                self.db,
                'vr',
                {
                    'title': event_data['change_data']['title'],
                    'price': item.get('price'),
                    'status': item.get('status'),
                    'raw_data': raw_data,
                },
            )
            if match:
                event_data['change_data']['match_candidate'] = {
                    'product_id': match.product.id,
                    'sku': match.product.sku,
                    'title': match.product.title,
                    'brand': match.product.brand,
                    'model': match.product.model,
                    'status': match.product.status.value if getattr(match.product.status, 'value', None) else str(match.product.status) if match.product.status else None,
                    'base_price': match.product.base_price,
                    'primary_image': match.product.primary_image,
                    'confidence': match.confidence,
                    'reason': match.reason,
                    'existing_platforms': match.existing_platforms,
                }
                event_data['change_data']['suggested_action'] = 'match'
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
            
            db_price_for_compare = db_data.get('price_notax')
            if db_price_for_compare is None:
                db_price_for_compare = db_data.get('base_price')
            db_price_for_compare = float(db_price_for_compare or 0.0)
            if abs(api_data['price'] - db_price_for_compare) > 0.01:
                all_events.append({
                    'sync_run_id': sync_run_id, 'platform_name': 'vr', 'product_id': db_data['product_id'],
                    'platform_common_id': db_data['platform_common_id'], 'external_id': api_data['vr_id'],
                    'change_type': 'price', 'change_data': {'old': db_price_for_compare, 'new': api_data['price'], 'vr_id': api_data['vr_id']},
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
                    db_price_for_compare = db_data.get('price_notax')
                    if db_price_for_compare is None:
                        db_price_for_compare = db_data.get('base_price')
                    db_price_for_compare = float(db_price_for_compare or 0.0)
                    if abs(api_data['price'] - db_price_for_compare) > 0.01:
                        all_events.append({
                            'sync_run_id': sync_run_id, 'platform_name': 'vr',
                            'product_id': db_data['product_id'], 'platform_common_id': db_data['platform_common_id'],
                            'external_id': api_data['external_id'], 'change_type': 'price',
                            'change_data': {'old': db_price_for_compare, 'new': api_data['price']},
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
            product_id = item.get('product_id')
            platform_common_id = item.get('platform_common_id')
            sku = item.get('sku')
            external_id = item.get('external_id')

            # Check the Reverb listing status to see if this was a manual removal on V&R only.
            reverb_status = await self._get_platform_status(product_id, 'reverb') if product_id else None
            reverb_status_normalized = (reverb_status or '').lower()

            if reverb_status_normalized in ('active', 'live'):
                logger.info(
                    "V&R listing %s missing but Reverb still %s – removing local V&R linkage instead of logging removal event",
                    external_id,
                    reverb_status_normalized
                )
                await self._remove_vr_association(platform_common_id)
                removed_count += 1
                continue

            events_to_create.append({
                'sync_run_id': sync_run_id,
                'platform_name': 'vr',
                'product_id': product_id,
                'platform_common_id': platform_common_id,
                'external_id': external_id,
                'change_type': 'removed_listing',
                'change_data': {
                    'sku': sku,
                    'vr_id': external_id,
                    'reason': 'not_found_in_api'
                },
                'status': 'pending'
            })
            removed_count += 1

        if events_to_create:
            try:
                stmt = insert(SyncEvent).values(events_to_create)
                stmt = stmt.on_conflict_do_nothing(
                    index_elements=['platform_name', 'external_id', 'change_type'],
                    index_where=(SyncEvent.status == 'pending')
                )
                await self.db.execute(stmt)
                events_logged = len(events_to_create)
                logger.info(f"Attempted to log {len(events_to_create)} V&R removal events (duplicates ignored)")
            except Exception as e:
                logger.error(f"Failed to bulk insert V&R removal events: {e}", exc_info=True)

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
            if result and result.get("success", False):
                stmt = select(VRListing).where(VRListing.vr_listing_id == external_id)
                listing_result = await self.db.execute(stmt)
                listing = listing_result.scalar_one_or_none()
                if listing:
                    listing.vr_state = 'sold'
                    listing.inventory_quantity = 0
                    listing.in_inventory = False
                    listing.updated_at = datetime.utcnow()
                    self.db.add(listing)
                return True
            return False
        except Exception as e:
            logger.error(f"Exception while marking V&R item {external_id} as sold: {e}", exc_info=True)
            return False

    async def restore_from_sold(self, external_id: str) -> bool:
        """Restores a sold V&R item back to active/live status.

        V&R may use an AJAX endpoint similar to mark_as_sold. If the endpoint
        doesn't exist or fails, we update local state and log a warning that
        the item may need to be manually relisted on V&R.

        Args:
            external_id: The V&R listing ID to restore.

        Returns:
            True if successful (or local-only update), False on error.
        """
        logger.info(f"Received request to restore V&R item {external_id} from sold.")
        settings = get_settings()
        client = VintageAndRareClient(settings.VINTAGE_AND_RARE_USERNAME, settings.VINTAGE_AND_RARE_PASSWORD, db_session=self.db)

        try:
            if not await client.authenticate():
                logger.error(f"Authentication failed for restoring item {external_id}.")
                return False

            # Call restore_from_sold AJAX endpoint (confirmed from V&R JS)
            import random
            random_num = random.random()
            url = f'https://www.vintageandrare.com/ajax/restore_from_sold/{random_num}'

            ajax_headers = {
                **client.headers,
                'X-Requested-With': 'XMLHttpRequest',
                'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                'Referer': 'https://www.vintageandrare.com/account/items',
            }

            restore_data = f'product_id={external_id}'

            if client.cf_session:
                response = client.cf_session.post(url, data=restore_data, headers=ajax_headers)
            else:
                response = client.session.post(url, data=restore_data, headers=ajax_headers)

            logger.info(f"V&R restore response: status={response.status_code}, body='{response.text}'")

            # Check if the endpoint worked
            if response.status_code == 200 and response.text.strip().lower() == 'true':
                logger.info(f"V&R item {external_id} restored successfully via AJAX.")
            else:
                # Endpoint may not exist or returned failure - update local state only
                logger.warning(
                    f"V&R restore AJAX may not be supported (status={response.status_code}, "
                    f"response='{response.text}'). Updating local state only. "
                    f"Item may need manual relist on V&R website."
                )

            # Update local database regardless (optimistic update)
            stmt = select(VRListing).where(VRListing.vr_listing_id == external_id)
            listing_result = await self.db.execute(stmt)
            listing = listing_result.scalar_one_or_none()
            if listing:
                listing.vr_state = 'active'
                listing.inventory_quantity = 1
                listing.in_inventory = True
                listing.updated_at = datetime.utcnow()
                self.db.add(listing)
                logger.info(f"V&R listing {external_id} local state updated to active.")

            return True

        except Exception as e:
            logger.error(f"Exception while restoring V&R item {external_id}: {e}", exc_info=True)
            return False

    async def create_listing_from_product(
        self,
        product: Product,
        reverb_data: Dict[str, Any] = None,
        platform_options: Optional[Dict[str, Any]] = None,
        skip_id_resolution: bool = False,
    ) -> Dict[str, Any]:
        """Creates a Vintage & Rare listing from a local master Product object.

        Args:
            product: The product to list
            reverb_data: Optional Reverb API data for images/shipping
            platform_options: Optional platform-specific options (price override, etc.)
            skip_id_resolution: If True, skip CSV download for ID resolution (for batched processing)
        """
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
            vr_options = platform_options or {}
            override_price = vr_options.get('price') or vr_options.get('price_display')

            product_data = {
                'sku': product.sku,
                'brand': product.brand or '',
                'model': product.model or '',
                'price': str(product.base_price) if product.base_price else '0',
                'year': str(product.year) if product.year else None,
                'finish': product.finish if product.finish else None,
                'description': product.description or '',
                'external_id': product.sku,

                # V&R specific fields
                'vr_show_vat': bool(getattr(product, 'show_vat', True)),
                'vr_call_for_price': False,
                'vr_in_collective': bool(getattr(product, 'in_collective', False)),
                'vr_in_inventory': bool(getattr(product, 'in_inventory', True)),
                'vr_in_reseller': bool(getattr(product, 'in_reseller', False)),
                'vr_buy_now': bool(getattr(product, 'buy_now', False)),
                'processing_time': str(getattr(product, 'processing_time', 3) or 3),
                'time_unit': 'Days',
                'available_for_shipment': bool(getattr(product, 'available_for_shipment', True)),
                'local_pickup': bool(getattr(product, 'local_pickup', False)),
            }

            collective_discount_value = getattr(product, 'collective_discount', None)
            if collective_discount_value is None:
                collective_discount_value = 0.0
            try:
                collective_discount_value = float(collective_discount_value)
            except (TypeError, ValueError):
                collective_discount_value = 0.0

            product_data['vr_collective_discount'] = (
                f"{collective_discount_value:.2f}"
                if collective_discount_value
                else None
            )
            product_data['collective_discount'] = collective_discount_value

            price_notax_value = getattr(product, 'price_notax', None)
            if price_notax_value is None:
                price_notax_value = product.base_price
            product_data['price_notax'] = price_notax_value

            if override_price is not None:
                try:
                    product_data['price'] = str(float(str(override_price).replace(',', '')))
                except ValueError:
                    logger.warning(f"Invalid V&R price override: {override_price}")

            if vr_options.get('notes'):
                product_data['notes'] = vr_options['notes']
            
            # Add shipping fees (use defaults or extract from reverb_data if available)
            default_shipping = {
                'uk': '75',
                'europe': '50',
                'usa': '100',
                'world': '150'
            }

            shipping_rates = default_shipping.copy()

            if reverb_data and 'shipping' in reverb_data:
                shipping_data = reverb_data.get('shipping', {}).get('rates', [])
                for rate in shipping_data:
                    region = rate.get('region_code', '')
                    amount = rate.get('rate', {}).get('amount', '')
                    try:
                        normalized = (
                            f"{float(amount):.2f}".rstrip('0').rstrip('.')
                            if amount is not None
                            else None
                        )
                    except (TypeError, ValueError):
                        normalized = None

                    if not normalized:
                        continue

                    if region == 'GB':
                        shipping_rates['uk'] = normalized
                    elif region == 'US':
                        shipping_rates['usa'] = normalized
                    elif region in ['EUR_EU', 'EU']:
                        shipping_rates['europe'] = normalized
                    elif region == 'XX':
                        shipping_rates['world'] = normalized

            if getattr(product, 'shipping_profile_id', None):
                profile = getattr(product, 'shipping_profile', None)
                if profile is None:
                    profile_result = await self.db.execute(
                        select(ShippingProfile).where(ShippingProfile.id == product.shipping_profile_id)
                    )
                    profile = profile_result.scalar_one_or_none()

                if profile and profile.rates:
                    def _format_rate(value, fallback):
                        try:
                            return (
                                f"{float(value):.2f}".rstrip('0').rstrip('.')
                                if value is not None
                                else fallback
                            )
                        except (TypeError, ValueError):
                            return fallback

                    shipping_rates = {
                        'uk': _format_rate(profile.rates.get('uk'), shipping_rates['uk']),
                        'europe': _format_rate(profile.rates.get('europe'), shipping_rates['europe']),
                        'usa': _format_rate(profile.rates.get('usa'), shipping_rates['usa']),
                        'world': _format_rate(profile.rates.get('row'), shipping_rates['world']),
                    }

            product_data['shipping_uk_fee'] = shipping_rates['uk']
            product_data['shipping_europe_fee'] = shipping_rates['europe']
            product_data['shipping_usa_fee'] = shipping_rates['usa']
            product_data['shipping_world_fee'] = shipping_rates['world']
            product_data['shipping_fees'] = shipping_rates

            logger.info(
                "VRService payload shipping fees for %s: %s",
                product.sku,
                shipping_rates,
            )
            
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

            product_images: List[str] = []
            if product.primary_image:
                product_images.append(product.primary_image)
            if hasattr(product, 'additional_images') and product.additional_images:
                product_images.extend(product.additional_images)
            if product_images:
                for img_url in product_images:
                    max_res_url = ImageTransformer.transform_reverb_url(img_url, ImageQuality.MAX_RES)
                    if max_res_url and max_res_url not in all_images:
                        all_images.append(max_res_url)

            logger.info("VR image payload for %s: %s", product.sku, all_images)

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

            # Fallback: Look up UUID from reverb_categories using product.category
            if not reverb_category_uuid and product.category:
                logger.info(f"No category UUID in reverb_data, looking up from product.category: {product.category}")
                uuid_query = text("""
                    SELECT uuid FROM reverb_categories
                    WHERE name = :category OR full_path = :category
                    LIMIT 1
                """)
                uuid_result = await self.db.execute(uuid_query, {"category": product.category})
                uuid_row = uuid_result.fetchone()
                if uuid_row:
                    reverb_category_uuid = uuid_row.uuid
                    logger.info(f"Found category UUID from product.category: {reverb_category_uuid}")
            
            # Default category IDs (as fallback)
            category_ids = {
                'Category': '51',  # Default to Guitars
                'SubCategory1': '83',  # Default to Electric solid body
                'SubCategory2': None,
                'SubCategory3': None
            }

            override_category = vr_options.get('category')
            if override_category:
                parts = str(override_category).split('/')
                if len(parts) >= 1 and parts[0]:
                    category_ids['Category'] = parts[0]
                if len(parts) >= 2 and parts[1]:
                    category_ids['SubCategory1'] = parts[1]
                if len(parts) >= 3 and parts[2]:
                    category_ids['SubCategory2'] = parts[2]
                if len(parts) >= 4 and parts[3]:
                    category_ids['SubCategory3'] = parts[3]
            
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
                logger.warning(f"No Reverb category UUID available (product.category={product.category}), using default V&R categories")
            
            # Set the category IDs in product_data
            product_data['Category'] = category_ids['Category']
            product_data['SubCategory1'] = category_ids['SubCategory1']
            product_data['SubCategory2'] = category_ids['SubCategory2']
            product_data['SubCategory3'] = category_ids['SubCategory3']
            
            # Create the listing using Selenium
            # Check for test mode from environment variable
            test_mode = os.getenv('VR_TEST_MODE', 'false').lower() == 'true'
            
            logger.info(f"Creating V&R listing via Selenium for SKU: {product.sku} (test_mode={test_mode}, skip_id={skip_id_resolution})")
            result = await client.create_listing_selenium(
                product_data=product_data,
                test_mode=test_mode,
                from_scratch=False,  # Using category strings, not IDs
                db_session=self.db,
                skip_id_resolution=skip_id_resolution,
            )
            
            logger.info(f"V&R creation result: {result}")
            if isinstance(result, dict):
                logger.info("V&R payload keys: %s", list(result.keys()))
                logger.info(
                    "V&R listing %s response payload primary/additional: %s / %s",
                    result.get("vr_listing_id"),
                    result.get("payload", {}).get("primary_image"),
                    result.get("payload", {}).get("additional_images"),
                )

            if result.get("status") == "success":
                needs_resolution = bool(result.get("needs_id_resolution", False))
                vr_listing_id = result.get("vr_listing_id")

                if vr_listing_id is not None:
                    vr_id_str = str(vr_listing_id).strip()
                    if vr_id_str and not vr_id_str.upper().startswith(("RIFF", "REV")):
                        # Looks like a real V&R ID, no further resolution required
                        needs_resolution = False

                existing_platform_common = await self.db.execute(
                    select(PlatformCommon).where(
                        PlatformCommon.product_id == product.id,
                        PlatformCommon.platform_name == "vr"
                    )
                )
                platform_common = existing_platform_common.scalar_one_or_none()

                sync_status = (
                    SyncStatus.PENDING.value if needs_resolution else SyncStatus.SYNCED.value
                ).upper()
                external_id = vr_listing_id or result.get("external_id") or product.sku

                if platform_common:
                    platform_common.external_id = external_id
                    platform_common.status = ListingStatus.ACTIVE.value
                    platform_common.sync_status = sync_status
                    platform_common.last_sync = datetime.utcnow()
                    platform_common.platform_specific_data = result
                else:
                    platform_common = PlatformCommon(
                        product_id=product.id,
                        platform_name="vr",
                        external_id=external_id,
                        status=ListingStatus.ACTIVE.value,
                        sync_status=sync_status,
                        last_sync=datetime.utcnow(),
                        platform_specific_data=result
                    )
                    self.db.add(platform_common)

                await self.db.flush()

                vr_listing_stmt = select(VRListing).where(VRListing.platform_id == platform_common.id)
                existing_vr_listing = await self.db.execute(vr_listing_stmt)
                vr_listing = existing_vr_listing.scalar_one_or_none()

                price_value = None
                try:
                    price_value = float(product_data.get('price') or 0)
                except (TypeError, ValueError):
                    price_value = None

                listing_state = 'pending' if needs_resolution else 'active'

                if vr_listing:
                    vr_listing.vr_listing_id = vr_listing_id or vr_listing.vr_listing_id
                    vr_listing.inventory_quantity = product.quantity or vr_listing.inventory_quantity
                    vr_listing.vr_state = listing_state
                    vr_listing.price_notax = price_value
                    vr_listing.extended_attributes = result
                    vr_listing.last_synced_at = datetime.utcnow()
                else:
                    vr_listing = VRListing(
                        platform_id=platform_common.id,
                        vr_listing_id=vr_listing_id,
                        inventory_quantity=product.quantity or 1,
                        vr_state=listing_state,
                        price_notax=price_value,
                        extended_attributes=result,
                        last_synced_at=datetime.utcnow()
                    )
                    self.db.add(vr_listing)

                await self.db.commit()
                result["platform_common_id"] = platform_common.id
                result.setdefault("payload", product_data)
                result.setdefault("images", all_images)
                result.setdefault("category_ids", category_ids)
            else:
                await self.db.rollback()

            return result
            
        except Exception as e:
            logger.error(f"Exception while creating V&R listing for SKU {product.sku}: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}

    async def update_listing_price(self, external_id: str, new_price: float) -> bool:
        """Outbound action to update the price of a listing on the V&R platform."""
        logger.info(f"Received request to update V&R listing {external_id} to price £{new_price:.2f}.")
        client = VintageAndRareClient(
            self.settings.VINTAGE_AND_RARE_USERNAME,
            self.settings.VINTAGE_AND_RARE_PASSWORD,
            db_session=None,
        )
        
        try:
            update_data = {'product_price': f"{new_price:.2f}"}
            result = await client.update_item_details(external_id, update_data)

            return result.get("success", False)
        except Exception as e:
            logger.error(f"Exception while updating price for V&R item {external_id}: {e}", exc_info=True)
            return False

    def apply_product_update_from_snapshot(
        self,
        product_data: Dict[str, Any],
        external_id: str,
        changed_fields: Set[str],
    ) -> Dict[str, Any]:
        """Push text-based edits for a VR listing using the HTTP helper."""

        relevant = {"title", "model", "description", "brand", "base_price"}
        if not (changed_fields & relevant):
            return {"status": "no_changes"}

        if not external_id:
            return {"status": "skipped", "reason": "missing_external_id"}

        updates: Dict[str, Any] = {}
        if "model" in changed_fields:
            updates["model"] = product_data.get("model") or ""
        if "title" in changed_fields:
            updates["title"] = product_data.get("title") or ""
        if "description" in changed_fields:
            updates["description"] = product_data.get("description") or ""
        if "brand" in changed_fields:
            updates["brand"] = product_data.get("brand") or ""
        if "base_price" in changed_fields:
            price_value = product_data.get("base_price")
            if price_value is not None:
                updates["price"] = f"{float(price_value):.2f}"

        if not updates:
            return {"status": "no_changes"}

        client = VintageAndRareClient(
            self.settings.VINTAGE_AND_RARE_USERNAME,
            self.settings.VINTAGE_AND_RARE_PASSWORD,
            db_session=None,
        )

        try:
            result = client.update_listing_via_requests(external_id, updates)
            result.setdefault("requested_fields", list(updates.keys()))
            return result
        except Exception as exc:
            logger.error(
                "Error updating VR listing %s: %s",
                external_id,
                exc,
                exc_info=True,
            )
            return {"status": "error", "message": str(exc)}

    async def update_local_listing_metadata(
        self,
        external_id: str,
        product_data: Dict[str, Any],
        changed_fields: Set[str],
        applied_fields: Optional[List[str]] = None,
    ) -> None:
        """Persist VR edit results back to the local database."""

        if applied_fields is not None:
            effective_fields = {
                field for field in applied_fields if field in {"title", "model", "description", "brand", "price"}
            }
        else:
            rename_map = {"base_price": "price"}
            effective_fields = {
                rename_map.get(field, field)
                for field in changed_fields & {"title", "model", "description", "brand", "base_price"}
            }

        if not effective_fields:
            return

        try:
            platform_query = (
                select(PlatformCommon)
                .where(
                    PlatformCommon.platform_name == "vr",
                    PlatformCommon.external_id == external_id,
                )
                .limit(1)
            )
            platform_result = await self.db.execute(platform_query)
            platform_common = platform_result.scalar_one_or_none()
            if not platform_common:
                logger.warning("No platform_common row found for VR listing %s", external_id)
                return

            listing_query = (
                select(VRListing)
                .where(VRListing.platform_id == platform_common.id)
                .order_by(VRListing.id.desc())
                .limit(1)
            )
            listing_result = await self.db.execute(listing_query)
            vr_listing = listing_result.scalar_one_or_none()

            timestamp = datetime.utcnow()
            platform_data = dict(platform_common.platform_specific_data or {})

            def apply_update(target: Dict[str, Any], key: str, value_key: str) -> None:
                value = product_data.get(value_key)
                if value is not None:
                    target[key] = value

            if "title" in effective_fields:
                apply_update(platform_data, "title", "title")
            if "model" in effective_fields:
                apply_update(platform_data, "model", "model")
            if "description" in effective_fields:
                apply_update(platform_data, "description", "description")
            if "brand" in effective_fields:
                apply_update(platform_data, "brand", "brand")
            if "price" in effective_fields:
                platform_data["price"] = float(product_data.get("base_price") or 0)

            platform_common.platform_specific_data = platform_data
            platform_common.last_sync = timestamp
            self.db.add(platform_common)

            if vr_listing:
                ext_attrs = dict(vr_listing.extended_attributes or {})
                if "title" in effective_fields:
                    apply_update(ext_attrs, "title", "title")
                if "model" in effective_fields:
                    apply_update(ext_attrs, "model", "model")
                if "description" in effective_fields:
                    apply_update(ext_attrs, "description", "description")
                if "brand" in effective_fields:
                    apply_update(ext_attrs, "brand", "brand")
                if "price" in effective_fields:
                    ext_attrs["price"] = float(product_data.get("base_price") or 0)
                    vr_listing.price_notax = float(product_data.get("base_price") or 0)

                vr_listing.extended_attributes = ext_attrs
                vr_listing.last_synced_at = timestamp
                self.db.add(vr_listing)

            await self.db.commit()
        except Exception as exc:
            logger.error(
                "Failed to persist VR edit for %s: %s",
                external_id,
                exc,
                exc_info=True,
            )

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
                p.base_price,
                p.is_stocked_item,
                p.quantity,
                pc.id as platform_common_id, 
                pc.external_id, 
                pc.status as platform_common_status,
                vl.price_notax
            FROM platform_common pc
            LEFT JOIN products p ON p.id = pc.product_id
            LEFT JOIN vr_listings vl ON vl.platform_id = pc.id
            WHERE pc.platform_name = 'vr'
              AND pc.status NOT IN ('refreshed', 'deleted', 'removed')
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
