# app/services/shopify_service.py
import logging
import math
import uuid
import json
from datetime import datetime, timezone
from typing import Optional, Dict, List, Any, Tuple, Set
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy import select

from app.models.product import Product, ProductCondition, ProductStatus
from app.models.platform_common import PlatformCommon, ListingStatus, SyncStatus
from app.models.shopify import ShopifyListing
from app.models.sync_event import SyncEvent
from app.core.config import Settings, get_settings
from app.core.exceptions import ShopifyAPIError
from app.services.shopify.client import ShopifyGraphQLClient  # You'll need to create this
from app.services.reverb_service import ReverbService # We might need this for data mapping later


logger = logging.getLogger(__name__)

class ShopifyService:
    """Service for managing Shopify products and synchronization."""


    # =========================================================================
    # 1. INITIALIZATION & HELPERS
    # =========================================================================
    def __init__(self, db: AsyncSession, settings: Settings = None):
        logger.debug("ShopifyService.__init__ - Initializing.")
        self.db = db
        self.settings = settings
        
        # Initialize Shopify client - it loads settings internally
        self.client = ShopifyGraphQLClient()
        logger.debug(f"ShopifyService initialized")

    # ------------------------------------------------------------------
    # Utility helpers reused by scripts and edit-propagation
    # ------------------------------------------------------------------

    def _resolve_product_gid(
        self, platform_link: PlatformCommon, listing: ShopifyListing
    ) -> Optional[str]:
        raw_id = None
        if listing and listing.extended_attributes:
            raw_id = listing.extended_attributes.get("id")
        if not raw_id:
            raw_id = platform_link.external_id
        if not raw_id:
            return None
        return raw_id if str(raw_id).startswith("gid://") else f"gid://shopify/Product/{raw_id}"

    def _resolve_location_gid(self) -> str:
        settings = self.settings or get_settings()
        raw = getattr(settings, "SHOPIFY_LOCATION_GID", None)
        if not raw:
            raise ValueError("SHOPIFY_LOCATION_GID is not configured; update the environment settings")
        return raw if str(raw).startswith("gid://") else f"gid://shopify/Location/{raw}"

    def _extract_variant_nodes(self, listing: ShopifyListing) -> List[Dict[str, Any]]:
        variants = []
        if listing and listing.extended_attributes:
            variants = (
                listing.extended_attributes.get("variants", {}).get("nodes", [])
                if isinstance(listing.extended_attributes, dict)
                else []
            )
        return variants if isinstance(variants, list) else []

    def _fetch_fresh_variant_nodes(self, product_gid: str) -> List[Dict[str, Any]]:
        try:
            data = self.client.get_product_snapshot_by_id(product_gid, num_variants=50)
        except Exception as exc:  # pragma: no cover
            logger.warning("Failed to fetch fresh Shopify variants for %s: %s", product_gid, exc)
            return []

        variants = data.get("variants", {}).get("edges") if data else None
        if not variants:
            return []
        return [edge.get("node", {}) for edge in variants if isinstance(edge, dict)]

    def _collect_inventory_adjustments(
        self,
        product: Product,
        product_gid: str,
        variants: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        adjustments: List[Dict[str, Any]] = []
        fallback_map: Dict[str, Dict[str, Any]] = {}
        missing_inventory_ids = any(
            not ((variant or {}).get("inventoryItem") or {}).get("id")
            and not (variant or {}).get("inventoryItemId")
            for variant in variants
        )

        if missing_inventory_ids:
            fresh_nodes = self._fetch_fresh_variant_nodes(product_gid)
            fallback_map = {
                (node.get("sku") or "").strip().lower(): node
                for node in fresh_nodes
                if node.get("sku")
            }
            if fallback_map:
                logger.info("Refreshed Shopify variant data for %s", product.sku)

        location_gid = self._resolve_location_gid()

        for variant in variants:
            variant = variant or {}
            inventory_item = variant.get("inventoryItem") or {}
            inventory_item_id = inventory_item.get("id") or variant.get("inventoryItemId")

            if not inventory_item_id and fallback_map:
                lookup = fallback_map.get((variant.get("sku") or "").strip().lower())
                if lookup:
                    inventory_item_id = (
                        ((lookup.get("inventoryItem") or {}).get("id"))
                        or lookup.get("inventoryItemId")
                    )

            if not inventory_item_id:
                logger.warning(
                    "Shopify variant for %s missing inventory item id; skipping adjustment", product.sku
                )
                continue

            adjustments.append(
                {
                    "inventoryItemId": inventory_item_id,
                    "locationId": location_gid,
                    "quantity": int(product.quantity or 0),
                }
            )

        return adjustments

    def _push_inventory_update(
        self,
        product: Product,
        product_gid: str,
        adjustments: List[Dict[str, Any]],
    ) -> None:
        if not adjustments:
            logger.warning("No Shopify adjustments generated for %s; skipping", product.sku)
            return

        mutation = """
        mutation inventorySetOnHandQuantities($input: InventorySetOnHandQuantitiesInput!) {
          inventorySetOnHandQuantities(input: $input) {
            userErrors {
              field
              message
            }
          }
        }
        """

        variables = {
            "input": {
                "reason": "correction",
                "setQuantities": adjustments,
            }
        }

        try:
            response = self.client.execute(mutation, variables)
        except Exception as exc:  # pragma: no cover
            logger.error("Shopify inventory update failed for %s: %s", product.sku, exc)
            raise

        errors = (
            response.get("data", {})
            .get("inventorySetOnHandQuantities", {})
            .get("userErrors", [])
        )
        if errors:
            logger.error("Shopify inventory update errors for %s: %s", product.sku, errors)
            raise ShopifyAPIError(f"Inventory update errors: {errors}")



    # =========================================================================
    # 2. MAIN SYNC ENTRY POINT (DETECTION PHASE)
    # =========================================================================
    async def run_import_process(self, sync_run_id: uuid.UUID, progress_callback=None) -> Dict[str, int]:
        """The main entry point for the Shopify sync process."""
        logger.info(f"=== ShopifyService: STARTING SHOPIFY SYNC (run_id: {sync_run_id}) ===")
        
        try:
            # Fetch all products from Shopify
            logger.info("Fetching all Shopify products...")
            products_from_api = self.client.get_all_products_summary()
            
            if not products_from_api:
                logger.error("No products fetched from Shopify API")
                return {"status": "error", "message": "No Shopify products received"}
            
            logger.info(f"Total products fetched from API: {len(products_from_api)}")
            
            # Run the differential sync logic
            sync_stats = await self.sync_shopify_inventory(products_from_api, sync_run_id)
            
            logger.info(f"=== ShopifyService: FINISHED SHOPIFY SYNC === Final Results: {sync_stats}")
            return sync_stats
            
        except Exception as e:
            logger.error(f"Error in Shopify sync: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}


    # =========================================================================
    # 3. DIFFERENTIAL SYNC LOGIC (Called by the main entry point)
    # =========================================================================
    async def sync_shopify_inventory(self, shopify_products: List[Dict], sync_run_id: uuid.UUID) -> Dict[str, Any]:
        """Compares Shopify API data with the local DB and logs necessary changes."""
        stats = {
            "total_from_shopify": len(shopify_products), 
            "events_logged": 0, 
            "created": 0, 
            "updated": 0, 
            "removed": 0, 
            "unchanged": 0, 
            "errors": 0
        }

        try:
            # Step 1: Fetch all existing Shopify data from our DB
            existing_data = await self._fetch_existing_shopify_data()

            # Step 2: Prepare data for comparison
            api_items = self._prepare_api_data(shopify_products)
            db_items = self._prepare_db_data(existing_data)

            # Step 3: Calculate differences
            changes = self._calculate_changes(api_items, db_items)
            logger.info(f"Applying changes: {len(changes['create'])} new, {len(changes['update'])} updates, {len(changes['remove'])} removals")

            # Step 4: Apply changes and log events
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
            await self.db.commit()
            
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Sync failed during differential sync: {e}", exc_info=True)
            stats['errors'] += 1
        
        return stats

    # ------------------------------------------------------------------
    # Manual propagation helpers (edit path, etc.)
    # ------------------------------------------------------------------

    async def apply_product_update(
        self,
        product: Product,
        platform_link: PlatformCommon,
        changed_fields: Set[str],
    ) -> Dict[str, Any]:
        listing_query = select(ShopifyListing).where(ShopifyListing.platform_id == platform_link.id)
        listing_result = await self.db.execute(listing_query)
        listing = listing_result.scalar_one_or_none()
        if not listing:
            return {"status": "skipped", "reason": "no_listing"}

        product_gid = self._resolve_product_gid(platform_link, listing)
        if not product_gid:
            return {"status": "error", "message": "missing_product_gid"}

        update_payload: Dict[str, Any] = {"id": product_gid}
        pushed = False

        if "title" in changed_fields and product.title:
            update_payload["title"] = product.title
            pushed = True

        if "description" in changed_fields:
            update_payload["descriptionHtml"] = product.description or ""
            pushed = True

        if pushed:
            self.client.update_product(update_payload)

        inventory_updated = False
        if "quantity" in changed_fields and product.is_stocked_item:
            variants = self._extract_variant_nodes(listing)
            if not variants:
                variants = self._fetch_fresh_variant_nodes(product_gid)
            adjustments = self._collect_inventory_adjustments(product, product_gid, variants)
            self._push_inventory_update(product, product_gid, adjustments)
            inventory_updated = True

        return {
            "status": "updated" if pushed or inventory_updated else "no_changes",
            "inventory": inventory_updated,
            "product": pushed,
        }

    def _calculate_changes(self, api_items: Dict, db_items: Dict) -> Dict[str, List]:
        """Calculates create, update, and remove operations."""
        changes = {'create': [], 'update': [], 'remove': []}
        api_ids = set(api_items.keys())
        db_ids = set(db_items.keys())

        # logger.info(f"API items: {len(api_ids)}, DB items: {len(db_ids)}")
        # logger.info(f"Sample API IDs: {list(api_ids)[:5]}")
        # logger.info(f"Sample DB IDs: {list(db_ids)[:5]}")
        # logger.info(f"Intersection: {len(api_ids & db_ids)} items")

        for eid in api_ids - db_ids:
            changes['create'].append(api_items[eid])
        for eid in api_ids & db_ids:
            if self._has_changed(api_items[eid], db_items[eid]):
                changes['update'].append({'api_data': api_items[eid], 'db_data': db_items[eid]})
        for eid in db_ids - api_ids:
            changes['remove'].append(db_items[eid])
        
        logger.info(f"Changes calculated: {len(changes['create'])} create, {len(changes['update'])} update, {len(changes['remove'])} remove")
        return changes

    def _has_changed(self, api_item: Dict, db_item: Dict) -> bool:
        """Compares API data against the correct fields and handles equivalent statuses."""
        api_status = api_item.get('status')
        db_status = db_item.get('platform_common_status')
        
        off_market_statuses = ['sold', 'ended', 'archived', 'removed', 'deleted']
        statuses_match = (api_status in off_market_statuses and db_status in off_market_statuses) or \
                            (api_status == db_status)

        if not statuses_match:
            # logger.info(f"--- [DEBUG] Change Detected for ID {api_item['external_id']}: STATUS MISMATCH ---")
            # logger.info(f"    API Status: '{api_status}' vs DB Status: '{db_status}'")
            return True
        
        # If the listing is not active, we don't care about price or URL changes.
        if db_status != 'active':
            return False
            
        db_price = float(db_item.get('base_price') or 0.0)
        api_price = api_item.get('price', 0.0)
        if abs(api_price - db_price) > 0.01:
            logger.info(f"--- [DEBUG] Change Detected for ID {api_item['external_id']}: PRICE MISMATCH ---")
            logger.info(f"    API Price: '{api_price}' vs DB Price: '{db_price}'")
            return True

        if api_item.get('listing_url') and api_item['listing_url'] != db_item.get('listing_url'):
            logger.info(f"--- [DEBUG] Change Detected for ID {api_item['external_id']}: URL MISMATCH ---")
            return True

        return False


    # =========================================================================
    # 4. BATCH PROCESSING / EVENT LOGGING (Called by differential sync)
    # =========================================================================
    async def _batch_create_products(self, items: List[Dict], sync_run_id: uuid.UUID) -> Tuple[int, int]:
        """Log rogue listings to sync_events only - no database records created."""
        created_count, events_logged = 0, 0
        
        # Prepare all events first
        events_to_create = []
        for item in items:
            try:
                logger.warning(
                    f"Rogue SKU Detected: Shopify product {item['external_id']} ('{item.get('title')}') "
                    f"not found in local DB. Logging to sync_events for later processing."
                )
                
                event_data = {
                    'sync_run_id': sync_run_id,
                    'platform_name': 'shopify',
                    'product_id': None,
                    'platform_common_id': None,
                    'external_id': item['external_id'],
                    'change_type': 'new_listing',
                    'change_data': {
                        'title': item['title'],
                        'price': item['price'],
                        'status': item['status'],
                        'vendor': item.get('vendor'),
                        'product_type': item.get('product_type'),
                        'raw_data': item['_raw']
                    },
                    'status': 'pending'
                }
                events_to_create.append(event_data)
                created_count += 1
            except Exception as e:
                logger.error(f"Failed to prepare event for Shopify product {item['external_id']}: {e}", exc_info=True)
        
        # Bulk insert with ON CONFLICT DO NOTHING to handle duplicates gracefully
        if events_to_create:
            try:
                stmt = insert(SyncEvent).values(events_to_create)
                stmt = stmt.on_conflict_do_nothing(
                    index_elements=['platform_name', 'external_id', 'change_type'],
                    index_where=(SyncEvent.status == 'pending')
                )
                result = await self.db.execute(stmt)
                events_logged = len(events_to_create)
                logger.info(f"Attempted to log {len(events_to_create)} new listing events (duplicates ignored)")
            except Exception as e:
                logger.error(f"Failed to bulk insert new listing events: {e}", exc_info=True)
        
        return created_count, events_logged

    async def _batch_update_products_old(self, items: List[Dict], sync_run_id: uuid.UUID) -> Tuple[int, int]:
        """SYNC PHASE: Only log changes to sync_events - NO database table updates."""
        updated_count, events_logged = 0, 0
        
        # Collect all events to insert
        all_events = []
        
        for item in items:
            try:
                api_data, db_data = item['api_data'], item['db_data']
                
                # Price change event
                db_price_for_compare = float(db_data.get('price') or 0.0)
                if abs(api_data['price'] - db_price_for_compare) > 0.01:
                    all_events.append({
                        'sync_run_id': sync_run_id,
                        'platform_name': 'shopify',
                        'product_id': db_data['product_id'],
                        'platform_common_id': db_data['platform_common_id'],
                        'external_id': api_data['external_id'],
                        'change_type': 'price',
                        'change_data': {
                            'old': db_data.get('price'),
                            'new': api_data['price'],
                            'shopify_id': api_data['external_id']
                        },
                        'status': 'pending'
                    })
                
                # Status change event
                if str(api_data.get('status', '')).lower() != str(db_data.get('shopify_status', '')).lower():
                    is_archived = api_data.get('status') == 'archived'
                    all_events.append({
                        'sync_run_id': sync_run_id,
                        'platform_name': 'shopify',
                        'product_id': db_data['product_id'],
                        'platform_common_id': db_data['platform_common_id'],
                        'external_id': api_data['external_id'],
                        'change_type': 'status_change',
                        'change_data': {
                            'old': db_data.get('shopify_status'),
                            'new': api_data['status'],
                            'shopify_id': api_data['external_id'],
                            'is_archived': is_archived
                        },
                        'status': 'pending'
                    })
                
                updated_count += 1
                
            except Exception as e:
                logger.error(f"Failed to prepare events for Shopify product {item['api_data']['external_id']}: {e}", exc_info=True)
        
        # Bulk insert all events with duplicate handling
        if all_events:
            try:
                stmt = insert(SyncEvent).values(all_events)
                stmt = stmt.on_conflict_do_nothing(
                    index_elements=['platform_name', 'external_id', 'change_type'],
                    index_where=(SyncEvent.status == 'pending')
                )
                result = await self.db.execute(stmt)
                events_logged = len(all_events)
                logger.info(f"Attempted to log {len(all_events)} update events (duplicates ignored)")
            except Exception as e:
                logger.error(f"Failed to bulk insert update events: {e}", exc_info=True)
        
        return updated_count, events_logged

    async def _batch_update_products(self, items: List[Dict], sync_run_id: uuid.UUID) -> Tuple[int, int]:
        """Logs price and status changes to sync_events, using the correct data keys."""
        updated_count, events_logged = 0, 0
        all_events = []
        
        for item in items:
            try:
                api_data, db_data = item['api_data'], item['db_data']
                
                # Price change event check using the correct 'base_price' key
                db_price_for_compare = float(db_data.get('base_price') or 0.0)
                if abs(api_data['price'] - db_price_for_compare) > 0.01:
                    all_events.append({
                        'sync_run_id': sync_run_id,
                        'platform_name': 'shopify',
                        'product_id': db_data['product_id'],
                        'platform_common_id': db_data['platform_common_id'],
                        'external_id': api_data['external_id'],
                        'change_type': 'price',
                        'change_data': {
                            'old': db_data.get('base_price'),
                            'new': api_data['price'],
                            'shopify_id': api_data['external_id']
                        },
                        'status': 'pending'
                    })
                
                # Status change event check using the nuanced 'off-market' logic
                api_status = (api_data.get('status') or '').lower()
                db_status = (db_data.get('platform_common_status') or '').lower()
                off_market_statuses = ['sold', 'ended', 'archived', 'removed', 'deleted']
                statuses_match = (api_status in off_market_statuses and db_status in off_market_statuses) or \
                                (api_status == db_status)

                if not statuses_match:
                    is_archived = api_data.get('status') == 'archived'
                    all_events.append({
                        'sync_run_id': sync_run_id,
                        'platform_name': 'shopify',
                        'product_id': db_data['product_id'],
                        'platform_common_id': db_data['platform_common_id'],
                        'external_id': api_data['external_id'],
                        'change_type': 'status_change',
                        'change_data': {
                            'old': db_status,
                            'new': api_status,
                            'shopify_id': api_data['external_id'],
                            'is_archived': is_archived
                        },
                        'status': 'pending'
                    })
                
                updated_count += 1
                
            except Exception as e:
                logger.error(f"Failed to prepare events for Shopify product {item['api_data']['external_id']}: {e}", exc_info=True)
        
        # Bulk insert logic
        if all_events:
            try:
                stmt = insert(SyncEvent).values(all_events)
                stmt = stmt.on_conflict_do_nothing(
                    index_elements=['platform_name', 'external_id', 'change_type'],
                    index_where=(SyncEvent.status == 'pending')
                )
                await self.db.execute(stmt)
                events_logged = len(all_events)
                logger.info(f"Attempted to log {len(all_events)} update events (duplicates ignored)")
            except Exception as e:
                logger.error(f"Failed to bulk insert update events: {e}", exc_info=True)
        
        return updated_count, events_logged

    async def _batch_mark_removed(self, items: List[Dict], sync_run_id: uuid.UUID) -> Tuple[int, int]:
        """SYNC PHASE: Only log removal events to sync_events - NO database table updates."""
        removed_count, events_logged = 0, 0
        
        # Prepare all removal events
        events_to_create = []
        for item in items:
            try:
                events_to_create.append({
                    'sync_run_id': sync_run_id,
                    'platform_name': 'shopify',
                    'product_id': item['product_id'],
                    'platform_common_id': item['platform_common_id'],
                    'external_id': item['external_id'],
                    'change_type': 'removed_listing',
                    'change_data': {
                        'sku': item['sku'],
                        'shopify_id': item['external_id'],
                        'reason': 'not_found_in_api'
                    },
                    'status': 'pending'
                })
                removed_count += 1
            except Exception as e:
                logger.error(f"Failed to prepare removal event for Shopify product {item['external_id']}: {e}", exc_info=True)
        
        # Bulk insert with duplicate handling
        if events_to_create:
            try:
                stmt = insert(SyncEvent).values(events_to_create)
                stmt = stmt.on_conflict_do_nothing(
                    index_elements=['platform_name', 'external_id', 'change_type'],
                    index_where=(SyncEvent.status == 'pending')
                )
                result = await self.db.execute(stmt)
                events_logged = len(events_to_create)
                logger.info(f"Attempted to log {len(events_to_create)} removal events (duplicates ignored)")
            except Exception as e:
                logger.error(f"Failed to bulk insert removal events: {e}", exc_info=True)
        
        return removed_count, events_logged
    
    
    # =========================================================================
    # 5. OUTBOUND ACTIONS (Called by the Action Phase)
    # =========================================================================
    async def mark_item_as_sold(self, external_id: str) -> bool:
        """Outbound action to mark a product as sold on Shopify because it sold elsewhere."""
        logger.info(f"Received request to mark Shopify product {external_id} as sold.")
        try:
            # 1. Construct the GID from the legacy ID, as you suggested.
            product_gid = f"gid://shopify/Product/{external_id}"

            # 2. Call the existing, proven client method.
            result = await self.client.mark_product_as_sold(product_gid)

            success = result.get("success", False)
            if success:
                listing_stmt = select(ShopifyListing).where(ShopifyListing.shopify_legacy_id == str(external_id))
                listing_result = await self.db.execute(listing_stmt)
                listing = listing_result.scalar_one_or_none()
                if listing:
                    listing.status = 'archived'
                    listing.last_synced_at = datetime.utcnow()
                    listing.updated_at = datetime.utcnow()
                    self.db.add(listing)

            return success
            
        except Exception as e:
            logger.error(f"Exception while updating Shopify product {external_id}: {e}", exc_info=True)
            return False

    async def update_listing_price(self, external_id: str, new_price: float) -> bool:
        """Outbound action to update the price of a listing on Shopify."""
        logger.info(f"Received request to update Shopify product {external_id} to price £{new_price:.2f}.")
        try:
            # The client needs the full GraphQL GID
            product_gid = f"gid://shopify/Product/{external_id}"
            
            # Your client takes a simple dictionary for the update payload
            update_payload = {"price": f"{new_price:.2f}"}
            
            result = await self.client.update_product_variant_price(product_gid, update_payload)
            
            # The client method returns a dictionary with a 'success' key
            return result.get("success", False)
        except Exception as e:
            logger.error(f"Exception while updating price for Shopify product {external_id}: {e}", exc_info=True)
            return False

    async def create_listing_from_product(
        self,
        product: Product,
        reverb_data: Dict[str, Any] = None,
        platform_options: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Creates a Shopify listing from a local master Product object.
        This is called by the SyncService during the 'Action Phase'.
        """
        logger.info(f"Creating Shopify listing for Product ID: {product.id}, SKU: {product.sku}")
        
        try:
            # Import image transformation utilities
            from app.core.utils import ImageTransformer, ImageQuality
            
            final_price: Optional[float] = None

            # 1. Prepare the data payload for the Shopify API
            tags = []
            
            # Add brand
            if product.brand:
                tags.append(product.brand)
            
            # Add year
            if product.year:
                tags.append(f"Year:{product.year}")
            
            # Add finish if available (from product or reverb_data)
            finish = product.finish if hasattr(product, 'finish') and product.finish else None
            if not finish and reverb_data:
                finish = reverb_data.get('finish')
            if finish:
                tags.append(f"Finish:{finish}")
            
            # Add condition from reverb_data
            if reverb_data:
                condition = reverb_data.get('condition')
                if isinstance(condition, dict):
                    condition_name = condition.get('display_name')
                elif isinstance(condition, str):
                    condition_name = condition
                else:
                    condition_name = None
                if condition_name:
                    tags.append(f"Condition:{condition_name}")
                
                # Add category from Reverb (more specific than product.category)
                categories = reverb_data.get('categories', [])
                if categories:
                    category_name = categories[0].get('full_name')
                    if category_name:
                        tags.append(category_name)
                
                # Add model if available for search
                model = reverb_data.get('model')
                if model and len(model) > 2:  # Skip very short model names
                    tags.append(f"Model:{model[:50]}")  # Limit length
                
                # Add shop name for provenance
                shop_name = reverb_data.get('shop_name')
                if shop_name:
                    tags.append(f"Source:{shop_name[:30]}")  # Limit length
            
            # Add generic category as fallback
            if product.category and product.category not in tags:
                tags.append(product.category)
            
            # Remove duplicates and filter out None/empty values
            tags = list(filter(None, set(tags)))
            
            # Extract and transform images to MAX_RES (same logic as VR)
            all_images = []
            
            # First try to get images from reverb_data if provided
            if reverb_data:
                cloudinary_photos = reverb_data.get('cloudinary_photos', [])
                if cloudinary_photos:
                    logger.info(f"Found {len(cloudinary_photos)} Cloudinary photos from Reverb for Shopify")
                    for photo in cloudinary_photos[:10]:  # Shopify has a lower limit than VR
                        image_url = None
                        if 'preview_url' in photo:
                            image_url = photo['preview_url']
                        elif 'url' in photo:
                            image_url = photo['url']
                        
                        if image_url:
                            # Transform to MAX_RES for Shopify
                            max_res_url = ImageTransformer.transform_reverb_url(image_url, ImageQuality.MAX_RES)
                            if max_res_url:  # Only add non-None URLs
                                all_images.append(max_res_url)
                                logger.debug(f"Added Cloudinary image: {max_res_url[:80]}...")
                
                # Fallback to regular photos if no cloudinary photos
                if not all_images:
                    photos = reverb_data.get('photos', [])
                    if photos:
                        logger.info(f"Found {len(photos)} regular photos from Reverb for Shopify")
                        for photo in photos[:10]:
                            image_url = None
                            if isinstance(photo, dict) and '_links' in photo:
                                if 'large_crop' in photo['_links']:
                                    image_url = photo['_links']['large_crop']['href']
                                elif 'full' in photo['_links']:
                                    image_url = photo['_links']['full']['href']
                            elif isinstance(photo, str):
                                image_url = photo
                            
                            if image_url:
                                max_res_url = ImageTransformer.transform_reverb_url(image_url, ImageQuality.MAX_RES)
                                if max_res_url:  # Only add non-None URLs
                                    all_images.append(max_res_url)
            
            # Fallback to product's stored images if no Reverb data
            if not all_images:
                if product.primary_image:
                    max_res_url = ImageTransformer.transform_reverb_url(product.primary_image, ImageQuality.MAX_RES)
                    if max_res_url:  # Only add non-None URLs
                        all_images.append(max_res_url)
                if hasattr(product, 'additional_images') and product.additional_images:
                    for img_url in product.additional_images[:9]:  # Limit to 10 total
                        max_res_url = ImageTransformer.transform_reverb_url(img_url, ImageQuality.MAX_RES)
                        all_images.append(max_res_url)
            
            logger.info(f"Prepared {len(all_images)} MAX_RES images for Shopify")

            # Step 1: Create product shell (without variants and images - GraphQL doesn't accept them in ProductInput)
            product_input = {
                "title": product.title or f"{product.year or ''} {product.brand} {product.model}".strip(),
                "vendor": product.brand,
                "descriptionHtml": product.description,
                "productType": product.category,
                "status": "ACTIVE",
                "tags": tags
            }

            # 2. Create the product shell
            creation_result = self.client.create_product(product_input)

            if not creation_result or not creation_result.get("product"):
                logger.error(f"Failed to create Shopify product shell. Response: {creation_result}")
                user_errors = creation_result.get('userErrors', []) if creation_result else []
                error_message = user_errors[0]['message'] if user_errors else "Failed to create product shell"
                return {"status": "error", "message": error_message}
            
            product_gid = creation_result["product"]["id"]
            product_legacy_id = creation_result["product"].get("legacyResourceId")
            logger.info(f"Created Shopify product shell with GID: {product_gid}")
            
            # Step 3: Update the variant with price, SKU, and inventory
            try:
                if creation_result["product"].get("variants", {}).get("edges"):
                    variant_gid = creation_result["product"]["variants"]["edges"][0]["node"]["id"]
                    
                    # Get inventory quantity from Reverb data if available
                    inventory_qty = 1  # Default to 1
                    if reverb_data and reverb_data.get('inventory'):
                        inventory_qty = int(reverb_data.get('inventory', 1))
                    
                    override_price = None
                    if platform_options:
                        override_price = platform_options.get("price") or platform_options.get("price_display")
                    local_final_price = None
                    if override_price is not None:
                        try:
                            local_final_price = float(str(override_price).replace(",", ""))
                        except ValueError:
                            logger.warning("Invalid Shopify override price '%s'", override_price)

                    if local_final_price is None:
                        source_price = self._extract_source_price(product, reverb_data)
                        shopify_price = None
                        if source_price:
                            try:
                                shopify_price = self._calculate_shopify_price(source_price)
                            except ValueError:
                                logger.warning("Invalid source price %s for Shopify calculation", source_price)

                        local_final_price = shopify_price if shopify_price else float(product.base_price or 0)

                    final_price = local_final_price

                    variant_update = {
                        "price": str(local_final_price),
                        "sku": product.sku,
                        "inventory": inventory_qty,
                        "inventoryPolicy": "DENY",  # Don't allow purchase when out of stock
                        "inventoryItem": {"tracked": True}  # Track inventory
                    }
                    
                    # Add inventory location if we have a default location
                    # You may need to set this based on your Shopify configuration
                    DEFAULT_LOCATION_GID = "gid://shopify/Location/109766639956"  # Update this to your location
                    if DEFAULT_LOCATION_GID:
                        variant_update["inventoryQuantities"] = [{
                            "availableQuantity": inventory_qty,
                            "locationId": DEFAULT_LOCATION_GID
                        }]
                    
                    self.client.update_variant_rest(variant_gid, variant_update)
                    logger.info(f"Updated variant with price, SKU, and inventory tracking (qty: {inventory_qty})")
            except Exception as e:
                logger.warning(f"Failed to update variant: {e}")
            
            # Step 4: Add images if available
            created_images: List[str] = []
            if all_images:
                try:
                    # Filter out any None values and use the validated format
                    valid_images = [url for url in all_images if url]
                    if valid_images:
                        logger.info("Shopify image payload (first 3): %s", valid_images[:3])
                        # Use the same format as the validated script for consistency
                        media_input = [{"src": url} for url in valid_images]
                        logger.debug("Shopify media_input: %s", media_input)
                        self.client.create_product_images(product_gid, media_input)
                        logger.info(f"Added {len(valid_images)} images (best quality available) to product")
                        created_images = valid_images
                    else:
                        logger.warning("No valid image URLs after filtering")
                except Exception as e:
                    logger.warning(f"Failed to add images: {e}")
            
            # Step 5: Set category if we have Reverb category mapping or platform override
            category_gid_override = None
            category_gid_assigned = None
            if platform_options:
                category_gid_override = platform_options.get("category_gid") or platform_options.get("category")

            if category_gid_override:
                try:
                    category_result = self.client.set_product_category(product_gid, category_gid_override)
                    if category_result:
                        logger.info("✅ Category set using platform override")
                        category_gid_assigned = category_gid_override
                except Exception as e:
                    logger.warning(f"Failed to set category via override: {e}")
            elif reverb_data:
                try:
                    categories = reverb_data.get('categories', [])
                    if categories and categories[0].get('uuid'):
                        category_uuid = categories[0]['uuid']
                        logger.info(f"Looking up category mapping for Reverb UUID: {category_uuid}")
                        
                        # Load category mappings
                        import json
                        mapping_file = "app/services/category_mappings/reverb_to_shopify.json"
                        try:
                            with open(mapping_file, 'r') as f:
                                mappings_data = json.load(f)
                                mappings = mappings_data.get('mappings', {})
                        except Exception as e:
                            logger.warning(f"Could not load category mappings: {e}")
                            mappings = {}
                        
                        if category_uuid in mappings:
                            category_gid = mappings[category_uuid].get('shopify_gid')
                            if category_gid:
                                logger.info(f"Setting Shopify category to: {category_gid}")
                                category_result = self.client.set_product_category(product_gid, category_gid)
                                if category_result:
                                    logger.info("✅ Category set successfully")
                                    category_gid_assigned = category_gid
                                else:
                                    logger.warning("Failed to set product category")
                        else:
                            logger.info(f"No category mapping found for UUID: {category_uuid}")
                except Exception as e:
                    logger.warning(f"Failed to set category: {e}")
            
            # Step 6: Publish to Online Store
            try:
                logger.info("Publishing product to Online Store...")
                online_store_gid = self.client.get_online_store_publication_id()
                if online_store_gid:
                    publish_result = self.client.publish_product_to_sales_channel(product_gid, online_store_gid)
                    if publish_result:
                        logger.info("✅ Product published to Online Store")
                    else:
                        logger.warning("Failed to publish product to Online Store")
                else:
                    logger.warning("Could not find Online Store publication GID")
            except Exception as e:
                logger.warning(f"Failed to publish product: {e}")
            
            if not product_legacy_id:
                return {"status": "error", "message": "No legacy ID returned"}

            logger.info(f"Successfully created Shopify product with ID: {product_legacy_id}")

            snapshot = None
            try:
                snapshot = self.client.get_product_snapshot_by_id(
                    product_gid,
                    num_variants=10,
                    num_images=20,
                    num_metafields=0,
                )
                if snapshot:
                    logger.info(
                        "Shopify snapshot for %s contains %s images (first 2: %s)",
                        product_gid,
                        len(snapshot.get("images", {}).get("edges", [])),
                        snapshot.get("images", {}).get("edges", [])[:2],
                    )
            except Exception as snapshot_error:
                logger.warning(f"Failed to fetch Shopify snapshot for {product_gid}: {snapshot_error}")

            return {
                "status": "success",
                "external_id": product_legacy_id,
                "shopify_product_id": product_legacy_id,
                "product_gid": product_gid,
                "price": final_price,
                "images": created_images,
                "category_gid": category_gid_assigned,
                "snapshot": snapshot,
            }

        except Exception as e:
            logger.error(f"Exception while creating Shopify listing for SKU {product.sku}: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}

    async def create_gallery_listing_from_product(self, product: Product) -> Dict[str, Any]:
        """
        Creates a Shopify listing as ARCHIVED and tags it for gallery/collection purposes.
        """
        logger.info(f"Creating Shopify GALLERY listing for Product ID: {product.id}, SKU: {product.sku}")
        
        try:
            # Prepare tags, including our new 'gallery-item' tag
            tags = [product.brand, product.category]
            if product.year:
                tags.append(f"Year:{product.year}")
            
            # --- KEY CHANGE 1: ADD THE GALLERY TAG ---
            tags.append("gallery-item")

            images = []
            if product.primary_image:
                images.append({'src': product.primary_image})

            product_input = {
                "title": product.title or f"{product.year or ''} {product.brand} {product.model}".strip(),
                "vendor": product.brand,
                "descriptionHtml": product.description,
                "productType": product.category,
                # --- KEY CHANGE 2: SET STATUS TO ARCHIVED ---
                "status": "ARCHIVED",
                "tags": tags,
                "variants": [{
                    "price": str(product.base_price),
                    "sku": product.sku
                }],
                "images": images
            }

            # Call the existing, powerful client method to create the product
            creation_result = self.client.create_product(product_input)

            if (creation_result and creation_result.get("product") and 
                    creation_result["product"].get("legacyResourceId")):
                
                new_shopify_id = creation_result["product"]["legacyResourceId"]
                logger.info(f"Successfully created Shopify GALLERY product with ID: {new_shopify_id}")
                return {"status": "success", "external_id": new_shopify_id}
            else:
                logger.error(f"Shopify API call did not return a valid product ID for gallery item. Response: {creation_result}")
                user_errors = creation_result.get('userErrors', [])
                error_message = user_errors[0]['message'] if user_errors else "Unknown API error."
                return {"status": "error", "message": error_message}

        except Exception as e:
            logger.error(f"Exception while creating Shopify gallery listing for SKU {product.sku}: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}
    
    
    # =========================================================================
    # 6. DATA PREPARATION & FETCHING HELPERS
    # =========================================================================
    async def _fetch_existing_shopify_data(self) -> List[Dict]:
        """Fetches all Shopify-related data from the local database, focusing on the source of truth."""
        query = text("""
            SELECT 
                p.id as product_id, 
                p.sku, 
                p.base_price, -- For price comparison
                pc.id as platform_common_id, 
                pc.external_id, 
                pc.status as platform_common_status, -- This is our source of truth
                pc.listing_url,
                sl.shopify_legacy_id -- Keep for matching
            FROM platform_common pc
            LEFT JOIN products p ON p.id = pc.product_id
            LEFT JOIN shopify_listings sl ON pc.id = sl.platform_id
            WHERE pc.platform_name = 'shopify'
        """)
        result = await self.db.execute(query)
        rows = [row._asdict() for row in result.fetchall()]

        # logger.info(f"--- [DEBUG] Fetched {len(rows)} total records from the database.")
        # if rows:
        #     logger.info(f"--- [DEBUG] Sample DB Row: {rows[0]}")

        return rows
    
    def _prepare_api_data(self, shopify_products: List[Dict]) -> Dict[str, Dict]:
        """Prepares Shopify API data into a standardized lookup dictionary."""
        logger.info("--- [DEBUG] Entering _prepare_api_data ---")
        prepared_items = {}
        for product in shopify_products:
            product_gid = str(product.get('id', ''))
            if not product_gid:
                continue

            product_id = product.get('legacyResourceId')
            if not product_id:
                continue
            
            # --- NEW SMARTER TRANSLATOR LOGIC ---
            api_status = str(product.get('status', 'active')).lower()
            inventory_quantity = product.get('totalInventory') # Can be None

            universal_status = api_status
            # If a product is 'active' but has no stock, it's functionally 'sold' for our system.
            if api_status == 'active' and inventory_quantity is not None and inventory_quantity <= 0:
                universal_status = 'sold'
            # --- END NEW LOGIC ---

            price = 0.0
            variants = product.get('variants', {}).get('nodes', [])
            if variants:
                raw_price = variants[0].get('price', 0)
                try:
                    price = float(raw_price) if raw_price else 0.0
                except (ValueError, TypeError):
                    price = 0.0
            
            prepared_items[product_id] = {
                'external_id': product_id,
                'full_gid': product_gid,
                'status': universal_status, # Use the smarter status
                'price': price,
                'title': product.get('title', ''),
                'listing_url': product.get('onlineStoreUrl'),
                '_raw': product
            }
        
        # if prepared_items:
        #     sample_key = next(iter(prepared_items))
        #     logger.info(f"--- [DEBUG] Sample Prepared API Item (ID: {sample_key}): {prepared_items[sample_key]}")

        return prepared_items

    def _prepare_db_data(self, existing_data: List[Dict]) -> Dict[str, Dict]:
        """Prepares local DB data into a lookup dictionary keyed by external_id."""
        db_items = {str(row['external_id']): row for row in existing_data if row.get('external_id')}
        logger.info(f"Prepared {len(db_items)} DB items for comparison")
        if db_items:
            sample_keys = list(db_items.keys())[:5]
            logger.info(f"Sample DB keys: {sample_keys}")
        return db_items


    # =========================================================================
    # (Optional) 7. WEBHOOK PROCESSING
    # =========================================================================
    async def process_order_webhook(self, payload: dict):
        """Process an incoming order webhook from Shopify."""
        # logger.info("Processing Shopify order webhook")
        # This would create sync_events for sold items
        # Implementation depends on your webhook structure
        # 1. Validate webhook signature (important!)
        # 2. Parse payload
        # 3. Check if order already processed
        # 4. Create/update local Sale/Order record
        # 5. Update local product stock/status
        # 6. Trigger StockUpdateEvent for StockManager
        # Example:
        # event = StockUpdateEvent(product_id=..., platform='shopify', new_quantity=..., ...)
        # await stock_manager.update_queue.put(event) # Assuming access to stock_manager instance
        pass
    @staticmethod
    def _extract_source_price(product: Product, reverb_data: Optional[Dict[str, Any]]) -> Optional[float]:
        """Determine the price that should seed the Shopify calculation."""

        # Prefer explicit Reverb pricing when available
        if reverb_data:
            price_info = reverb_data.get("price") or reverb_data.get("listing_price")
            if isinstance(price_info, dict):
                amount = price_info.get("amount") or price_info.get("value") or price_info.get("display")
                if amount:
                    try:
                        return float(amount)
                    except (TypeError, ValueError):
                        pass
            elif isinstance(price_info, (int, float, str)):
                try:
                    return float(price_info)
                except (TypeError, ValueError):
                    pass

        # Fallback to any platform data captured on the product
        platform_data = getattr(product, "package_dimensions", {}) or {}
        if isinstance(platform_data, dict):
            reverb_payload = platform_data.get("platform_data", {}).get("reverb", {})
            amount = reverb_payload.get("price")
            if amount:
                try:
                    return float(amount)
                except (TypeError, ValueError):
                    pass

        # Finally fall back to the product's base price
        for attr in ("base_price", "price", "price_notax"):
            value = getattr(product, attr, None)
            if value not in (None, 0, 0.0):
                try:
                    return float(value)
                except (TypeError, ValueError):
                    continue

        return None

    @staticmethod
    def _calculate_shopify_price(source_price: float) -> int:
        """Apply a 5% discount and round up to the nearest price ending in 999."""

        if source_price <= 0:
            raise ValueError("Source price must be positive to calculate Shopify price")

        discounted = source_price * 0.95

        if discounted <= 999:
            rounded = 999
        else:
            thousands = math.floor(discounted / 1000)
            rounded = thousands * 1000 + 999
            if rounded < discounted:
                rounded += 1000

        if rounded >= source_price:
            lower_thousands = max(math.floor(source_price / 1000) - 1, 0)
            candidate = lower_thousands * 1000 + 999
            if candidate >= source_price or candidate < 0:
                candidate = max(int(source_price) - 1, 1)
            rounded = candidate

        return int(rounded)
