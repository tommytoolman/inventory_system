#!/usr/bin/env python3
"""
Generate a squashed migration directly from the current database schema
This ensures the migration matches exactly what's in the database
"""

import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

# Add the app directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.core.config import get_settings


async def extract_database_schema():
    """Extract complete schema from database"""
    settings = get_settings()
    db_url = str(settings.DATABASE_URL)

    # Ensure it's async
    if not db_url.startswith('postgresql+asyncpg://'):
        db_url = db_url.replace('postgresql://', 'postgresql+asyncpg://', 1)

    engine = create_async_engine(db_url)

    async with engine.begin() as conn:
        # Get custom types/enums
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
        enums = {row[0]: list(row[1]) for row in result}

        # Get all tables (excluding alembic_version)
        result = await conn.execute(text("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
            AND table_type = 'BASE TABLE'
            AND table_name != 'alembic_version'
            ORDER BY table_name
        """))
        tables = [row[0] for row in result]

        # Extract full DDL for each table
        table_ddls = {}
        for table in tables:
            # Get CREATE TABLE statement
            result = await conn.execute(text(f"""
                SELECT
                    'CREATE TABLE ' || quote_ident('{table}') || ' (' || E'\\n' ||
                    string_agg(
                        '    ' || column_definition ||
                        CASE WHEN constraint_definition IS NOT NULL
                            THEN E',\\n    ' || constraint_definition
                            ELSE ''
                        END,
                        E',\\n' ORDER BY ordinal_position, constraint_type DESC
                    ) || E'\\n);'
                FROM (
                    -- Column definitions
                    SELECT
                        c.ordinal_position,
                        quote_ident(c.column_name) || ' ' ||
                        CASE
                            WHEN c.data_type = 'USER-DEFINED' THEN c.udt_name
                            WHEN c.character_maximum_length IS NOT NULL THEN
                                c.data_type || '(' || c.character_maximum_length || ')'
                            WHEN c.data_type = 'numeric' AND c.numeric_precision IS NOT NULL THEN
                                c.data_type || '(' || c.numeric_precision ||
                                CASE WHEN c.numeric_scale > 0 THEN ',' || c.numeric_scale ELSE '' END || ')'
                            ELSE c.data_type
                        END ||
                        CASE WHEN c.is_nullable = 'NO' THEN ' NOT NULL' ELSE '' END ||
                        CASE WHEN c.column_default IS NOT NULL THEN ' DEFAULT ' || c.column_default ELSE '' END
                        AS column_definition,
                        NULL as constraint_definition,
                        0 as constraint_type
                    FROM information_schema.columns c
                    WHERE c.table_name = '{table}'
                    AND c.table_schema = 'public'

                    UNION ALL

                    -- Constraints
                    SELECT
                        1000 + row_number() OVER () as ordinal_position,
                        NULL as column_definition,
                        CASE tc.constraint_type
                            WHEN 'PRIMARY KEY' THEN 'PRIMARY KEY (' || string_agg(quote_ident(kcu.column_name), ', ') || ')'
                            WHEN 'UNIQUE' THEN 'CONSTRAINT ' || quote_ident(tc.constraint_name) || ' UNIQUE (' || string_agg(quote_ident(kcu.column_name), ', ') || ')'
                            WHEN 'FOREIGN KEY' THEN 'CONSTRAINT ' || quote_ident(tc.constraint_name) || ' FOREIGN KEY (' || string_agg(quote_ident(kcu.column_name), ', ') || ') REFERENCES ' || ccu.table_name || ' (' || string_agg(ccu.column_name, ', ') || ')'
                        END as constraint_definition,
                        CASE tc.constraint_type
                            WHEN 'PRIMARY KEY' THEN 1
                            WHEN 'FOREIGN KEY' THEN 2
                            WHEN 'UNIQUE' THEN 3
                            ELSE 4
                        END as constraint_type
                    FROM information_schema.table_constraints tc
                    JOIN information_schema.key_column_usage kcu ON tc.constraint_name = kcu.constraint_name
                    LEFT JOIN information_schema.constraint_column_usage ccu ON tc.constraint_name = ccu.constraint_name
                    WHERE tc.table_name = '{table}'
                    AND tc.table_schema = 'public'
                    AND tc.constraint_type IN ('PRIMARY KEY', 'UNIQUE', 'FOREIGN KEY')
                    GROUP BY tc.constraint_name, tc.constraint_type, ccu.table_name
                ) t
                WHERE column_definition IS NOT NULL OR constraint_definition IS NOT NULL;
            """))

            ddl_result = result.scalar()
            if ddl_result:
                table_ddls[table] = ddl_result

        # Get indexes
        indexes = {}
        for table in tables:
            result = await conn.execute(text("""
                SELECT
                    indexname,
                    indexdef
                FROM pg_indexes
                WHERE tablename = :table_name
                AND schemaname = 'public'
                AND indexname NOT LIKE '%_pkey'
                AND indexname NOT LIKE '%_key'
                ORDER BY indexname
            """), {"table_name": table})

            table_indexes = [(row[0], row[1]) for row in result]
            if table_indexes:
                indexes[table] = table_indexes

    await engine.dispose()

    return {
        'enums': enums,
        'tables': table_ddls,
        'indexes': indexes,
        'table_list': tables
    }


def generate_migration_from_schema(schema):
    """Generate migration content from extracted schema"""

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    revision = datetime.now().strftime("%Y%m%d%H%M%S")[:12]

    # Start migration content
    content = f'''"""Squashed initial migration - creates all tables from existing database

Revision ID: {revision}
Revises:
Create Date: {datetime.now().isoformat()}

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '{revision}'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create custom types/enums
'''

    # Add enum creation
    for enum_name, values in schema['enums'].items():
        values_str = ', '.join([f"'{v}'" for v in values])
        content += f"""
    {enum_name}_enum = postgresql.ENUM(
        {values_str},
        name='{enum_name}'
    )
    {enum_name}_enum.create(op.get_bind(), checkfirst=True)
"""

    content += "\n    # Create tables\n"

    # Add table creation DDL
    for table in schema['table_list']:
        if table in schema['tables']:
            content += f"\n    # Table: {table}\n"
            content += f"    op.execute('''{schema['tables'][table]}''')\n"

    # Add indexes
    content += "\n    # Create indexes\n"
    for table, table_indexes in schema['indexes'].items():
        for index_name, index_def in table_indexes:
            # Convert CREATE INDEX to Alembic operation
            content += f"    op.execute('''{index_def}''')\n"

    # Add downgrade function
    content += "\n\ndef downgrade() -> None:\n"
    content += "    # Drop all tables in reverse order\n"

    # Reverse table order for proper foreign key handling
    for table in reversed(schema['table_list']):
        content += f"    op.drop_table('{table}')\n"

    # Drop enums
    content += "\n    # Drop enums\n"
    for enum_name in schema['enums']:
        content += f"    op.execute('DROP TYPE IF EXISTS {enum_name}')\n"

    return content


async def main():
    print("Extracting database schema...")
    schema = await extract_database_schema()

    print(f"Found {len(schema['tables'])} tables and {len(schema['enums'])} enums")

    # Generate migration
    migration_content = generate_migration_from_schema(schema)

    # Write to file
    migration_path = Path(__file__).parent.parent / 'alembic' / 'versions' / 'squashed_initial_from_db.py'

    with open(migration_path, 'w') as f:
        f.write(migration_content)

    print(f"✅ Squashed migration created at: {migration_path}")
    print(f"\nThis migration includes {len(schema['tables'])} tables (excluding alembic_version)")
    print("\nTables included:")
    for i, table in enumerate(schema['table_list'], 1):
        print(f"  {i:2d}. {table}")


if __name__ == "__main__":
    asyncio.run(main())