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
    async def _update_vr_data_to_db(self, df: pd.DataFrame) -> dict:
        """Update existing products and add new ones from V&R CSV without deleting anything."""
        stats = {"total": len(df), "created": 0, "updated": 0, "errors": 0, "skipped": 0}
        logger.info(f"Updating V&R data. Available columns: {df.columns.tolist()}")
        
        id_column = 'product_id'
        if id_column not in df.columns:
            logger.error(f"Required column '{id_column}' not found in DataFrame.")
            stats["errors"] = len(df)
            return stats
        
        # Process each row
        for _, row in df.iterrows():
            item_id = str(row[id_column])
            sku = f"VR-{item_id}"
            
            try:
                # Remove all async with self.db.begin_nested(): blocks and just let the parent transaction manage everything.
                # async with self.db.begin_nested():
                # Check if product exists
                stmt = text("SELECT id FROM products WHERE sku = :sku")
                result = await self.db.execute(stmt, {"sku": sku})
                existing_product_id = result.scalar_one_or_none()
                
                if existing_product_id:
                    # Update existing product
                    await self._update_existing_product(existing_product_id, row)
                    stats["updated"] += 1
                else:
                    # Create new product
                    await self._create_new_product(row, sku)
                    stats["created"] += 1
                    
            except Exception as e:
                logger.error(f"Error processing {sku}: {e}")
                stats["errors"] += 1
        
        logger.info(f"Update complete. Created={stats['created']}, Updated={stats['updated']}, Errors={stats['errors']}")
        return stats

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
            vr_state='sold' if is_sold else 'active',
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

