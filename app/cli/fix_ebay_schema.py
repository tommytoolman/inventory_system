"""
A specialized script likely created during development to address schema inconsistencies specifically for eBay listings. 
It can add the platform_id column and attempts to backfill platform_common records and link them. 
Potential Cleanup: This script might be obsolete given database schema is now managed consistently via Alembic migrations. 
You might be able to remove it, assuming the migrations handle the current schema state correctly.
"""

import asyncio
import logging
import click
from sqlalchemy import text
from app.database import async_session

logger = logging.getLogger(__name__)

@click.command()
@click.option('--add-column', is_flag=True, help='Add platform_id column to ebay_listings')
@click.option('--create-platform-records', is_flag=True, help='Create platform_common records for existing eBay listings')
@click.option('--link-listings', is_flag=True, help='Link eBay listings to platform_common records')
def fix_ebay_schema(add_column, create_platform_records, link_listings):
    """Fix the eBay schema to match Reverb and V&R structure"""
    logging.basicConfig(level=logging.INFO)
    
    if not any([add_column, create_platform_records, link_listings]):
        click.echo("Please specify at least one operation to perform")
        return
    
    asyncio.run(run_fixes(add_column, create_platform_records, link_listings))

async def run_fixes(add_column, create_platform_records, link_listings):
    """Run the requested database fixes"""
    async with async_session() as session:
        # Add platform_id column if requested
        if add_column:
            try:
                # Check if column already exists
                result = await session.execute(text("""
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_name = 'ebay_listings' AND column_name = 'platform_id'
                """))
                if result.fetchone():
                    logger.info("platform_id column already exists in ebay_listings")
                else:
                    # Add the column
                    await session.execute(text("""
                        ALTER TABLE ebay_listings 
                        ADD COLUMN platform_id INTEGER REFERENCES platform_common(id)
                    """))
                    await session.commit()
                    logger.info("Added platform_id column to ebay_listings table")
            except Exception as e:
                logger.error(f"Error adding platform_id column: {str(e)}")
                return
        
        # Create platform_common records if requested
        if create_platform_records:
            try:
                # Get all eBay listings that don't have platform_common records
                result = await session.execute(text("""
                    SELECT id, ebay_item_id, title 
                    FROM ebay_listings
                    WHERE platform_id IS NULL
                """))
                ebay_listings = result.fetchall()
                
                if not ebay_listings:
                    logger.info("No eBay listings found without platform_common records")
                    return
                
                logger.info(f"Creating platform_common records for {len(ebay_listings)} eBay listings")
                
                # Process in batches
                batch_size = 50
                created_count = 0
                
                for i in range(0, len(ebay_listings), batch_size):
                    batch = ebay_listings[i:i+batch_size]
                    logger.info(f"Processing batch {i//batch_size + 1}/{(len(ebay_listings)+batch_size-1)//batch_size}")
                    
                    for listing in batch:
                        # First create a product record
                        product_result = await session.execute(text("""
                            INSERT INTO products 
                            (sku, brand, model, condition, status, created_at, updated_at)
                            VALUES 
                            (:sku, 'Unknown', :title, 'GOOD', 'ACTIVE', NOW(), NOW())
                            RETURNING id
                        """), {
                            "sku": f"EB-{listing.ebay_item_id}",
                            "title": listing.title
                        })
                        product_id = product_result.scalar()
                        
                        # Create platform_common record
                        platform_result = await session.execute(text("""
                            INSERT INTO platform_common
                            (product_id, platform_name, external_id, status, sync_status, created_at, updated_at)
                            VALUES
                            (:product_id, 'ebay', :external_id, 'ACTIVE', 'SUCCESS', NOW(), NOW())
                            RETURNING id
                        """), {
                            "product_id": product_id,
                            "external_id": listing.ebay_item_id
                        })
                        platform_id = platform_result.scalar()
                        
                        # Update the eBay listing with the platform_id
                        await session.execute(text("""
                            UPDATE ebay_listings
                            SET platform_id = :platform_id
                            WHERE id = :listing_id
                        """), {
                            "platform_id": platform_id,
                            "listing_id": listing.id
                        })
                        
                        created_count += 1
                    
                    # Commit after each batch
                    await session.commit()
                
                logger.info(f"Created {created_count} platform_common records and linked them to eBay listings")
                
            except Exception as e:
                logger.error(f"Error creating platform_common records: {str(e)}")
                await session.rollback()
        
        # Link existing listings if requested
        if link_listings and not create_platform_records:
            try:
                # Check if there are any unlinked listings
                result = await session.execute(text("""
                    SELECT COUNT(*) 
                    FROM ebay_listings
                    WHERE platform_id IS NULL
                """))
                unlinked_count = result.scalar()
                
                if unlinked_count == 0:
                    logger.info("No unlinked eBay listings found")
                    return
                
                logger.info(f"Found {unlinked_count} unlinked eBay listings")
                
                # Check if there are matching platform_common records
                result = await session.execute(text("""
                    SELECT COUNT(*) 
                    FROM platform_common pc
                    JOIN ebay_listings e ON pc.external_id = e.ebay_item_id
                    WHERE e.platform_id IS NULL AND pc.platform_name = 'ebay'
                """))
                matching_count = result.scalar()
                
                if matching_count > 0:
                    # Link matching records
                    await session.execute(text("""
                        UPDATE ebay_listings e
                        SET platform_id = pc.id
                        FROM platform_common pc
                        WHERE pc.external_id = e.ebay_item_id 
                        AND e.platform_id IS NULL 
                        AND pc.platform_name = 'ebay'
                    """))
                    await session.commit()
                    logger.info(f"Linked {matching_count} eBay listings to existing platform_common records")
                else:
                    logger.info("No matching platform_common records found")
            except Exception as e:
                logger.error(f"Error linking listings: {str(e)}")
                await session.rollback()

if __name__ == "__main__":
    fix_ebay_schema()