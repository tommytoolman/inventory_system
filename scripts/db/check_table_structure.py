#!/usr/bin/env python3
"""
Check the structure of platform_category_mappings table
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sqlalchemy import text
from app.database import async_session


async def check_table_structure():
    """Check the structure of platform_category_mappings table"""
    
    async with async_session() as db:
        # Check columns in the table
        query = text("""
            SELECT 
                column_name, 
                data_type, 
                character_maximum_length,
                is_nullable
            FROM information_schema.columns 
            WHERE table_name = 'platform_category_mappings'
            ORDER BY ordinal_position
        """)
        
        result = await db.execute(query)
        columns = result.fetchall()
        
        if columns:
            print("📊 Table 'platform_category_mappings' structure:")
            print("-" * 60)
            for col in columns:
                nullable = "NULL" if col.is_nullable == 'YES' else "NOT NULL"
                if col.character_maximum_length:
                    print(f"  {col.column_name}: {col.data_type}({col.character_maximum_length}) {nullable}")
                else:
                    print(f"  {col.column_name}: {col.data_type} {nullable}")
        else:
            print("❌ Table 'platform_category_mappings' not found!")
            print("\nCreate it with this SQL:")
            print("""
CREATE TABLE platform_category_mappings (
    id SERIAL PRIMARY KEY,
    source_platform VARCHAR(50),
    source_category_id VARCHAR(100),
    source_category_name TEXT,
    target_platform VARCHAR(50),
    target_category_id VARCHAR(100),
    target_category_name TEXT,
    item_count INTEGER,
    created_at TIMESTAMP DEFAULT NOW()
);
            """)


if __name__ == "__main__":
    asyncio.run(check_table_structure())