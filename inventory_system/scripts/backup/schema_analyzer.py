# At the top of schema_analyzer.py
import os
import sys
import json
import pandas as pd
from pathlib import Path
from sqlalchemy import create_engine, inspect
from collections import defaultdict


# Add the parent directory to Python path to import app modules
sys.path.append(str(Path(__file__).parent.parent))
from app.core.config import Settings

# database_url = Settings().DATABASE_URL


def analyze_schema(connection_string):
    """Analyze PostgreSQL schema and identify potential duplicates."""
    engine = create_engine(connection_string)
    inspector = inspect(engine)

    schema_info = defaultdict(dict)
    column_usage = defaultdict(list)

    # Collect all table and column information
    for table_name in inspector.get_table_names():
        columns = inspector.get_columns(table_name)
        schema_info[table_name]['columns'] = {
            col['name']: {
                'type': str(col['type']),
                'nullable': col['nullable'],
                'default': col.get('default'),
            }
            for col in columns
        }
        
        # Get primary key information
        pks = inspector.get_pk_constraint(table_name)
        schema_info[table_name]['primary_keys'] = pks.get('constrained_columns', [])
        
        # Get foreign key information
        fks = inspector.get_foreign_keys(table_name)
        schema_info[table_name]['foreign_keys'] = fks
        
        # Track column names for potential duplicates
        for col in columns:
            column_usage[col['name']].append(table_name)
    
    # Identify potential duplicate columns (similar names)
    potential_duplicates = {
        name: tables for name, tables in column_usage.items()
        if any(similar_name for similar_name in column_usage.keys()
               if name != similar_name and
               (name in similar_name or similar_name in name))
    }
    
    return {
        'schema': dict(schema_info),
        'potential_duplicates': potential_duplicates
    }


def generate_schema_report(analysis_result):
    """Generate a readable report of the schema analysis."""
    report = []
    
    # Schema Overview
    report.append("# Database Schema Analysis")
    report.append("\n## Tables Overview")
    
    for table_name, info in analysis_result['schema'].items():
        report.append(f"\n### {table_name}")
        
        # Columns
        report.append("\nColumns:")
        for col_name, col_info in info['columns'].items():
            nullable = "NULL" if col_info['nullable'] else "NOT NULL"
            default = f"DEFAULT {col_info['default']}" if col_info['default'] else ""
            report.append(f"- {col_name} ({col_info['type']}) {nullable} {default}")
        
        # Primary Keys
        if info['primary_keys']:
            report.append("\nPrimary Keys:")
            for pk in info['primary_keys']:
                report.append(f"- {pk}")
        
        # Foreign Keys
        if info['foreign_keys']:
            report.append("\nForeign Keys:")
            for fk in info['foreign_keys']:
                referred = f"{fk['referred_table']}({', '.join(fk['referred_columns'])})"
                local = f"{', '.join(fk['constrained_columns'])}"
                report.append(f"- {local} → {referred}")
    
    # Potential Duplicates
    report.append("\n## Potential Column Duplications")
    for col_name, tables in analysis_result['potential_duplicates'].items():
        report.append(f"\n- {col_name} appears in:")
        for table in tables:
            report.append(f"  - {table}")
    
    return "\n".join(report)


def save_schema_analysis(analysis, report):
    script_dir = Path(__file__).parent
    
    # Save readable text report
    with open(script_dir / "schema_report.txt", "w") as f:
        f.write(report)
    
    # Save structured JSON data
    with open(script_dir / "schema_data.json", "w") as f:
        json.dump(analysis, f, indent=2, default=str)


def find_table_references(project_root):
    """Scan Python files for table references"""
    references = defaultdict(list)
    for path in Path(project_root).rglob('*.py'):
        if 'venv' in str(path) or '__pycache__' in str(path):
            continue
        with open(path) as f:
            content = f.read()
            for table in ['old_platform_listings', 'platform_common', 'products']:
                if table in content:
                    references[table].append(str(path))
    return dict(references)


def find_field_usage(project_root, table_fields):
    """
    Scan Python files for specific field references
    table_fields: dict of fields to check, e.g. {'products': ['brand', 'brand_name']}
    """
    field_usage = defaultdict(list)
    for path in Path(project_root).rglob('*.py'):
        if 'venv' in str(path) or '__pycache__' in str(path):
            continue
        with open(path) as f:
            content = f.read()
            for field in table_fields['products']:
                if field in content:
                    field_usage[field].append(str(path))
    return dict(field_usage)


if __name__ == "__main__":
    database_url = Settings().DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    analysis = analyze_schema(database_url)
    report = generate_schema_report(analysis)
    print(report)
    save_schema_analysis(analysis, report)
    print("Schema analysis saved to schema_report.txt and schema_data.json")

    project_root = Path(__file__).parent.parent
    table_refs = find_table_references(project_root)
    print("\nTable references in codebase:")
    for table, files in table_refs.items():
        print(f"\n{table} referenced in:")
        for f in files:
            print(f"  - {f}")

    # Check usage of duplicated fields
    duplicate_fields = {
        'products': ['brand', 'brand_name', 'model', 'product_model', 'category', 'category_name']
    }
    field_refs = find_field_usage(project_root, duplicate_fields)
    print("\nField usage in products table:")
    for field, files in field_refs.items():
        print(f"\n{field} used in:")
        for f in files:
            print(f"  - {f}")