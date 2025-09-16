#!/usr/bin/env python3
"""
Compare actual database schema with SQLAlchemy models
Shows discrepancies between what's in the DB and what the models define
"""

import asyncio
import os
import sys
from sqlalchemy import text, inspect
from sqlalchemy.ext.asyncio import create_async_engine
from collections import defaultdict
import importlib
from pathlib import Path

# Add the app directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.core.config import get_settings
from app.database import Base


async def get_database_schema():
    """Get the actual database schema"""
    settings = get_settings()
    db_url = str(settings.DATABASE_URL)

    # Ensure it's async
    if not db_url.startswith('postgresql+asyncpg://'):
        db_url = db_url.replace('postgresql://', 'postgresql+asyncpg://', 1)

    engine = create_async_engine(db_url)
    db_schema = {}

    async with engine.begin() as conn:
        # Get all tables
        result = await conn.execute(text("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
            AND table_type = 'BASE TABLE'
            ORDER BY table_name
        """))
        tables = [row[0] for row in result]

        for table in tables:
            # Get columns for each table
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

            columns = {}
            for row in result:
                col_type = row[1]
                if row[2]:  # has max length
                    col_type += f"({row[2]})"

                columns[row[0]] = {
                    'type': col_type,
                    'nullable': row[3] == 'YES',
                    'default': row[4]
                }

            db_schema[table] = columns

    await engine.dispose()
    return db_schema


def get_model_schema():
    """Get schema from SQLAlchemy models"""
    model_schema = {}

    # Import all model modules to ensure they're registered
    models_dir = Path(__file__).parent.parent / 'app' / 'models'

    for filepath in models_dir.glob('*.py'):
        if filepath.name.startswith('__'):
            continue

        module_name = f"app.models.{filepath.stem}"
        try:
            importlib.import_module(module_name)
        except Exception as e:
            print(f"Warning: Could not import {module_name}: {e}")

    # Get all registered models
    for mapper in Base.registry.mappers:
        model = mapper.class_
        table_name = model.__tablename__

        columns = {}
        for column in model.__table__.columns:
            col_type = str(column.type)

            # Normalize types
            if 'VARCHAR' in col_type and not '(' in col_type:
                col_type = 'character varying'
            elif 'INTEGER' in col_type:
                col_type = 'integer'
            elif 'FLOAT' in col_type or 'DOUBLE' in col_type:
                col_type = 'double precision'
            elif 'BOOLEAN' in col_type:
                col_type = 'boolean'
            elif 'DATETIME' in col_type or 'TIMESTAMP' in col_type:
                col_type = 'timestamp without time zone'
            elif 'TEXT' in col_type:
                col_type = 'text'
            elif 'JSONB' in col_type:
                col_type = 'jsonb'

            columns[column.name] = {
                'type': col_type.lower(),
                'nullable': column.nullable,
                'default': str(column.default.arg) if column.default else None,
                'primary_key': column.primary_key,
                'foreign_keys': [str(fk.target_fullname) for fk in column.foreign_keys]
            }

        model_schema[table_name] = columns

    return model_schema


def compare_schemas(db_schema, model_schema):
    """Compare database schema with model schema"""
    comparison = {
        'tables_only_in_db': [],
        'tables_only_in_models': [],
        'table_differences': {},
        'summary': {
            'db_tables': len(db_schema),
            'model_tables': len(model_schema),
            'matching_tables': 0,
            'tables_with_differences': 0
        }
    }

    # Find tables only in DB
    comparison['tables_only_in_db'] = sorted(set(db_schema.keys()) - set(model_schema.keys()))

    # Find tables only in models
    comparison['tables_only_in_models'] = sorted(set(model_schema.keys()) - set(db_schema.keys()))

    # Compare common tables
    common_tables = set(db_schema.keys()) & set(model_schema.keys())

    for table in sorted(common_tables):
        db_cols = db_schema[table]
        model_cols = model_schema[table]

        differences = {
            'columns_only_in_db': [],
            'columns_only_in_model': [],
            'column_differences': {}
        }

        # Find column differences
        db_col_names = set(db_cols.keys())
        model_col_names = set(model_cols.keys())

        differences['columns_only_in_db'] = sorted(db_col_names - model_col_names)
        differences['columns_only_in_model'] = sorted(model_col_names - db_col_names)

        # Compare common columns
        for col in sorted(db_col_names & model_col_names):
            db_col = db_cols[col]
            model_col = model_cols[col]

            col_diffs = []

            # Compare types (normalize for comparison)
            db_type = db_col['type'].lower()
            model_type = model_col['type'].lower()

            # Normalize common type differences
            type_mappings = {
                'character varying': ['varchar', 'string'],
                'timestamp without time zone': ['datetime', 'timestamp'],
                'double precision': ['float', 'double']
            }

            type_mismatch = True
            for norm_type, variants in type_mappings.items():
                if (db_type == norm_type and any(v in model_type for v in variants)) or \
                   (model_type == norm_type and any(v in db_type for v in variants)):
                    type_mismatch = False
                    break

            if type_mismatch and db_type != model_type:
                col_diffs.append(f"type: {db_type} (db) vs {model_type} (model)")

            # Compare nullable
            if db_col['nullable'] != model_col['nullable']:
                col_diffs.append(f"nullable: {db_col['nullable']} (db) vs {model_col['nullable']} (model)")

            if col_diffs:
                differences['column_differences'][col] = col_diffs

        # Only add to differences if there are actual differences
        if any([differences['columns_only_in_db'],
                differences['columns_only_in_model'],
                differences['column_differences']]):
            comparison['table_differences'][table] = differences
            comparison['summary']['tables_with_differences'] += 1
        else:
            comparison['summary']['matching_tables'] += 1

    return comparison


async def main():
    print("="*80)
    print("DATABASE vs MODELS COMPARISON")
    print("="*80)

    # Get schemas
    print("\n1. Reading database schema...")
    db_schema = await get_database_schema()
    print(f"   Found {len(db_schema)} tables in database")

    print("\n2. Reading model schema...")
    model_schema = get_model_schema()
    print(f"   Found {len(model_schema)} tables in models")

    # Compare
    print("\n3. Comparing schemas...")
    comparison = compare_schemas(db_schema, model_schema)

    # Report results
    print("\n" + "="*80)
    print("COMPARISON RESULTS")
    print("="*80)

    print(f"\n📊 SUMMARY:")
    print(f"   Database tables: {comparison['summary']['db_tables']}")
    print(f"   Model tables: {comparison['summary']['model_tables']}")
    print(f"   Matching tables: {comparison['summary']['matching_tables']}")
    print(f"   Tables with differences: {comparison['summary']['tables_with_differences']}")

    if comparison['tables_only_in_db']:
        print(f"\n🗄️  TABLES ONLY IN DATABASE ({len(comparison['tables_only_in_db'])}):")
        for table in comparison['tables_only_in_db']:
            print(f"   - {table}")
            if table in db_schema:
                print(f"     Columns: {', '.join(db_schema[table].keys())}")

    if comparison['tables_only_in_models']:
        print(f"\n📋 TABLES ONLY IN MODELS ({len(comparison['tables_only_in_models'])}):")
        for table in comparison['tables_only_in_models']:
            print(f"   - {table}")

    if comparison['table_differences']:
        print(f"\n⚠️  TABLES WITH DIFFERENCES ({len(comparison['table_differences'])}):")
        for table, diffs in comparison['table_differences'].items():
            print(f"\n   Table: {table}")

            if diffs['columns_only_in_db']:
                print(f"   Columns only in DB: {', '.join(diffs['columns_only_in_db'])}")

            if diffs['columns_only_in_model']:
                print(f"   Columns only in Model: {', '.join(diffs['columns_only_in_model'])}")

            if diffs['column_differences']:
                print(f"   Column differences:")
                for col, col_diffs in diffs['column_differences'].items():
                    print(f"     - {col}: {'; '.join(col_diffs)}")

    # List all database tables for reference
    print("\n" + "="*80)
    print("ALL DATABASE TABLES:")
    print("="*80)
    for i, table in enumerate(sorted(db_schema.keys()), 1):
        print(f"{i:2d}. {table}")


if __name__ == "__main__":
    asyncio.run(main())