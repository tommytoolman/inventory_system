# scripts/create_initial_mappings.py
import asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_session, async_session
from app.models.category_mapping import CategoryMapping

async def create_initial_mappings():
    """Create initial category mappings for the demo"""
    async with async_session() as session:
        # Default mapping (fallback)
        default_mapping = CategoryMapping(
            source_platform="default",
            source_id="default",
            source_name="Default Category",
            target_platform="vr",
            target_id="51",  # Electric Guitars
            target_subcategory_id="63"  # Solid Body
        )
        session.add(default_mapping)
        
        # Add specific mappings for demo
        # Electric Guitars
        mapping1 = CategoryMapping(
            source_platform="internal",
            source_id="electric_guitars",
            source_name="Electric Guitars",
            target_platform="vr",
            target_id="51",  # Electric Guitars
            target_subcategory_id="63"  # Solid Body
        )
        session.add(mapping1)
        
        mapping2 = CategoryMapping(
            source_platform="internal",
            source_id="electric_guitars_solid_body",
            source_name="Electric Guitars / Solid Body",
            target_platform="vr",
            target_id="51",  # Electric Guitars
            target_subcategory_id="63"  # Solid Body
        )
        session.add(mapping2)
        
        # Acoustic Guitars
        mapping3 = CategoryMapping(
            source_platform="internal",
            source_id="acoustic_guitars",
            source_name="Acoustic Guitars",
            target_platform="vr",
            target_id="51",  # Guitars
            target_subcategory_id="82"  # Acoustic
        )
        session.add(mapping3)
        
        # Bass Guitars
        mapping4 = CategoryMapping(
            source_platform="internal",
            source_id="bass_guitars",
            source_name="Bass Guitars",
            target_platform="vr",
            target_id="52",  # Bass
            target_subcategory_id="83"  # Electric Bass
        )
        session.add(mapping4)
        
        # Add at least one mapping from Reverb
        mapping5 = CategoryMapping(
            source_platform="reverb",
            source_id="dfd39027-d134-4353-b9e4-57dc6be791b9",
            source_name="Electric Guitars",
            target_platform="vr",
            target_id="51",
            target_subcategory_id="63"
        )
        session.add(mapping5)
        
        # Add more mappings as needed
        
        await session.commit()
        print("Initial mappings created successfully")

if __name__ == "__main__":
    asyncio.run(create_initial_mappings())