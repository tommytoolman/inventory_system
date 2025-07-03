# scripts/fix_alembic_heads.py
"""
Diagnose and help fix multiple Alembic head revisions.
"""

import subprocess
import sys
from pathlib import Path

def check_alembic_heads():
    """Check current Alembic heads status."""
    print("🔍 CHECKING ALEMBIC HEADS STATUS")
    print("=" * 50)
    
    try:
        # Get current heads
        result = subprocess.run(['alembic', 'heads'], 
                              capture_output=True, text=True)
        
        if result.returncode == 0:
            heads_output = result.stdout.strip()
            print("📋 Current heads:")
            print(heads_output)
            
            # Count heads
            head_lines = [line for line in heads_output.split('\n') if line.strip()]
            print(f"\n📊 Found {len(head_lines)} head revisions")
            
            return head_lines
        else:
            print(f"❌ Error checking heads: {result.stderr}")
            return []
            
    except FileNotFoundError:
        print("❌ Alembic not found. Make sure you're in the right environment.")
        return []

def check_alembic_history():
    """Check Alembic revision history."""
    print("\n🔍 CHECKING ALEMBIC REVISION HISTORY")
    print("=" * 50)
    
    try:
        result = subprocess.run(['alembic', 'history'], 
                              capture_output=True, text=True)
        
        if result.returncode == 0:
            history_output = result.stdout.strip()
            print("📜 Recent revision history:")
            
            # Show last 10 lines
            lines = history_output.split('\n')
            for line in lines[-15:]:  # Last 15 lines
                print(line)
                
        else:
            print(f"❌ Error checking history: {result.stderr}")
            
    except Exception as e:
        print(f"❌ Error: {e}")

def suggest_merge_solution(heads):
    """Suggest how to merge the heads."""
    print("\n🔧 SUGGESTED SOLUTION")
    print("=" * 50)
    
    if len(heads) > 1:
        print("You have multiple heads that need to be merged.")
        print("\nOption 1 - Create a merge revision:")
        print("alembic merge heads -m 'merge multiple heads'")
        print("alembic upgrade head")
        
        print("\nOption 2 - Manually specify which head to use:")
        for i, head in enumerate(heads, 1):
            head_id = head.split()[0] if head.split() else "unknown"
            print(f"alembic upgrade {head_id}")
        
        print("\nOption 3 - Check what each head contains:")
        print("alembic show <revision_id>")
        
    else:
        print("✅ Only one head found - this should work normally")

def examine_migration_files():
    """Look at migration files to understand the branches."""
    print("\n📁 EXAMINING MIGRATION FILES")
    print("=" * 50)
    
    versions_dir = Path("alembic/versions")
    
    if versions_dir.exists():
        migration_files = list(versions_dir.glob("*.py"))
        migration_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        
        print(f"📊 Found {len(migration_files)} migration files")
        print("\n📋 Recent migrations (newest first):")
        
        for i, file in enumerate(migration_files[:10]):  # Show 10 most recent
            print(f"   {i+1}. {file.name}")
            
            # Try to read the revision info
            try:
                with open(file, 'r') as f:
                    content = f.read()
                    
                # Extract revision and down_revision
                for line in content.split('\n'):
                    if line.strip().startswith('revision ='):
                        revision = line.split('=')[1].strip().strip('\'"')
                        print(f"      Revision: {revision}")
                    elif line.strip().startswith('down_revision ='):
                        down_revision = line.split('=')[1].strip().strip('\'"')
                        print(f"      Down revision: {down_revision}")
                        break
                        
            except Exception as e:
                print(f"      ❌ Error reading file: {e}")
            
            print()
    else:
        print("❌ alembic/versions directory not found")

def main():
    """Main function to diagnose Alembic issues."""
    
    # Check if we're in the right directory
    if not Path("alembic.ini").exists():
        print("❌ alembic.ini not found. Run this from your project root.")
        return
    
    # Check heads
    heads = check_alembic_heads()
    
    # Check history  
    check_alembic_history()
    
    # Examine migration files
    examine_migration_files()
    
    # Suggest solution
    suggest_merge_solution(heads)
    
    print("\n🎯 NEXT STEPS:")
    print("1. Fix the multiple heads issue using one of the suggested methods")
    print("2. Run 'alembic upgrade head' to ensure you're at the latest revision")  
    print("3. Then we can add our Shopify category migration")

if __name__ == "__main__":
    main()