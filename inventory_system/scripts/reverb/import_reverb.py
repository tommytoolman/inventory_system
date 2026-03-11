"""
CLI script for Reverb import via ReverbImporter (presumably from app/services/). 
Includes options for handling sold listings and using cached data.
"""
import os, json
import asyncio
import logging
import click
from datetime import datetime, timezone
from sqlalchemy.sql import text

from app.database import async_session, engine
from app.services.reverb.importer import ReverbImporter

logger = logging.getLogger(__name__)

@click.command()
@click.option('--recreate-table', is_flag=True, help='Recreate the reverb_listings table before import')
@click.option('--import-sold', is_flag=True, help='Import sold listings from orders API')
@click.option('--sold-only', is_flag=True, help='Only import sold listings, skip active listings')
@click.option('--use-cache', is_flag=True, help='Use cached orders data if available')
@click.option('--save-cache-only', is_flag=True, help='Only download and save orders to cache without importing')
def import_reverb(recreate_table, import_sold, sold_only, use_cache, save_cache_only):
    """Import Reverb listings into database"""
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    start_time = datetime.now()
    logger.info(f"Starting Reverb import at {start_time}")
    
    try:
        asyncio.run(run_import(recreate_table, import_sold, sold_only, use_cache, save_cache_only))
        
        end_time = datetime.now()
        duration = end_time - start_time
        logger.info(f"Completed Reverb import in {duration}")
    except Exception as e:
        logger.exception("Error during Reverb import")
        click.echo(f"Error during import: {str(e)}")

async def run_import(recreate_table=False, import_sold=False, sold_only=False, use_cache=False, save_cache_only=False):
    """Run the Reverb import process."""
    # Check current state
    async with engine.connect() as conn:
        try:
            # Verify table exists
            result = await conn.execute(text("SELECT COUNT(*) FROM reverb_listings"))
            count = result.scalar()
            logger.info(f"Found {count} existing Reverb listings in database")
            
            # Handle recreation if requested
            if recreate_table:
                await conn.execute(text("TRUNCATE reverb_listings CASCADE"))
                logger.info("Cleared existing reverb_listings table")
        except Exception as e:
            logger.warning(f"Error checking reverb_listings table: {str(e)}")
            if recreate_table:
                logger.info("Tables will be created by SQLAlchemy models")
    
    # If we're just saving cache, handle it first
    if save_cache_only and import_sold:
        logger.info("Cache-only mode: Downloading orders and saving to cache file")
        
        # Create importer with temporary session just for API access
        async with async_session() as session:
            importer = ReverbImporter(session)
            
            try:
                # This will just download all orders
                # orders = await importer.client.get_all_sold_orders()
                orders = await importer.client.get_all_listings_detailed(max_concurrent=10, state="sold")
                
                # Save to cache file
                cache_dir = os.path.join("data", "reverb_orders")
                os.makedirs(cache_dir, exist_ok=True)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                cache_file = os.path.join(cache_dir, f"reverb_orders_{timestamp}.json")
                
                with open(cache_file, 'w') as f:
                    json.dump(orders, f)
                
                logger.info(f"Saved {len(orders)} orders to cache file: {cache_file}")
                return {"total": len(orders), "cached": True}
            except Exception as e:
                logger.error(f"Error saving orders to cache: {str(e)}")
                raise ImportError(f"Failed to save orders cache: {str(e)}")
    
    # Create a session but don't start a transaction here
    async with async_session() as session:
        try:
            # Run the import - let the importer manage its own transactions
            importer = ReverbImporter(session)
            
            all_stats = {
                "total": 0,
                "created": 0,
                "errors": 0,
                "skipped": 0,
                "sold_imported": 0
            }
            
            # Import active listings if not sold_only
            if not sold_only:
                
                # Before ... importing EVERYTHING
                # logger.info("Importing active Reverb listings")
                # active_stats = await importer.import_all_listings()

                # After (only live)
                logger.info("Importing LIVE Reverb listings only")
                active_stats = await importer.import_all_listings(include_all_states=False)
                
                # Merge stats
                for key in active_stats:
                    if key in all_stats:
                        all_stats[key] += active_stats[key]
            
            # Import sold listings if requested
            if import_sold:
                logger.info("Importing sold Reverb listings from orders API")
                
                # Pass the use_cache flag to the importer
                sold_stats = await importer.import_sold_listings(use_cache=use_cache)
                
                # Merge stats
                for key in sold_stats:
                    if key in all_stats:
                        all_stats[key] += sold_stats[key]
                
                # Copy special sold stats
                if "sold_imported" in sold_stats:
                    all_stats["sold_imported"] = sold_stats["sold_imported"]
                
                # Add cache info to stats
                if "cache_used" in sold_stats:
                    all_stats["cache_used"] = sold_stats["cache_used"]
            
            # Print summary
            click.echo("\nImport completed!")
            click.echo(f"Total listings processed: {all_stats['total']}")
            click.echo(f"Successfully created: {all_stats['created']}")
            click.echo(f"Errors: {all_stats['errors']}")
            click.echo(f"Skipped: {all_stats.get('skipped', 0)}")
            
            if "sold_imported" in all_stats:
                click.echo(f"Sold items imported: {all_stats['sold_imported']}")
            
            if "cache_used" in all_stats:
                click.echo(f"Cache used: {'Yes' if all_stats['cache_used'] else 'No'}")
            
            # Verify data was written
            async with engine.connect() as conn:
                result = await conn.execute(text("SELECT COUNT(*) FROM reverb_listings"))
                count = result.scalar()
                click.echo(f"Verified records in database: {count}")
                logger.info(f"Verified {count} records in database after import")
                
            return all_stats
        except Exception as e:
            logger.exception("Error during Reverb import process")
            raise

if __name__ == "__main__":
    import_reverb()