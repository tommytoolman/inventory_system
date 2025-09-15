# app.services.reverb_service.py
import json
import time
import uuid
import logging
import iso8601

from datetime import datetime, timezone    
from fastapi import HTTPException
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.future import select
from sqlalchemy import update, text

from app.models.product import Product, ProductStatus, ProductCondition
from app.models.platform_common import PlatformCommon, ListingStatus, SyncStatus
from app.models.product import Product
from app.models.reverb import ReverbListing
from app.models.sync_event import SyncEvent
from app.services.reverb.client import ReverbClient
from app.core.config import Settings
from app.core.exceptions import ListingNotFoundError, ReverbAPIError

logger = logging.getLogger(__name__)

class ReverbService:
    """
    Service for interacting with Reverb marketplace.
    
    This class manages the integration between our inventory system and
    the Reverb platform, handling data transformation, error handling,
    and synchronization.
    """
    
    def __init__(self, db: AsyncSession, settings: Settings):
        """
        Initialize the Reverb service with database session and settings.
        
        Args:
            db: Database session for data access
            settings: Application settings including API credentials
        """
        self.db = db
        self.settings = settings
        
        # Use sandbox API for testing if enabled in settings
        use_sandbox = self.settings.REVERB_USE_SANDBOX
        # api_key = self.settings.REVERB_SANDBOX_API_KEY if use_sandbox else self.settings.REVERB_API_KEY
        
        self.client = ReverbClient(api_key=self.settings.REVERB_API_KEY, use_sandbox=use_sandbox)
    
    async def get_categories(self) -> Dict:
        """
        Get all categories from Reverb.
        
        Returns:
            Dict: Categories data
            
        Raises:
            ReverbAPIError: If the API request fails
        """
        try:
            return await self.client.get_categories()
        except Exception as e:
            logger.error(f"Error fetching categories: {str(e)}")
            if isinstance(e, ReverbAPIError):
                raise
            raise ReverbAPIError(f"Failed to fetch categories: {str(e)}")
    
    async def get_category(self, uuid: str) -> Dict:
        """
        Get a specific category by UUID.
        
        Args:
            uuid: Category UUID
            
        Returns:
            Dict: Category data
            
        Raises:
            ReverbAPIError: If the API request fails
        """
        try:
            return await self.client.get_category(uuid)
        except Exception as e:
            logger.error(f"Error fetching category {uuid}: {str(e)}")
            if isinstance(e, ReverbAPIError):
                raise
            raise ReverbAPIError(f"Failed to fetch category {uuid}: {str(e)}")
    
    async def get_conditions(self) -> Dict:
        """
        Get all listing conditions from Reverb.
        
        Returns:
            Dict: Listing conditions data
            
        Raises:
            ReverbAPIError: If the API request fails
        """
        try:
            return await self.client.get_listing_conditions()
        except Exception as e:
            logger.error(f"Error fetching conditions: {str(e)}")
            if isinstance(e, ReverbAPIError):
                raise
            raise ReverbAPIError(f"Failed to fetch conditions: {str(e)}")
            
    async def fetch_and_store_condition_mapping(self) -> Dict[str, str]:
        """
        Fetch conditions from Reverb and store for future use
        
        Returns:
            Dict[str, str]: Mapping of condition display names to UUIDs
            
        Raises:
            ReverbAPIError: If the API request fails
        """
        try:
            response = await self.client.get_listing_conditions()
            
            # Extract conditions and create a mapping of display names to UUIDs
            condition_mapping = {}
            
            if 'conditions' in response:
                for condition in response['conditions']:
                    if 'display_name' in condition and 'uuid' in condition:
                        condition_mapping[condition['display_name']] = condition['uuid']
            
            return condition_mapping
        except Exception as e:
            logger.error(f"Error fetching conditions: {str(e)}")
            if isinstance(e, ReverbAPIError):
                raise
            raise ReverbAPIError(f"Failed to fetch conditions: {str(e)}")
    
    async def create_draft_listing(self, reverb_listing_id: int, listing_data: Dict[str, Any] = None) -> ReverbListing:
        """
        Create a draft listing on Reverb based on product data.
        
        Args:
            reverb_listing_id: Database ID of the ReverbListing
            listing_data: Optional custom listing data overrides
            
        Returns:
            ReverbListing: Updated database record with Reverb listing ID
            
        Raises:
            ListingNotFoundError: If listing not found
            ReverbAPIError: If the API request fails
        """
        try:
            # Get the ReverbListing and associated PlatformCommon and Product
            listing = await self._get_reverb_listing(reverb_listing_id)
            if not listing:
                raise ListingNotFoundError(f"ReverbListing {reverb_listing_id} not found")
            
            platform_common = await self._get_platform_common(listing.platform_id)
            if not platform_common or not platform_common.product_id:
                raise ListingNotFoundError(f"PlatformCommon {listing.platform_id} or related Product not found")
            
            product = await self._get_product(platform_common.product_id)
            if not product:
                raise ListingNotFoundError(f"Product {platform_common.product_id} not found")
            
            # Prepare the listing data for Reverb API
            api_listing_data = listing_data or self._prepare_listing_data(listing, product)
            
            # Create the listing on Reverb
            response = await self.client.create_listing(api_listing_data)
            
            # Update database with the new Reverb listing ID
            if 'listing' in response and 'id' in response['listing']:
                reverb_id = str(response['listing']['id'])
                
                # Update the ReverbListing record
                listing.reverb_listing_id = reverb_id
                
                # Update platform_common sync status
                platform_common.sync_status = SyncStatus.SYNCED.value
                
                # Save changes to database
                self.db.add(listing)
                self.db.add(platform_common)
                await self.db.flush()
                
                logger.info(f"Created draft listing on Reverb with ID {reverb_id}")
                return listing
            else:
                logger.error(f"Failed to create listing: No listing ID in response: {response}")
                raise ReverbAPIError("Failed to create listing: No listing ID in response")
                
        except Exception as e:
            logger.error(f"Error creating draft listing: {str(e)}")
            if isinstance(e, (ListingNotFoundError, ReverbAPIError)):
                raise
            raise ReverbAPIError(f"Failed to create draft listing: {str(e)}")
    
    async def get_listing_details(self, reverb_listing_id: int) -> Dict:
        """
        Get detailed information about a listing from Reverb API
        
        Args:
            reverb_listing_id: Database ID of the ReverbListing
            
        Returns:
            Dict: Listing details from Reverb API
            
        Raises:
            ListingNotFoundError: If listing not found
            ReverbAPIError: If the API request fails
        """
        try:
            # Get the ReverbListing record
            listing = await self._get_reverb_listing(reverb_listing_id)
            if not listing or not listing.reverb_listing_id:
                raise ListingNotFoundError(f"ReverbListing {reverb_listing_id} not found or has no Reverb ID")
            
            # Fetch the listing details from Reverb API
            return await self.client.get_listing(listing.reverb_listing_id)
        
        except Exception as e:
            logger.error(f"Error getting listing details: {str(e)}")
            if isinstance(e, (ListingNotFoundError, ReverbAPIError)):
                raise
            raise ReverbAPIError(f"Failed to get listing details: {str(e)}")
    
    async def update_inventory(self, reverb_listing_id: int, quantity: int) -> bool:
        """
        Update the inventory quantity of a listing on Reverb
        
        Args:
            reverb_listing_id: Database ID of the ReverbListing
            quantity: New inventory quantity
            
        Returns:
            bool: Success status
            
        Raises:
            ListingNotFoundError: If listing not found
            ReverbAPIError: If the API request fails
        """
        try:
            # Get the ReverbListing record
            listing = await self._get_reverb_listing(reverb_listing_id)
            if not listing or not listing.reverb_listing_id:
                raise ListingNotFoundError(f"ReverbListing {reverb_listing_id} not found or has no Reverb ID")
            
            # Prepare inventory update data
            inventory_data = {
                "inventory": quantity,
                "has_inventory": quantity > 0
            }
            
            # Update the listing on Reverb
            await self.client.update_listing(listing.reverb_listing_id, inventory_data)
            
            # Update local database record
            listing.inventory_quantity = quantity
            listing.has_inventory = quantity > 0
            self.db.add(listing)
            await self.db.flush()
            
            logger.info(f"Updated inventory for listing {listing.reverb_listing_id} to {quantity}")
            return True
            
        except Exception as e:
            logger.error(f"Error updating inventory: {str(e)}")
            if isinstance(e, (ListingNotFoundError, ReverbAPIError)):
                raise
            raise ReverbAPIError(f"Failed to update inventory: {str(e)}")
    
    async def publish_listing(self, reverb_listing_id: int) -> bool:
        """
        Publish a draft listing on Reverb
        
        Args:
            reverb_listing_id: Database ID of the ReverbListing
            
        Returns:
            bool: Success status
            
        Raises:
            ListingNotFoundError: If listing not found
            ReverbAPIError: If the API request fails
        """
        try:
            # Get the ReverbListing and PlatformCommon records
            listing = await self._get_reverb_listing(reverb_listing_id)
            if not listing or not listing.reverb_listing_id:
                raise ListingNotFoundError(f"ReverbListing {reverb_listing_id} not found or has no Reverb ID")
            
            platform_common = await self._get_platform_common(listing.platform_id)
            if not platform_common:
                raise ListingNotFoundError(f"PlatformCommon {listing.platform_id} not found")
            
            # Publish the listing on Reverb
            publish_data = {"publish": True}
            await self.client.update_listing(listing.reverb_listing_id, publish_data)
            
            # Update local database records
            platform_common.status = ListingStatus.ACTIVE.value
            listing.reverb_state = "published"
            
            self.db.add(platform_common)
            self.db.add(listing)
            await self.db.flush()
            
            logger.info(f"Published listing {listing.reverb_listing_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error publishing listing: {str(e)}")
            if isinstance(e, (ListingNotFoundError, ReverbAPIError)):
                raise
            raise ReverbAPIError(f"Failed to publish listing: {str(e)}")
    
    async def end_listing(self, reverb_listing_id: int, reason: str = "not_for_sale") -> bool:
        """
        End a listing on Reverb
        
        Args:
            reverb_listing_id: Database ID of the ReverbListing
            reason: Reason for ending the listing
            
        Returns:
            bool: Success status
            
        Raises:
            ListingNotFoundError: If listing not found
            ReverbAPIError: If the API request fails
        """
        try:
            # Get the ReverbListing and PlatformCommon records
            listing = await self._get_reverb_listing(reverb_listing_id)
            if not listing or not listing.reverb_listing_id:
                raise ListingNotFoundError(f"ReverbListing {reverb_listing_id} not found or has no Reverb ID")
            
            platform_common = await self._get_platform_common(listing.platform_id)
            if not platform_common:
                raise ListingNotFoundError(f"PlatformCommon {listing.platform_id} not found")
            
            # End the listing on Reverb
            end_data = {"state": "ended"}
            await self.client.update_listing(listing.reverb_listing_id, end_data)
            
            # Update local database records
            platform_common.status = ListingStatus.ENDED.value
            listing.reverb_state = "ended"
            
            self.db.add(platform_common)
            self.db.add(listing)
            await self.db.flush()
            
            logger.info(f"Ended listing {listing.reverb_listing_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error ending listing: {str(e)}")
            if isinstance(e, (ListingNotFoundError, ReverbAPIError)):
                raise
            raise ReverbAPIError(f"Failed to end listing: {str(e)}")

    # Commented out 16/08/25 ... depcrecated in favour of new process
    # async def run_import_process(self, api_key: str, sync_run_id: uuid.UUID, use_cache: bool = False, cache_file: str = "reverb_data.json"):
    #     """
    #     Run the Reverb inventory import process, with optional caching.
        
    #     Args:
    #         api_key: The Reverb API key.
    #         sync_run_id: The UUID for this synchronization run.
    #         use_cache: If True, tries to load data from cache_file instead of the API.
    #         cache_file: The path to the cache file.
    #     """
    #     listings = []
    #     cache_path = Path(cache_file)

    #     try:
    #         print(f"Starting Reverb.run_import_process (Caching {'enabled' if use_cache else 'disabled'})")

    #         # --- CACHING LOGIC ---
    #         if use_cache and cache_path.exists():
    #             print(f"Loading listings from cache file: {cache_path}")
    #             with open(cache_path, 'r') as f:
    #                 listings = json.load(f)
    #             print(f"Loaded {len(listings)} listings from cache.")
    #         else:
    #             print("Cache not used or not found. Downloading listings from Reverb API...")
    #             client = ReverbClient(api_key)
    #             start_time = time.time()
    #             listings = await client.get_all_listings_detailed(max_concurrent=10)
    #             end_time = time.time()
    #             print(f"Downloaded {len(listings)} detailed listings in {end_time - start_time:.1f} seconds")

    #             # Save the fresh download to the cache file for future runs
    #             print(f"Saving fresh API data to cache file: {cache_path}")
    #             cache_path.parent.mkdir(parents=True, exist_ok=True)
    #             with open(cache_path, 'w') as f:
    #                 json.dump(listings, f, indent=2)
    #         # --- END CACHING LOGIC ---

    #         if not listings:
    #             print("Reverb listings download failed or cache was empty.")
    #             return {"status": "error", "message": "No Reverb listings data received"}
            
    #         print(f"Successfully loaded inventory with {len(listings)} items.")
            
    #         # Process inventory updates using differential sync
    #         # NOTE: We can now switch back to the clean sync_reverb_inventory function
    #         print("Processing inventory updates using differential sync...")
    #         sync_stats = await self.sync_reverb_inventory(listings, sync_run_id)

    #         print(f"Inventory sync process complete: {sync_stats}")
    #         return {
    #             "status": "success",
    #             "message": "Reverb inventory synced successfully.",
    #             **sync_stats
    #         }
        
    #     except Exception as e:
    #         import traceback
    #         error_traceback = traceback.format_exc()
    #         print(f"Exception in ReverbService.run_import_process: {str(e)}")
    #         print(f"Traceback: {error_traceback}")
    #         return {"status": "error", "message": str(e)}

    # Private helper methods
    
    async def _get_platform_common(self, platform_id: int) -> Optional[PlatformCommon]:
        """Get platform_common record by ID with associated product"""
        query = select(PlatformCommon).where(PlatformCommon.id == platform_id)
        result = await self.db.execute(query)
        return result.scalars().first()
    
    async def _get_product(self, product_id: int) -> Optional[Product]:
        """Get product record by ID"""
        query = select(Product).where(Product.id == product_id)
        result = await self.db.execute(query)
        return result.scalars().first()
    
    async def _get_reverb_listing(self, listing_id: int) -> Optional[ReverbListing]:
        """Get reverb_listing record by ID"""
        query = select(ReverbListing).where(ReverbListing.id == listing_id)
        result = await self.db.execute(query)
        return result.scalars().first()

    async def _get_all_listings_from_api(self, state: str) -> List[Dict]:
        """
        Fetches all listings for a given state by paginating through results
        using the service's own client.
        """
        logger.info(f"Fetching all listings from Reverb API with state: '{state}'...")
        # This now correctly uses the service's own configured client
        return await self.client.get_all_listings(state=state)
    
    def _prepare_listing_data(self, listing: ReverbListing, product: Product) -> Dict[str, Any]:
        """
        Prepare listing data for Reverb API
        
        Args:
            listing: ReverbListing record
            product: Associated Product record
            
        Returns:
            Dict: Listing data formatted for Reverb API
        """
        data = {
            "title": product.title or f"{product.brand} {product.model}",
            "description": product.description or "",
            "make": product.brand,
            "model": product.model,
            # Format condition as object with UUID
            "condition": {
                "uuid": self._get_condition_uuid(product.condition)
            },
            # Format price as object with amount and currency
            "price": {
                "amount": str(product.base_price),  # Must be a string
                "currency": "USD" if self.client.use_sandbox else "GBP"  # USD for sandbox, GBP for production
            },
            "shipping": {
                "local": True,
                "us": True,
                "us_rate": "25.00"  # Default shipping rate
            },
            "categories": [
                {"uuid": listing.reverb_category_uuid or "dfd39027-d134-4353-b9e4-57dc6be791b9"}  # Default to Electric Guitars
            ],
            "has_inventory": listing.has_inventory,
            "inventory": listing.inventory_quantity or 1,
            "offers_enabled": listing.offers_enabled
        }
        
        # Add photos if available
        if listing.photos:
            data["photos"] = listing.photos.split(",")
            
        # Add year if available
        if product.year:
            data["year"] = str(product.year)
            
        # Add finish if available
        if product.finish:
            data["finish"] = product.finish
            
        return data

    def _get_condition_uuid(self, condition_name: str) -> str:
        """Map condition name to UUID"""
        condition_map = {
            "Mint": "ec942c5e-fd9d-4a70-af95-ce686ed439e5",
            "Excellent": "df268ad1-c462-4ba6-b6db-e007e23922ea",
            "Very Good": "ae4d9114-1bd7-4ec5-a4ba-6653af5ac84d", 
            "Good": "ddadff2a-188c-42e0-be90-ebed197400a3",
            "Fair": "a2356006-97f9-487c-bd68-6c148a8ffe93",
            "Poor": "41b843b5-af33-4f37-9e9e-eec54aac6ce4",
            "Non Functioning": "196adee9-5415-4b5d-910f-39f2eb72e92f"
        }
        # Default to "Excellent" condition if not found
        return condition_map.get(condition_name, "df268ad1-c462-4ba6-b6db-e007e23922ea")
    
    # Replaced by _fetch_existing_reverb_data for new sync sats 14/07
    async def _process_reverb_listings(self, listings: List[Dict]) -> Dict[str, int]:
        """Process Reverb listings (update existing, create new)"""
        stats = {"total": len(listings), "created": 0, "updated": 0, "errors": 0}
        
        try:
            for listing in listings:
                try:
                    # Extract Reverb listing ID
                    reverb_id = str(listing.get('id'))
                    sku = f"REV-{reverb_id}"
                    
                    # Check if product exists
                    stmt = text("SELECT id FROM products WHERE sku = :sku")
                    result = await self.db.execute(stmt, {"sku": sku})
                    existing_product_id = result.scalar_one_or_none()
                    
                    if existing_product_id:
                        # Update existing product
                        await self._update_existing_product(existing_product_id, listing)
                        stats["updated"] += 1
                    else:
                        # Create new product
                        await self._create_new_product(listing, sku)
                        stats["created"] += 1
                        
                except Exception as e:
                    logger.error(f"Error processing listing {listing.get('id')}: {e}")
                    stats["errors"] += 1
            
            await self.db.commit()
            return stats
            
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error in _process_reverb_listings: {e}")
            raise

    # Fixed query to mirror eBay/V&R/Shopify pattern
    async def _fetch_existing_reverb_data_old(self) -> List[Dict]:
        """Fetches all Reverb-related data from the local database."""
        query = text("""
            WITH reverb_data AS (
                -- Get all Reverb listings with their platform_common records
                SELECT DISTINCT ON (rl.reverb_listing_id)
                    p.id as product_id, 
                    p.sku, 
                    p.base_price, 
                    p.description, 
                    p.status as product_status,
                    pc.id as platform_common_id, 
                    pc.external_id, 
                    pc.status as platform_common_status,
                    rl.id as reverb_listing_id, 
                    rl.reverb_state, 
                    rl.list_price
                FROM reverb_listings rl
                JOIN platform_common pc ON pc.id = rl.platform_id AND pc.platform_name = 'reverb'
                LEFT JOIN products p ON p.id = pc.product_id
                ORDER BY rl.reverb_listing_id, rl.id DESC
            )
            SELECT 
                product_id, sku, base_price, description, product_status,
                platform_common_id, external_id, platform_common_status,
                reverb_listing_id, reverb_state, list_price
            FROM reverb_data
            
            UNION ALL
            
            -- Also get platform_common records without reverb_listings (orphaned records)
            SELECT 
                p.id as product_id, 
                p.sku, 
                p.base_price, 
                p.description, 
                p.status as product_status,
                pc.id as platform_common_id, 
                pc.external_id, 
                pc.status as platform_common_status,
                NULL as reverb_listing_id, 
                NULL as reverb_state, 
                NULL as list_price
            FROM platform_common pc
            LEFT JOIN products p ON p.id = pc.product_id
            WHERE pc.platform_name = 'reverb'
            AND NOT EXISTS (
                SELECT 1 FROM reverb_listings rl 
                WHERE rl.platform_id = pc.id
            )
        """)
        result = await self.db.execute(query)
        return [row._asdict() for row in result.fetchall()]

    async def _fetch_existing_reverb_data(self) -> List[Dict]:
        """Fetches all Reverb-related data from the local database, focusing on the source of truth."""
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
            WHERE pc.platform_name = 'reverb'
        """)
        result = await self.db.execute(query)
        return [row._asdict() for row in result.fetchall()]

    # Remove the diagnostic version and replace with clean sync
    async def sync_reverb_inventory(self, listings: List[Dict], sync_run_id: uuid.UUID) -> Dict[str, Any]:
        """Main sync method - compares API data with DB and applies only necessary changes."""
        stats = {
            "total_from_reverb": len(listings), 
            "events_logged": 0, 
            "created": 0, 
            "updated": 0, 
            "removed": 0, 
            "unchanged": 0, 
            "errors": 0
        }
        
        try:
            # Step 1: Fetch all existing Reverb data from DB
            existing_data = await self._fetch_existing_reverb_data()
            
            # Step 2: Convert data to lookup dictionaries for O(1) access
            api_items = self._prepare_api_data(listings)
            db_items = self._prepare_db_data(existing_data)
            
            # Step 3: Calculate differences (remove pending_ids logic for simplicity)
            changes = self._calculate_changes(api_items, db_items)
            
            # Step 4: Apply changes in batches
            logger.info(f"Applying changes: {len(changes['create'])} new, "
                        f"{len(changes['update'])} updates, {len(changes['remove'])} removals")
            
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
            logger.error(f"Sync failed: {str(e)}", exc_info=True)
            stats['errors'] += 1
            
        return stats
    
    # Fixed batch methods to only log events (no DB updates)
    async def _batch_create_products(self, items: List[Dict], sync_run_id: uuid.UUID) -> Tuple[int, int]:
        """Log rogue listings to sync_events only - no database records created."""
        created_count, events_logged = 0, 0
        
        # Prepare all events first
        events_to_create = []
        for item in items:
            try:
                logger.warning(f"Rogue SKU Detected: Reverb item {item['reverb_id']} ('{item.get('title')}') not found in local DB. Logging to sync_events for later processing.")
                
                event_data = {
                    'sync_run_id': sync_run_id,
                    'platform_name': 'reverb',
                    'product_id': None,
                    'platform_common_id': None,
                    'external_id': item['reverb_id'],
                    'change_type': 'new_listing',
                    'change_data': {
                        'title': item['title'],
                        'price': item['price'],
                        'state': item['state'],
                        'sku': item['sku'],
                        'brand': item['brand'],
                        'model': item['model'],
                        'raw_data': item['_raw']
                    },
                    'status': 'pending'
                }
                events_to_create.append(event_data)
                created_count += 1
            except Exception as e:
                logger.error(f"Failed to prepare event for Reverb item {item['reverb_id']}: {e}", exc_info=True)
        
        # Bulk insert with ON CONFLICT DO NOTHING to handle duplicates gracefully
        if events_to_create:
            try:
                stmt = insert(SyncEvent).values(events_to_create)
                stmt = stmt.on_conflict_do_nothing(
                    constraint='sync_events_platform_external_change_unique'
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
                db_price_for_compare = float(db_data.get('list_price') or 0.0)
                if abs(api_data['price'] - db_price_for_compare) > 0.01:
                    all_events.append({
                        'sync_run_id': sync_run_id,
                        'platform_name': 'reverb',
                        'product_id': db_data['product_id'],
                        'platform_common_id': db_data['platform_common_id'],
                        'external_id': api_data['reverb_id'],
                        'change_type': 'price',
                        'change_data': {
                            'old': db_data.get('list_price'),
                            'new': api_data['price'],
                            'reverb_id': api_data['reverb_id']
                        },
                        'status': 'pending'
                    })
                
                # Status change event
                if api_data['state'] != str(db_data.get('reverb_state', '')).lower():
                    all_events.append({
                        'sync_run_id': sync_run_id,
                        'platform_name': 'reverb',
                        'product_id': db_data['product_id'],
                        'platform_common_id': db_data['platform_common_id'],
                        'external_id': api_data['reverb_id'],
                        'change_type': 'status_change',
                        'change_data': {
                            'old': db_data.get('reverb_state'),
                            'new': api_data['state'],
                            'reverb_id': api_data['reverb_id'],
                            'is_sold': api_data['is_sold']
                        },
                        'status': 'pending'
                    })
                
                updated_count += 1
                
            except Exception as e:
                logger.error(f"Failed to prepare events for Reverb item {item['api_data']['reverb_id']}: {e}", exc_info=True)
        
        # Bulk insert all events with duplicate handling
        if all_events:
            try:
                stmt = insert(SyncEvent).values(all_events)
                stmt = stmt.on_conflict_do_nothing(
                    constraint='sync_events_platform_external_change_unique'
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
                
                # Price change event check
                db_price_for_compare = float(db_data.get('base_price') or 0.0)
                if abs(api_data['price'] - db_price_for_compare) > 0.01:
                    all_events.append({
                        'sync_run_id': sync_run_id, 'platform_name': 'reverb',
                        'product_id': db_data['product_id'], 'platform_common_id': db_data['platform_common_id'],
                        'external_id': api_data['external_id'], 'change_type': 'price',
                        'change_data': {'old': db_data.get('base_price'), 'new': api_data['price']},
                        'status': 'pending'
                    })
                
                # Status change event check
                api_status = api_data.get('status')
                db_status = db_data.get('platform_common_status')
                off_market_statuses = ['sold', 'ended', 'archived']
                statuses_match = (api_status in off_market_statuses and db_status in off_market_statuses) or (api_status == db_status)

                if not statuses_match:
                    all_events.append({
                        'sync_run_id': sync_run_id, 'platform_name': 'reverb',
                        'product_id': db_data['product_id'], 'platform_common_id': db_data['platform_common_id'],
                        'external_id': api_data['external_id'], 'change_type': 'status_change',
                        'change_data': {'old': db_status, 'new': api_status},
                        'status': 'pending'
                    })
                
                updated_count += 1
            except Exception as e:
                logger.error(f"Failed to prepare events for Reverb item {item['api_data']['external_id']}: {e}", exc_info=True)
        
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
        """SYNC PHASE: Only log removal events to sync_events - NO database table updates."""
        removed_count, events_logged = 0, 0
        
        # Prepare all removal events
        events_to_create = []
        for item in items:
            try:
                events_to_create.append({
                    'sync_run_id': sync_run_id,
                    'platform_name': 'reverb',
                    'product_id': item['product_id'],
                    'platform_common_id': item['platform_common_id'],
                    'external_id': item['external_id'],
                    'change_type': 'removed_listing',
                    'change_data': {
                        'sku': item['sku'],
                        'reverb_id': item['external_id'],
                        'reason': 'not_found_in_api'
                    },
                    'status': 'pending'
                })
                removed_count += 1
            except Exception as e:
                logger.error(f"Failed to prepare removal event for Reverb item {item['external_id']}: {e}", exc_info=True)
        
        # Bulk insert with duplicate handling
        if events_to_create:
            try:
                stmt = insert(SyncEvent).values(events_to_create)
                stmt = stmt.on_conflict_do_nothing(
                    constraint='sync_events_platform_external_change_unique'
                )
                result = await self.db.execute(stmt)
                events_logged = len(events_to_create)
                logger.info(f"Attempted to log {len(events_to_create)} removal events (duplicates ignored)")
            except Exception as e:
                logger.error(f"Failed to bulk insert removal events: {e}", exc_info=True)
        
        return removed_count, events_logged

    async def _fetch_pending_new_listings(self) -> set[str]:
            """Fetch external_ids for Reverb listings that are already pending creation."""
            query = text("""
                SELECT external_id FROM sync_events
                WHERE platform_name = 'reverb'
                AND change_type = 'new_listing'
                AND status = 'pending'
            """)
            result = await self.db.execute(query)
            return {row[0] for row in result.fetchall()}
    
    async def _mark_removed_reverb_products(self, listings: List[Dict]) -> Dict[str, int]:
        """Mark products that are no longer on Reverb as removed"""
        stats = {"marked_removed": 0}
        
        # Get Reverb listing IDs from current data
        current_ids = {f"REV-{listing.get('id')}" for listing in listings if listing.get('id')}
        
        # Find products in DB but not in current listings
        stmt = text("SELECT sku, id FROM products WHERE sku LIKE 'REV-%' AND sku != ALL(:current_skus)")
        result = await self.db.execute(stmt, {"current_skus": tuple(current_ids)})
        removed_products = result.fetchall()
        
        # Mark as removed
        for sku, product_id in removed_products:
            platform_update = text("""
                UPDATE platform_common 
                SET status = 'REMOVED', 
                    sync_status = 'SYNCED',
                    last_sync = timezone('utc', now()),
                    updated_at = timezone('utc', now())
                WHERE product_id = :product_id AND platform_name = 'reverb'
            """)
            await self.db.execute(platform_update, {"product_id": product_id})
            stats["marked_removed"] += 1
        
        logger.info(f"Marked {stats['marked_removed']} Reverb products as removed")
        return stats

    async def update_listing_price(self, external_id: str, new_price: float) -> bool:
        """Outbound action to update the price of a listing on Reverb."""
        logger.info(f"Received request to update Reverb listing {external_id} to price £{new_price:.2f}.")
        try:
            # Reverb's API expects the price as an object with amount and currency
            price_data = {
                "price": {
                    "amount": f"{new_price:.2f}",
                    "currency": "GBP"
                }
            }
            
            response = await self.client.update_listing(external_id, price_data)
            
            # A successful update returns the updated listing object.
            if response and 'id' in response.get('listing', {}):
                logger.info(f"Successfully sent price update for Reverb listing {external_id}.")
                return True
            
            logger.error(f"API call to update price for Reverb listing {external_id} failed. Response: {response}")
            return False
        except Exception as e:
            logger.error(f"Exception while updating price for Reverb listing {external_id}: {e}", exc_info=True)
            return False

    async def _update_existing_product(self, product_id: int, listing: Dict):
        """Update an existing product with new Reverb data"""
        # Extract data from listing
        is_sold = listing.get('state', {}).get('slug') == 'sold'
        new_status = ProductStatus.SOLD if is_sold else ProductStatus.ACTIVE
        
        # Update product
        update_stmt = text("""
            UPDATE products 
            SET base_price = :price,
                description = :description,
                status = :status,
                updated_at = timezone('utc', now())
            WHERE id = :product_id
        """)
        
        await self.db.execute(update_stmt, {
            "product_id": product_id,
            "price": float(listing.get('price', {}).get('amount', 0)) if listing.get('price') else 0,
            "description": listing.get('description', ''),
            "status": new_status.value
        })
        
        # Update platform_common
        platform_update = text("""
            UPDATE platform_common 
            SET status = :status,
                sync_status = 'SYNCED',
                last_sync = timezone('utc', now()),
                updated_at = timezone('utc', now())
            WHERE product_id = :product_id AND platform_name = 'reverb'
        """)
        
        platform_status = ListingStatus.SOLD if is_sold else ListingStatus.ACTIVE
        await self.db.execute(platform_update, {
            "product_id": product_id,
            "status": platform_status.value
        })

    async def run_import_process_old(self, sync_run_id: uuid.UUID) -> Dict[str, Any]:
        """
        Runs the differential sync for Reverb using a single, consistently
        configured client for all API calls.
        """
        stats = {"api_live_count": 0, "db_live_count": 0, "events_logged": 0, "rogue_listings": 0, "status_changes": 0, "errors": 0}
        logger.info(f"=== ReverbService: STARTING SYNC (run_id: {sync_run_id}) ===")

        try:
            # --- REFACTORED: No longer imports or calls the external script ---
            live_listings_api = await self._get_all_listings_from_api(state='live')
            
            api_live_ids = {str(item['id']) for item in live_listings_api}
            stats['api_live_count'] = len(api_live_ids)
            logger.info(f"Found {stats['api_live_count']} live listings on Reverb API.")

            # (The rest of the method remains exactly the same as before)
            # ...
            local_live_ids_map = await self._fetch_local_live_reverb_ids()
            local_live_ids = set(local_live_ids_map.keys())
            stats['db_live_count'] = len(local_live_ids)
            logger.info(f"Found {stats['db_live_count']} live listings in local DB for Reverb.")

            new_rogue_ids = api_live_ids - local_live_ids
            missing_live_ids = local_live_ids - api_live_ids
            
            logger.info(f"Detected {len(new_rogue_ids)} potential new listings and {len(missing_live_ids)} status changes.")
            stats['rogue_listings'] = len(new_rogue_ids)
            stats['status_changes'] = len(missing_live_ids)
            
            events_to_log = []

            for reverb_id in new_rogue_ids:
                events_to_log.append(self._prepare_sync_event(
                    sync_run_id, 'new_listing', external_id=reverb_id,
                    change_data={'reason': 'Live on Reverb but not in local DB'}
                ))

            for reverb_id in missing_live_ids:
                db_item = local_live_ids_map[reverb_id]
                try:
                    details = await self.client.get_listing_details(reverb_id)
                    new_status = details.get('state', {}).get('slug', 'unknown')
                    
                    events_to_log.append(self._prepare_sync_event(
                        sync_run_id, 'status_change', 
                        external_id=reverb_id,
                        product_id=db_item['product_id'],
                        platform_common_id=db_item['platform_common_id'],
                        change_data={'old': 'live', 'new': new_status, 'reverb_id': reverb_id}
                    ))
                except ReverbAPIError:
                    logger.warning(f"Logging item {reverb_id} as 'deleted' due to API error (Not Found).")
                    events_to_log.append(self._prepare_sync_event(
                        sync_run_id, 'status_change',
                        external_id=reverb_id,
                        product_id=db_item['product_id'],
                        platform_common_id=db_item['platform_common_id'],
                        change_data={'old': 'live', 'new': 'deleted', 'reverb_id': reverb_id, 'reason': 'API Not Found'}
                    ))
                    stats['errors'] += 1

            if events_to_log:
                await self._batch_log_events(events_to_log)
                stats['events_logged'] = len(events_to_log)
            
            await self.db.commit()
            logger.info(f"=== ReverbService: FINISHED SYNC === Final Stats: {stats}")
            return {"status": "success", "message": "Reverb sync complete.", **stats}

        except Exception as e:
            await self.db.rollback()
            logger.error(f"Reverb sync failed: {e}", exc_info=True)
            stats['errors'] += 1
            return {"status": "error", "message": str(e), **stats}

    async def run_import_process(self, sync_run_id: uuid.UUID) -> Dict[str, Any]:
        """
        Runs the sync for Reverb. This method detects new live listings on Reverb
        and status changes for existing listings (e.g., live -> sold).
        """
        stats = {"api_live_count": 0, "db_live_count": 0, "events_logged": 0, "errors": 0}
        logger.info(f"=== ReverbService: STARTING SYNC (run_id: {sync_run_id}) ===")

        try:
            # 1. Fetch all LIVE listings from the Reverb API.
            live_listings_api = await self._get_all_listings_from_api(state='live')
            api_live_ids = {str(item['id']) for item in live_listings_api}
            stats['api_live_count'] = len(api_live_ids)
            logger.info(f"Found {stats['api_live_count']} live listings on Reverb API.")

            # 2. Fetch all Reverb listings marked as 'live' in our local DB.
            local_live_ids_map = await self._fetch_local_live_reverb_ids()
            local_live_ids = set(local_live_ids_map.keys())
            stats['db_live_count'] = len(local_live_ids)
            logger.info(f"Found {stats['db_live_count']} live listings in local DB for Reverb.")

            # 3. Compare the sets of IDs to find differences.
            new_rogue_ids = api_live_ids - local_live_ids
            missing_from_api_ids = local_live_ids - api_live_ids
            
            logger.info(f"Detected {len(new_rogue_ids)} new 'rogue' listings and {len(missing_from_api_ids)} potential status changes.")

            events_to_log = []

            # 4. Create 'new_listing' events for rogue items.
            for reverb_id in new_rogue_ids:
                events_to_log.append(self._prepare_sync_event(
                    sync_run_id, 'new_listing', external_id=reverb_id,
                    change_data={'reason': 'Live on Reverb but not in local DB'}
                ))

            # 5. For items no longer 'live' on the API, fetch their details to find out WHY.
            for reverb_id in missing_from_api_ids:
                db_item = local_live_ids_map[reverb_id]
                try:
                    # This second API call is crucial to get the new status (e.g., 'sold', 'ended').
                    details = await self.client.get_listing_details(reverb_id)
                    new_status = details.get('state', {}).get('slug', 'unknown')
                    
                    events_to_log.append(self._prepare_sync_event(
                        sync_run_id, 'status_change', 
                        external_id=reverb_id,
                        product_id=db_item['product_id'],
                        platform_common_id=db_item['platform_common_id'],
                        change_data={'old': 'live', 'new': new_status, 'reverb_id': reverb_id}
                    ))
                except ReverbAPIError:
                    # If the API gives a 'Not Found' error, the listing was likely deleted.
                    logger.warning(f"Logging item {reverb_id} as 'deleted' due to API error (Not Found).")
                    events_to_log.append(self._prepare_sync_event(
                        sync_run_id, 'status_change',
                        external_id=reverb_id,
                        product_id=db_item['product_id'],
                        platform_common_id=db_item['platform_common_id'],
                        change_data={'old': 'live', 'new': 'deleted', 'reverb_id': reverb_id, 'reason': 'API Not Found'}
                    ))
                    stats['errors'] += 1

            # 6. Log all generated events to the database.
            if events_to_log:
                await self._batch_log_events(events_to_log)
                stats['events_logged'] = len(events_to_log)
            
            await self.db.commit()
            logger.info(f"=== ReverbService: FINISHED SYNC === Final Stats: {stats}")
            return {"status": "success", "message": "Reverb sync complete.", **stats}

        except Exception as e:
            await self.db.rollback()
            logger.error(f"Reverb sync failed: {e}", exc_info=True)
            stats['errors'] += 1
            return {"status": "error", "message": str(e), **stats}

    # Ensure these helper methods are in your ReverbService class
    
    def _prepare_api_data_old(self, listings: List[Dict]) -> Dict[str, Dict]:
        """Convert API data to lookup dict by Reverb ID."""
        api_items = {}
        for listing in listings:
            reverb_id = str(listing.get('id', ''))
            if not reverb_id:
                continue
            
            state_obj = listing.get('state', {})
            state_slug = state_obj.get('slug', 'unknown') if isinstance(state_obj, dict) else 'unknown'
            
            api_items[reverb_id] = {
                'reverb_id': reverb_id,
                'sku': f"REV-{reverb_id}",
                'price': float(listing.get('price', {}).get('amount', 0)) if listing.get('price') else 0,
                'is_sold': state_slug == 'sold',
                'state': state_slug,
                'title': listing.get('title', ''),
                'brand': listing.get('make', 'Unknown'),
                'model': listing.get('model', 'Unknown'),
                'description': listing.get('description', ''),
                '_raw': listing
            }
        return api_items

    def _prepare_api_data(self, listings: List[Dict]) -> Dict[str, Dict]:
        """Convert API data to a lookup dict and translate statuses."""
        api_items = {}
        for listing in listings:
            reverb_id = str(listing.get('id', ''))
            if not reverb_id:
                continue
            
            state_slug = str(listing.get('state', {}).get('slug', 'unknown')).lower()

            # Translate Reverb's 'live' to our universal 'active'
            universal_status = 'active' if state_slug == 'live' else state_slug
            
            api_items[reverb_id] = {
                'external_id': reverb_id,
                'status': universal_status, # Use the translated status
                'price': float(listing.get('price', {}).get('amount', 0)),
                '_raw': listing
            }
        return api_items

    def _prepare_db_data(self, existing_data: List[Dict]) -> Dict[str, Dict]:
        """Convert DB data to lookup dict by external ID."""
        return {str(row['external_id']): row for row in existing_data if row.get('external_id')}

    def _calculate_changes(self, api_items: Dict, db_items: Dict) -> Dict[str, List]:
        """Calculate what needs to be created, updated, or removed."""
        changes = {'create': [], 'update': [], 'remove': []}
        
        api_ids = set(api_items.keys())
        db_ids = set(db_items.keys())
        
        for reverb_id in api_ids - db_ids:
            changes['create'].append(api_items[reverb_id])
        
        for reverb_id in api_ids & db_ids:
            if self._has_changed(api_items[reverb_id], db_items[reverb_id]):
                changes['update'].append({'api_data': api_items[reverb_id], 'db_data': db_items[reverb_id]})
        
        for reverb_id in db_ids - api_ids:
            changes['remove'].append(db_items[reverb_id])
            
        return changes

    def _has_changed_old(self, api_item: Dict, db_item: Dict) -> bool:
        """Check if an item has meaningful changes."""
        # Price check
        db_price = float(db_item.get('list_price') or 0)
        if abs(api_item['price'] - db_price) > 0.01:
            return True
        
        # Status check
        api_state = api_item['state']
        db_state = str(db_item.get('reverb_state', '')).lower()
        if api_state != db_state:
            return True
        
        return False

    def _has_changed(self, api_item: Dict, db_item: Dict) -> bool:
        """Compares API data against the new, correct fields from our database query."""
        api_status = api_item.get('status')
        db_status = db_item.get('platform_common_status')
        
        off_market_statuses = ['sold', 'ended', 'archived']
        statuses_match = (api_status in off_market_statuses and db_status in off_market_statuses) or \
                         (api_status == db_status)

        if not statuses_match:
            return True
            
        db_price = float(db_item.get('base_price') or 0.0)
        if abs(api_item['price'] - db_price) > 0.01:
            return True

        return False

    def _prepare_sync_event(self, sync_run_id, change_type, external_id, change_data, product_id=None, platform_common_id=None) -> Dict:
        """Helper to construct a SyncEvent dictionary for bulk insertion."""
        return {
            'sync_run_id': sync_run_id,
            'platform_name': 'reverb',
            'product_id': product_id,
            'platform_common_id': platform_common_id,
            'external_id': external_id,
            'change_type': change_type,
            'change_data': change_data,
            'status': 'pending'
        }

    async def _batch_log_events(self, events: List[Dict]):
        """Bulk inserts a list of sync events."""
        if not events:
            return
        logger.info(f"Logging {len(events)} events to the database.")
        try:
            # stmt = insert(SyncEvent).values(events)
            # stmt = stmt.on_conflict_do_nothing(
            #     constraint='sync_events_platform_external_change_unique'
            # )
            stmt = insert(SyncEvent).values(events)
            stmt = stmt.on_conflict_do_nothing(
                index_elements=['platform_name', 'external_id', 'change_type'],
                index_where=(SyncEvent.status == 'pending')
            )
            await self.db.execute(stmt)
        except Exception as e:
            logger.error(f"Failed to bulk insert sync events: {e}", exc_info=True)
            raise

    async def mark_item_as_sold(self, external_id: str) -> bool:
        """Outbound action to end a listing on Reverb because it sold elsewhere."""
        logger.info(f"Received request to end Reverb listing {external_id} (sold elsewhere).")
        try:
            response = await self.client.end_listing(external_id, reason="not_sold")

            # --- FINAL ROBUST CHECK ---

            # Scenario 1: The response is empty or None. We now treat this as a
            # likely success for an end_listing call that returns 200 OK but no body.
            if not response:
                logger.warning(f"Reverb API returned an empty success response for {external_id}, likely because it was already ended. Treating as success.")
                return True

            # Scenario 2: The response has a body, so we inspect it for explicit confirmation.
            listing_info = response.get('listing', {})
            state_info = listing_info.get('state')

            is_ended_nested = isinstance(state_info, dict) and state_info.get('slug') == 'ended'
            is_ended_simple = isinstance(state_info, str) and state_info.lower() == 'ended'

            if is_ended_nested or is_ended_simple:
                logger.info(f"Successfully CONFIRMED Reverb listing {external_id} is ended via response body.")
                return True
            else:
                # This covers the case of a 200 OK but with an unexpected body.
                logger.error(f"API call to end Reverb listing {external_id} returned a non-empty, unconfirmed response: {response}")
                return False

        except ReverbAPIError as e:
            # Scenario 3: The API returns a 422 error because the listing is already ended.
            error_message = str(e)
            if "This listing has already ended" in error_message:
                logger.warning(f"Reverb listing {external_id} is already ended (confirmed via 422 error). Treating as success.")
                return True 
            else:
                logger.error(f"A genuine Reverb API Error occurred for listing {external_id}: {e}", exc_info=True)
                return False
        except Exception as e:
            # Scenario 4: Any other exception (network error, etc.)
            logger.error(f"A non-API exception occurred while ending Reverb listing {external_id}: {e}", exc_info=True)
            return False

    async def _fetch_local_live_reverb_ids(self) -> Dict[str, Dict]:
        """Fetches all Reverb listings marked as 'live' in the local DB."""
        logger.info("Fetching live Reverb listings from local DB.")
        query = text("""
            SELECT pc.external_id, pc.product_id, pc.id as platform_common_id
            FROM platform_common pc
            JOIN reverb_listings rl ON pc.id = rl.platform_id
            WHERE pc.platform_name = 'reverb' AND rl.reverb_state = 'live'
        """)
        result = await self.db.execute(query)
        return {str(row.external_id): row._asdict() for row in result.fetchall()}

    def _convert_api_timestamp_to_naive_utc(self, timestamp_str: str | None) -> datetime | None:
        """
        Parses an ISO 8601 timestamp string (which can be offset-aware)
        from an API, converts it to UTC, and returns an offset-naive 
        datetime object suitable for storing in TIMESTAMP WITHOUT TIME ZONE columns.
        """
        if not timestamp_str:
            return None
        try:
            # 1. Parse the string from Reverb. 
            #    iso8601.parse_date() will create an "offset-aware" datetime object
            #    if the string has timezone info (e.g., '2023-03-09T04:46:32-06:00').
            dt_aware = iso8601.parse_date(timestamp_str)
            
            # 2. Convert this "aware" datetime object to its equivalent in UTC.
            #    The object is still "aware" at this point, but its time and tzinfo now represent UTC.
            dt_utc_aware = dt_aware.astimezone(datetime.timezone.utc)
            
            # 3. Make it "naive" by removing the timezone information.
            #    The actual clock time is now UTC, and we remove the "UTC" label
            #    because the database column doesn't store the label.
            dt_utc_naive = dt_utc_aware.replace(tzinfo=None)
            
            return dt_utc_naive
        except Exception as e:
            return None
    
    