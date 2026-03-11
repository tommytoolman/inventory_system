#!/usr/bin/env python3
"""
Analyze SQLAlchemy models and their usage in the codebase
Helps identify potentially unused tables
"""

import os
import sys
import ast
import importlib
import inspect
from pathlib import Path
from collections import defaultdict

# Add the app directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.database import Base


def get_all_models():
    """Get all SQLAlchemy model classes"""
    models = {}

    # Import all model modules
    models_dir = Path(__file__).parent.parent / 'app' / 'models'

    for filepath in models_dir.glob('*.py'):
        if filepath.name.startswith('__'):
            continue

        module_name = f"app.models.{filepath.stem}"
        try:
            module = importlib.import_module(module_name)
            for name, obj in inspect.getmembers(module):
                if (inspect.isclass(obj) and
                    issubclass(obj, Base) and
                    obj != Base and
                    hasattr(obj, '__tablename__')):
                    models[obj.__tablename__] = {
                        'class': obj,
                        'module': module_name,
                        'file': str(filepath),
                        'relationships': [],
                        'used_in_files': set()
                    }
        except Exception as e:
            print(f"Warning: Could not import {module_name}: {e}")

    return models


def analyze_relationships(models):
    """Analyze relationships between models"""
    for table_name, model_info in models.items():
        model_class = model_info['class']

        # Check for relationships
        for attr_name in dir(model_class):
            attr = getattr(model_class, attr_name)
            if hasattr(attr, 'property') and hasattr(attr.property, 'mapper'):
                related_model = attr.property.mapper.class_
                if hasattr(related_model, '__tablename__'):
                    model_info['relationships'].append({
                        'attribute': attr_name,
                        'related_table': related_model.__tablename__,
                        'type': 'relationship'
                    })

        # Check for foreign keys
        for column in model_class.__table__.columns:
            if column.foreign_keys:
                for fk in column.foreign_keys:
                    table_name = fk.column.table.name
                    model_info['relationships'].append({
                        'attribute': column.name,
                        'related_table': table_name,
                        'type': 'foreign_key'
                    })


def find_model_usage(models):
    """Find where each model is used in the codebase"""

    # Directories to search
    search_dirs = [
        'app/routes',
        'app/services',
        'app/schemas',
        'scripts'
    ]

    for dir_path in search_dirs:
        full_path = Path(__file__).parent.parent / dir_path
        if not full_path.exists():
            continue

        for filepath in full_path.glob('**/*.py'):
            try:
                with open(filepath, 'r') as f:
                    content = f.read()

                # Look for model imports and usage
                for table_name, model_info in models.items():
                    class_name = model_info['class'].__name__

                    # Check for imports
                    if f"from app.models import {class_name}" in content or \
                       f"from app.models.{Path(model_info['file']).stem} import {class_name}" in content or \
                       f"{class_name}" in content:
                        model_info['used_in_files'].add(str(filepath.relative_to(Path(__file__).parent.parent)))

            except Exception as e:
                print(f"Warning: Could not read {filepath}: {e}")


def main():
    print("="*80)
    print("MODEL USAGE ANALYSIS")
    print("="*80)

    # Get all models
    models = get_all_models()
    print(f"\nFound {len(models)} models/tables:")

    # Analyze relationships
    analyze_relationships(models)

    # Find usage
    find_model_usage(models)

    # Sort by usage
    sorted_models = sorted(models.items(), key=lambda x: len(x[1]['used_in_files']))

    # Report findings
    print("\n" + "="*80)
    print("USAGE REPORT (sorted by least used first)")
    print("="*80)

    unused_tables = []
    rarely_used_tables = []

    for table_name, info in sorted_models:
        usage_count = len(info['used_in_files'])
        class_name = info['class'].__name__

        print(f"\n📊 Table: {table_name} (Model: {class_name})")
        print(f"   Module: {info['module']}")
        print(f"   Used in {usage_count} files")

        if usage_count == 0:
            unused_tables.append(table_name)
            print("   ⚠️  NOT USED ANYWHERE!")
        elif usage_count <= 2:
            rarely_used_tables.append(table_name)
            print("   ⚠️  Rarely used")

        if info['used_in_files']:
            print("   Files using this model:")
            for file in sorted(info['used_in_files'])[:5]:  # Show first 5
                print(f"     - {file}")
            if len(info['used_in_files']) > 5:
                print(f"     ... and {len(info['used_in_files']) - 5} more")

        if info['relationships']:
            print("   Relationships:")
            for rel in info['relationships']:
                print(f"     - {rel['attribute']} -> {rel['related_table']} ({rel['type']})")

    # Summary
    print("\n" + "="*80)
    print("SUMMARY")
    print("="*80)

    if unused_tables:
        print(f"\n🚨 UNUSED TABLES ({len(unused_tables)}):")
        for table in unused_tables:
            print(f"   - {table}")
        print("\n   These tables have no references in the codebase and might be safe to remove.")

    if rarely_used_tables:
        print(f"\n⚠️  RARELY USED TABLES ({len(rarely_used_tables)}):")
        for table in rarely_used_tables:
            print(f"   - {table}")
        print("\n   These tables have very few references and might be candidates for removal or consolidation.")

    # Check for tables referenced in relationships but not defined
    all_referenced_tables = set()
    for model_info in models.values():
        for rel in model_info['relationships']:
            all_referenced_tables.add(rel['related_table'])

    missing_tables = all_referenced_tables - set(models.keys())
    if missing_tables:
        print(f"\n❌ MISSING TABLES (referenced but not defined):")
        for table in missing_tables:
            print(f"   - {table}")

    print(f"\n✅ ACTIVELY USED TABLES: {len(models) - len(unused_tables) - len(rarely_used_tables)}")


if __name__ == "__main__":
    main()