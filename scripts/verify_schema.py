# scripts/verify_schema.py
import asyncio
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine
from app.core.config import get_settings
from app.models.reverb import ReverbListing

async def verify_schema():
    """Verify that database schema matches model definitions"""
    settings = get_settings()
    engine = create_async_engine(settings.DATABASE_URL)
    
    async with engine.connect() as conn:
        # Get database table info
        inspector = inspect(conn)
        db_columns = {col["name"]: col for col in inspector.get_columns("reverb_listings")}
        
        # Get model info from declarative class
        model_columns = ReverbListing.__table__.columns
        
        print("Database columns:")
        for name, col in db_columns.items():
            print(f"  - {name}: {col['type']}")
        
        print("\nModel columns:")
        for name, col in model_columns.items():
            print(f"  - {name}: {col.type}")
        
        print("\nMissing in database:")
        for name, col in model_columns.items():
            if name not in db_columns:
                print(f"  - {name}: {col.type}")
        
        print("\nMissing in model:")
        for name, col in db_columns.items():
            if name not in model_columns:
                print(f"  - {name}: {col['type']}")
        
        print("\nType mismatches:")
        for name, model_col in model_columns.items():
            if name in db_columns:
                db_type = str(db_columns[name]["type"])
                model_type = str(model_col.type)
                if db_type != model_type:
                    print(f"  - {name}: DB={db_type}, Model={model_type}")

if __name__ == "__main__":
    asyncio.run(verify_schema())