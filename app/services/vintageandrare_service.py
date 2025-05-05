# app/services/vintageandrare_service.py
import asyncio
import logging
import os
import pandas as pd
import shutil
import json
from datetime import datetime, timezone
from typing import Optional
from pathlib import Path
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import SyncStatus # Consolidated SyncStatus from core.enums
from app.services.vintageandrare.client import VintageAndRareClient
from app.models.product import Product, ProductStatus, ProductCondition
from app.models.platform_common import PlatformCommon, ListingStatus
from app.models.vr import VRListing

logger = logging.getLogger(__name__)

class VintageAndRareService:
    """
    Purpose: Clearly focused on orchestrating the import process triggered
    Service layer for handling Vintage & Rare inventory import and processing.
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

    async def _cleanup_vr_data(self):
        """Clean up existing VR data before import."""
        logger.info("Cleaning up existing Vintage & Rare data from database")
        async with self.db.begin(): # Use the session provided to the service
            # 1. Get products with VR SKUs
            stmt = text("SELECT id FROM products WHERE sku LIKE 'VR-%'")
            result = await self.db.execute(stmt)
            product_ids = [row[0] for row in result.fetchall()]

            if not product_ids:
                logger.info("No existing Vintage & Rare data found to clean up")
                return

            # 2. Get platform_common IDs linked to these products (specific to VR)
            stmt = text("""
                SELECT id FROM platform_common
                WHERE platform_name = 'vintageandrare' AND product_id = ANY(:p_ids)
            """)
            result = await self.db.execute(stmt, {"p_ids": product_ids})
            platform_ids = [row[0] for row in result.fetchall()]

            # 3. Delete VR listings
            if platform_ids:
                stmt = text("DELETE FROM vr_listings WHERE platform_id = ANY(:p_ids)")
                result = await self.db.execute(stmt, {"p_ids": platform_ids})
                logger.info(f"Deleted {result.rowcount} VR listing records")

                # 4. Delete platform_common records for VR
                stmt = text("DELETE FROM platform_common WHERE id = ANY(:p_ids)")
                result = await self.db.execute(stmt, {"p_ids": platform_ids})
                logger.info(f"Deleted {result.rowcount} platform_common records for Vintage & Rare")

            # 5. Delete VR products (only if no other platform_common records exist for them)
            # Check for remaining references
            check_refs_stmt = text("""
                SELECT product_id FROM platform_common WHERE product_id = ANY(:p_ids)
            """)
            refs_result = await self.db.execute(check_refs_stmt, {"p_ids": product_ids})
            referenced_product_ids = {row[0] for row in refs_result.fetchall()}

            products_to_delete = [pid for pid in product_ids if pid not in referenced_product_ids]

            if products_to_delete:
                stmt = text("DELETE FROM products WHERE id = ANY(:p_ids)")
                result = await self.db.execute(stmt, {"p_ids": products_to_delete})
                logger.info(f"Deleted {result.rowcount} product records previously unique to Vintage & Rare")
            else:
                logger.info("No product records to delete (all have listings on other platforms).")

    async def _import_vr_data_to_db(self, df: pd.DataFrame) -> dict:
        """Import Vintage & Rare data from DataFrame to database."""
        stats = {"total": len(df), "created": 0, "errors": 0, "skipped": 0, "existing": 0, "sold_imported": 0}
        logger.info(f"Importing data from DataFrame. Available columns: {df.columns.tolist()}")

        sold_count = len(df[df['product_sold'].astype(str).str.lower() == 'yes'])
        logger.info(f"DataFrame contains {sold_count} items marked as sold out of {len(df)} total")

        sku_prefix = "VR-"
        id_column = 'product_id' # V&R's internal ID used in CSV

        if id_column not in df.columns:
            logger.error(f"Required column '{id_column}' not found in DataFrame.")
            stats["errors"] = len(df)
            return stats

        df = df[df[id_column].notna() & (df[id_column] != '')].copy() # Filter and make copy
        df[id_column] = df[id_column].astype(str) # Ensure ID is string
        logger.info(f"Processing {len(df)} rows with valid product IDs")

        potential_skus = [f"{sku_prefix}{item_id}" for item_id in df[id_column]]

        async with self.db.begin(): # Check existing within transaction
            stmt = text("SELECT sku FROM products WHERE sku = ANY(:skus)")
            result = await self.db.execute(stmt, {"skus": potential_skus})
            existing_skus = {row[0] for row in result.fetchall()}

        logger.info(f"Found {len(existing_skus)} existing SKUs that will be skipped")
        stats["existing"] = len(existing_skus)

        # Process rows
        for _, row in df.iterrows():
            item_id = str(row[id_column])
            sku = f"{sku_prefix}{item_id}"

            if sku in existing_skus:
                stats["skipped"] += 1
                continue

            # Use nested transaction for each row to isolate errors
            try:
                async with self.db.begin_nested(): # Use nested transaction
                    # --- Extract and Create Product ---
                    brand = str(row.get('brand_name', '')) if pd.notna(row.get('brand_name')) else 'Unknown'
                    model = str(row.get('product_model_name', '')) if pd.notna(row.get('product_model_name')) else 'Unknown'
                    condition = ProductCondition.GOOD # Default for V&R
                    year = None
                    if pd.notna(row.get('product_year')):
                        try: year = int(float(row['product_year']))
                        except: pass
                    price = 0.0
                    if pd.notna(row.get('product_price')):
                        try: price_str = str(row['product_price']).replace('$', '').replace('£', '').replace(',', '').strip(); price = float(price_str)
                        except: pass
                    description = str(row.get('product_description', '')) if pd.notna(row.get('product_description')) else ''
                    primary_image = str(row.get('image_url', '')) if pd.notna(row.get('image_url')) else None
                    is_sold = str(row.get('product_sold', '')).lower() == 'yes'

                    product = Product(
                        sku=sku, brand=brand, model=model, year=year, description=description,
                        condition=condition, category=str(row.get('category_name', '')) if pd.notna(row.get('category_name')) else None,
                        base_price=price, primary_image=primary_image,
                        status=ProductStatus.SOLD if is_sold else ProductStatus.ACTIVE
                    )
                    self.db.add(product)
                    await self.db.flush()

                    # --- Create PlatformCommon ---
                    listing_url = str(row.get('external_link', '')) if pd.notna(row.get('external_link')) else None
                    platform_common = PlatformCommon(
                        product_id=product.id, platform_name="vintageandrare", external_id=item_id,
                        status=ListingStatus.SOLD if is_sold else ListingStatus.ACTIVE,
                        sync_status=SyncStatus.SYNCED, # Imported = Synced initially
                        # last_sync=datetime.now(timezone.utc), listing_url=listing_url
                        last_sync=datetime.now(), listing_url=listing_url
                    )
                    self.db.add(platform_common)
                    await self.db.flush()

                    # --- Create VRListing ---
                    extended_attributes = self._sanitize_for_json({
                        "category": row.get('category_name'), "finish": row.get('product_finish'),
                        "decade": row.get('decade'), "year": year, "brand": brand, "model": model,
                        "is_sold": is_sold # Keep track if needed here too
                    })
                    vr_listing = VRListing(
                        platform_id=platform_common.id, vr_listing_id=item_id,
                        in_collective=str(row.get('product_in_collective', '')).lower() == 'yes',
                        in_inventory=str(row.get('product_in_inventory', '')).lower() == 'yes',
                        in_reseller=str(row.get('product_in_reseller', '')).lower() == 'yes',
                        show_vat=str(row.get('show_vat', '')).lower() == 'yes',
                        collective_discount=float(row['collective_discount']) if pd.notna(row.get('collective_discount')) else None,
                        price_notax=price, # Assuming price is notax for V&R
                        inventory_quantity=0 if is_sold else 1, # Set quantity based on sold status
                        processing_time=None, # Not in CSV?
                        vr_state='sold' if is_sold else 'active',
                        extended_attributes=extended_attributes,
                        # last_synced_at=datetime.now(timezone.utc)
                        last_synced_at=datetime.now() # Use TZ aware
                    )
                    self.db.add(vr_listing)

                    stats["created"] += 1
                    if is_sold: stats["sold_imported"] += 1
                    logger.debug(f"Created DB records for VR listing {sku}{' (SOLD)' if is_sold else ''}")

            except Exception as e:
                logger.error(f"Error processing row for VR listing {item_id} (SKU: {sku}): {e}")
                stats["errors"] += 1
                # The nested transaction ensures this row fails but doesn't stop others

        logger.info(f"DB Import Summary: Created={stats['created']}, Skipped={stats['skipped']}, Errors={stats['errors']}")
        logger.info(f"Imported {stats['sold_imported']} items marked as sold")
        return stats

    async def run_import_process(self, username: str, password: str, save_only: bool = False) -> Optional[dict]:
        """
        Orchestrates the full V&R import process: download, cleanup, import.

        Args:
            username: V&R username.
            password: V&R password.
            save_only: If True, only download and save CSV, skip DB import.

        Returns:
            A dictionary with import statistics, or None if download fails.
        """
        temp_file_path: Optional[str] = None
        client: Optional[VintageAndRareClient] = None
                
        try:
            logger.info("Initializing VintageAndRareClient...")
            # manager = VRInventoryManager(username, password) # Old
            client = VintageAndRareClient(username, password, db_session=self.db) # New (pass db if needed by client methods)

            logger.info("Authenticating with Vintage & Rare...")
            # --- CHANGE AUTHENTICATION CALL ---
            # if not await manager.authenticate_async(): # Old
            if not await client.authenticate(): # New (using the async method from the client)
                logger.error("Failed to authenticate with Vintage & Rare")
                return None
            # --- END CHANGE ---

            logger.info("Downloading V&R inventory...")
            # --- CHANGE DOWNLOAD CALL USING run_in_executor ---
            # df = await manager.get_inventory_async(save_to_file=True) # Old assumption
            # loop = asyncio.get_event_loop()
            # Call the synchronous download method in an executor thread
            # Pass save_to_file=True as an argument to the download method
            # df = await loop.run_in_executor(
            #     None,               # Use default executor (thread pool)
            #     client.download_inventory_dataframe, # The synchronous function to call
            #     True                # Argument for save_to_file
            #     # Pass other arguments if the method signature changes
            # )
            # --- END CHANGE ---

            df = await client.download_inventory_dataframe(save_to_file=True)
            
            if df is None:
                logger.error("Failed to download Vintage & Rare inventory DataFrame")
                return None

            temp_file_path = client.temp_files[-1] if client.temp_files else None

            # Save a copy of the downloaded CSV
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S") # Use TZ aware
            csv_path = Path(f"data/vintageandrare_{timestamp}.csv") # Use Path object
            csv_path.parent.mkdir(parents=True, exist_ok=True) # Ensure directory exists

            if temp_file_path and os.path.exists(temp_file_path):
                shutil.copy2(temp_file_path, csv_path)
                logger.info(f"Downloaded inventory CSV saved to: {csv_path.resolve()}")
            elif df is not None: # Check df is not None before saving
                df.to_csv(csv_path, index=False) # Fallback if temp file not found but df exists
                logger.warning(f"Saved DataFrame directly to {csv_path.resolve()} (temp file issue?).")
            else:
                logger.error("Cannot save inventory CSV, DataFrame is None and no temp file path found.")


            logger.info(f"Successfully downloaded {len(df) if df is not None else 0} listings from Vintage & Rare")

            if save_only:
                logger.info("Save-only mode enabled, skipping database operations.")
                return {"total": len(df) if df is not None else 0, "saved_to": str(csv_path.resolve())}

            # Perform database operations (cleanup + import)
            await self._cleanup_vr_data()
            import_stats = await self._import_vr_data_to_db(df) # Pass the DataFrame

            # Optionally commit the main transaction if not using autocommit per row
            # await self.db.commit() # Usually handled by the calling context (e.g., CLI script)

            return import_stats

        except Exception as e:
            logger.exception("Fatal error during V&R import process")
            # await self.db.rollback() # Rollback main transaction if needed (usually handled by caller)
            return {"error": str(e)}
        finally:
            # Cleanup the temporary file tracked by the client
            if client and hasattr(client, 'cleanup_temp_files'):
                client.cleanup_temp_files() # Call the client's cleanup method
