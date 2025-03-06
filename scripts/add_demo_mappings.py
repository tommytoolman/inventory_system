# scripts/add_demo_mappings.py
import asyncio
import sys
import os

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

load_dotenv()

# Add the parent directory to the path so we can import from app
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import async_session
from app.models.category_mapping import CategoryMapping

# Create a direct database connection without loading app settings
DATABASE_URL = os.environ.get("DATABASE_URL")

engine = create_async_engine(DATABASE_URL)
async_session = async_sessionmaker(engine, expire_on_commit=False)

async def add_demo_mappings():
    """Add specific category mappings for the demo"""
    async with async_session() as session:
        # 1. Reverb → Vintage & Rare mapping
        mapping_reverb_to_vr = CategoryMapping(
            source_platform="reverb",
            source_id="e57deb7a-382b-4e18-a008-67d4fbcb2879",
            source_name="Electric Guitars / Solid Body",
            target_platform="vr",
            target_id="51",
            target_subcategory_id="83"
        )
        session.add(mapping_reverb_to_vr)

        # 2. Reverb → eBay mapping
        mapping_reverb_to_ebay = CategoryMapping(
            source_platform="reverb",
            source_id="e57deb7a-382b-4e18-a008-67d4fbcb2879",
            source_name="Electric Guitars / Solid Body",
            target_platform="ebay",
            target_id="619",
            target_subcategory_id="3858",
            target_tertiary_id="33034"
        )
        session.add(mapping_reverb_to_ebay)

        # 3. eBay → Vintage & Rare mapping
        mapping_ebay_to_vr = CategoryMapping(
            source_platform="ebay",
            source_id="33034",
            source_name="Musical Instruments & Gear / Guitars & Basses / Electric Guitars",
            target_platform="vr",
            target_id="51",
            target_subcategory_id="83"
        )
        session.add(mapping_ebay_to_vr)

        # 4. Internal → Vintage & Rare mapping
        mapping_internal_to_vr = CategoryMapping(
            source_platform="internal",
            source_id="electric_guitars_solid_body",
            source_name="Electric Guitars / Solid Body",
            target_platform="vr",
            target_id="51",
            target_subcategory_id="83"
        )
        session.add(mapping_internal_to_vr)

        # 5. Internal → Reverb mapping
        mapping_internal_to_reverb = CategoryMapping(
            source_platform="internal",
            source_id="electric_guitars_solid_body",
            source_name="Electric Guitars / Solid Body",
            target_platform="reverb",
            target_id="dfd39027-d134-4353-b9e4-57dc6be791b9",
            target_subcategory_id="e57deb7a-382b-4e18-a008-67d4fbcb2879"
        )
        session.add(mapping_internal_to_reverb)

        # 6. Internal → eBay mapping
        mapping_internal_to_ebay = CategoryMapping(
            source_platform="internal",
            source_id="electric_guitars_solid_body",
            source_name="Electric Guitars / Solid Body",
            target_platform="ebay",
            target_id="619",
            target_subcategory_id="3858",
            target_tertiary_id="33034"
        )
        session.add(mapping_internal_to_ebay)

        # Add a default mapping as fallback
        default_mapping = CategoryMapping(
            source_platform="default",
            source_id="default",
            source_name="Default Category",
            target_platform="vr",
            target_id="51",
            target_subcategory_id="63"
        )
        session.add(default_mapping)

        try:
            await session.commit()
            print("Demo mappings added successfully!")
        except Exception as e:
            await session.rollback()
            print(f"Error adding mappings: {str(e)}")

if __name__ == "__main__":
    # Make sure to replace the DATABASE_URL with your actual database URL before running
    print(f"Using database URL: {DATABASE_URL}")
    answer = input("Is this correct? (y/n): ")
    if answer.lower() == 'y':
        asyncio.run(add_demo_mappings())
    else:
        print("Please update the DATABASE_URL in the script and try again.")