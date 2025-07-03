# scripts/verify_shopify_migration.py (MODIFIED FOR YOUR ASYNC DATABASE)
"""
Verify the Shopify migration worked and set up category processing.
Modified to work with your async database setup.
"""

import sys
import asyncio
from pathlib import Path
import subprocess

# Add workspace to path
sys.path.insert(0, str(Path(__file__).parent.parent))

async def check_database_changes():
    """Check that the database changes were applied correctly."""
    print("🔍 VERIFYING DATABASE CHANGES")
    print("=" * 40)
    
    try:
        from app.database import get_session
        from sqlalchemy import text
        
        async with get_session() as db:
            # Check if shopify_listings table exists
            result = await db.execute(text("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name IN ('shopify_listings', 'website_listings')
            """))
            
            tables = [row[0] for row in result.fetchall()]
            
            if 'shopify_listings' in tables:
                print("✅ Table 'shopify_listings' exists")
            else:
                print("❌ Table 'shopify_listings' not found")
                
            if 'website_listings' in tables:
                print("⚠️ Table 'website_listings' still exists (should be renamed)")
            else:
                print("✅ Table 'website_listings' no longer exists (correctly renamed)")
            
            # Check columns in shopify_listings
            if 'shopify_listings' in tables:
                result = await db.execute(text("""
                    SELECT column_name, data_type 
                    FROM information_schema.columns 
                    WHERE table_name = 'shopify_listings'
                    ORDER BY column_name
                """))
                
                columns = {row[0]: row[1] for row in result.fetchall()}
                
                print(f"\n📊 Columns in shopify_listings:")
                required_columns = [
                    'shopify_product_id', 'handle', 'title', 'status',
                    'category_gid', 'category_name', 'category_full_name',
                    'category_assigned_at', 'category_assignment_status'
                ]
                
                missing_columns = []
                for col in required_columns:
                    if col in columns:
                        print(f"   ✅ {col} ({columns[col]})")
                    else:
                        print(f"   ❌ {col} (missing)")
                        missing_columns.append(col)
                
                if missing_columns:
                    print(f"\n⚠️ Missing columns: {missing_columns}")
                    return False
                else:
                    print(f"\n✅ All required columns present")
            
            return 'shopify_listings' in tables
        
    except Exception as e:
        print(f"❌ Error checking database: {e}")
        return False

def check_model_compatibility():
    """Check if the updated model is compatible."""
    print(f"\n🔍 CHECKING MODEL COMPATIBILITY")
    print("=" * 40)
    
    try:
        from app.models.shopify import ShopifyListing
        
        # Try to create a model instance (without saving)
        listing = ShopifyListing()
        
        # Check if new fields are accessible
        new_fields = [
            'shopify_product_id', 'handle', 'title', 'status',
            'category_gid', 'category_name', 'category_full_name',
            'category_assigned_at', 'category_assignment_status'
        ]
        
        missing_fields = []
        for field in new_fields:
            if not hasattr(listing, field):
                missing_fields.append(field)
        
        if missing_fields:
            print(f"❌ Model missing fields: {missing_fields}")
            print(f"📝 You need to update app/models/shopify.py with the new fields")
            return False
        else:
            print(f"✅ Model has all required fields")
            return True
            
    except Exception as e:
        print(f"❌ Error checking model: {e}")
        print(f"📝 You may need to update app/models/shopify.py")
        return False

def check_alembic_status():
    """Check final Alembic status."""
    print(f"\n🔍 CHECKING ALEMBIC STATUS")
    print("=" * 30)
    
    try:
        # Check current revision
        result = subprocess.run(['alembic', 'current'], 
                              capture_output=True, text=True)
        
        if result.returncode == 0:
            current_revision = result.stdout.strip()
            print(f"📍 Current revision: {current_revision}")
            
            if 'cb02bcbc3fdb' in current_revision:
                print(f"✅ Successfully at the latest revision")
                return True
            else:
                print(f"⚠️ Unexpected revision")
                return False
        else:
            print(f"❌ Error checking revision: {result.stderr}")
            return False
            
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

def create_category_processor():
    """Create the category processing script that works with your async database."""
    print(f"\n🔧 CREATING CATEGORY PROCESSOR")
    print("=" * 35)
    
    processor_script = '''# scripts/process_shopify_categories.py
"""
Process your Excel file and assign Shopify categories.
Works with your async database setup.
"""

import sys
import json
import pandas as pd
import asyncio
from pathlib import Path
from datetime import datetime

# Add workspace to path
sys.path.insert(0, str(Path(__file__).parent.parent))

class ShopifyCategoryProcessor:
    """Process categories for Shopify listings using async database."""
    
    def __init__(self):
        # Import here to avoid circular imports
        from app.services.shopify.client import ShopifyGraphQLClient
        self.client = ShopifyGraphQLClient()
        self.category_mapping = self._load_category_mapping()
        
    def _load_category_mapping(self):
        """Load the category mapping we built."""
        mapping_file = Path(__file__).parent.parent / "data" / "csv_category_to_gid_mapping.json"
        
        if mapping_file.exists():
            with open(mapping_file, 'r') as f:
                return json.load(f)
        return {}
    
    def find_category_gid(self, category_string):
        """Find category GID for a category string."""
        if not category_string or not category_string.strip():
            return None
        
        category_string = category_string.strip()
        
        # Direct mapping lookup
        if category_string in self.category_mapping:
            return self.category_mapping[category_string]
        
        # Case-insensitive lookup
        for mapped_cat, gid in self.category_mapping.items():
            if mapped_cat.lower() == category_string.lower():
                return gid
        
        # Keyword matching
        category_lower = category_string.lower()
        keyword_mappings = {
            'electric guitar': "gid://shopify/TaxonomyCategory/ae-2-8-7-2-4",
            'acoustic guitar': "gid://shopify/TaxonomyCategory/ae-2-8-7-2-1",
            'bass guitar': "gid://shopify/TaxonomyCategory/ae-2-8-7-2-2",
            'classical guitar': "gid://shopify/TaxonomyCategory/ae-2-8-7-2-3",
            'guitar amplifier': "gid://shopify/TaxonomyCategory/ae-2-7-10-3",
            'bass amplifier': "gid://shopify/TaxonomyCategory/ae-2-7-10-2",
            'mandolin': "gid://shopify/TaxonomyCategory/ae-2-8-7-8-1"
        }
        
        for keyword, gid in keyword_mappings.items():
            if keyword in category_lower:
                return gid
        
        return None
    
    async def assign_category(self, handle, category_string):
        """Assign category to a Shopify listing."""
        from app.models.shopify import ShopifyListing
        from app.database import get_session
        from sqlalchemy import select
        
        # Find category GID
        category_gid = self.find_category_gid(category_string)
        if not category_gid:
            print(f"❌ No category GID for: '{category_string}'")
            return False
        
        async with get_session() as db:
            # Find ShopifyListing by handle
            result = await db.execute(
                select(ShopifyListing).where(ShopifyListing.handle == handle)
            )
            listing = result.scalar_one_or_none()
            
            if not listing:
                print(f"❌ No ShopifyListing found for handle: {handle}")
                return False
            
            # Check if we have a shopify_product_id
            if not listing.shopify_product_id:
                print(f"❌ No shopify_product_id for handle: {handle}")
                return False
            
            # Update category in Shopify
            try:
                success = self.client.set_product_category(
                    listing.shopify_product_id,
                    category_gid
                )
                
                if success:
                    # Update local record
                    listing.category_gid = category_gid
                    listing.category_name = self._extract_category_name(category_string)
                    listing.category_full_name = category_string
                    listing.category_assigned_at = datetime.utcnow()
                    listing.category_assignment_status = 'ASSIGNED'
                    
                    await db.commit()
                    print(f"✅ Assigned {handle}: {listing.category_name}")
                    return True
                else:
                    listing.category_assignment_status = 'FAILED'
                    await db.commit()
                    print(f"❌ Failed to assign {handle}")
                    return False
                    
            except Exception as e:
                listing.category_assignment_status = 'FAILED'
                await db.commit()
                print(f"❌ Error assigning {handle}: {e}")
                return False
    
    def _extract_category_name(self, category_string):
        """Extract final category name from full path."""
        if '>' in category_string:
            return category_string.split('>')[-1].strip()
        return category_string
    
    async def get_stats(self):
        """Get current statistics."""
        from app.models.shopify import ShopifyListing
        from app.database import get_session
        from sqlalchemy import select, func
        
        async with get_session() as db:
            # Total listings
            total_result = await db.execute(
                select(func.count()).select_from(ShopifyListing)
            )
            total = total_result.scalar()
            
            # Assigned
            assigned_result = await db.execute(
                select(func.count()).select_from(ShopifyListing).where(
                    ShopifyListing.category_assignment_status == 'ASSIGNED'
                )
            )
            assigned = assigned_result.scalar()
            
            # Failed
            failed_result = await db.execute(
                select(func.count()).select_from(ShopifyListing).where(
                    ShopifyListing.category_assignment_status == 'FAILED'
                )
            )
            failed = failed_result.scalar()
            
            return {
                'total_listings': total,
                'assigned': assigned,
                'failed': failed,
                'unprocessed': total - assigned - failed,
                'percentage': (assigned / total * 100) if total > 0 else 0
            }
    
    async def process_excel_file(self, excel_file):
        """Process Excel file and assign categories."""
        print(f"📊 Processing: {excel_file}")
        
        if not Path(excel_file).exists():
            print(f"❌ File not found: {excel_file}")
            return
        
        try:
            df = pd.read_excel(excel_file)
        except:
            try:
                df = pd.read_csv(excel_file)
            except Exception as e:
                print(f"❌ Could not read file: {e}")
                return
        
        if 'Handle' not in df.columns or 'Product Category' not in df.columns:
            print(f"❌ Required columns missing: Handle, Product Category")
            print(f"Available columns: {list(df.columns)}")
            return
        
        # Show current stats
        print(f"\\n📊 CURRENT STATS:")
        stats = await self.get_stats()
        for key, value in stats.items():
            print(f"   {key}: {value}")
        
        results = {'successful': 0, 'failed': 0, 'skipped': 0}
        total = len(df)
        
        print(f"\\n🔄 Processing {total} products...")
        
        for index, row in df.iterrows():
            handle = str(row.get('Handle', '')).strip()
            category = str(row.get('Product Category', '')).strip()
            
            print(f"\\n📦 Processing ({index + 1}/{total}): {handle}")
            
            if not handle or not category or category.lower() in ['nan', 'none', '']:
                print(f"   ⏭️ Skipping - missing data")
                results['skipped'] += 1
                continue
            
            success = await self.assign_category(handle, category)
            
            if success:
                results['successful'] += 1
            else:
                results['failed'] += 1
            
            # Rate limiting
            await asyncio.sleep(0.3)
        
        print(f"\\n📊 PROCESSING COMPLETE:")
        print(f"   Successful: {results['successful']}")
        print(f"   Failed: {results['failed']}")
        print(f"   Skipped: {results['skipped']}")
        
        # Show updated stats
        print(f"\\n📊 UPDATED STATS:")
        stats = await self.get_stats()
        for key, value in stats.items():
            print(f"   {key}: {value}")
        
        return results

async def main():
    """Main processing function."""
    
    # Your Excel file
    excel_file = "scripts/data/shopify_import_from_vr_new_cats.xlsx"
    
    try:
        # Process categories
        processor = ShopifyCategoryProcessor()
        await processor.process_excel_file(excel_file)
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
'''
    
    script_file = Path("scripts/process_shopify_categories.py")
    with open(script_file, 'w') as f:
        f.write(processor_script)
    
    print(f"✅ Created: {script_file}")
    return script_file

async def main():
    """Verify migration and set up category processing."""
    
    print("🎉 SHOPIFY MIGRATION VERIFICATION")
    print("=" * 50)
    
    # Check database changes
    db_ok = await check_database_changes()
    
    # Check model compatibility
    model_ok = check_model_compatibility()
    
    # Check Alembic status
    alembic_ok = check_alembic_status()
    
    if db_ok and model_ok and alembic_ok:
        print(f"\n🎉 MIGRATION SUCCESSFUL!")
        
        # Create category processor
        script_file = create_category_processor()
        
        print(f"\n📝 NEXT STEPS:")
        print(f"1. Run: python {script_file}")
        print(f"2. This will process your Excel file and assign categories")
        
    else:
        print(f"\n⚠️ SOME ISSUES DETECTED")
        if not db_ok:
            print(f"   - Database verification failed")
        if not model_ok:
            print(f"   - Model compatibility issues")
        if not alembic_ok:
            print(f"   - Alembic status issues")
        
        if model_ok and alembic_ok:
            # Create processor anyway since migration seems to have worked
            script_file = create_category_processor()
            print(f"\n📝 You can still try:")
            print(f"   python {script_file}")

if __name__ == "__main__":
    asyncio.run(main())