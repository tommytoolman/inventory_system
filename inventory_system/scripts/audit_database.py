#!/usr/bin/env python3
"""
Database Audit Script - Comprehensive analysis of database schema
"""

import asyncio
import os
import sys
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from tabulate import tabulate

# Add the app directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.core.config import get_settings


async def audit_database():
    """Perform a comprehensive audit of the database schema"""

    # Get database URL
    settings = get_settings()
    db_url = settings.database_url

    # Ensure it's async
    if not db_url.startswith('postgresql+asyncpg://'):
        db_url = db_url.replace('postgresql://', 'postgresql+asyncpg://', 1)

    print(f"Connecting to database: {db_url.split('@')[1] if '@' in db_url else db_url}")

    # Create engine
    engine = create_async_engine(db_url)

    async with engine.begin() as conn:
        # 1. Get all tables
        print("\n" + "="*80)
        print("DATABASE AUDIT REPORT")
        print("="*80)

        result = await conn.execute(text("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
            ORDER BY table_name
        """))
        tables = [row[0] for row in result]

        print(f"\nFound {len(tables)} tables:")
        for table in tables:
            print(f"  - {table}")

        # 2. For each table, get detailed column information
        for table in tables:
            print(f"\n{'='*80}")
            print(f"TABLE: {table}")
            print(f"{'='*80}")

            # Get column details
            result = await conn.execute(text("""
                SELECT
                    column_name,
                    data_type,
                    character_maximum_length,
                    is_nullable,
                    column_default
                FROM information_schema.columns
                WHERE table_name = :table_name
                AND table_schema = 'public'
                ORDER BY ordinal_position
            """), {"table_name": table})

            columns = []
            for row in result:
                col_type = row[1]
                if row[2]:  # has max length
                    col_type += f"({row[2]})"
                columns.append([
                    row[0],  # column_name
                    col_type,  # data_type
                    row[3],  # is_nullable
                    row[4] if row[4] else ""  # column_default
                ])

            print(tabulate(columns, headers=["Column", "Type", "Nullable", "Default"], tablefmt="grid"))

            # Get indexes
            result = await conn.execute(text("""
                SELECT
                    i.indexname,
                    i.indexdef,
                    idx.indisunique
                FROM pg_indexes i
                JOIN pg_class c ON c.relname = i.indexname
                JOIN pg_index idx ON idx.indexrelid = c.oid
                WHERE i.tablename = :table_name
                AND i.schemaname = 'public'
            """), {"table_name": table})

            indexes = list(result)
            if indexes:
                print(f"\nIndexes ({len(indexes)}):")
                for idx in indexes:
                    unique = " (UNIQUE)" if idx[2] else ""
                    print(f"  - {idx[0]}{unique}")

            # Get foreign keys
            result = await conn.execute(text("""
                SELECT
                    tc.constraint_name,
                    kcu.column_name,
                    ccu.table_name AS foreign_table_name,
                    ccu.column_name AS foreign_column_name
                FROM information_schema.table_constraints AS tc
                JOIN information_schema.key_column_usage AS kcu
                    ON tc.constraint_name = kcu.constraint_name
                    AND tc.table_schema = kcu.table_schema
                JOIN information_schema.constraint_column_usage AS ccu
                    ON ccu.constraint_name = tc.constraint_name
                    AND ccu.table_schema = tc.table_schema
                WHERE tc.constraint_type = 'FOREIGN KEY'
                AND tc.table_name = :table_name
            """), {"table_name": table})

            fks = list(result)
            if fks:
                print(f"\nForeign Keys ({len(fks)}):")
                for fk in fks:
                    print(f"  - {fk[0]}: {fk[1]} -> {fk[2]}.{fk[3]}")

            # Get constraints
            result = await conn.execute(text("""
                SELECT
                    tc.constraint_name,
                    tc.constraint_type,
                    kcu.column_name
                FROM information_schema.table_constraints AS tc
                JOIN information_schema.key_column_usage AS kcu
                    ON tc.constraint_name = kcu.constraint_name
                    AND tc.table_schema = kcu.table_schema
                WHERE tc.table_name = :table_name
                AND tc.constraint_type IN ('PRIMARY KEY', 'UNIQUE', 'CHECK')
                ORDER BY tc.constraint_type, tc.constraint_name
            """), {"table_name": table})

            constraints = list(result)
            if constraints:
                print(f"\nConstraints ({len(constraints)}):")
                for con in constraints:
                    print(f"  - {con[1]}: {con[0]} on ({con[2]})")

        # 3. Check for custom types/enums
        print(f"\n{'='*80}")
        print("CUSTOM TYPES/ENUMS")
        print(f"{'='*80}")

        result = await conn.execute(text("""
            SELECT
                t.typname AS enum_name,
                array_agg(e.enumlabel ORDER BY e.enumsortorder) AS enum_values
            FROM pg_type t
            JOIN pg_enum e ON t.oid = e.enumtypid
            JOIN pg_catalog.pg_namespace n ON n.oid = t.typnamespace
            WHERE n.nspname = 'public'
            GROUP BY t.typname
        """))

        enums = list(result)
        if enums:
            for enum in enums:
                print(f"\n{enum[0]}:")
                for value in enum[1]:
                    print(f"  - {value}")
        else:
            print("No custom types found")

        # 4. Check alembic version
        print(f"\n{'='*80}")
        print("ALEMBIC MIGRATION STATUS")
        print(f"{'='*80}")

        if 'alembic_version' in tables:
            result = await conn.execute(text("SELECT version_num FROM alembic_version"))
            version = result.scalar()
            print(f"Current migration version: {version}")
        else:
            print("No alembic_version table found - migrations have not been run")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(audit_database())