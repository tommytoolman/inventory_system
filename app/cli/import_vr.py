# app/cli/import_vr.py
import asyncio
import logging
import click
import os
import pandas as pd
import shutil
import json
from datetime import datetime, timezone
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.vintageandrare.download_inventory import VRInventoryManager
from app.database import async_session
from app.models.product import Product, ProductStatus, ProductCondition
from app.models.platform_common import PlatformCommon, ListingStatus, SyncStatus
from app.models.vr import VRListing

logger = logging.getLogger(__name__)

def sanitize_for_json(obj):
    """Recursively check through a dictionary and replace NaN values with None."""
    if isinstance(obj, dict):
        return {k: sanitize_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize_for_json(i) for i in obj]
    elif pd.isna(obj):
        return None  # Replace NaN with None (becomes null in JSON)
    else:
        return obj

@click.command()
@click.option('--username', required=True, help='VintageAndRare username')
@click.option('--password', required=True, help='VintageAndRare password')
@click.option('--save-only', is_flag=True, help='Only save CSV without importing')
def import_vr(username, password, save_only):
    """Import Vintage & Rare listings into the database"""
    logging.basicConfig(level=logging.INFO)
    
    start_time = datetime.now()
    logger.info(f"Starting Vintage & Rare import at {start_time}")
    
    try:
        asyncio.run(run_vr_import(username, password, save_only))
        
        end_time = datetime.now()
        duration = end_time - start_time
        logger.info(f"Completed Vintage & Rare import in {duration}")
    except Exception as e:
        logger.exception("Error during Vintage & Rare import")
        click.echo(f"Error: {str(e)}")

async def run_vr_import(username, password, save_only=False):
    """Download and import Vintage & Rare listings"""
    # Download inventory data
    manager = VRInventoryManager(username, password)
    
    # Authenticate and download
    if not manager.authenticate():
        logger.error("Failed to authenticate with Vintage & Rare")
        return
        
    # Get inventory data (this will save to a temporary file)
    df = manager.get_inventory(save_to_file=True)
    if df is None:
        logger.error("Failed to download Vintage & Rare inventory")
        return
    
    # Get the temporary file path
    temp_file = manager.temp_file if hasattr(manager, 'temp_file') else None
    
    # Create a timestamped filename for the CSV
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = f"data/vintageandrare_{timestamp}.csv"
    
    # Make sure the directory exists
    os.makedirs(os.path.dirname(csv_path), exist_ok=True)
    
    # Copy the temporary file to our permanent location if it exists
    if temp_file and os.path.exists(temp_file):
        shutil.copy2(temp_file, csv_path)
        logger.info(f"DataFrame saved to: {os.path.abspath(csv_path)}")
    else:
        # Save the DataFrame directly if we can't find the temp file
        df.to_csv(csv_path, index=False)
        logger.info(f"DataFrame saved to: {os.path.abspath(csv_path)}")
    
    logger.info(f"Successfully downloaded {len(df)} listings from Vintage & Rare")
    
    # If we're just saving the CSV, we're done
    if save_only:
        logger.info("Save-only mode enabled, skipping database import")
        return
    
    # Now import the data
    async with async_session() as session:
        # Clean up existing VR data first
        await cleanup_vr_data(session)
        
        # Import the data into the database
        import_stats = await import_vr_data_to_db(session, df)
        
        # Check database counts
        async with session.begin():
            stmt = text("SELECT COUNT(*) FROM vr_listings")
            result = await session.execute(stmt)
            count = result.scalar()
            logger.info(f"Found {count} Vintage & Rare listings in database")
        
        # Print summary
        logger.info("\nImport Summary:")
        logger.info(f"Total listings processed: {import_stats['total']}")
        logger.info(f"Successfully created: {import_stats['created']}")
        logger.info(f"Errors: {import_stats['errors']}")
        logger.info(f"Skipped: {import_stats['skipped']}")
    
    # Cleanup the temporary file
    if temp_file and os.path.exists(temp_file):
        os.remove(temp_file)
        logger.info(f"Removed temporary file: {temp_file}")

