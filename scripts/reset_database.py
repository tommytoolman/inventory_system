# scripts/reset_database.py
import asyncio
from sqlalchemy import delete
from app.database import get_session
from app.models.reverb import ReverbListing
from app.models.platform_common import PlatformCommon
from app.models.product import Product

async def reset_database():
    """ Clear products, platform_common, and reverb_listings tables.
        Since we need to respect foreign key constraints, we'll delete in reverse order of dependencies.
    """
    
    async with get_session() as session:
        try:
            print("Clearing database tables...")
            
            # Delete in order of dependencies (children first)
            print("Deleting reverb_listings...")
            await session.execute(delete(ReverbListing))
            
            print("Deleting platform_common...")
            await session.execute(delete(PlatformCommon))
            
            print("Deleting products...")
            await session.execute(delete(Product))
            
            await session.commit()
            print("Database reset complete.")
        except Exception as e:
            await session.rollback()
            print(f"Error resetting database: {str(e)}")

if __name__ == "__main__":
    asyncio.run(reset_database())