"""
Check Alembic migration status and history
"""
import asyncio
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from sqlalchemy import text
from app.database import async_session
import os
from datetime import datetime

async def check_alembic_history():
    """Check alembic version history in database"""
    async with async_session() as session:
        try:
            # Check if alembic_version table exists
            result = await session.execute(text("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_schema = 'public' 
                    AND table_name = 'alembic_version'
                )
            """))
            exists = result.scalar()
            
            if not exists:
                print("❌ No alembic_version table found - migrations have never been run")
                return None
            
            # Get current version
            result = await session.execute(text("SELECT version_num FROM alembic_version"))
            current_version = result.scalar()
            print(f"✅ Current migration version in DB: {current_version}")
            return current_version
            
        except Exception as e:
            print(f"❌ Error checking alembic history: {e}")
            return None

def check_migration_files():
    """Check what migration files exist"""
    migrations_dir = Path("alembic/versions")
    
    if not migrations_dir.exists():
        print("❌ No alembic/versions directory found")
        return []
    
    migrations = []
    for file in sorted(migrations_dir.glob("*.py")):
        if file.name == "__pycache__":
            continue
        
        # Read file to get revision info
        content = file.read_text()
        revision = None
        down_revision = None
        message = None
        
        for line in content.split('\n'):
            if line.startswith('revision ='):
                revision = line.split('=')[1].strip().strip("'\"")
            elif line.startswith('down_revision ='):
                down_revision = line.split('=')[1].strip().strip("'\"")
            elif line.startswith('"""') and not message:
                # First docstring is usually the message
                message = line.strip('"""')
        
        migrations.append({
            'file': file.name,
            'revision': revision,
            'down_revision': down_revision,
            'message': message,
            'modified': datetime.fromtimestamp(file.stat().st_mtime)
        })
    
    return migrations

async def main():
    print("="*60)
    print("ALEMBIC MIGRATION STATUS CHECK")
    print("="*60)
    
    # Check database
    print("\n=== DATABASE STATUS ===")
    current_version = await check_alembic_history()
    
    # Check files
    print("\n=== MIGRATION FILES ===")
    migrations = check_migration_files()
    
    if not migrations:
        print("❌ No migration files found")
    else:
        print(f"Found {len(migrations)} migration files:\n")
        for m in migrations:
            status = "✅ CURRENT" if m['revision'] == current_version else "  "
            print(f"{status} {m['file']}")
            print(f"     Revision: {m['revision']}")
            print(f"     Message: {m['message']}")
            print(f"     Modified: {m['modified'].strftime('%Y-%m-%d %H:%M:%S')}")
            print()
    
    # Summary
    print("\n=== SUMMARY ===")
    if current_version:
        matching = [m for m in migrations if m['revision'] == current_version]
        if matching:
            print(f"✅ Database is at migration: {matching[0]['file']}")
        else:
            print(f"⚠️  Database version {current_version} not found in migration files")
    else:
        print("❌ Database has no migration history")
    
    # Check for pending migrations
    if current_version and migrations:
        current_index = -1
        for i, m in enumerate(migrations):
            if m['revision'] == current_version:
                current_index = i
                break
        
        if current_index >= 0 and current_index < len(migrations) - 1:
            print(f"\n⚠️  {len(migrations) - current_index - 1} migrations pending")

if __name__ == "__main__":
    asyncio.run(main())