# scripts/fix_long_revision_id.py
"""
Fix the overly long revision ID in our Shopify migration.
"""

import re
import secrets
from pathlib import Path

def generate_short_revision_id():
    """Generate a proper short revision ID like Alembic normally does."""
    # Generate 12 random hex characters (like Alembic does)
    return secrets.token_hex(6)  # 6 bytes = 12 hex chars

def fix_revision_id():
    """Fix the long revision ID in our migration file."""
    
    print("🔧 FIXING LONG REVISION ID")
    print("=" * 40)
    
    # Find the migration file
    migration_file = Path("alembic/versions/20250603_173717_rename_website_to_shopify_add_categories.py")
    
    if not migration_file.exists():
        print(f"❌ Migration file not found: {migration_file}")
        return False
    
    # Generate new short revision ID
    new_revision_id = generate_short_revision_id()
    
    print(f"📄 Found migration file: {migration_file.name}")
    print(f"🆔 Old revision ID: rename_website_to_shopify_add_categories (41 chars)")
    print(f"🆔 New revision ID: {new_revision_id} (12 chars)")
    
    # Read the file content
    with open(migration_file, 'r') as f:
        content = f.read()
    
    # Replace the revision ID
    old_revision_pattern = r"revision = 'rename_website_to_shopify_add_categories'"
    new_revision_line = f"revision = '{new_revision_id}'"
    
    if old_revision_pattern in content:
        updated_content = content.replace(old_revision_pattern, new_revision_line)
        
        # Write back the updated content
        with open(migration_file, 'w') as f:
            f.write(updated_content)
        
        print(f"✅ Updated revision ID in migration file")
        
        # Rename the file to use the new revision ID
        new_filename = f"{new_revision_id}_rename_website_to_shopify_add_categories.py"
        new_file_path = migration_file.parent / new_filename
        
        migration_file.rename(new_file_path)
        print(f"✅ Renamed file to: {new_filename}")
        
        return new_revision_id
    else:
        print(f"❌ Could not find revision pattern in file")
        return False

def check_alembic_status():
    """Check Alembic status after fix."""
    print(f"\n🔍 CHECKING ALEMBIC STATUS")
    print("=" * 30)
    
    import subprocess
    
    try:
        # Check heads
        result = subprocess.run(['alembic', 'heads'], 
                              capture_output=True, text=True)
        
        if result.returncode == 0:
            print(f"📊 Current heads:")
            print(result.stdout.strip())
        else:
            print(f"❌ Error checking heads: {result.stderr}")
        
        # Check current revision
        result = subprocess.run(['alembic', 'current'], 
                              capture_output=True, text=True)
        
        if result.returncode == 0:
            print(f"\n📍 Current revision:")
            print(result.stdout.strip())
        else:
            print(f"❌ Error checking current: {result.stderr}")
            
    except Exception as e:
        print(f"❌ Error: {e}")

def main():
    """Fix the revision ID and check status."""
    
    # Fix the revision ID
    new_revision_id = fix_revision_id()
    
    if new_revision_id:
        print(f"\n🎉 REVISION ID FIXED!")
        print(f"🆔 New revision ID: {new_revision_id}")
        
        # Check status
        check_alembic_status()
        
        print(f"\n📝 Now you can run:")
        print(f"   alembic upgrade head")
        print(f"   (This should work without the string length error)")
        
    else:
        print(f"\n❌ Could not fix revision ID automatically")
        print(f"📝 Please manually edit the migration file:")
        print(f"   1. Change 'revision = ...' to a shorter ID (12 chars)")
        print(f"   2. Rename the file to match the new revision ID")

if __name__ == "__main__":
    main()