# app/services/ebay_service.py
import os
import logging
import uuid
import json
import asyncio
from decimal import Decimal
from typing import Optional, Dict, List, Any, Tuple, Set
from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text, select, update, delete
from sqlalchemy.dialects.postgresql import insert

from app.models.ebay import EbayListing
from app.models.product import Product, ProductCondition, ProductStatus
from app.models.platform_common import PlatformCommon, ListingStatus, SyncStatus
from app.models.sync_event import SyncEvent
from app.core.config import Settings
from app.core.exceptions import EbayAPIError
from app.services.ebay.trading import EbayTradingLegacyAPI

logger = logging.getLogger(__name__)

class EbayService:
    """
    Service for managing eBay listings and synchronization.
    Follows the differential sync pattern to detect and log changes.
    """
    
    # =========================================================================
    # 1. INITIALIZATION & HELPERS
    # =========================================================================
    def __init__(self, db: AsyncSession, settings: Settings = None):
        logger.debug("EbayService.__init__ - Initializing.")
        self.db = db
        self.settings = settings
        
        sandbox_mode = settings.EBAY_SANDBOX_MODE if settings else False
        logger.debug(f"EbayService.__init__ - Sandbox mode: {sandbox_mode}")
        
        self.trading_api = EbayTradingLegacyAPI(sandbox=sandbox_mode)
        self.expected_user_id = "londonvintagegts" 
        logger.debug(f"EbayService.__init__ - Expected User ID: {self.expected_user_id}")

        # --- NEW: Load the category map from the JSON file on startup ---
        self.category_map = self._load_category_map()

    async def _fetch_full_item_with_retry(self, item_id: str, attempts: int = 3) -> Optional[Dict[str, Any]]:
        """Fetch the full GetItem payload with simple retry/backoff."""
        delay_seconds = 1
        for attempt in range(1, attempts + 1):
            try:
                response = await self.trading_api.get_item(item_id)
                if response and response.get('Item'):
                    return response
                logger.warning(
                    "GetItem returned no Item payload for %s on attempt %s/%s",
                    item_id,
                    attempt,
                    attempts
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "GetItem failed for %s on attempt %s/%s: %s",
                    item_id,
                    attempt,
                    attempts,
                    exc
                )
            if attempt < attempts:
                await asyncio.sleep(delay_seconds)
                delay_seconds = min(delay_seconds * 2, 8)

        return None

    def _load_category_map(self, file_path: str = 'app/services/category_mappings/reverb_to_ebay_categories.json') -> Dict:
        """Loads the Reverb to eBay category mapping from a JSON file."""
        try:
            # Get the absolute path to the file relative to the project root
            # This makes the script runnable from any directory
            project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
            full_path = os.path.join(project_root, file_path)
            
            with open(full_path, 'r') as f:
                logger.info(f"Loading eBay category map from {full_path}")
                return json.load(f)
        except FileNotFoundError:
            logger.error(f"FATAL: Category mapping file not found at {full_path}")
            return {"default": {"CategoryID": "33034"}} # Fallback
        except json.JSONDecodeError:
            logger.error(f"FATAL: Error decoding JSON from {full_path}")
            return {"default": {"CategoryID": "33034"}} # Fallback

    def _get_ebay_category_from_reverb_uuid(self, reverb_uuid: str) -> Dict:
        """Looks up the eBay CategoryID from the loaded map."""
        if not reverb_uuid:
            return self.category_map.get('default')
            
        # The map is now stored in self.category_map, loaded during __init__
        return self.category_map.get(reverb_uuid, self.category_map.get('default'))
    
    def _map_category_string_to_ebay(self, category_str: str) -> Dict:
        """
        Maps product category string to eBay category.
        Handles cases where we don't have a Reverb UUID.
        """
        if not category_str:
            return self.category_map.get('default')
            
        category_lower = category_str.lower()
        
        # Map based on category patterns
        if 'bass' in category_lower:
            if 'acoustic' in category_lower:
                # Acoustic Bass Guitars
                return {'CategoryID': '4713', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Bass Guitars (4713)'}
            else:
                # All other bass guitars
                return {'CategoryID': '4713', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Bass Guitars (4713)'}
        elif 'electric' in category_lower and 'guitar' in category_lower:
            return {'CategoryID': '33034', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Electric Guitars (33034)'}
        elif 'acoustic' in category_lower and 'guitar' in category_lower:
            return {'CategoryID': '33021', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Acoustic Guitars (33021)'}
        elif 'amp' in category_lower or 'amplifier' in category_lower:
            return {'CategoryID': '38072', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Guitar Amplifiers (38072)'}
        elif 'effects' in category_lower or 'pedal' in category_lower:
            return {'CategoryID': '41407', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Effects Pedals (41407)'}
        else:
            # Default to electric guitars
            return self.category_map.get('default')

    def _get_ebay_condition_id(self, condition: ProductCondition, category_id: str = None) -> str:
        """
        Maps our internal ProductCondition enum to an eBay Condition ID.
        Musical Instruments categories only support: 1000, 1500, 2500, 3000, 7000
        """
        
        # Check if this is a musical instruments category
        musical_instrument_categories = [
            "33034",  # Electric Guitars
            "33021",  # Acoustic Guitars
            "4713",   # Bass Guitars
            "38072",  # Guitar Amplifiers
            "41407",  # Effects Pedals
            "119544", # Classical Guitars
            "181220", # Lap & Pedal Steel Guitars
            "159948", # Travel Guitars
            "181219", # Resonators
        ]
        
        is_musical_instrument = category_id in musical_instrument_categories if category_id else True
        
        if is_musical_instrument:
            # Musical instruments have limited condition options
            condition_map = {
                ProductCondition.NEW: "1000",           # New
                ProductCondition.EXCELLENT: "3000",     # Used - Best for excellent vintage items
                ProductCondition.VERYGOOD: "3000",      # Used
                ProductCondition.GOOD: "3000",          # Used  
                ProductCondition.FAIR: "3000",          # Used
                ProductCondition.POOR: "7000",          # For parts or not working
            }
        else:
            # Other categories may support more condition codes
            # This is for future expansion when we add non-musical categories
            condition_map = {
                ProductCondition.NEW: "1000",           # New
                ProductCondition.EXCELLENT: "2000",     # Manufacturer refurbished / Excellent
                ProductCondition.VERYGOOD: "3000",      # Used
                ProductCondition.GOOD: "4000",          # Good
                ProductCondition.FAIR: "5000",          # Acceptable
                ProductCondition.POOR: "7000",          # For parts or not working
            }
        
        # Default to 'Used' if the condition is not in the map
        return condition_map.get(condition, "3000")
    
    def _get_ebay_condition_display_name(self, condition_id: str) -> str:
        """
        Maps eBay condition IDs to their display names.
        """
        condition_display_map = {
            "1000": "New",
            "1500": "New other (see details)",
            "2500": "Refurbished",
            "3000": "Used",
            "7000": "For parts or not working"
        }
        
        return condition_display_map.get(condition_id, "Used")

    @staticmethod
    def _truncate_item_specific(value: str, limit: int) -> str:
        """Return value truncated to the last whole word within limit characters."""
        if not value:
            return value

        if len(value) <= limit:
            return value

        truncated = value[:limit].rstrip()
        last_space = truncated.rfind(" ")
        if last_space == -1:
            return truncated

        trimmed = truncated[:last_space].rstrip()
        return trimmed if trimmed else truncated
    
    def _build_item_specifics(self, product: Product, category_id: str) -> Dict[str, str]:
        """
        Build comprehensive ItemSpecifics based on product data and category.
        """
        # Base specifics that apply to all items
        model_value = product.model or "Unknown Model"
        model_value = self._truncate_item_specific(model_value, 65)

        item_specifics = {
            "Brand": product.brand or "Unbranded",
            "Model": model_value,
            "UPC": "Does not apply",
            "MPN": "Does not apply"
        }
        
        # Add year if available
        if product.year:
            item_specifics["Year"] = str(product.year)
        
        # Add condition display name
        condition_display = self._get_condition_display_name(product.condition)
        if condition_display:
            item_specifics["Condition"] = condition_display
        
        # Category-specific ItemSpecifics
        if category_id == "38072":  # Guitar Amplifiers
            # For amplifiers, use 'Amplifier Type'
            amp_type = self._extract_amplifier_type(product)
            item_specifics["Amplifier Type"] = amp_type
        elif category_id == "33034":  # Electric Guitars
            # For electric guitars, use 'Type'
            item_specifics["Type"] = "Electric Guitar"
            # Add body type if we can determine it
            if product.category and "solid" in product.category.lower():
                item_specifics["Body Type"] = "Solid"
            elif product.category and ("hollow" in product.category.lower() or "semi" in product.category.lower()):
                item_specifics["Body Type"] = "Hollow"
        elif category_id == "33021":  # Acoustic Guitars
            item_specifics["Type"] = "Acoustic Guitar"
        elif category_id == "4713":  # Bass Guitars
            item_specifics["Type"] = "Bass Guitar"
            # Check for number of strings
            if product.title:
                if "5 string" in product.title.lower() or "5-string" in product.title.lower():
                    item_specifics["String Configuration"] = "5 String"
                elif "6 string" in product.title.lower() or "6-string" in product.title.lower():
                    item_specifics["String Configuration"] = "6 String"
                else:
                    item_specifics["String Configuration"] = "4 String"  # Default
        elif category_id == "41407":  # Effects Pedals
            item_specifics["Type"] = "Effects Pedal"
        else:
            # For other categories, try to extract type from title/category
            guitar_type = self._extract_guitar_type(product)
            if guitar_type:
                item_specifics["Type"] = guitar_type
        
        return item_specifics
    
    def _get_condition_display_name(self, condition: ProductCondition) -> str:
        """Maps our ProductCondition enum to a display name."""
        if not condition:
            return "Used"
            
        condition_map = {
            ProductCondition.NEW: "New",
            ProductCondition.EXCELLENT: "Excellent",
            ProductCondition.VERYGOOD: "Very Good",
            ProductCondition.GOOD: "Good",
            ProductCondition.FAIR: "Fair",
            ProductCondition.POOR: "Poor"
        }
        
        return condition_map.get(condition, "Used")
    
    def _extract_amplifier_type(self, product: Product) -> str:
        """Extract amplifier type from product data."""
        title = (product.title or "").lower()
        category = (product.category or "").lower()
        
        # Check for combo
        if any(word in title for word in ["combo", "1x12", "2x12", "4x10", "1x15"]):
            return "Combo"
        
        # Check for head
        if any(word in title for word in ["head", "amp head", "amplifier head"]):
            return "Head"
        
        # Check for cabinet
        if any(word in title for word in ["cabinet", "cab ", "speaker cabinet"]):
            return "Cabinet"
        
        # Check category
        if "combo" in category:
            return "Combo"
        elif "head" in category:
            return "Head"
        elif "cabinet" in category:
            return "Cabinet"
        
        # Default to Combo for general amplifiers
        return "Combo"
    
    def _extract_guitar_type(self, product: Product) -> str:
        """Extract guitar type from product data."""
        title = (product.title or "").lower()
        category = (product.category or "").lower()
        brand = (product.brand or "").lower()
        
        # Check for effects/pedals first (more specific)
        if any(keyword in title for keyword in ["pedal", "effect", "flanger", "delay", "reverb", "distortion", "overdrive"]):
            return "Effects Pedal"
        elif any(keyword in category for keyword in ["effects", "pedal"]):
            return "Effects Pedal"
        
        # Check for bass
        if "bass" in title or "bass" in category:
            if "acoustic" in title or "acoustic" in category:
                return "Acoustic Bass Guitar"
            else:
                return "Bass Guitar"
        
        # Check for acoustic
        if "acoustic" in title or "acoustic" in category:
            return "Acoustic Guitar"
        
        # Check for electric
        if "electric" in title or "electric" in category:
            return "Electric Guitar"
        
        # Default based on common patterns
        if any(model in title for model in ["stratocaster", "telecaster", "les paul", "sg ", "335"]):
            return "Electric Guitar"
        
        return "Electric Guitar"  # Default for guitars

    async def verify_credentials(self) -> bool:
        logger.debug("EbayService.verify_credentials - Attempting to verify eBay credentials.")
        try:
            user_info = await self.trading_api.get_user_info()
            if not user_info or not user_info.get('success'):
                logger.error(f"EbayService.verify_credentials - Failed to get eBay user info. API Response: {user_info}")
                return False
            user_id = user_info.get('user_data', {}).get('UserID')
            if user_id != self.expected_user_id:
                logger.error(f"EbayService.verify_credentials - Unexpected eBay user: '{user_id}', expected: '{self.expected_user_id}'")
                return False
            logger.info(f"EbayService.verify_credentials - Successfully authenticated as eBay user: {user_id}")
            return True
        except Exception as e:
            logger.error(f"EbayService.verify_credentials - EXCEPTION during credential verification: {e}", exc_info=True)
            return False


    # =========================================================================
    # 2. MAIN SYNC ENTRY POINT (DETECTION PHASE)
    # =========================================================================
    async def run_import_process(self, sync_run_id: uuid.UUID, progress_callback=None) -> Dict[str, int]:
        """The main entry point for the eBay sync process, replacing the old sync_inventory_from_ebay."""
        logger.info(f"=== EbayService: STARTING EBAY SYNC (run_id: {sync_run_id}) ===")
        
        if not await self.verify_credentials():
            logger.error("EbayService - Credentials verification FAILED. Aborting sync.")
            return {"status": "error", "message": "Failed to verify eBay credentials"}

        logger.info("Fetching all eBay listings (active, sold, unsold).")
        all_listings_from_api = await self.trading_api.get_all_selling_listings(
            include_active=True, include_sold=True, include_unsold=True, include_details=True
        )       

        # ====== DEBUGGING =======
        # logger.info("API Response structure:")
        # for list_type in ['active', 'sold', 'unsold']:
        #     items = all_listings_from_api.get(list_type, [])
        #     if items:
        #         logger.info(f"{list_type}: {len(items)} items")
        #         # Log first item's structure
        #         logger.info(f"Sample {list_type} item keys: {list(items[0].keys()) if items else 'None'}")
        #         if 'SellingStatus' in items[0]:
        #             logger.info(f"  SellingStatus keys: {list(items[0]['SellingStatus'].keys())}")

        
        # Flatten the API response into a single list
        flat_api_list = []
        for list_type in ['active', 'sold', 'unsold']:
            items = all_listings_from_api.get(list_type, [])
            # Add the list_type to each item so we don't lose this context
            for item in items:
                item['_list_type'] = list_type
                flat_api_list.append(item)

        # Get the count for each list type for a more detailed log
        active_count = len(all_listings_from_api.get('active', []))
        sold_count = len(all_listings_from_api.get('sold', []))
        unsold_count = len(all_listings_from_api.get('unsold', []))
        total_count = len(flat_api_list)

        logger.info(
            f"Total items fetched from API: {total_count} "
            f"(Active: {active_count}, Sold: {sold_count}, Unsold: {unsold_count})"
        )

        # Run the differential sync logic
        sync_stats = await self.sync_ebay_inventory(flat_api_list, sync_run_id)
        
        logger.info(f"=== EbayService: FINISHED EBAY SYNC === Final Results: {sync_stats}")
        return sync_stats


    # =========================================================================
    # 3. DIFFERENTIAL SYNC LOGIC (Called by the main entry point)
    # =========================================================================
    async def sync_ebay_inventory(self, ebay_api_items: List[Dict], sync_run_id: uuid.UUID) -> Dict[str, Any]:
        """Compares eBay API data with the local DB and logs necessary changes."""
        stats = {"total_from_ebay": len(ebay_api_items), "events_logged": 0, "created": 0, "updated": 0, "removed": 0, "unchanged": 0, "errors": 0}
        
        try:
            # NEW: Fetch existing pending events first for duplicate checking
            pending_events = await self._fetch_pending_events()
            
            # Step 1: Fetch all existing eBay data from our DB
            existing_data = await self._fetch_existing_ebay_data()
            
            # Step 2: Prepare data for comparison
            api_items = self._prepare_api_data(ebay_api_items)
            db_items = self._prepare_db_data(existing_data)
            
            # --- ADD THIS DEBUG BLOCK ---
            logger.info("--- [DEBUG] DICTIONARY INSPECTION ---")
            logger.info(f"Total API items prepared: {len(api_items)}")
            logger.info(f"Total DB items prepared : {len(db_items)}")
            
            # Print a few keys from each to check for type mismatches (e.g., str vs int)
            if api_items:
                logger.info(f"Sample API keys: {list(api_items.keys())[:5]}")
            if db_items:
                logger.info(f"Sample DB keys : {list(db_items.keys())[:5]}")
            
            # Check for our specific test item in both dictionaries
            test_id = '257056048177'
            logger.info(f"Test item '{test_id}' in api_items: {test_id in api_items}")
            logger.info(f"Test item '{test_id}' in db_items : {test_id in db_items}")
            # --- END DEBUG BLOCK ---

            # Step 3: Calculate differences
            changes = self._calculate_changes(api_items, db_items)
            logger.info(f"Applying changes: {len(changes['create'])} new, {len(changes['update'])} updates, {len(changes['remove'])} removals")

            # Step 4: Apply changes and log events
            if changes['create']:
                stats['created'], events_created = await self._batch_create_products(changes['create'], sync_run_id, pending_events)
                stats['events_logged'] += events_created
            if changes['update']:
                stats['updated'], events_updated = await self._batch_update_products(changes['update'], sync_run_id, pending_events)
                stats['events_logged'] += events_updated
            if changes['remove']:
                stats['removed'], events_removed = await self._batch_mark_removed(changes['remove'], sync_run_id, pending_events)
                stats['events_logged'] += events_removed

            stats['unchanged'] = len(api_items) - stats['created'] - stats['updated']
            await self.db.commit()
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Sync failed during differential sync: {e}", exc_info=True)
            stats['errors'] += 1
        
        return stats

    def _calculate_changes_old(self, api_items: Dict, db_items: Dict) -> Dict[str, List]:
        """Calculates create, update, and remove operations based on business rules."""
        changes = {'create': [], 'update': [], 'remove': []}
        api_ids = set(api_items.keys())
        db_ids = set(db_items.keys())

        # Loop through items found on the API but not in our database.
        for eid in api_ids - db_ids:
            api_item = api_items[eid]
            # The '_list_type' was added when the API data was first processed.
            list_type = api_item.get('_list_type')

            # Only flag 'active' or 'sold' items as new. Ignore 'unsold'.
            if list_type in ['active', 'sold']:
                changes['create'].append(api_item)
            else:
                # If list_type is 'unsold' or unknown, we ignore it as per the new rules.
                pass

        # This logic remains the same.
        for eid in api_ids & db_ids:
            if self._has_changed(api_items[eid], db_items[eid]):
                changes['update'].append({'api_data': api_items[eid], 'db_data': db_items[eid]})
                
        for eid in db_ids - api_ids:
            changes['remove'].append(db_items[eid])
            
        return changes

    def _calculate_changes(self, api_items: Dict, db_items: Dict) -> Dict[str, List]:
        """Calculates create, update, and remove operations using a clear, set-based approach."""
        changes = {'create': [], 'update': [], 'remove': []}
        api_ids = set(api_items.keys())
        db_ids = set(db_items.keys())

        # Case 1: Items on the API that are not in our DB.
        # These are potential new listings.
        for eid in api_ids - db_ids:
            api_item = api_items[eid]
            # Only flag it as 'new' if it's active or was sold without us knowing.
            if api_item.get('status') == 'active':
                changes['create'].append(api_item)

        # Case 2: Items to check for updates
        for eid in api_ids & db_ids:
            # --- FINAL, TYPE-SAFE DEBUG BLOCK ---
            test_id = '257056048177'
            # Explicitly cast eid to a string for a reliable comparison
            if str(eid) == test_id:
                logger.info(f"--- [FINAL DEBUG] MATCH FOUND FOR TEST ITEM IN INTERSECTION LOOP ---")
                logger.info(f"    Item ID (eid): '{eid}' (type: {type(eid)})")
                logger.info(f"    DB Item being passed to _has_changed: {db_items[eid]}")
                logger.info(f"    Calling _has_changed...")
            # --- END FINAL DEBUG BLOCK ---
            
            if self._has_changed(api_items[eid], db_items[eid]):
                changes['update'].append({'api_data': api_items[eid], 'db_data': db_items[eid]})

        # Case 3: Items in our DB that are not on the API.
        # These are potential removals.
        for eid in db_ids - api_ids:
            db_item = db_items[eid]
            # ONLY flag for removal if our database thinks the listing is currently 'active'.
            if db_item.get('platform_common_status') == 'active':
                changes['remove'].append(db_item)
                
        return changes

    def _has_changed_old(self, api_item: Dict, db_item: Dict) -> bool:
        # """Compares a single item from the API and the DB."""
        # # Price check
        # db_price = float(db_item.get('ebay_price') or 0.0)  # Safely handle None by treating it as 0.0
        # if abs(api_item['price'] - db_price) > 0.01:
        #     return True
        # # Status check (direct, case-insensitive comparison)
        # if str(api_item.get('status', '')).lower() != str(db_item.get('ebay_listing_status', '')).lower():
        #     return True
        """Compares a single item from the API and the DB against platform_common."""
        # Status check against platform_common (the Manager)
        if str(api_item.get('status', '')).lower() != str(db_item.get('platform_common_status', '')).lower():
            return True
            
        # URL check
        if api_item.get('listing_url') and api_item['listing_url'] != db_item.get('listing_url'):
            return True

        # Price check can be added back here if needed, but status and URL are key for now.
        # For example, to compare against a price in ebay_listings, the _fetch query would need to be more complex.
        # Let's focus on fixing status and URL first.
        return False

    def _has_changed(self, api_item: Dict, db_item: Dict) -> bool:
        """Compares API data against the new, correct fields from our database query."""
        # Status check against platform_common (the Manager)
        if str(api_item.get('status', '')).lower() != str(db_item.get('platform_common_status', '')).lower():
            return True
            
        # URL check
        if api_item.get('listing_url') and api_item['listing_url'] != db_item.get('listing_url'):
            return True

        api_qty = api_item.get('quantity_available')
        db_qty = db_item.get('listing_quantity_available')
        if db_qty is None:
            db_qty = db_item.get('product_quantity')
        if api_qty is not None and db_qty is not None and api_qty != db_qty:
            return True

        
        # # --- FINAL DEBUG BLOCK ---
        # # This will print the SKU for every item being checked.
        # logger.info(f"[DEBUG-SKU-CHECK] Checking SKU: '{db_item.get('sku')}'")

        # test_sku = "REV-85380995"
        # if db_item.get('sku') == test_sku:
        #     logger.info("--- [FINAL DEBUG] MATCH FOUND FOR TEST SKU ---")
        #     logger.info(f"API ITEM: {api_item}")
        #     logger.info(f"DB ITEM : {db_item}")

        #     # Explicitly check the prices
        #     api_price_val = api_item.get('price')
        #     specialist_price_val = db_item.get('specialist_price')
        #     base_price_val = db_item.get('base_price')
            
        #     logger.info(f"API Price         : {api_price_val}")
        #     logger.info(f"Specialist Price  : {specialist_price_val}")
        #     logger.info(f"Base (Master) Price: {base_price_val}")
        # # --- END FINAL DEBUG BLOCK ---

        # Price check against the product's base_price
        db_price = float(db_item.get('specialist_price') or db_item.get('base_price') or 0.0)
        if abs(api_item['price'] - db_price) > 0.01:
            return True

        return False


    # =========================================================================
    # 4. BATCH PROCESSING / EVENT LOGGING (Called by differential sync)
    # =========================================================================
    async def _fetch_pending_events(self) -> set:
        """Fetches all pending sync events for eBay for quick lookups."""
        query = text("""
            SELECT external_id, change_type 
            FROM sync_events
            WHERE platform_name = 'ebay' AND status = 'pending'
        """)
        result = await self.db.execute(query)
        # Return a set of tuples for very fast checking, e.g., {('12345', 'status'), ('67890', 'price')}
        return {(row.external_id, row.change_type) for row in result.fetchall()}
    
    async def _batch_create_products(self, items: List[Dict], sync_run_id: uuid.UUID, pending_events: set) -> Tuple[int, int]:
        """Log rogue listings to sync_events only if no pending event already exists."""
        created_count, events_logged = 0, 0
        
        # Prepare only new, non-pending events
        events_to_log = []
        for item in items:
            try:
                external_id = item['external_id']
                
                # Check if a 'new_listing' event is already pending for this item
                if (external_id, 'new_listing') not in pending_events:
                    logger.warning(f"Rogue SKU Detected: eBay item {external_id} ('{item.get('title')}') not found in local DB. Logging to sync_events for later processing.")
                    
                    event_data = {
                        'sync_run_id': sync_run_id,
                        'platform_name': 'ebay',
                        'product_id': None,
                        'platform_common_id': None,
                        'external_id': external_id,
                        'change_type': 'new_listing',
                        'change_data': {
                            'title': item['title'],
                            'price': item['price'],
                            'status': item.get('status'),
                            'listing_url': item['_raw'].get('ListingDetails', {}).get('ViewItemURL'),
                            'raw_data': item['_raw']
                        },
                        'status': 'pending'
                    }
                    events_to_log.append(event_data)
                else:
                    logger.info(f"Skipping duplicate pending 'new_listing' event for eBay item {external_id}")

                # Increment count of items identified for creation, even if event logging is skipped
                created_count += 1
            except Exception as e:
                logger.error(f"Failed to prepare event for eBay item {item.get('external_id', 'Unknown')}: {e}", exc_info=True)
        
        # Bulk insert only the truly new events
        if events_to_log:
            try:
                stmt = insert(SyncEvent).values(events_to_log)
                stmt = stmt.on_conflict_do_nothing(
                    index_elements=['platform_name', 'external_id', 'change_type'],
                    index_where=(SyncEvent.status == 'pending')
                )
                result = await self.db.execute(stmt)
                events_logged = len(events_to_log)
                logger.info(f"Attempted to log {len(events_to_log)} new listing events (duplicates ignored)")
            except Exception as e:
                logger.error(f"Failed to bulk insert new listing events: {e}", exc_info=True)
        
        return created_count, events_logged 

    async def _batch_update_products(self, items: List[Dict], sync_run_id: uuid.UUID, pending_events: set) -> Tuple[int, int]:
        """SYNC PHASE: Only log changes to sync_events if no pending event already exists."""
        updated_count, events_logged = 0, 0
        events_to_log = []
        
        for item in items:
            try:
                api_data, db_data = item['api_data'], item['db_data']
                external_id = api_data['external_id']
                
                # Price change event check using the correct 'base_price' key
                db_price_for_compare = float(db_data.get('specialist_price') or db_data.get('base_price') or 0.0)
                if abs(api_data['price'] - db_price_for_compare) > 0.01:
                    if (external_id, 'price') not in pending_events:
                        events_to_log.append({
                            'sync_run_id': sync_run_id,
                            'platform_name': 'ebay',
                            'product_id': db_data['product_id'],
                            'platform_common_id': db_data['platform_common_id'],
                            'external_id': external_id,
                            'change_type': 'price',
                            # IMPORTANT: The 'old' price should always be the MASTER price,
                            # as the anomaly is the deviation from the canonical price.
                            'change_data': {'old': db_data.get('base_price'), 'new': api_data['price'], 'item_id': external_id},
                            'status': 'pending'
                        })

                # Quantity change detection (primarily for stocked items)
                api_quantity_available = api_data.get('quantity_available')
                db_quantity_available = db_data.get('listing_quantity_available')
                if db_quantity_available is None:
                    db_quantity_available = db_data.get('product_quantity')

                if api_quantity_available is not None and db_quantity_available is not None and api_quantity_available != db_quantity_available:
                    if (external_id, 'quantity_change') not in pending_events:
                        events_to_log.append({
                            'sync_run_id': sync_run_id,
                            'platform_name': 'ebay',
                            'product_id': db_data['product_id'],
                            'platform_common_id': db_data['platform_common_id'],
                            'external_id': external_id,
                            'change_type': 'quantity_change',
                            'change_data': {
                                'old_quantity': db_quantity_available,
                                'new_quantity': api_quantity_available,
                                'total_quantity': api_data.get('quantity_total'),
                                'quantity_sold': api_data.get('quantity_sold'),
                                'is_stocked_item': db_data.get('product_is_stocked'),
                                'item_id': external_id
                            },
                            'status': 'pending'
                        })

                # Status change event check using the correct 'platform_common_status' key
                if str(api_data.get('status', '')).lower() != str(db_data.get('platform_common_status', '')).lower():
                    if (external_id, 'status_change') not in pending_events:
                        is_sold_on_api = str(api_data.get('status', '')).lower() == 'sold'
                        events_to_log.append({
                            'sync_run_id': sync_run_id,
                            'platform_name': 'ebay',
                            'product_id': db_data['product_id'],
                            'platform_common_id': db_data['platform_common_id'],
                            'external_id': external_id,
                            'change_type': 'status_change',
                            'change_data': {'old': db_data.get('platform_common_status'), 'new': api_data.get('status'), 'item_id': external_id, 'is_sold': is_sold_on_api},
                            'status': 'pending'
                        })
                
                updated_count += 1
            except Exception as e:
                logger.error(f"Failed to prepare events for eBay item {item['api_data']['external_id']}: {e}", exc_info=True)
        
        # Bulk insert logic remains the same
        if events_to_log:
            try:
                stmt = insert(SyncEvent).values(events_to_log)
                # stmt = stmt.on_conflict_do_nothing(
                #     constraint='sync_events_platform_external_change_unique'
                # )
                stmt = stmt.on_conflict_do_nothing(
                    index_elements=['platform_name', 'external_id', 'change_type'],
                    index_where=(SyncEvent.status == 'pending')
                )
                result = await self.db.execute(stmt)
                events_logged = len(events_to_log)
                logger.info(f"Attempted to log {len(events_to_log)} new update events (duplicates ignored)")
            except Exception as e:
                logger.error(f"Failed to bulk insert update events: {e}", exc_info=True)
        
        return updated_count, events_logged

    async def _batch_mark_removed(self, items: List[Dict], sync_run_id: uuid.UUID, pending_events: set) -> Tuple[int, int]:
        """SYNC PHASE: Only log removal events if no pending event already exists."""
        removed_count, events_logged = 0, 0
        
        # Prepare only new, non-pending removal events
        events_to_log = []
        for item in items:
            try:
                external_id = item['external_id']

                # Check if a 'removed_listing' event is already pending for this item
                if (external_id, 'removed_listing') not in pending_events:
                    events_to_log.append({
                        'sync_run_id': sync_run_id,
                        'platform_name': 'ebay',
                        'product_id': item['product_id'],
                        'platform_common_id': item['platform_common_id'],
                        'external_id': external_id,
                        'change_type': 'removed_listing',
                        'change_data': {
                            'sku': item['sku'],
                            'item_id': external_id,
                            'reason': 'not_found_in_api'
                        },
                        'status': 'pending'
                    })
                else:
                    logger.info(f"Skipping duplicate pending 'removed_listing' event for eBay item {external_id}")

                # Increment count of items identified for removal, even if event logging is skipped
                removed_count += 1
            except Exception as e:
                logger.error(f"Failed to prepare removal event for eBay item {item.get('external_id', 'Unknown')}: {e}", exc_info=True)
        
        # Bulk insert only the truly new events
        if events_to_log:
            try:
                stmt = insert(SyncEvent).values(events_to_log)
                stmt = stmt.on_conflict_do_nothing(
                    index_elements=['platform_name', 'external_id', 'change_type'],
                    index_where=(SyncEvent.status == 'pending')
                )
                result = await self.db.execute(stmt)
                events_logged = len(events_to_log)
                logger.info(f"Attempted to log {len(events_to_log)} new removal events (duplicates ignored)")
            except Exception as e:
                logger.error(f"Failed to bulk insert removal events: {e}", exc_info=True)
        
        return removed_count, events_logged
    

    # =========================================================================
    # 5. OUTBOUND ACTIONS (ACTION PHASE)
    # =========================================================================
    def _map_reverb_shipping_to_ebay(self, reverb_api_data: Dict) -> Dict[str, Any]:
        """
        Maps Reverb shipping data to eBay ShippingDetails format.
        Falls back to hardcoded values if Reverb data is missing.
        """
        logger.info("Mapping Reverb shipping to eBay format")
        
        # Default/fallback shipping configuration - ARRAYS for eBay API
        # Using UK_DHL and UK_CollectInPersonInternational based on existing listings
        default_shipping = {
            "ShippingType": "Flat",
            "ShippingServiceOptions": [
                {
                    "ShippingServicePriority": "1",
                    "ShippingService": "UK_DHL",  # DHL service as used in existing listings
                    "ShippingServiceCost": "60.00"
                }
            ],
            "InternationalShippingServiceOption": [
                {
                    "ShippingServicePriority": "1",
                    "ShippingService": "UK_CollectInPersonInternational",  # International collect in person
                    "ShippingServiceCost": "200.00",
                    "ShipToLocation": "Worldwide"
                }
            ]
        }
        
        # Check if Reverb shipping data exists
        shipping_data = reverb_api_data.get('shipping')
        if not shipping_data:
            logger.warning("No shipping data in Reverb response, using defaults")
            return default_shipping
            
        # Extract rates array
        rates = shipping_data.get('rates', [])
        if not rates:
            logger.warning("No shipping rates in Reverb data, using defaults")
            return default_shipping
        
        # Build rate lookup by region
        region_rates = {}
        for rate_info in rates:
            region_code = rate_info.get('region_code')
            rate_amount = rate_info.get('rate', {}).get('amount')
            if region_code and rate_amount:
                region_rates[region_code] = rate_amount
                logger.info(f"Found Reverb shipping rate: {region_code} = {rate_amount}")
        
        # Map to eBay structure - ARRAYS for eBay API
        shipping_details = {
            "ShippingType": "Flat",
            "ShippingServiceOptions": [
                {
                    "ShippingServicePriority": "1",
                    "ShippingService": "UK_DHL",  # Using UK_DHL based on existing listings
                    "ShippingServiceCost": region_rates.get('GB', '60.00')  # Use GB rate or default
                }
            ]
        }
        
        # Handle international shipping
        # Priority: US rate, then EUR_EU, then XX (worldwide), then default
        intl_rate = (region_rates.get('US') or 
                    region_rates.get('EUR_EU') or 
                    region_rates.get('XX') or 
                    '200.00')
        
        shipping_details["InternationalShippingServiceOption"] = [
            {
                "ShippingServicePriority": "1",
                "ShippingService": "UK_RoyalMailInternationalTracked",  # Changed from UK_InternationalStandard
                "ShippingServiceCost": intl_rate,
                "ShipToLocation": "Worldwide"
            }
        ]
        
        logger.info(f"Mapped shipping - Domestic: £{shipping_details['ShippingServiceOptions'][0]['ShippingServiceCost']}, "
                   f"International: £{intl_rate}")
        
        return shipping_details
    
    async def create_listing_from_product(
        self, 
        product: Product, 
        reverb_api_data: Dict = None,
        sandbox: bool = None,
        use_shipping_profile: bool = False,
        shipping_profile_id: str = None,
        payment_profile_id: str = None,
        return_profile_id: str = None,
        shipping_details: Dict = None,
        price_override: Optional[Decimal] = None,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """
        Creates an eBay listing from a master Product object and rich Reverb API data.
        
        Args:
            product: The Product to list
            reverb_api_data: Optional Reverb API data for extracting images/shipping
            sandbox: Override sandbox mode (None = use settings)
            use_shipping_profile: If True, use business policies instead of inline shipping
            shipping_profile_id: The shipping profile ID to use (if use_shipping_profile=True)
            payment_profile_id: The payment profile ID to use (if use_shipping_profile=True)
            return_profile_id: The return profile ID to use (if use_shipping_profile=True)
            shipping_details: Custom shipping details to use (if use_shipping_profile=False)
            price_override: Optional Decimal price override for the listing
            dry_run: If True, validate but don't create the listing
        """
        logger.info(f"=== CREATING EBAY LISTING ===")
        logger.info(f"Product ID: {product.id}, SKU: {product.sku}")
        logger.info(f"Title: {product.title}")
        logger.info(f"Category: {product.category}")
        logger.info(f"Condition: {product.condition}")
        logger.info(f"Is Stocked Item: {product.is_stocked_item}, Quantity: {product.quantity}")
        logger.info(f"Sandbox: {sandbox if sandbox is not None else self.settings.EBAY_SANDBOX_MODE}")
        logger.info(f"Use shipping profile: {use_shipping_profile}")
        logger.info(f"Shipping Profile ID: {shipping_profile_id}")
        logger.info(f"Payment Profile ID: {payment_profile_id}")
        logger.info(f"Return Profile ID: {return_profile_id}")
        logger.info(f"Dry run: {dry_run}")

        try:
            # 1. Map to eBay Category
            # First check if we have enriched data with categories (from form submission)
            enriched_data = reverb_api_data if reverb_api_data else {}
            reverb_categories = enriched_data.get('categories', [])
            reverb_uuid = None
            
            if reverb_categories and isinstance(reverb_categories, list) and len(reverb_categories) > 0:
                reverb_uuid = reverb_categories[0].get('uuid')
                logger.info(f"  Reverb categories from enriched data: {reverb_categories}")
                logger.info(f"  Extracted Reverb UUID: {reverb_uuid}")
            
            # Map to eBay category
            logger.info(f"=== CATEGORY MAPPING ===")
            if reverb_uuid:
                # Use UUID mapping if available
                ebay_category_info = self._get_ebay_category_from_reverb_uuid(reverb_uuid)
                logger.info(f"  Using UUID mapping: {reverb_uuid} -> CategoryID: {ebay_category_info.get('CategoryID')}")
                logger.info(f"  Category Name: {ebay_category_info.get('full_name', 'N/A')}")
            else:
                # Fall back to category string mapping
                ebay_category_info = self._map_category_string_to_ebay(product.category)
                logger.info(f"  No UUID found, using category string mapping")
                logger.info(f"  Product category: '{product.category}'")
                logger.info(f"  Mapped to CategoryID: {ebay_category_info.get('CategoryID')}")
                logger.info(f"  Category Name: {ebay_category_info.get('full_name', 'N/A')}")
            
            # Store for use in _create_ebay_listing_entry
            self._last_category_info = ebay_category_info

            # 2. Map internal Product Condition to an eBay Condition ID (category-specific)
            logger.info(f"=== CONDITION MAPPING ===")
            logger.info(f"  Product condition: {product.condition}")
            ebay_condition_id = self._get_ebay_condition_id(product.condition, ebay_category_info['CategoryID'])
            logger.info(f"  Mapped to eBay ConditionID: {ebay_condition_id}")
            logger.info(f"  Condition display name: {self._get_ebay_condition_display_name(ebay_condition_id)}")
            
            # 3. Prepare Pictures with MAX_RES transformation
            pictures = []
            from app.core.utils import ImageTransformer, ImageQuality
            
            if product.primary_image:
                # Transform to MAX_RES like Shopify and VR
                max_res_url = ImageTransformer.transform_reverb_url(product.primary_image, ImageQuality.MAX_RES)
                if max_res_url:  # Only add non-None URLs
                    pictures.append(max_res_url)
                    logger.info(f"  Transformed primary image to MAX_RES")
            
            # Add additional images if they exist
            if product.additional_images and isinstance(product.additional_images, list):
                for img_url in product.additional_images:
                    max_res_url = ImageTransformer.transform_reverb_url(img_url, ImageQuality.MAX_RES)
                    if max_res_url:  # Only add non-None URLs
                        pictures.append(max_res_url)
                logger.info(f"  Transformed {len(product.additional_images)} additional images to MAX_RES")
            
            logger.info(f"  Total MAX_RES images available: {len(pictures)}")
            
            # eBay has a maximum of 24 pictures per listing
            if len(pictures) > 24:
                logger.warning(f"  ⚠️ Too many images ({len(pictures)}). eBay allows max 24. Truncating...")
                pictures = pictures[:24]
                logger.info(f"  Using first 24 images only")
            
            logger.info(f"  Final images to send to eBay: {len(pictures)}")

            # 4. Handle shipping based on mode
            logger.info("=== CONFIGURING SHIPPING ===")
            if use_shipping_profile:
                logger.info("  Using Business Policies mode")
                logger.info(f"  Shipping Profile ID: {shipping_profile_id}")
                logger.info(f"  Payment Profile ID: {payment_profile_id}")
                logger.info(f"  Return Profile ID: {return_profile_id}")
                # Use Business Policies (profiles)
                if not shipping_profile_id:
                    logger.error("  ERROR: Shipping profile ID required when use_shipping_profile=True")
                    return {"status": "error", "error": "Missing shipping_profile_id"}
            else:
                # Use inline shipping details
                if shipping_details:
                    # Use provided custom shipping details
                    shipping_data = shipping_details
                elif reverb_api_data:
                    # Extract from Reverb data
                    shipping_data = self._map_reverb_shipping_to_ebay(reverb_api_data)
                else:
                    # Use default shipping
                    shipping_data = self._map_reverb_shipping_to_ebay({})
            
            # 5. Determine quantity based on is_stocked_item
            quantity = str(product.quantity) if product.is_stocked_item and product.quantity > 1 else "1"
            logger.info(f"  Quantity: {quantity} (is_stocked_item: {product.is_stocked_item})")
            
            # 6. Build ItemSpecifics based on category
            logger.info(f"=== BUILDING ITEM SPECIFICS ===")
            item_specifics = self._build_item_specifics(product, ebay_category_info['CategoryID'])
            logger.info(f"  ItemSpecifics: {json.dumps(item_specifics, indent=2)}")
            
            # Determine price
            if price_override is not None:
                price_decimal = Decimal(str(price_override))
            else:
                price_decimal = Decimal(str(product.base_price or 0))
            price_str = f"{price_decimal.quantize(Decimal('0.01'))}"
            logger.info(f"  Listing price: £{price_str}")

            # 7. Build the complete item_data payload for the eBay API
            item_data = {
                "Title": (product.title or f"{product.year or ''} {product.brand} {product.model}".strip())[:80],  # eBay limit is 80 chars
                "Description": product.description or "No description available.",
                "CategoryID": ebay_category_info['CategoryID'],
                "Price": price_str,
                "CurrencyID": "GBP",
                "Quantity": quantity,
                "ListingDuration": "GTC",
                "ListingType": "FixedPriceItem",  # Add ListingType for _create_ebay_listing_entry
                "ConditionID": ebay_condition_id,
                "SKU": product.sku,  # Add SKU for tracking
                "ItemSpecifics": item_specifics,
                "PictureURLs": pictures,
                "DispatchTimeMax": "3",
                "Location": "London, UK",
                "Country": "GB",
                "PostalCode": "SW1A 1AA",  # Required for shipping
                "Site": "UK"
            }
            
            # Add shipping/payment/return based on mode
            if use_shipping_profile:
                logger.info("=== APPLYING BUSINESS POLICIES ===")
                # Use Business Policies
                item_data["SellerProfiles"] = {
                    "SellerShippingProfile": {
                        "ShippingProfileID": shipping_profile_id
                    }
                }
                logger.info(f"  Added Shipping Profile: {shipping_profile_id}")
                
                if payment_profile_id:
                    item_data["SellerProfiles"]["SellerPaymentProfile"] = {
                        "PaymentProfileID": payment_profile_id
                    }
                    logger.info(f"  Added Payment Profile: {payment_profile_id}")
                    
                if return_profile_id:
                    item_data["SellerProfiles"]["SellerReturnProfile"] = {
                        "ReturnProfileID": return_profile_id
                    }
                    logger.info(f"  Added Return Profile: {return_profile_id}")
                
                logger.info(f"  Final SellerProfiles: {json.dumps(item_data['SellerProfiles'], indent=2)}")
            else:
                # Use inline shipping details
                item_data["ShippingDetails"] = shipping_data
                logger.info(f"=== SHIPPING DETAILS BEING SENT TO EBAY ===")
                logger.info(f"Shipping data structure: {json.dumps(shipping_data, indent=2)}")
                logger.info(f"ShippingType: {shipping_data.get('ShippingType')}")
                logger.info(f"Domestic shipping service: {shipping_data.get('ShippingServiceOptions', [{}])[0].get('ShippingService')}")
                logger.info(f"Domestic shipping cost: {shipping_data.get('ShippingServiceOptions', [{}])[0].get('ShippingServiceCost')}")
                if 'InternationalShippingServiceOption' in shipping_data:
                    intl_option = shipping_data['InternationalShippingServiceOption'][0]
                    logger.info(f"International shipping service: {intl_option.get('ShippingService')}")
                    logger.info(f"International shipping cost: {intl_option.get('ShippingServiceCost')}")
                item_data["ReturnPolicy"] = {
                    "ReturnsAcceptedOption": "ReturnsAccepted",
                    "ReturnsWithinOption": "Days_30",
                    "ShippingCostPaidByOption": "Buyer"
                }
                item_data["PaymentMethods"] = "PayPal"
                item_data["PayPalEmailAddress"] = "payments@londonvintage.co.uk"
            
            # 7. Handle dry run
            if dry_run:
                logger.info("DRY RUN - Would create listing with:")
                logger.info(f"  Title: {item_data['Title']}")
                logger.info(f"  Category: {item_data['CategoryID']}")
                logger.info(f"  Price: {item_data['Price']} {item_data['CurrencyID']}")
                logger.info(f"  Quantity: {item_data['Quantity']}")
                if use_shipping_profile:
                    logger.info(f"  Shipping Profile: {shipping_profile_id}")
                else:
                    logger.info(f"  Shipping: Inline details")
                return {"status": "dry_run", "item_data": item_data}
            
            # 8. Create a new trading API instance if sandbox override is specified
            if sandbox is not None and sandbox != (self.settings.EBAY_SANDBOX_MODE if self.settings else False):
                # Need to create a temporary trading API with different sandbox setting
                from app.services.ebay.trading import EbayTradingLegacyAPI
                temp_trading_api = EbayTradingLegacyAPI(sandbox=sandbox)
                api_to_use = temp_trading_api
                logger.info(f"Using temporary trading API with sandbox={sandbox}")
            else:
                api_to_use = self.trading_api
            
            # 9. Call the API to create the listing
            result = await api_to_use.add_fixed_price_item(item_data)
            
            if result.get("success"):
                new_ebay_id = result.get("item_id")
                logger.info(f"Successfully created eBay listing with Item ID: {new_ebay_id}")
                
                # 10. Fetch the full listing details from eBay to store comprehensive data
                full_listing_data = None
                try:
                    logger.info(f"Fetching full listing details for eBay item {new_ebay_id}")
                    get_item_response = await api_to_use.get_item(new_ebay_id)
                    if get_item_response and get_item_response.get("Item"):
                        full_listing_data = get_item_response
                        logger.info("Successfully fetched full listing details from eBay")
                    else:
                        logger.warning("Could not fetch full listing details, using creation data")
                except Exception as e:
                    logger.warning(f"Error fetching full listing details: {e}")
                
                # 11. Create ebay_listings entry with full data
                await self._create_ebay_listing_entry(
                    product=product,
                    ebay_item_id=new_ebay_id,
                    listing_data=item_data,
                    full_api_response=full_listing_data,
                    sandbox=sandbox if sandbox is not None else self.settings.EBAY_SANDBOX_MODE
                )
                
                return {
                    "status": "success", 
                    "external_id": new_ebay_id,
                    "ItemID": new_ebay_id,  # For compatibility with existing code
                    "sandbox": sandbox if sandbox is not None else self.settings.EBAY_SANDBOX_MODE
                }
            else:
                error_message = "; ".join(result.get("errors", ["Unknown API error."]))
                logger.error(f"Failed to create eBay listing for SKU {product.sku}: {error_message}")
                logger.error(f"Full API response: {json.dumps(result, indent=2)}")
                return {"status": "error", "message": error_message}
                
        except Exception as e:
            logger.error(f"Exception while creating eBay listing for SKU {product.sku}: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}

    async def mark_item_as_sold(self, external_id: str) -> bool:
        """Outbound action to end a listing on eBay because it sold elsewhere."""
        logger.info(f"Received request to end eBay listing {external_id} (sold elsewhere).")
        try:
            # 'Sold' is the most accurate reason code for an item that sold on another platform.
            response = await self.trading_api.end_listing(external_id, reason_code='NotAvailable')
            
            if response and "EndItemResponse" in response:
                ack = response["EndItemResponse"].get("Ack", "")
                if ack in ["Success", "Warning"]:
                    logger.info(f"Successfully sent 'end' request for eBay listing {external_id}.")

                    # Update local listing metadata so we stay in sync without
                    # waiting for the next detection pass.
                    stmt = select(EbayListing).where(EbayListing.ebay_item_id == external_id)
                    listing_result = await self.db.execute(stmt)
                    listing = listing_result.scalar_one_or_none()
                    if listing:
                        listing.listing_status = 'ended'
                        listing.quantity_available = 0
                        listing.quantity = listing.quantity or 0
                        listing.updated_at = datetime.utcnow()
                        self.db.add(listing)

                    return True
            
            logger.error(f"API call to end eBay listing {external_id} failed. Response: {response}")
            return False
        except Exception as e:
            logger.error(f"Exception while ending eBay listing {external_id}: {e}", exc_info=True)
            return False
    
    async def _create_ebay_listing_entry(
        self,
        product: Product,
        ebay_item_id: str,
        listing_data: Dict[str, Any],
        full_api_response: Optional[Dict[str, Any]] = None,
        sandbox: bool = False
    ) -> None:
        """Create platform_common and ebay_listings entries for a new eBay listing."""
        try:
            # First, create platform_common entry
            platform_common = PlatformCommon(
                product_id=product.id,
                platform_name='ebay',
                external_id=ebay_item_id,
                status=ListingStatus.ACTIVE,  # Changed from listing_status
                sync_status=SyncStatus.SYNCED,
                last_sync=datetime.now(timezone.utc).replace(tzinfo=None),  # Changed from last_sync_date and removed timezone
                listing_url=f"https://www.ebay.co.uk/itm/{ebay_item_id}",
                platform_specific_data={
                    'created_via': 'api',
                    'created_at': datetime.now(timezone.utc).isoformat(),
                    'sandbox': sandbox
                }
            )
            self.db.add(platform_common)
            await self.db.flush()  # Get the ID
            
            if not full_api_response:
                full_api_response = await self._fetch_full_item_with_retry(ebay_item_id)

            seed_listing_data = listing_data or {}
            api_item_payload = None
            if full_api_response and isinstance(full_api_response.get('Item'), dict):
                api_item_payload = full_api_response['Item']
            listing_source = api_item_payload or seed_listing_data

            # Extract seller profiles if present
            seller_profiles = listing_source.get('SellerProfiles') or seed_listing_data.get('SellerProfiles', {})
            shipping_profile_id = seller_profiles.get('SellerShippingProfile', {}).get('ShippingProfileID')
            payment_profile_id = seller_profiles.get('SellerPaymentProfile', {}).get('PaymentProfileID')
            return_profile_id = seller_profiles.get('SellerReturnProfile', {}).get('ReturnProfileID')

            # Extract pictures for ebay_listings table
            pictures_source = (
                listing_source.get('PictureURLs')
                or listing_source.get('PictureURL')
                or seed_listing_data.get('PictureURLs')
                or seed_listing_data.get('PictureURL')
                or []
            )
            picture_urls = pictures_source if isinstance(pictures_source, list) else [pictures_source] if pictures_source else []
            gallery_url = picture_urls[0] if picture_urls else None

            # Get category name from ebay_category_info if available
            ebay_category_name = None
            if hasattr(self, '_last_category_info') and self._last_category_info:
                # Extract the actual category name from the full_name field
                full_name = self._last_category_info.get('full_name', '')
                if full_name:
                    # Format: "Musical Instruments & Gear (619) / Guitars & Basses (3858) / Electric Guitars (33034)"
                    # We want: "Musical Instruments & DJ Equipment:Guitars & Basses:Electric Guitars"
                    parts = full_name.split(' / ')
                    category_parts = []
                    for part in parts:
                        # Remove the ID in parentheses
                        name_part = part.split(' (')[0].strip()
                        if name_part == 'Musical Instruments & Gear':
                            name_part = 'Musical Instruments & DJ Equipment'
                        category_parts.append(name_part)
                    ebay_category_name = ':'.join(category_parts)

            raw_price = (
                listing_source.get('Price')
                or listing_source.get('StartPrice')
                or (listing_source.get('SellingStatus') or {}).get('CurrentPrice')
                or seed_listing_data.get('Price')
            )
            if isinstance(raw_price, dict):
                raw_price = raw_price.get('#text') or raw_price.get('_value')
            try:
                price_value = float(raw_price) if raw_price is not None else 0.0
            except (TypeError, ValueError):
                price_value = 0.0

            def _to_int(value: Any) -> Optional[int]:
                try:
                    return int(value)
                except (TypeError, ValueError):
                    return None

            quantity_total_int = _to_int(listing_source.get('Quantity'))
            quantity_available_int = _to_int(listing_source.get('QuantityAvailable'))
            quantity_sold_int = _to_int((listing_source.get('SellingStatus') or {}).get('QuantitySold'))

            if quantity_total_int is None:
                quantity_total_int = _to_int(seed_listing_data.get('Quantity'))

            if quantity_available_int is None and quantity_total_int is not None and quantity_sold_int is not None:
                quantity_available_int = max(quantity_total_int - quantity_sold_int, 0)

            if quantity_total_int is None:
                quantity_total_int = quantity_available_int or 1
            if quantity_available_int is None:
                quantity_available_int = quantity_total_int

            listing_type_value = listing_source.get('ListingType', seed_listing_data.get('ListingType', 'FixedPriceItem'))
            listing_duration_value = listing_source.get('ListingDuration', seed_listing_data.get('ListingDuration', 'GTC'))
            condition_id_value = listing_source.get('ConditionID', seed_listing_data.get('ConditionID', ''))
            condition_display_name = listing_source.get('ConditionDisplayName', seed_listing_data.get('ConditionDisplayName'))
            category_id_value = listing_source.get('CategoryID')
            if not category_id_value:
                primary_category = listing_source.get('PrimaryCategory') or seed_listing_data.get('PrimaryCategory', {})
                category_id_value = primary_category.get('CategoryID', '')

            listing_url_value = (
                (listing_source.get('ListingDetails') or {}).get('ViewItemURL')
                or seed_listing_data.get('ListingURL')
                or f"https://www.ebay.co.uk/itm/{ebay_item_id}"
            )

            # Then create ebay_listings entry
            ebay_listing = EbayListing(
                platform_id=platform_common.id,
                ebay_item_id=ebay_item_id,  # Changed from ebay_listing_id
                title=(listing_source.get('Title') or seed_listing_data.get('Title', ''))[:255],
                price=price_value,
                quantity=quantity_total_int,
                quantity_available=quantity_available_int,
                ebay_category_id=category_id_value,
                ebay_category_name=ebay_category_name,  # Add the category name
                ebay_condition_id=condition_id_value,
                condition_display_name=condition_display_name or (self._get_ebay_condition_display_name(condition_id_value) if condition_id_value else None),
                format='FIXEDPRICEITEM' if listing_type_value == 'FixedPriceItem' else 'AUCTION',
                listing_status='active',
                listing_url=listing_url_value,
                shipping_policy_id=shipping_profile_id,
                payment_policy_id=payment_profile_id,
                return_policy_id=return_profile_id,
                gallery_url=gallery_url,
                picture_urls=picture_urls,
                start_time=datetime.now(timezone.utc).replace(tzinfo=None),
                end_time=(datetime.now(timezone.utc) + timedelta(days=30)).replace(tzinfo=None) if listing_duration_value == 'GTC' else None,
                # Store additional data in appropriate JSONB fields
                item_specifics=listing_source.get('ItemSpecifics', seed_listing_data.get('ItemSpecifics', {})),
                listing_data=full_api_response if full_api_response else {
                    'Raw': {
                        'Item': seed_listing_data,
                        'Description': seed_listing_data.get('Description')
                    }
                }
            )
            self.db.add(ebay_listing)
            
            # Commit the transaction
            await self.db.commit()
            logger.info(f"Created eBay listing entries for product {product.sku} with eBay ID {ebay_item_id}")
            
        except Exception as e:
            logger.error(f"Failed to create eBay listing entries: {e}", exc_info=True)
            await self.db.rollback()
            raise

    async def update_listing_price(self, external_id: str, new_price: float) -> bool:
        """Outbound action to update the price of a listing on eBay."""
        logger.info(f"Received request to update eBay listing {external_id} to price £{new_price:.2f}.")
        try:
            response = await self.trading_api.revise_listing_price(external_id, new_price)
            
            if response and response.get("Ack") in ["Success", "Warning"]:
                logger.info(f"Successfully sent price update for eBay listing {external_id}.")
                return True
            
            logger.error(f"API call to update price for eBay listing {external_id} failed. Response: {response}")
            return False
        except Exception as e:
            logger.error(f"Exception while updating price for eBay listing {external_id}: {e}", exc_info=True)
            return False

    async def update_listing_quantity(
        self,
        external_id: str,
        new_quantity: int,
        *,
        platform_common_id: Optional[int] = None,
        sku: Optional[str] = None,
    ) -> bool:
        """Outbound action to update the available quantity for an eBay listing."""
        logger.info(
            "Received request to update eBay listing %s to quantity %s.",
            external_id,
            new_quantity,
        )

        safe_quantity = max(int(new_quantity or 0), 0)

        try:
            response = await self.trading_api.revise_listing_quantity(external_id, safe_quantity, sku)
            ack = (response or {}).get('ack')
            method_used = (response or {}).get('method')
            payload = (response or {}).get('payload') or {}

            if ack not in ("Success", "Warning"):
                logger.error(
                    "API call to update quantity for eBay listing %s via %s failed. Payload: %s",
                    external_id,
                    method_used or "unknown method",
                    payload,
                )
                return False

            logger.info(
                "Successfully sent quantity update for eBay listing %s using %s.",
                external_id,
                method_used,
            )

            timestamp = datetime.now(timezone.utc).replace(tzinfo=None)

            db_platform_id = platform_common_id
            if not db_platform_id:
                result = await self.db.execute(
                    select(PlatformCommon.id)
                    .where(
                        PlatformCommon.external_id == external_id,
                        PlatformCommon.platform_name == 'ebay',
                    )
                    .limit(1)
                )
                db_platform_id = result.scalar_one_or_none()

            if db_platform_id:
                await self.db.execute(
                    update(EbayListing)
                    .where(EbayListing.platform_id == db_platform_id)
                    .values(
                        quantity=safe_quantity,
                        quantity_available=safe_quantity,
                        updated_at=timestamp,
                    )
                )

                await self.db.execute(
                    update(PlatformCommon)
                    .where(PlatformCommon.id == db_platform_id)
                    .values(
                        last_sync=timestamp,
                        sync_status=SyncStatus.SYNCED,
                        updated_at=timestamp,
                    )
                )

            await self.db.commit()
            return True

        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Exception while updating quantity for eBay listing %s: %s",
                external_id,
                exc,
                exc_info=True,
            )
            await self.db.rollback()
            return False

    async def apply_product_update(
        self,
        product: Product,
        platform_link: PlatformCommon,
        changed_fields: Set[str],
    ) -> Dict[str, Any]:
        if not platform_link.external_id:
            return {"status": "skipped", "reason": "missing_external_id"}

        listing_stmt = select(EbayListing).where(EbayListing.platform_id == platform_link.id)
        listing_result = await self.db.execute(listing_stmt)
        listing = listing_result.scalar_one_or_none()

        results: Dict[str, Any] = {"status": "no_changes"}

        if "quantity" in changed_fields and product.is_stocked_item:
            await self.update_listing_quantity(
                platform_link.external_id,
                product.quantity or 0,
                platform_common_id=platform_link.id,
                sku=product.sku,
            )
            results["quantity"] = "updated"

        title = product.title if "title" in changed_fields else None
        description = product.description if "description" in changed_fields else None
        item_specifics = None
        if "model" in changed_fields and product.model:
            item_specifics = {"Model": product.model}

        if title or description or item_specifics:
            response = await self.trading_api.revise_listing_details(
                platform_link.external_id,
                title=title,
                description=description,
                item_specifics=item_specifics,
            )
            if listing:
                if title:
                    listing.title = title
                listing.updated_at = datetime.utcnow()
                self.db.add(listing)
            results["details"] = response
            results["status"] = "updated"

        return results


    # =========================================================================
    # 6. DATA PREPARATION & FETCHING HELPERS
    # =========================================================================
    async def _fetch_existing_ebay_data(self) -> List[Dict]:
        """Fetches all eBay-related data from the local database."""
        query = text("""
            SELECT 
                p.id                    AS product_id,
                p.sku,
                p.base_price,                        -- Canonical price
                p.quantity              AS product_quantity,
                p.is_stocked_item       AS product_is_stocked,
                pc.id                   AS platform_common_id,
                pc.external_id,
                pc.status               AS platform_common_status,
                pc.listing_url,
                el.price                AS specialist_price,
                el.quantity             AS listing_quantity,
                el.quantity_available   AS listing_quantity_available
            FROM platform_common pc
            LEFT JOIN products p      ON p.id = pc.product_id
            LEFT JOIN ebay_listings el ON pc.id = el.platform_id
            WHERE pc.platform_name = 'ebay'
        """)
        result = await self.db.execute(query)
        return [row._asdict() for row in result.fetchall()]

    def _prepare_api_data(self, ebay_api_items: List[Dict]) -> Dict[str, Dict]:
        """Prepares eBay API data and translates statuses to our universal vocabulary."""
        prepared_items = {}
        for item in ebay_api_items:
            item_id = item.get('ItemID')
            if not item_id:
                continue

            selling_status = item.get('SellingStatus', {})
            price_data = selling_status.get('CurrentPrice', {})

            quantity_total = item.get('Quantity')
            quantity_available = item.get('QuantityAvailable')
            quantity_sold = selling_status.get('QuantitySold')

            try:
                quantity_total_int = int(quantity_total) if quantity_total is not None else None
            except (TypeError, ValueError):
                quantity_total_int = None

            try:
                quantity_available_int = int(quantity_available) if quantity_available is not None else None
            except (TypeError, ValueError):
                quantity_available_int = None

            try:
                quantity_sold_int = int(quantity_sold) if quantity_sold is not None else None
            except (TypeError, ValueError):
                quantity_sold_int = None

            if quantity_available_int is None and quantity_total_int is not None and quantity_sold_int is not None:
                quantity_available_int = max(quantity_total_int - quantity_sold_int, 0)

            list_type = item.get('_list_type', 'unknown')
            
            # Map eBay's list type to our universal platform_common statuses
            status_mapping = {
                'active': 'active',
                'sold': 'sold',
                'unsold': 'ended'
            }
            listing_status = status_mapping.get(list_type, 'unknown')
            
            prepared_items[str(item_id)] = {
                'external_id': str(item_id),
                'status': listing_status,
                'price': float(price_data.get('#text', 0)),
                'title': item.get('Title'),
                'listing_url': item.get('ListingDetails', {}).get('ViewItemURL'),
                'quantity_total': quantity_total_int,
                'quantity_available': quantity_available_int,
                'quantity_sold': quantity_sold_int,
                '_raw': item
            }
        return prepared_items

    def _prepare_db_data(self, existing_data: List[Dict]) -> Dict[str, Dict]:
        """Prepares local DB data into a lookup dictionary."""
        return {str(row['external_id']): row for row in existing_data if row.get('external_id')}

    def _extract_ebay_listing_data(self, listing: Dict[str, Any], listing_type: str) -> Dict[str, Any]:
        # This method is preserved from your original code.
        extracted = {}
        primary_category = listing.get('PrimaryCategory', {})
        extracted['ebay_category_id'] = primary_category.get('CategoryID')
        extracted['ebay_category_name'] = primary_category.get('CategoryName')
        secondary_category = listing.get('SecondaryCategory', {})
        extracted['ebay_second_category_id'] = secondary_category.get('CategoryID')
        extracted['ebay_condition_id'] = listing.get('ConditionID')
        extracted['condition_display_name'] = listing.get('ConditionDisplayName')
        listing_type_api = listing.get('ListingType', '')
        if listing_type_api == 'Chinese': extracted['format'] = 'AUCTION'
        elif listing_type_api in ['FixedPriceItem', 'StoreInventory']: extracted['format'] = 'BUY_IT_NOW'
        else: extracted['format'] = listing_type_api.upper()
        listing_details = listing.get('ListingDetails', {})
        if listing_details:
            extracted['start_time'] = self._parse_ebay_datetime(listing_details.get('StartTime'))
            extracted['end_time'] = self._parse_ebay_datetime(listing_details.get('EndTime'))
            extracted['listing_url'] = listing_details.get('ViewItemURL')
        picture_details = listing.get('PictureDetails', {})
        if picture_details:
            extracted['gallery_url'] = picture_details.get('GalleryURL')
            picture_urls = picture_details.get('PictureURL', [])
            if not isinstance(picture_urls, list):
                picture_urls = [picture_urls] if picture_urls else []
            extracted['picture_urls'] = json.dumps(picture_urls)
        item_specifics = self._extract_item_specifics(listing)
        if item_specifics: extracted['item_specifics'] = json.dumps(item_specifics)
        seller_profiles = listing.get('SellerProfiles', {})
        if seller_profiles:
            payment_profile = seller_profiles.get('SellerPaymentProfile', {})
            if payment_profile: extracted['payment_policy_id'] = payment_profile.get('PaymentProfileID')
            return_profile = seller_profiles.get('SellerReturnProfile', {})
            if return_profile: extracted['return_policy_id'] = return_profile.get('ReturnProfileID')
            shipping_profile = seller_profiles.get('SellerShippingProfile', {})
            if shipping_profile: extracted['shipping_policy_id'] = shipping_profile.get('ShippingProfileID')
        # if listing_type.lower() == 'sold' or str(listing.get('SellingStatus', {}).get('ListingStatus')).lower() == 'endedwithsales':
        # if str(listing_type).lower() == 'sold' or str(listing.get('SellingStatus', {}).get('ListingStatus')).lower() == 'endedwithsales':
        if str(listing_type).lower() == 'sold':
            transactions = listing.get('TransactionArray', {}).get('Transaction', [])
            if not isinstance(transactions, list):
                transactions = [transactions] if transactions else []
            if transactions:
                transaction = transactions[0] 
                extracted['transaction_id'] = transaction.get('TransactionID')
                extracted['order_line_item_id'] = transaction.get('OrderLineItemID')
                buyer = transaction.get('Buyer', {})
                if buyer: extracted['buyer_user_id'] = buyer.get('UserID')
                extracted['paid_time'] = self._parse_ebay_datetime(transaction.get('PaidTime'))
                status_info = transaction.get('Status', {})
                if transaction.get('PaidTime'):
                    extracted['payment_status'] = "Paid"
                    if transaction.get('ShippedTime'):
                        extracted['shipping_status'] = "SHIPPED"
                    else:
                        extracted['shipping_status'] = "READY_TO_SHIP"
                else:
                    extracted['payment_status'] = status_info.get('eBayPaymentStatus', "NotPaid")
                    extracted['shipping_status'] = "PENDING_PAYMENT"
            elif listing.get('SellingStatus', {}).get('OrderStatus') == 'Completed':
                 selling_status = listing.get('SellingStatus', {})
                 if selling_status.get('PaidStatus') == 'Paid':
                    extracted['payment_status'] = "Paid"
                    extracted['shipping_status'] = "READY_TO_SHIP"
        return extracted
    
    def _parse_ebay_datetime(self, dt_str: Optional[str]) -> Optional[datetime]:
        if not dt_str: return None
        try:
            dt = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
            return dt.replace(tzinfo=None)
        except (ValueError, TypeError):
            try:
                dt = datetime.strptime(dt_str, "%Y-%m-%dT%H:%M:%S.%fZ")
                return dt.replace(tzinfo=None)
            except (ValueError, TypeError):
                logger.warning(f"Could not parse eBay datetime: {dt_str}")
                return None
    
    def _extract_item_specifics(self, listing: Dict[str, Any]) -> Dict[str, Any]:
        result = {}
        try:
            item_specifics_node = listing.get("ItemSpecifics", {})
            if not item_specifics_node: return result
            name_value_list = item_specifics_node.get("NameValueList")
            if not name_value_list: return result
            if isinstance(name_value_list, list):
                for item in name_value_list:
                    if not isinstance(item, dict): continue
                    name, value = item.get("Name"), item.get("Value")
                    if name and value: result[name] = value if not isinstance(value, list) else value[0]
            elif isinstance(name_value_list, dict):
                name, value = name_value_list.get("Name"), name_value_list.get("Value")
                if name and value: result[name] = value if not isinstance(value, list) else value[0]
        except Exception as e:
            logger.exception(f"Error extracting item specifics from listing ItemID {listing.get('ItemID', 'N/A')}: {str(e)}")
        return result
    
    def _convert_item_specifics_to_api_format(self, item_specifics: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Convert item specifics from simple dict to eBay API NameValueList format."""
        name_value_list = []
        for name, value in item_specifics.items():
            name_value_list.append({
                "Name": name,
                "Value": value if not isinstance(value, list) else value
            })
        return name_value_list
