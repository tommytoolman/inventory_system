# app/cli/import_reverb.py
import asyncio
import logging
import click
from datetime import datetime
from sqlalchemy.sql import text

from app.database import async_session, engine
from app.services.reverb.importer import ReverbImporter

logger = logging.getLogger(__name__)

@click.command()
@click.option('--recreate-table', is_flag=True, help='Recreate the reverb_listings table before import')
def import_reverb(recreate_table):
    """Import Reverb listings into database"""
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    start_time = datetime.now()
    logger.info(f"Starting Reverb import at {start_time}")
    
    try:
        asyncio.run(run_import(recreate_table))
        
        end_time = datetime.now()
        duration = end_time - start_time
        logger.info(f"Completed Reverb import in {duration}")
    except Exception as e:
        logger.exception("Error during Reverb import")
        click.echo(f"Error during import: {str(e)}")

async def run_import(recreate_table=False):
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
    
    # Create a session but don't start a transaction here
    async with async_session() as session:
        try:
            # Run the import - let the importer manage its own transactions
            importer = ReverbImporter(session)
            stats = await importer.import_all_listings()
            
            # Print summary
            click.echo("\nImport completed!")
            click.echo(f"Total listings: {stats['total']}")
            click.echo(f"Created: {stats['created']}")
            click.echo(f"Errors: {stats['errors']}")
            click.echo(f"Skipped: {stats.get('skipped', 0)}")
            
            # Verify data was written
            async with engine.connect() as conn:
                result = await conn.execute(text("SELECT COUNT(*) FROM reverb_listings"))
                count = result.scalar()
                click.echo(f"Verified records in database: {count}")
                logger.info(f"Verified {count} records in database after import")
                
            return stats
        except Exception as e:
            logger.exception("Error during Reverb import process")
            raise

if __name__ == "__main__":
    import_reverb()