async def cleanup_vr_data(session: AsyncSession):
    """Clean up existing VR data before import"""
    logger.info("Cleaning up existing Vintage & Rare data")
    
    async with session.begin():
        # 1. Get products with VR SKUs
        stmt = text("""
            SELECT id FROM products WHERE sku LIKE 'VR-%'
        """)
        result = await session.execute(stmt)
        product_ids = [row[0] for row in result.fetchall()]
        
        if not product_ids:
            logger.info("No existing Vintage & Rare data found to clean up")
            return
        
        # 2. Get platform_common IDs linked to these products
        stmt = text("""
            SELECT id FROM platform_common 
            WHERE product_id = ANY(:product_ids)
        """)
        result = await session.execute(stmt, {"product_ids": product_ids})
        platform_ids = [row[0] for row in result.fetchall()]
        
        # 3. Delete VR listings
        if platform_ids:
            stmt = text("""
                DELETE FROM vr_listings
                WHERE platform_id = ANY(:platform_ids)
            """)
            result = await session.execute(stmt, {"platform_ids": platform_ids})
            vr_deleted = result.rowcount
            logger.info(f"Deleted {vr_deleted} VR listing records")
            
            # 4. Delete platform_common records
            stmt = text("""
                DELETE FROM platform_common
                WHERE id = ANY(:platform_ids)
            """)
            result = await session.execute(stmt, {"platform_ids": platform_ids})
            pc_deleted = result.rowcount
            logger.info(f"Deleted {pc_deleted} platform_common records for Vintage & Rare")
        
        # 5. Delete products
        stmt = text("""
            DELETE FROM products
            WHERE id = ANY(:product_ids)
        """)
        result = await session.execute(stmt, {"product_ids": product_ids})
        products_deleted = result.rowcount
        logger.info(f"Deleted {products_deleted} product records for Vintage & Rare")

