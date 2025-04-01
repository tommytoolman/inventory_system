# app/cli/create_tables.py
import asyncio
import click
from sqlalchemy.ext.asyncio import create_async_engine
from app.database import Base

# Import all your models to ensure they're registered with the Base
from app.models.product import Product
from app.models.platform_common import PlatformCommon
from app.models.ebay import EbayListing
from app.models.reverb import ReverbListing
from app.models.vr import VRListing
# Import any other models that need to be created

@click.command()
def create_tables():
    """Create all database tables directly using SQLAlchemy"""
    from app.core.config import get_settings
    settings = get_settings()
    
    async def _create_tables():
        engine = create_async_engine(settings.DATABASE_URL, echo=True)
        async with engine.begin() as conn:
            # This will create all tables defined in models that inherit from Base
            await conn.run_sync(Base.metadata.create_all)
        print("All tables created successfully!")
        
    asyncio.run(_create_tables())

if __name__ == "__main__":
    create_tables()