# app/cli/import_ebay.py
import asyncio
import logging
import click
from datetime import datetime

from app.services.ebay.importer import EbayImporter

logger = logging.getLogger(__name__)

@click.command()
@click.option('--recreate-table', is_flag=True, help='Recreate the ebay_listings table before import')
def import_ebay(recreate_table):
    """Import eBay listings into database"""
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    start_time = datetime.now()
    logger.info(f"Starting eBay import at {start_time}")
    
    try:
        asyncio.run(run_import(recreate_table))
        
        end_time = datetime.now()
        duration = end_time - start_time
        logger.info(f"Completed eBay import in {duration}")
    except Exception as e:
        logger.exception("Error during eBay import")
        click.echo(f"Error during import: {str(e)}")

async def run_import(recreate_table=False):
    """Run the eBay import process using direct database connection."""
    # Create importer
    importer = EbayImporter()
    
    # Recreate table if requested
    if recreate_table:
        logger.info("Recreating ebay_listings table...")
        success = await importer.recreate_ebay_listings_table()
        if not success:
            logger.error("Failed to recreate ebay_listings table, aborting")
            return
        logger.info("Successfully recreated ebay_listings table")
    
    # Run import
    stats = await importer.import_all_listings()
    
    # Verify data was written
    count = await importer.verify_data_written()
    logger.info(f"Verified {count} records in database after import")
    
    # Display results
    click.echo(f"\nImport completed!")
    click.echo(f"Total listings: {stats['total']}")
    click.echo(f"Created: {stats['created']}")
    click.echo(f"Updated: {stats['updated']}")
    click.echo(f"Errors: {stats['errors']}")
    click.echo(f"Verified records in database: {count}")
    
    return stats

if __name__ == "__main__":
    import_ebay()