# scripts/fix_migration_down_revision.py
"""
Fix the down_revision in our Shopify migration to point to the correct parent.
"""

import re
from pathlib import Path

def fix_shopify_migration():
    """Fix the down_revision in our Shopify migration."""
    
    print("🔧 FIXING SHOPIFY MIGRATION DOWN_REVISION")
    print("=" * 50)
    
    # Find our migration file
    migration_file = Path("alembic/versions/20250603_173717_rename_website_to_shopify_add_categories.py")
    
    if not migration_file.exists():
        print(f"❌ Migration file not found: {migration_file}")
        return False
    
    # Read the current content
    with open(migration_file, 'r') as f:
        content = f.read()
    
    print(f"📄 Found migration file: {migration_file.name}")
    
    # Replace the down_revision line
    # Current: down_revision = None  # Replace with your latest revision
    # New: down_revision = '99c07d825b2c'
    
    old_pattern = r'down_revision = None  # Replace with your latest revision'
    new_line = "down_revision = '99c07d825b2c'"
    
    if old_pattern in content:
        updated_content = content.replace(old_pattern, new_line)
        
        # Write back the fixed content
        with open(migration_file, 'w') as f:
            f.write(updated_content)
        
        print(f"✅ Fixed down_revision to point to: 99c07d825b2c")
        print(f"📝 Updated: {migration_file}")
        return True
    else:
        print(f"❌ Could not find the pattern to replace in migration file")
        print(f"📋 Please manually edit the file and change:")
        print(f"   FROM: down_revision = None")
        print(f"   TO:   down_revision = '99c07d825b2c'")
        return False

def verify_fix():
    """Verify the fix by checking alembic heads again."""
    print(f"\n🔍 VERIFYING FIX")
    print("=" * 30)
    
    import subprocess
    
    try:
        result = subprocess.run(['alembic', 'heads'], 
                              capture_output=True, text=True)
        
        if result.returncode == 0:
            heads_output = result.stdout.strip()
            head_lines = [line for line in heads_output.split('\n') if line.strip()]
            
            print(f"📊 Current heads after fix:")
            print(heads_output)
            
            if len(head_lines) == 1:
                print(f"✅ SUCCESS! Now only 1 head revision")
                return True
            else:
                print(f"❌ Still {len(head_lines)} heads - manual intervention needed")
                return False
        else:
            print(f"❌ Error checking heads: {result.stderr}")
            return False
            
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

def main():
    """Fix the migration and verify."""
    
    # Fix the migration file
    success = fix_shopify_migration()
    
    if success:
        # Verify the fix
        if verify_fix():
            print(f"\n🎉 MIGRATION FIXED SUCCESSFULLY!")
            print(f"📝 You can now run:")
            print(f"   alembic upgrade head")
            print(f"   (This will apply our Shopify migration)")
        else:
            print(f"\n⚠️ Fix applied but still multiple heads")
            print(f"📝 Try running: alembic merge heads -m 'merge heads'")
    else:
        print(f"\n❌ Could not automatically fix migration")
        print(f"📝 Please manually edit the migration file")

if __name__ == "__main__":
    main()