async def import_vr_data_to_db(session: AsyncSession, df: pd.DataFrame) -> dict:
    """Import Vintage & Rare data from DataFrame to database"""
    stats = {
        "total": len(df),
        "created": 0,
        "errors": 0,
        "skipped": 0,
        "existing": 0,
        "sold_imported": 0
    }
    
    # Show the column names for debugging
    logger.info(f"Available columns: {df.columns.tolist()}")
    
    # Let's analyze the sold status distribution in the data
    sold_count = len(df[df['product_sold'].astype(str).str.lower() == 'yes'])
    logger.info(f"CSV contains {sold_count} items marked as sold out of {len(df)} total")
    
    # Check for existing SKUs to avoid duplicates
    sku_prefix = "VR-"
    
    # Based on your CSV, use 'product_id' as the ID column
    id_column = 'product_id'
    
    if id_column not in df.columns:
        logger.error(f"Column '{id_column}' not found in DataFrame. Available columns: {df.columns.tolist()}")
        return stats
    
    # Filter out rows with empty IDs
    df = df[df[id_column].notna() & (df[id_column] != '')]
    logger.info(f"Processing {len(df)} rows with valid product IDs")
    
    potential_skus = [f"{sku_prefix}{item_id}" for item_id in df[id_column]]
    
    # Check which ones already exist
    async with session.begin():
        stmt = text("SELECT sku FROM products WHERE sku = ANY(:skus)")
        result = await session.execute(stmt, {"skus": potential_skus})
        existing_skus = {row[0] for row in result.fetchall()}
    
    logger.info(f"Found {len(existing_skus)} existing SKUs that will be skipped")
    stats["existing"] = len(existing_skus)
    
    # Process rows in batches
    batch_size = 50
    batch_count = 0
    for i in range(0, len(df), batch_size):
        batch_count += 1
        batch = df.iloc[i:i+batch_size]
        logger.info(f"Processing batch {batch_count}/{(len(df)+batch_size-1)//batch_size}")
        
        # Process each row in the batch independently
        for _, row in batch.iterrows():
            # Create a new transaction for each row to isolate errors
            async with session.begin():
                try:
                    # Create SKU
                    item_id = str(row[id_column])
                    sku = f"{sku_prefix}{item_id}"
                    
                    # Skip if already exists
                    if sku in existing_skus:
                        stats["skipped"] += 1
                        logger.debug(f"Skipping existing SKU: {sku}")
                        continue
                    
                    # Extract product data - based on your CSV column names
                    brand = row.get('brand_name', '')
                    if pd.isna(brand):
                        brand = ''
                        
                    model = row.get('product_model_name', '')
                    if pd.isna(model):
                        model = ''
                    
                    # Map condition - V&R doesn't have condition in the CSV, so use a default
                    condition = ProductCondition.GOOD.value  # Default
                    
                    # Extract year (as int if possible)
                    year = None
                    if 'product_year' in row and row['product_year']:
                        try:
                            year = int(float(row['product_year']))
                        except (ValueError, TypeError):
                            pass
                    
                    # Extract price
                    price = 0.0
                    if 'product_price' in row and row['product_price']:
                        try:
                            price_str = str(row['product_price']).replace('$', '').replace('£', '').replace(',', '').strip()
                            price = float(price_str)
                        except (ValueError, TypeError):
                            pass
                    
                    # Extract description and handle NaN
                    description = row.get('product_description', '')
                    if pd.isna(description):
                        description = ''
                    
                    # Extract image and handle NaN
                    primary_image = row.get('image_url', '')
                    if pd.isna(primary_image):
                        primary_image = ''  # Convert NaN to empty string
                    
                    # Check if product is sold
                    is_sold = False
                    sold_str = str(row.get('product_sold', '')).lower()
                    if sold_str == 'yes':
                        is_sold = True
                        stats["sold_imported"] += 1
                        logger.debug(f"Item {sku} is marked as sold (value: '{row.get('product_sold')}')")
                    
                    # Create Product with correct field mappings - INCLUDE sold items
                    product = Product(
                        sku=sku,
                        brand=brand,
                        model=model,
                        year=year,
                        description=description,
                        condition=condition,
                        category=row.get('category_name', ''),
                        base_price=price,
                        primary_image=primary_image,
                        status=ProductStatus.SOLD if is_sold else ProductStatus.ACTIVE
                    )
                    
                    session.add(product)
                    await session.flush()  # This assigns an ID to the product
                    
                    # Create PlatformCommon
                    now_naive = datetime.now(timezone.utc).replace(tzinfo=None)  # Convert to naive datetime
                    
                    # Handle NaN values in all string fields
                    listing_url = row.get('external_link', '')
                    if pd.isna(listing_url) or listing_url == 'nan':
                        listing_url = ''  # Convert NaN to empty string
                    
                    platform_common = PlatformCommon(
                        product_id=product.id,
                        platform_name="vintageandrare",
                        external_id=item_id,
                        status=ListingStatus.SOLD if is_sold else ListingStatus.ACTIVE,
                        sync_status=SyncStatus.SUCCESS,
                        last_sync=now_naive,
                        listing_url=listing_url,
                        created_at=now_naive,
                        updated_at=now_naive
                    )
                    
                    session.add(platform_common)
                    await session.flush()  # This assigns an ID to platform_common
                    
                    # Create extended attributes dictionary
                    extended_attributes = {
                        "category": row.get('category_name', ''),
                        "finish": row.get('product_finish', ''),
                        "decade": row.get('decade'),
                        "year": year,
                        "brand": brand,
                        "model": model,
                        "is_sold": is_sold  # Record sold status in extended attributes
                    }
                    
                    # Sanitize the dictionary to remove NaN values
                    extended_attributes = sanitize_for_json(extended_attributes)
                    
                    # Create VRListing with all fields at once
                    vr_listing = VRListing(
                        platform_id=platform_common.id,
                        vr_listing_id=item_id,
                        
                        # Boolean fields
                        in_collective=row.get('product_in_collective', False) == 'yes',
                        in_inventory=row.get('product_in_inventory', True) == 'yes',
                        in_reseller=row.get('product_in_reseller', False) == 'yes',
                        show_vat=row.get('show_vat', True) == 'yes',
                        
                        # Numeric fields
                        collective_discount=float(row.get('collective_discount', 0)) if pd.notna(row.get('collective_discount')) else None,
                        price_notax=price,
                        inventory_quantity=1,
                        processing_time=None,
                        
                        # String fields
                        vr_state='sold' if is_sold else 'active',
                        
                        # Timestamp fields
                        created_at=now_naive,
                        updated_at=now_naive,
                        last_synced_at=now_naive,
                        
                        # JSON field
                        extended_attributes=extended_attributes
                    )
                    
                    session.add(vr_listing)
                    stats["created"] += 1
                    logger.info(f"Created VR listing for {sku}{' (SOLD)' if is_sold else ''}")

                except Exception as e:
                    # Log error but continue with next row
                    logger.error(f"Error creating records for VR listing {row.get(id_column, 'unknown')}: {str(e)}")
                    stats["errors"] += 1
                    # No need to rollback as the transaction is automatically rolled back on exception
    
    # Summary after all batches
    logger.info(f"Successfully processed {stats['created']} Vintage & Rare listings")
    logger.info(f"Imported {stats['sold_imported']} items that were marked as sold")
    return stats

if __name__ == "__main__":
    import_vr()