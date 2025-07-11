
# app/services/vintageandrare_service.py
import asyncio
import logging
import uuid
import pandas as pd
import json
from datetime import datetime, timezone
from typing import Optional, Dict, List, Set, Tuple, Generator, Any
from pathlib import Path
from sqlalchemy import text, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import SyncStatus, ListingStatus, ProductStatus, ProductCondition
from app.core.config import get_settings
from app.services.vintageandrare.client import VintageAndRareClient
from app.models.product import Product, ProductStatus, ProductCondition
from app.models.platform_common import PlatformCommon, ListingStatus
from app.models.vr import VRListing
from app.models.sync_event import SyncEvent

logger = logging.getLogger(__name__)

class VintageAndRareService:
    """
    Service for handling the full Vintage & Rare inventory import and differential sync process.
    """
    def __init__(self, db: AsyncSession):
        self.db = db

    def _sanitize_for_json(self, obj):
        """Recursively check through a dictionary and replace NaN values with None."""
        if isinstance(obj, dict):
            return {k: self._sanitize_for_json(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._sanitize_for_json(i) for i in obj]
        elif pd.isna(obj):
            return None
        else:
            return obj

    async def run_import_process(self, username: str, password: str, sync_run_id: uuid.UUID, save_only: bool = False):
        """Run the V&R inventory import process."""
        try:
            logger.info("Starting VintageAndRareService.run_import_process")
            
            # Initialize client
            client = VintageAndRareClient(username, password, db_session=self.db)
            
            # Authenticate
            logger.info("Attempting authentication with V&R...")
            if not await client.authenticate():
                logger.error("V&R authentication failed")
                return {"status": "error", "message": "V&R authentication failed"}
            
            # Download inventory
            logger.info("Authentication successful. Downloading inventory...")
            inventory_df = await client.download_inventory_dataframe(save_to_file=True)
            
            if inventory_df is None or inventory_df.empty:
                logger.error("V&R inventory download failed or returned empty.")
                return {"status": "error", "message": "No V&R inventory data received."}
            
            logger.info(f"Successfully downloaded inventory with {len(inventory_df)} items")
            
            if save_only:
                return {
                    "status": "success", 
                    "message": f"V&R inventory saved with {len(inventory_df)} records",
                    "count": len(inventory_df)
                }
            
            # Process inventory updates
            logger.info("Processing inventory updates using differential sync...")
            sync_stats = await self.sync_vr_inventory(inventory_df, sync_run_id)

            logger.info(f"Inventory sync process complete: {sync_stats}")
            return {
                "status": "success",
                "message": "V&R inventory synced successfully.",
                **sync_stats
            }
        
        except Exception as e:
            import traceback
            logger.error(f"Exception in VintageAndRareService.run_import_process: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}

    # --- Outbound Action Method (The Missing Piece) ---

    async def mark_item_as_sold(self, external_id: str) -> bool:
        """
        Marks an item as sold on the V&R platform via an AJAX call.
        This is called by the central orchestrator when a sale is detected on another platform.
        """
        logger.info(f"Received request to mark V&R item {external_id} as sold.")
        settings = get_settings()
        username = settings.VINTAGE_AND_RARE_USERNAME
        password = settings.VINTAGE_AND_RARE_PASSWORD

        if not all([username, password]):
            logger.error("V&R credentials not configured for outbound action.")
            return False

        try:
            # We use the standalone client for this outbound action.
            client = VintageAndRareClient(username, password, db_session=self.db)
            if not await client.authenticate():
                logger.error(f"Authentication failed for marking item {external_id} as sold.")
                return False
            
            # The logic is adapted from scripts/vr/manage_vr_items.py
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, client.mark_item_as_sold, external_id)
            return result.get("success", False)
        except Exception as e:
            logger.error(f"Exception while marking V&R item {external_id} as sold: {e}", exc_info=True)
            return False

    # --- Differential Sync Methods ---
    
    async def sync_vr_inventory(self, df: pd.DataFrame, sync_run_id: uuid.UUID) -> Dict[str, int]:
        """
        Main sync method - compares API data with DB and applies only necessary changes.
        """
        stats = {
            "total_from_vr": len(df),
            "events_logged": 0,
            "created": 0,
            "updated": 0,
            "removed": 0,
            "unchanged": 0,
            "errors": 0
        }
        
        try:
            # Step 1: Fetch all existing V&R data from DB
            logger.info("Fetching existing V&R inventory from database...")
            existing_data = await self._fetch_existing_vr_data()
            
            # Step 2: Convert data to lookup dictionaries for O(1) access
            api_items = self._prepare_api_data(df)
            db_items = self._prepare_db_data(existing_data)
            
            # Step 3: Calculate differences
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
            
            logger.info(f"Sync complete: {stats}")
            
        except Exception as e:
            logger.error(f"Sync failed: {str(e)}", exc_info=True)
            stats['errors'] += 1
            raise
            
        return stats
    
    async def _fetch_existing_vr_data(self) -> List[Dict]:
        """Fetch all V&R products and their platform data from DB."""
        query = text("""
            SELECT
                p.id as product_id, p.sku, p.base_price, p.description,
                pc.id as platform_common_id, pc.external_id,
                vl.id as vr_listing_id, vl.vr_state
            FROM products p
            JOIN platform_common pc ON pc.product_id = p.id AND pc.platform_name = 'vr'
            LEFT JOIN vr_listings vl ON vl.platform_id = pc.id
            WHERE p.sku LIKE 'VR-%'
        """)
        result = await self.db.execute(query)
        return [row._asdict() for row in result.fetchall()]


    
    def _prepare_api_data(self, df: pd.DataFrame) -> Dict[str, Dict]:
        """Convert API DataFrame to a clean lookup dict by VR ID."""
        api_items = {}
        for _, row in df.iterrows():
            vr_id = str(row.get('product_id', ''))
            if not vr_id:
                continue
            
            clean_row = self._sanitize_for_json(row.to_dict())
            api_items[vr_id] = {
                'vr_id': vr_id,
                'sku': f"VR-{vr_id}",
                'price': float(clean_row.get('product_price', 0) or 0),
                'is_sold': str(clean_row.get('product_sold', '')).lower() == 'yes',
                'brand': clean_row.get('brand_name') or 'Unknown',
                'model': clean_row.get('product_model_name') or 'Unknown',
                'description': clean_row.get('product_description') or '',
                'category': clean_row.get('category_name'),
                'year': int(clean_row['product_year']) if clean_row.get('product_year') else None,
                'image_url': clean_row.get('image_url'),
                'listing_url': clean_row.get('external_link'),
                'extended_attributes': clean_row
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
        
        for vr_id in api_ids - db_ids:
            changes['create'].append(api_items[vr_id])
        
        for vr_id in api_ids & db_ids:
            if self._has_changed(api_items[vr_id], db_items[vr_id]):
                changes['update'].append({'api_data': api_items[vr_id], 'db_data': db_items[vr_id]})
        
        for vr_id in db_ids - api_ids:
            changes['remove'].append(db_items[vr_id])
            
        return changes
    
    def _has_changed(self, api_item: Dict, db_item: Dict) -> bool:
        """Check if an item has meaningful changes."""
        vr_id = api_item['vr_id']
        
        # Price check
        api_price = api_item['price']
        db_price = float(db_item.get('base_price') or 0)
        if abs(api_price - db_price) > 0.01:
            logger.debug(f"VR-{vr_id}: Price changed {db_price} -> {api_price}")
            return True

        # Direct status check: Compare the API status with the last known status in vr_listings.
        api_status = 'sold' if api_item['is_sold'] else 'active'
        db_vr_state = str(db_item.get('vr_state', '')).lower()
        if api_status != db_vr_state:
            logger.debug(f"VR-{vr_id}: V&R state changed '{db_vr_state}' -> '{api_status}'")
            return True
        
        # Description check
        if api_item['description'] != db_item.get('description', ''):
            logger.debug(f"VR-{vr_id}: Description changed")
            return True
        
        return False
    
    async def _batch_create_products(self, items: List[Dict], sync_run_id: uuid.UUID) -> Tuple[int, int]:
        """
        Handles "rogue" listings found on V&R that are not in our system.
        It creates platform-specific records for tracking but does NOT create a master product.
        This flags the item for manual review.
        """
        events_logged = 0
        created_count = 0
        for item in items:
            try:
                logger.warning(
                    f"Rogue SKU Detected: V&R item {item['vr_id']} ('{item.get('brand')} {item.get('model')}') "
                    f"not found in local DB. Creating placeholder records for review."
                )
                # 1. Create a PlatformCommon record with a special status
                # We set product_id to NULL because it doesn't exist yet.
                pc_stmt = insert(PlatformCommon).values(
                    product_id=None, # CRITICAL: No master product link
                    platform_name='vr',
                    external_id=item['vr_id'],
                    status=ListingStatus.UNMATCHED.value, # Use a specific 'unmatched' status
                    sync_status=SyncStatus.NEEDS_REVIEW.value,
                    listing_url=item['listing_url']
                ).returning(PlatformCommon.id)
                platform_common_id = (await self.db.execute(pc_stmt)).scalar_one()

                # 2. Create the vr_listings record and link it to the new platform_common record
                vr_stmt = insert(VRListing).values(
                    platform_id=platform_common_id,
                    vr_listing_id=item['vr_id'],
                    price_notax=item['price'],
                    vr_state='sold' if item['is_sold'] else 'active',
                    inventory_quantity=0 if item['is_sold'] else 1,
                    extended_attributes=item['extended_attributes']
                )
                await self.db.execute(vr_stmt)

                # 3. Log a SyncEvent for this "rogue" listing
                sync_event = SyncEvent(
                    sync_run_id=sync_run_id,
                    platform_name='vr',
                    product_id=None,
                    platform_common_id=platform_common_id,
                    external_id=item['vr_id'],
                    change_type='new_listing',
                    change_data={'title': f"{item.get('brand')} {item.get('model')}", 'price': item['price']},
                    status='pending' # The orchestrator will review this
                )
                self.db.add(sync_event)
                events_logged += 1
                created_count += 1
            except Exception as e:
                logger.error(f"Failed to create placeholder for rogue V&R item {item['vr_id']}: {e}", exc_info=True)
                # Continue to next item

        return created_count, events_logged
    
    async def _batch_update_products(self, items: List[Dict], sync_run_id: uuid.UUID) -> Tuple[int, int]:
        """
        Update existing products following the correct data flow:
        Platform Specific Table -> Platform Common Table -> Master Product Table
        """
        events_logged = 0
        updated_count = 0
        for item in items:
            try:
                api_data, db_data = item['api_data'], item['db_data']
                product_id = db_data['product_id']
                platform_common_id = db_data['platform_common_id']
                vr_listing_id = db_data['vr_listing_id']

                # Determine new statuses
                new_product_status = ProductStatus.SOLD if api_data['is_sold'] else ProductStatus.ACTIVE
                new_platform_status = ListingStatus.SOLD if api_data['is_sold'] else ListingStatus.ACTIVE
                new_vr_state = 'sold' if api_data['is_sold'] else 'active'
                events_to_log = []

                # --- CORRECTED UPDATE ORDER ---

                # Step 1: Update the platform-specific table (vr_listings)
                vr_stmt = text("""
                    UPDATE vr_listings SET price_notax = :price, vr_state = :state, inventory_quantity = :qty, 
                    updated_at = NOW(), last_synced_at = NOW() WHERE id = :id
                """)
                await self.db.execute(vr_stmt, {'price': api_data['price'], 'state': new_vr_state, 'qty': 0 if api_data['is_sold'] else 1, 'id': vr_listing_id})

                # Step 2: Update the generic platform table (platform_common)
                pc_stmt = text("UPDATE platform_common SET status = :status, last_sync = NOW(), updated_at = NOW() WHERE id = :id")
                await self.db.execute(pc_stmt, {'status': new_platform_status.value, 'id': platform_common_id})

                # Step 3: Update the master record (products)
                product_stmt = text("""
                    UPDATE products SET base_price = :price, status = :status, description = :desc, 
                    updated_at = NOW() WHERE id = :id
                """)
                await self.db.execute(product_stmt, {
                    'price': api_data['price'], 
                    'status': new_product_status.value, 
                    'desc': api_data['description'], 
                    'id': product_id
                })

                # Step 4: Log SyncEvents for all detected changes for this item
                # Price Change Event
                if abs(api_data['price'] - float(db_data.get('base_price', 0))) > 0.01:
                    events_to_log.append(SyncEvent(
                        sync_run_id=sync_run_id, platform_name='vr', product_id=product_id,
                        platform_common_id=platform_common_id, external_id=api_data['vr_id'],
                        change_type='price',
                        change_data={'old': db_data.get('base_price'), 'new': api_data['price']}
                    ))

                # Status Change Event
                # Log the direct change from the platform-specific table.
                db_vr_state = db_data.get('vr_state', 'unknown')
                if new_vr_state.lower() != str(db_vr_state).lower():
                    events_to_log.append(SyncEvent(
                        sync_run_id=sync_run_id, platform_name='vr', product_id=product_id,
                        platform_common_id=platform_common_id, external_id=api_data['vr_id'],
                        change_type='status',
                        change_data={'old': db_vr_state, 'new': new_vr_state}
                    ))

                # Add events to the session
                if events_to_log:
                    logger.info(f"Logging {len(events_to_log)} change events for product ID {product_id} from V&R.")
                    self.db.add_all(events_to_log)
                    events_logged += len(events_to_log)
                
                updated_count += 1
            except Exception as e:
                logger.error(f"Failed to update product for V&R item {item['api_data']['vr_id']}: {e}", exc_info=True)

        return updated_count, events_logged
    
    async def _batch_mark_removed(self, items: List[Dict], sync_run_id: uuid.UUID) -> Tuple[int, int]:
        """Mark items as removed (don't delete)."""
        events_logged = 0
        product_ids = [item['product_id'] for item in items if item.get('product_id')]
        if not product_ids:
            return 0, 0
        
        stmt = text("UPDATE platform_common SET status = :status, last_sync = NOW() WHERE product_id = ANY(:p_ids) AND platform_name = 'vr'")
        await self.db.execute(stmt, {'status': ListingStatus.REMOVED.value, 'p_ids': product_ids})

        # Log a SyncEvent for each removed item
        for item in items:
            self.db.add(SyncEvent(
                sync_run_id=sync_run_id, platform_name='vr', product_id=item['product_id'],
                platform_common_id=item['platform_common_id'], external_id=item['external_id'],
                change_type='removed_listing', change_data={'sku': item['sku']}
            ))
            events_logged += 1

        return len(product_ids), events_logged
    
    
    
    
# --- Deprecated Methods (Commented Out for Safety) ---    
    
    
# app/services/vintageandrare_service.py
# import asyncio
# import logging
# import os
# import pandas as pd
# import shutil
# import json
# from datetime import datetime, timezone
# from typing import Optional, Dict, List, Set, Tuple, Generator
# from pathlib import Path
# from sqlalchemy import text, select
# from sqlalchemy.dialects.postgresql import insert
# from sqlalchemy.ext.asyncio import AsyncSession

# from app.core.enums import SyncStatus # Consolidated SyncStatus from core.enums
# from app.services.vintageandrare.client import VintageAndRareClient
# from app.models.product import Product, ProductStatus, ProductCondition
# from app.models.platform_common import PlatformCommon, ListingStatus
# from app.models.vr import VRListing

# logger = logging.getLogger(__name__)

class VintageAndRareServiceOld:
    """
    Purpose: Clearly focused on orchestrating the import process triggered service layer for handling Vintage & Rare inventory import and processing.
    
    Orchestrates scraping via VRInventoryManager and database operations.
        - High-level orchestrator, specifically for the inventory import process. 
        - Takes the database session and coordinates downloading the inventory (using a client), cleaning up old DB data, 
            and importing the new data from the downloaded file into the database (Product, PlatformCommon, VRListing tables).
    
    Import Logic (_import_vr_data_to_db):
        - Handles parsing the DataFrame from the download.
        - Correctly identifies V&R's product_id as the key identifier.
        - Efficiently checks for existing SKUs (VR-<product_id>) before processing rows to avoid redundant work or errors.
        - Uses nested transactions per row, which is excellent for error isolation during the import loop.
        - Creates Product, PlatformCommon, and VRListing records, correctly linking them and populating fields based on the CSV data. Handles basic data cleaning/type conversion. Uses pd.notna robustly.
        - Correctly sets ProductStatus and ListingStatus based on the product_sold column.
        - Uses _sanitize_for_json for the extended_attributes field in VRListing.
    
    Cleanup Logic (_cleanup_vr_data): Implements a "full refresh" strategy by deleting existing V&R data (Product records only if not linked elsewhere, PlatformCommon, VRListing) before importing. Uses raw SQL for efficiency. This is a clear strategy, suitable if the V&R CSV is the source of truth.
    
    Orchestration (run_import_process):
        - Coordinates the steps: authenticate, download, save copy, (optional) cleanup, import.
        - Handles temporary file management and saving a permanent copy of the downloaded CSV (good for auditing).
        - Includes try...finally for cleanup.
    
    Async Calls: The service correctly uses async/await for its database operations. However, the calls manager.authenticate_async() and manager.get_inventory_async() 
        assume async methods exist in the old VRInventoryManager. We need to adjust these calls to match the methods in our merged VintageAndRareClient.
        await client.authenticate() should work directly.
        client.download_inventory_dataframe() is currently synchronous in our merged code. The service should call it using run_in_executor:
    
    """
    def __init__(self, db: AsyncSession):
        self.db = db

    def _sanitize_for_json(self, obj):
        """Recursively check through a dictionary and replace NaN values with None."""
        if isinstance(obj, dict):
            return {k: self._sanitize_for_json(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._sanitize_for_json(i) for i in obj]
        elif pd.isna(obj):
            return None
        else:
            return obj

    # NEW SAFE METHOD replacing _cleanup_vr_data
    async def _mark_removed_products(self, df: pd.DataFrame) -> dict:
        """Mark products that are no longer in V&R CSV as removed, but keep all records."""
        logger.info("Marking products removed from V&R (no deletion)")
        
        stats = {"marked_removed": 0}
        
        # Get current V&R product SKUs from CSV
        csv_skus = {f"VR-{row['product_id']}" for _, row in df.iterrows() if pd.notna(row.get('product_id'))}
        
        # async with self.db.begin(): # Remove the transaction block - let caller manage it
        # Find products in DB but not in CSV
        stmt = text("SELECT sku, id FROM products WHERE sku LIKE 'VR-%' AND sku != ALL(:csv_skus)")
        result = await self.db.execute(stmt, {"csv_skus": tuple(csv_skus)})
        removed_products = result.fetchall()
        
        # Update platform_common status for removed products
        for sku, product_id in removed_products:
            platform_update = text("""
                UPDATE platform_common 
                SET status = 'REMOVED', 
                    sync_status = 'SYNCED',
                    last_sync = timezone('utc', now()),
                    updated_at = timezone('utc', now())
                WHERE product_id = :product_id AND platform_name = 'vr'
            """)
            await self.db.execute(platform_update, {"product_id": product_id})
            
            # Update VR listing status if exists
            vr_update = text("""
                UPDATE vr_listings 
                SET vr_state = 'removed',
                    last_synced_at = timezone('utc', now()),
                    updated_at = timezone('utc', now())
                WHERE platform_id IN (
                    SELECT id FROM platform_common 
                    WHERE product_id = :product_id AND platform_name = 'vr'
                )
            """)
            await self.db.execute(vr_update, {"product_id": product_id})
            
            stats["marked_removed"] += 1
            logger.info(f"Marked {sku} as removed from V&R")
        
        logger.info(f"Marked {stats['marked_removed']} products as removed from V&R")
        return stats

    # NEW SAFE METHOD replacing _cleanup_vr_data
    # async def _update_vr_data_to_db(self, df: pd.DataFrame) -> dict:
    #     """Update existing products and add new ones from V&R CSV without deleting anything."""
    #     stats = {"total": len(df), "created": 0, "updated": 0, "errors": 0, "skipped": 0}
    #     logger.info(f"Updating V&R data. Available columns: {df.columns.tolist()}")
        
    #     id_column = 'product_id'
    #     if id_column not in df.columns:
    #         logger.error(f"Required column '{id_column}' not found in DataFrame.")
    #         stats["errors"] = len(df)
    #         return stats
        
    #     # Process each row
    #     for _, row in df.iterrows():
    #         item_id = str(row[id_column])
    #         sku = f"VR-{item_id}"
            
    #         try:
    #             # Remove all async with self.db.begin_nested(): blocks and just let the parent transaction manage everything.
    #             # async with self.db.begin_nested():
    #             # Check if product exists
    #             stmt = text("SELECT id FROM products WHERE sku = :sku")
    #             result = await self.db.execute(stmt, {"sku": sku})
    #             existing_product_id = result.scalar_one_or_none()
                
    #             if existing_product_id:
    #                 # Update existing product
    #                 await self._update_existing_product(existing_product_id, row)
    #                 stats["updated"] += 1
    #             else:
    #                 # Create new product
    #                 await self._create_new_product(row, sku)
    #                 stats["created"] += 1
                    
    #         except Exception as e:
    #             logger.error(f"Error processing {sku}: {e}")
    #             stats["errors"] += 1
        
    #     logger.info(f"Update complete. Created={stats['created']}, Updated={stats['updated']}, Errors={stats['errors']}")
    #     return stats


    async def _update_vr_data_to_db(self, df: pd.DataFrame) -> dict:
        """Update V&R data using differential sync"""
        sync = VRDifferentialSyncOld(self.db)
        return await sync.sync_vr_inventory(df)


    # Helper Method 1: _update_existing_product
    # ==========================================
    async def _update_existing_product(self, product_id: int, row: pd.Series):
        """Update an existing product with new data from V&R CSV."""
        # Extract data from row
        is_sold = str(row.get('product_sold', '')).lower() == 'yes'
        new_status = ProductStatus.SOLD if is_sold else ProductStatus.ACTIVE
        
        # Update product
        update_stmt = text("""
            UPDATE products 
            SET base_price = :price,
                description = :description,
                status = :status,
                price_notax = :price_notax,
                updated_at = timezone('utc', now())
            WHERE id = :product_id
        """)
        
        await self.db.execute(update_stmt, {
            "product_id": product_id,
            "price": float(row.get('product_price', 0)) if pd.notna(row.get('product_price')) else 0,
            "description": str(row.get('product_description', '')),
            "status": new_status.value,  # Use .value for enum
            "price_notax": float(row.get('product_price_notax', 0)) if pd.notna(row.get('product_price_notax')) else None
        })
        
        # Update platform_common
        platform_update = text("""
            UPDATE platform_common 
            SET status = :status,
                sync_status = 'SYNCED',
                last_sync = timezone('utc', now()),
                updated_at = timezone('utc', now())
            WHERE product_id = :product_id AND platform_name = 'vr'
        """)
        
        platform_status = ListingStatus.SOLD if is_sold else ListingStatus.ACTIVE
        await self.db.execute(platform_update, {
            "product_id": product_id,
            "status": platform_status.value  # Use .value for enum
        })

    # Helper Method 2: _create_new_product
    # ==========================================
    async def _create_new_product(self, row: pd.Series, sku: str):
        """Create a new product from V&R CSV data."""
        # Extract data from row
        brand = str(row.get('brand_name', '')) if pd.notna(row.get('brand_name')) else 'Unknown'
        model = str(row.get('product_model_name', '')) if pd.notna(row.get('product_model_name')) else 'Unknown'
        condition = ProductCondition.GOOD  # Default for V&R
        year = None
        if pd.notna(row.get('product_year')):
            try: 
                year = int(float(row['product_year']))
            except: 
                pass
        price = 0.0
        if pd.notna(row.get('product_price')):
            try: 
                price_str = str(row['product_price']).replace('$', '').replace('£', '').replace(',', '').strip()
                price = float(price_str)
            except: 
                pass
        description = str(row.get('product_description', '')) if pd.notna(row.get('product_description')) else ''
        primary_image = str(row.get('image_url', '')) if pd.notna(row.get('image_url')) else None
        is_sold = str(row.get('product_sold', '')).lower() == 'yes'
        
        # Create product
        product = Product(
            sku=sku,
            brand=brand,
            model=model,
            year=year,
            description=description,
            condition=condition,
            category=str(row.get('category_name', '')) if pd.notna(row.get('category_name')) else None,
            base_price=price,
            primary_image=primary_image,
            status=ProductStatus.SOLD if is_sold else ProductStatus.ACTIVE
        )
        self.db.add(product)
        await self.db.flush()
        
        # Create platform_common entry
        listing_url = str(row.get('external_link', '')) if pd.notna(row.get('external_link')) else None
        platform_common = PlatformCommon(
            product_id=product.id,
            platform_name="vr",
            external_id=str(row['product_id']),
            status=ListingStatus.SOLD if is_sold else ListingStatus.ACTIVE,
            sync_status=SyncStatus.SYNCED,
            last_sync=datetime.now(),
            listing_url=listing_url
        )
        self.db.add(platform_common)
        await self.db.flush()
        
        # Create VRListing entry
        extended_attributes = self._sanitize_for_json({
            "category": row.get('category_name'),
            "finish": row.get('product_finish'),
            "decade": row.get('decade'),
            "year": year,
            "brand": brand,
            "model": model,
            "is_sold": is_sold
        })
        
        vr_listing = VRListing(
            platform_id=platform_common.id,
            vr_listing_id=str(row['product_id']),
            in_collective=str(row.get('product_in_collective', '')).lower() == 'yes',
            in_inventory=str(row.get('product_in_inventory', '')).lower() == 'yes',
            in_reseller=str(row.get('product_in_reseller', '')).lower() == 'yes',
            show_vat=str(row.get('show_vat', '')).lower() == 'yes',
            collective_discount=float(row['collective_discount']) if pd.notna(row.get('collective_discount')) else None,
            price_notax=price,
            inventory_quantity=0 if is_sold else 1,
            processing_time=None,
            vr_state='SOLD' if is_sold else 'ACTIVE',
            extended_attributes=extended_attributes,
            last_synced_at=datetime.now()
        )
        self.db.add(vr_listing)


    # NEW process which calls safe methods
    async def run_import_process(self, username, password, save_only=False):
        """Run the V&R inventory import process."""
        try:
            print("Starting VintageAndRareService.run_import_process")
            print(f"Username provided: {'Yes' if username else 'No'}")
            print(f"Password provided: {'Yes' if password else 'No'}")
            
            # Initialize client
            client = VintageAndRareClient(username, password, db_session=self.db)
            
            # Authenticate
            print("Attempting authentication with V&R...")
            authenticated = await client.authenticate()
            print(f"Authentication result: {authenticated}")
            
            if not authenticated:
                return {"status": "error", "message": "V&R authentication failed"}
            
            # Download inventory
            print("Authentication successful. Downloading inventory...")
            inventory_df = await client.download_inventory_dataframe(save_to_file=True)
            
            if inventory_df is None:
                print("V&R inventory download failed - received None")
                return {"status": "error", "message": "No V&R inventory data received (None)"}
                
            if inventory_df.empty:
                print("V&R inventory download returned empty DataFrame")
                return {"status": "error", "message": "No V&R inventory data received (empty DataFrame)"}
            
            print(f"Successfully downloaded inventory with {len(inventory_df)} items")
            print(f"Columns: {inventory_df.columns.tolist()}")
            print(f"Sample data: {inventory_df.head(1).to_dict('records')}")
            
            if save_only:
                return {
                    "status": "success", 
                    "message": f"V&R inventory saved with {len(inventory_df)} records",
                    "count": len(inventory_df)
                }
            
            # Process inventory updates
            print("Processing inventory updates...")
            removed_stats = await self._mark_removed_products(inventory_df)
            update_stats = await self._update_vr_data_to_db(inventory_df)

            # Combine results
            result = {
                **update_stats,
                **removed_stats,
                "import_type": "UPDATE-BASED (No deletions)",
                "total_processed": len(inventory_df)
            }
            
            print(f"Inventory update processing complete: {result}")
            return {
                "status": "success",
                "message": f"V&R inventory processed successfully",
                "processed": len(inventory_df),
                "new_products": result.get("new_products", 0),
                "updated_products": result.get("updated_products", 0),
                "status_changes": result.get("status_changes", 0),
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        
        except Exception as e:
            import traceback
            error_traceback = traceback.format_exc()
            print(f"Exception in VintageAndRareService.run_import_process: {str(e)}")
            print(f"Traceback: {error_traceback}")
            return {"status": "error", "message": str(e)}


class VRDifferentialSyncOld:
    """Efficient differential sync for V&R inventory"""
    
    def __init__(self, db_session):
        self.db = db_session
        
    async def sync_vr_inventory(self, df: pd.DataFrame) -> Dict[str, int]:
        """
        Main sync method - compares API data with DB and applies only necessary changes
        
        Args:
            df: DataFrame from V&R API with inventory data
            
        Returns:
            Dict with counts of operations performed
        """
        stats = {
            "total_api_items": len(df),
            "created": 0,
            "updated": 0,
            "removed": 0,
            "unchanged": 0,
            "errors": 0
        }
        
        try:
            # Step 1: Fetch all existing V&R data from DB
            logger.info("Fetching existing V&R inventory from database...")
            existing_data = await self._fetch_existing_vr_data()
            
            # Step 2: Convert to lookup dictionaries for O(1) access
            api_items = self._prepare_api_data(df)
            db_items = self._prepare_db_data(existing_data)
            
            # Step 3: Calculate differences
            changes = self._calculate_changes(api_items, db_items)
            
            # Step 4: Apply changes in batches
            logger.info(f"Applying changes: {len(changes['create'])} new, "
                       f"{len(changes['update'])} updates, {len(changes['remove'])} removals")
            
            # Process creates
            if changes['create']:
                created = await self._batch_create_products(changes['create'])
                stats['created'] = created
                
            # Process updates
            if changes['update']:
                updated = await self._batch_update_products(changes['update'])
                stats['updated'] = updated
                
            # Process removals (mark as removed, don't delete)
            if changes['remove']:
                removed = await self._batch_mark_removed(changes['remove'])
                stats['removed'] = removed
                
            stats['unchanged'] = len(api_items) - stats['created'] - stats['updated']
            
            await self.db.commit()
            logger.info(f"Sync complete: {stats}")
            
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Sync failed: {str(e)}")
            stats['errors'] = 1
            raise
            
        return stats
    
    async def _fetch_existing_vr_data(self) -> List[Dict]:
        """Fetch all V&R products and their platform data from DB"""
        query = text("""
            SELECT 
                p.id as product_id,
                p.sku,
                p.base_price,
                p.status,
                p.updated_at as product_updated,
                pc.id as platform_common_id,
                pc.external_id,
                pc.status as platform_status,
                pc.last_sync,
                vl.id as vr_listing_id,
                vl.vr_listing_id as vr_external_id,
                vl.price_notax as vr_price,
                vl.vr_state,
                vl.updated_at as vr_updated
            FROM products p
            INNER JOIN platform_common pc ON pc.product_id = p.id
            LEFT JOIN vr_listings vl ON vl.platform_id = pc.id
            WHERE p.sku LIKE 'VR-%'
            AND pc.platform_name = 'vr'
        """)
        
        result = await self.db.execute(query)
        return [row._asdict() for row in result.fetchall()]
    
    def _prepare_api_data(self, df: pd.DataFrame) -> Dict[str, Dict]:
        """Convert API DataFrame to lookup dict by VR ID"""
        api_items = {}
        
        for _, row in df.iterrows():
            vr_id = str(row.get('product_id', ''))
            if not vr_id:
                continue
                
            # Normalize the data
            api_items[vr_id] = {
                'vr_id': vr_id,
                'sku': f"VR-{vr_id}",
                'price': float(row.get('product_price', 0)) if pd.notna(row.get('product_price')) else 0,
                'is_sold': str(row.get('product_sold', '')).lower() == 'yes',
                'brand': str(row.get('brand_name', '')) if pd.notna(row.get('brand_name')) else 'Unknown',
                'model': str(row.get('product_model_name', '')) if pd.notna(row.get('product_model_name')) else 'Unknown',
                'description': str(row.get('product_description', '')) if pd.notna(row.get('product_description')) else '',
                'category': str(row.get('category_name', '')) if pd.notna(row.get('category_name')) else None,
                'year': int(float(row['product_year'])) if pd.notna(row.get('product_year')) else None,
                'image_url': str(row.get('image_url', '')) if pd.notna(row.get('image_url')) else None,
                'listing_url': str(row.get('external_link', '')) if pd.notna(row.get('external_link')) else None,
                '_raw': row.to_dict()  # Keep raw data for extended attributes
            }
            
        return api_items
    
    def _prepare_db_data(self, existing_data: List[Dict]) -> Dict[str, Dict]:
        """Convert DB data to lookup dict by external ID"""
        db_items = {}
        
        for row in existing_data:
            external_id = str(row['external_id']) if row['external_id'] else None
            if external_id:
                db_items[external_id] = row
                
        return db_items
    
    def _calculate_changes(self, api_items: Dict, db_items: Dict) -> Dict[str, List]:
        """Calculate what needs to be created, updated, or removed"""
        changes = {
            'create': [],
            'update': [],
            'remove': []
        }
        
        api_ids = set(api_items.keys())
        db_ids = set(db_items.keys())
        
        # New items (in API but not in DB)
        for vr_id in api_ids - db_ids:
            changes['create'].append(api_items[vr_id])
        
        # Updated items (in both, check if changed)
        for vr_id in api_ids & db_ids:
            if self._has_changed(api_items[vr_id], db_items[vr_id]):
                changes['update'].append({
                    'api_data': api_items[vr_id],
                    'db_data': db_items[vr_id]
                })
        
        # Removed items (in DB but not in API)
        for vr_id in db_ids - api_ids:
            changes['remove'].append(db_items[vr_id])
            
        return changes
    
    def _has_changed(self, api_item: Dict, db_item: Dict) -> bool:
        """Check if an item has meaningful changes"""
        # Check price change
        api_price = api_item['price']
        db_price = float(db_item['base_price']) if db_item['base_price'] else 0
        if abs(api_price - db_price) > 0.01:
            return True
            
        # Check status change
        api_sold = api_item['is_sold']
        db_sold = db_item['platform_status'] == 'SOLD' or db_item['vr_state'] == 'SOLD'
        if api_sold != db_sold:
            return True
            
        # Add more change detection as needed
        return False
    
    async def _batch_create_products(self, items: List[Dict]) -> int:
        """Create new products and their platform entries using UPSERT"""
        created = 0
        
        for batch in self._chunk_list(items, 100):
            try:
                # Create products
                for item in batch:
                    # Insert product
                    product_stmt = insert(Product).values(
                        sku=item['sku'],
                        brand=item['brand'],
                        model=item['model'],
                        year=item['year'],
                        description=item['description'],
                        category=item['category'],
                        base_price=item['price'],
                        primary_image=item['image_url'],
                        condition=ProductCondition.VERYGOOD,
                        status='SOLD' if item['is_sold'] else 'ACTIVE',
                        created_at=datetime.now(),
                        updated_at=datetime.now()
                    )
                    
                    product_stmt = product_stmt.returning(Product.id)
                    result = await self.db.execute(product_stmt)
                    product_id = result.scalar_one()
                    
                    # Insert platform_common
                    pc_stmt = insert(PlatformCommon).values(
                        product_id=product_id,
                        platform_name='vr',
                        external_id=item['vr_id'],
                        status='SOLD' if item['is_sold'] else 'ACTIVE',
                        sync_status='synced',
                        listing_url=item['listing_url'],
                        last_sync=datetime.now(),
                        created_at=datetime.now(),
                        updated_at=datetime.now()
                    )
                    
                    pc_stmt = pc_stmt.returning(PlatformCommon.id)
                    result = await self.db.execute(pc_stmt)
                    platform_common_id = result.scalar_one()
                    
                    # Insert VR listing with UPSERT
                    vr_stmt = insert(VRListing).values(
                        platform_id=platform_common_id,
                        vr_listing_id=item['vr_id'],
                        price_notax=item['price'],
                        vr_state='SOLD' if item['is_sold'] else 'ACTIVE',
                        inventory_quantity=0 if item['is_sold'] else 1,
                        extended_attributes=item['_raw'],
                        created_at=datetime.now(),
                        updated_at=datetime.now(),
                        last_synced_at=datetime.now()
                    )
                    
                    # Use ON CONFLICT to handle duplicates
                    vr_stmt = vr_stmt.on_conflict_do_update(
                        index_elements=['vr_listing_id'],
                        set_={
                            'platform_id': vr_stmt.excluded.platform_id,
                            'price_notax': vr_stmt.excluded.price_notax,
                            'vr_state': vr_stmt.excluded.vr_state,
                            'inventory_quantity': vr_stmt.excluded.inventory_quantity,
                            'updated_at': datetime.now(),
                            'last_synced_at': datetime.now()
                        }
                    )
                    
                    await self.db.execute(vr_stmt)
                    created += 1
                    
            except Exception as e:
                logger.error(f"Error creating batch: {str(e)}")
                raise
                
        return created
    
    async def _batch_update_products(self, items: List[Dict]) -> int:
        """Update existing products efficiently"""
        updated = 0
        
        for batch in self._chunk_list(items, 100):
            try:
                for item in batch:
                    api_data = item['api_data']
                    db_data = item['db_data']
                    
                    # Update product
                    product_stmt = text("""
                        UPDATE products 
                        SET base_price = :price,
                            status = :status,
                            updated_at = NOW()
                        WHERE id = :product_id
                    """)
                    
                    await self.db.execute(product_stmt, {
                        'product_id': db_data['product_id'],
                        'price': api_data['price'],
                        'status': 'SOLD' if api_data['is_sold'] else 'ACTIVE'
                    })
                    
                    # Update platform_common
                    pc_stmt = text("""
                        UPDATE platform_common
                        SET status = :status,
                            last_sync = NOW(),
                            updated_at = NOW()
                        WHERE id = :id
                    """)
                    
                    await self.db.execute(pc_stmt, {
                        'id': db_data['platform_common_id'],
                        'status': 'SOLD' if api_data['is_sold'] else 'ACTIVE'
                    })
                    
                    # Update VR listing
                    vr_stmt = text("""
                        UPDATE vr_listings
                        SET price_notax = :price,
                            vr_state = :state,
                            inventory_quantity = :quantity,
                            updated_at = NOW(),
                            last_synced_at = NOW()
                        WHERE id = :id
                    """)
                    
                    await self.db.execute(vr_stmt, {
                        'id': db_data['vr_listing_id'],
                        'price': api_data['price'],
                        'state': 'SOLD' if api_data['is_sold'] else 'ACTIVE',
                        'quantity': 0 if api_data['is_sold'] else 1
                    })
                    
                    updated += 1
                    
            except Exception as e:
                logger.error(f"Error updating batch: {str(e)}")
                raise
                
        return updated
    
    async def _batch_mark_removed(self, items: List[Dict]) -> int:
        """Mark items as removed (don't delete)"""
        removed = 0
        
        product_ids = [item['product_id'] for item in items]
        
        if product_ids:
            # Update platform_common
            stmt = text("""
                UPDATE platform_common
                SET status = 'removed',
                    sync_status = 'synced',
                    last_sync = NOW(),
                    updated_at = NOW()
                WHERE product_id = ANY(:product_ids)
                AND platform_name = 'vr'
            """)
            
            await self.db.execute(stmt, {'product_ids': product_ids})
            removed = len(product_ids)
            
        return removed
    
    def _chunk_list(self, lst: List, chunk_size: int) -> Generator[List, None, None]:
        """Split list into chunks for batch processing"""
        for i in range(0, len(lst), chunk_size):
            yield lst[i:i + chunk_size]
            
