"""
Verify that SQLAlchemy models match the actual database schema
"""
import asyncio
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from sqlalchemy import text
from app.database import async_session
from app.models.product import Base
from sqlalchemy import inspect

async def get_db_schema():
    """Get current database schema"""
    async with async_session() as session:
        # Get all tables
        result = await session.execute(text("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND table_type = 'BASE TABLE'
            ORDER BY table_name
        """))
        tables = [row[0] for row in result]
        
        print("=== TABLES IN DATABASE ===")
        for table in tables:
            print(f"  - {table}")
        
        # Get columns for each table
        schema = {}
        for table in tables:
            result = await session.execute(text(f"""
                SELECT 
                    column_name,
                    data_type,
                    character_maximum_length,
                    is_nullable,
                    column_default
                FROM information_schema.columns
                WHERE table_name = '{table}'
                AND table_schema = 'public'
                ORDER BY ordinal_position
            """))
            schema[table] = []
            for row in result:
                schema[table].append({
                    'name': row[0],
                    'type': row[1],
                    'length': row[2],
                    'nullable': row[3] == 'YES',
                    'default': row[4]
                })
        
        return schema

def get_model_schema():
    """Get schema from SQLAlchemy models"""
    model_schema = {}
    
    # Get all tables from metadata
    for table_name, table in Base.metadata.tables.items():
        model_schema[table_name] = []
        for column in table.columns:
            model_schema[table_name].append({
                'name': column.name,
                'type': str(column.type),
                'nullable': column.nullable,
                'primary_key': column.primary_key,
                'foreign_keys': [str(fk) for fk in column.foreign_keys]
            })
    
    return model_schema

async def compare_schemas():
    """Compare database schema with model schema"""
    print("\n" + "="*50)
    print("COMPARING DATABASE SCHEMA WITH SQLALCHEMY MODELS")
    print("="*50 + "\n")
    
    # Get schemas
    db_schema = await get_db_schema()
    model_schema = get_model_schema()
    
    # Tables in DB but not in models
    db_tables = set(db_schema.keys())
    model_tables = set(model_schema.keys())
    
    print("\n=== TABLES IN DB BUT NOT IN MODELS ===")
    missing_in_models = db_tables - model_tables
    if missing_in_models:
        for table in sorted(missing_in_models):
            print(f"  ❌ {table}")
    else:
        print("  ✅ None - all DB tables have models")
    
    print("\n=== TABLES IN MODELS BUT NOT IN DB ===")
    missing_in_db = model_tables - db_tables
    if missing_in_db:
        for table in sorted(missing_in_db):
            print(f"  ❌ {table}")
    else:
        print("  ✅ None - all model tables exist in DB")
    
    # Compare columns for tables that exist in both
    print("\n=== COLUMN DIFFERENCES ===")
    common_tables = db_tables & model_tables
    
    for table in sorted(common_tables):
        db_cols = {col['name']: col for col in db_schema[table]}
        model_cols = {col['name']: col for col in model_schema[table]}
        
        db_col_names = set(db_cols.keys())
        model_col_names = set(model_cols.keys())
        
        # Missing columns
        missing_in_model = db_col_names - model_col_names
        missing_in_db = model_col_names - db_col_names
        
        if missing_in_model or missing_in_db:
            print(f"\n  Table: {table}")
            if missing_in_model:
                print(f"    Columns in DB but not in model:")
                for col in sorted(missing_in_model):
                    col_info = db_cols[col]
                    print(f"      ❌ {col} ({col_info['type']})")
            
            if missing_in_db:
                print(f"    Columns in model but not in DB:")
                for col in sorted(missing_in_db):
                    col_info = model_cols[col]
                    print(f"      ❌ {col} ({col_info['type']})")
    
    print("\n" + "="*50)
    print("SUMMARY")
    print("="*50)
    print(f"Tables in DB: {len(db_tables)}")
    print(f"Tables in Models: {len(model_tables)}")
    print(f"Tables missing in Models: {len(missing_in_models)}")
    print(f"Tables missing in DB: {len(missing_in_db)}")

if __name__ == "__main__":
    asyncio.run(compare_schemas())