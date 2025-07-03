# scripts/import_reverb.py
import asyncio
import logging
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.services.reverb.importer import ReverbImporter

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

async def import_reverb_listings():
    """Import all listings from Reverb"""
    async with get_session() as session:
        try:
            importer = ReverbImporter(session)
            stats = await importer.import_all_listings()
            
            print("\nImport Summary:")
            print(f"Total listings processed: {stats['total']}")
            print(f"Successfully created: {stats['created']}")
            print(f"Errors: {stats['errors']}")
            
        except Exception as e:
            print(f"Error during import: {str(e)}")

if __name__ == "__main__":
    asyncio.run(import_reverb_listings())