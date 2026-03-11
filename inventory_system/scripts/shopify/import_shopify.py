"""
CLI script for Shopify import via ShopifyImporter.
Imports all product statuses (ACTIVE, DRAFT, ARCHIVED) from Shopify API.
"""
import asyncio
import logging
import click
from datetime import datetime, timezone
from sqlalchemy.sql import text

from app.database import async_session, engine
from app.services.shopify.importer import ShopifyImporter

logger = logging.getLogger(__name__)

@click.command()
@click.option('--recreate-table', is_flag=True, help='Recreate the shopify_listings table before import')
@click.option('--status-filter', type=str, help='Filter by status: ACTIVE, DRAFT, ARCHIVED, or ALL (default: ALL)')
@click.option('--limit', type=int, help='Limit number of products to import (for testing)')
def import_shopify(recreate_table, status_filter, limit):
    """Import Shopify listings into database"""
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    start_time = datetime.now()
    logger.info(f"Starting Shopify import at {start_time}")
    
    try:
        asyncio.run(run_import(recreate_table, status_filter, limit))
        
        end_time = datetime.now()
        duration = end_time - start_time
        logger.info(f"Completed Shopify import in {duration}")
    except Exception as e:
        logger.exception("Error during Shopify import")
        click.echo(f"Error during import: {str(e)}")

async def run_import(recreate_table=False, status_filter=None, limit=None):
    """Run the Shopify import process."""
    # Check current state
    async with engine.connect() as conn:
        try:
            # Verify table exists
            result = await conn.execute(text("SELECT COUNT(*) FROM shopify_listings"))
            count = result.scalar()
            logger.info(f"Found {count} existing Shopify listings in database")
            
            # Handle recreation if requested
            if recreate_table:
                await conn.execute(text("TRUNCATE shopify_listings CASCADE"))
                await conn.execute(text("TRUNCATE platform_common CASCADE"))
                await conn.execute(text("TRUNCATE products CASCADE"))
                logger.info("Cleared existing shopify_listings, platform_common, and products tables")
        except Exception as e:
            logger.warning(f"Error checking shopify_listings table: {str(e)}")
            if recreate_table:
                logger.info("Tables will be created by SQLAlchemy models")
    
    # Create a session for the import
    async with async_session() as session:
        try:
            # Run the import - let the importer manage its own transactions
            importer = ShopifyImporter(session)
            
            # Set import options
            import_options = {}
            if status_filter and status_filter.upper() != 'ALL':
                import_options['status_filter'] = status_filter.upper()
            if limit:
                import_options['limit'] = limit
            
            logger.info(f"Importing Shopify listings with options: {import_options}")
            
            # Import all listings
            stats = await importer.import_all_listings(**import_options)
            
            # Print summary
            click.echo("\nImport completed!")
            click.echo(f"Total listings processed: {stats.get('total', 0)}")
            click.echo(f"Successfully created: {stats.get('created', 0)}")
            click.echo(f"Errors: {stats.get('errors', 0)}")
            click.echo(f"Skipped: {stats.get('skipped', 0)}")
            
            # Status breakdown
            status_counts = stats.get('status_counts', {})
            if status_counts:
                click.echo("\nStatus breakdown:")
                for status, count in status_counts.items():
                    click.echo(f"  {status}: {count}")
            
            # Verify data was written
            async with engine.connect() as conn:
                # Verify shopify_listings
                result = await conn.execute(text("SELECT COUNT(*) FROM shopify_listings"))
                shopify_count = result.scalar()
                
                # Verify platform_common
                result = await conn.execute(text("SELECT COUNT(*) FROM platform_common WHERE platform_name = 'shopify'"))
                platform_count = result.scalar()
                
                # Verify products
                result = await conn.execute(text("SELECT COUNT(*) FROM products"))
                products_count = result.scalar()
                
                click.echo(f"\nVerified records in database:")
                click.echo(f"  shopify_listings: {shopify_count}")
                click.echo(f"  platform_common (shopify): {platform_count}")
                click.echo(f"  products: {products_count}")
                click.echo(f"  SKU matches (reused existing): {stats.get('sku_matched', 0)}")
                
                logger.info(f"Verified {shopify_count} shopify_listings, {platform_count} platform_common, {products_count} products after import")
                
            return stats
        except Exception as e:
            logger.exception("Error during Shopify import process")
            raise

if __name__ == "__main__":
    import_shopify()