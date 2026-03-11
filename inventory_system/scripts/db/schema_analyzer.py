# At the top of schema_analyzer.py (User's Original Imports)
import os
import sys
import json
# import pandas as pd # Not used in the core schema analysis part, can be removed if only for other functions
from pathlib import Path
from sqlalchemy import create_engine, inspect, Enum as SQLAlchemyEnum # ADDED SQLAlchemyEnum
from collections import defaultdict
# import logging # Not used in user's provided snippet for analyze_schema/generate_schema_report

# Add the parent directory to Python path to import app modules (User's Original)
sys.path.append(str(Path(__file__).parent.parent))
from app.core.config import Settings # User's Original

# database_url = Settings().DATABASE_URL # This is defined in if __name__ == "__main__": in user's code

# --- NEW HELPER FUNCTION for PostgreSQL ENUMs ---
def get_postgres_enum_details(db_engine, inspector, schema_name='public'):
    """
    Fetches details of user-defined ENUM types from a PostgreSQL database.
    """
    enum_types_details = []
    if db_engine.dialect.name == 'postgresql':
        try:
            with db_engine.connect() as connection:
                enums_in_db = inspector.dialect.get_enums(connection, schema=schema_name)
            for enum_def in enums_in_db:
                # Filter for the specific types the user is interested in, or list all.
                # User mentioned: 'productcondition', 'productstatus', 'productstatus_old', 'shipmentstatus'
                # Listing all found, user can visually confirm their types.
                enum_types_details.append({
                    'name': enum_def['name'],
                    'values': enum_def['labels']
                })
        except Exception as e:
            print(f"Warning: Could not retrieve PostgreSQL ENUM type details for schema '{schema_name}': {e}")
    return enum_types_details

# User's original analyze_schema function with minimal additions
def analyze_schema(connection_string):
    """Analyze PostgreSQL schema and identify potential duplicates."""
    engine = create_engine(connection_string)
    inspector = inspect(engine)

    # schema_info = defaultdict(dict) # User's original
    # Using a standard dict for schema_info to more easily add top-level keys like postgres_enum_types
    schema_info = {}
    column_usage = defaultdict(list) # User's original

    # --- ADDITION: Fetch PostgreSQL Specific ENUM type details ---
    # Stored at the top level of the main analysis dictionary
    # The overall function now returns a dict with 'schema', 'potential_duplicates', and 'postgres_enum_types'
    postgres_enum_types = get_postgres_enum_details(engine, inspector)


    # Collect all table and column information (User's Original Loop)
    for table_name in inspector.get_table_names():
        # Initialize table entry in schema_info if not already (it won't be with standard dict)
        schema_info[table_name] = {
            'columns': {},
            'primary_keys': [],
            'foreign_keys': []
        }
        
        columns = inspector.get_columns(table_name)
        # Prepare columns data with potential per-column enum info
        table_columns_dict = {}
        for col in columns:
            column_detail = {
                'type': str(col['type']), # col is a dict from inspector.get_columns
                'nullable': col['nullable'],
                'default': col.get('default'),
            }
            
            # --- ADDITION: Per-column ENUM information ---
            # inspector.get_columns returns dicts, col['type'] is a SQLAlchemy type object here
            col_type_obj = col['type'] 
            if isinstance(col_type_obj, SQLAlchemyEnum):
                # For SQLAlchemy Enum columns, try to get Python class and DB values
                if col_type_obj.enum_class:
                    column_detail["python_enum_class"] = col_type_obj.enum_class.__name__
                    column_detail["python_enum_values"] = [member.value for member in col_type_obj.enum_class]
                if hasattr(col_type_obj, 'enums') and col_type_obj.enums:
                     column_detail["reflected_db_enum_values"] = list(col_type_obj.enums)
            
            table_columns_dict[col['name']] = column_detail
        schema_info[table_name]['columns'] = table_columns_dict
        
        # Get primary key information (User's Original)
        pks = inspector.get_pk_constraint(table_name)
        schema_info[table_name]['primary_keys'] = pks.get('constrained_columns', [])
        
        # Get foreign key information (User's Original)
        fks = inspector.get_foreign_keys(table_name)
        schema_info[table_name]['foreign_keys'] = fks # This is already a list of dicts
        
        # Track column names for potential duplicates (User's Original)
        for col_dict in columns: # Iterate the list of dicts from inspector.get_columns
            column_usage[col_dict['name']].append(table_name)
    
    # Identify potential duplicate columns (User's Original)
    # This part of the original script might need adjustment if the structure of column_usage or schema_info changed
    # For now, keeping it as is, assuming it can still work with the modified schema_info structure.
    # The user's original `column_usage` logic should still work as it iterates `columns` list from inspector.
    potential_duplicates = {
        name: tables for name, tables in column_usage.items()
        if any(similar_name for similar_name in column_usage.keys()
               if name != similar_name and
               (name in similar_name or similar_name in name))
    }
    
    return {
        'schema': dict(schema_info), # schema_info is no longer defaultdict, so dict() is fine.
        'potential_duplicates': potential_duplicates,
        'postgres_enum_types': postgres_enum_types # --- ADDITION ---
    }

# User's original generate_schema_report function with minimal additions
def generate_schema_report(analysis_result):
    """Generate a readable report of the schema analysis."""
    report = []
    
    # --- ADDITION: Display PostgreSQL ENUM Types ---
    if "postgres_enum_types" in analysis_result and analysis_result["postgres_enum_types"]:
        report.append("\n## PostgreSQL User-Defined ENUM Types (Schema: public)")
        for enum_type in analysis_result["postgres_enum_types"]:
            # Filter for the specific types user mentioned, or list all.
            # if enum_type['name'] in ['productcondition', 'productstatus', 'productstatus_old', 'shipmentstatus']:
            report.append(f"\n### ENUM Type: {enum_type['name']}")
            report.append(f"  Values: {', '.join(enum_type['values'])}")
        report.append("\n" + "-"*40)


    report.append("\n# Database Schema Analysis") # Original title moved after ENUMs for grouping
    report.append("\n## Tables Overview")
    
    for table_name, info in analysis_result['schema'].items():
        report.append(f"\n### {table_name}")
        
        # Columns
        report.append("\nColumns:")
        if info.get('columns'): # Check if columns exist
            for col_name, col_info in info['columns'].items():
                nullable = "NULL" if col_info.get('nullable') else "NOT NULL" # use .get for safety
                default_val = col_info.get('default', '') # use .get for safety
                default_str = f"DEFAULT {default_val}" if default_val not in [None, ''] else ""
                report.append(f"- {col_name} ({col_info.get('type', 'N/A')}) {nullable} {default_str}") # use .get
                
                # --- ADDITION: Display per-column ENUM values ---
                if "python_enum_values" in col_info and col_info["python_enum_values"]:
                    report.append(f"  - Linked Python Enum: {col_info.get('python_enum_class', 'N/A')}, Values: {', '.join(map(str, col_info['python_enum_values']))}")
                if "reflected_db_enum_values" in col_info and col_info["reflected_db_enum_values"]:
                    is_redundant = ("python_enum_values" in col_info and 
                                    col_info["python_enum_values"] and 
                                    set(map(str, col_info["python_enum_values"])) == set(map(str, col_info["reflected_db_enum_values"])))
                    if not is_redundant:
                        report.append(f"  - Reflected DB ENUM Values: {', '.join(map(str, col_info['reflected_db_enum_values']))}")
        else:
            report.append("  No columns found for this table.")

        # Primary Keys (User's Original - adapted for safety with .get)
        if info.get('primary_keys'):
            report.append("\nPrimary Keys:")
            for pk in info['primary_keys']:
                report.append(f"- {pk}")
        
        # Foreign Keys (User's Original - adapted for safety with .get)
        if info.get('foreign_keys'):
            report.append("\nForeign Keys:")
            for fk in info['foreign_keys']: # fk is already a dict
                referred_table = fk.get('referred_table', 'N/A')
                referred_columns = ', '.join(fk.get('referred_columns', []))
                constrained_columns = ', '.join(fk.get('constrained_columns', []))
                referred = f"{referred_table}({referred_columns})"
                local = f"{constrained_columns}"
                report.append(f"- {local} → {referred} (Name: {fk.get('name', 'N/A')})") # Added FK name for clarity
    
    # Potential Duplicates (User's Original)
    if analysis_result.get('potential_duplicates'): # Check if key exists
        report.append("\n## Potential Column Duplications")
        for col_name, tables in analysis_result['potential_duplicates'].items():
            report.append(f"\n- {col_name} appears in:")
            for table in tables:
                report.append(f"  - {table}")
    
    return "\n".join(report)


# User's original save_schema_analysis
def save_schema_analysis(analysis, report):
    script_dir = Path(__file__).parent
    
    # Save readable text report
    report_file = script_dir / "schema_report.txt"
    with open(report_file, "w") as f:
        f.write(report)
    print(f"Schema report saved to {report_file}")
    
    # Save structured JSON data
    json_file = script_dir / "schema_data.json"
    with open(json_file, "w") as f:
        # Added sort_keys for consistent JSON output, helpful for diffs
        json.dump(analysis, f, indent=2, default=str, sort_keys=True)
    print(f"Schema data saved to {json_file}")


# User's original find_table_references and find_field_usage functions
# These are unchanged as they are separate from the schema analysis part requested.
def find_table_references(project_root_path): # Renamed arg to avoid clash
    """Scan Python files for table references"""
    references = defaultdict(list)
    for path in Path(project_root_path).rglob('*.py'): # Use renamed arg
        if 'venv' in str(path) or '__pycache__' in str(path):
            continue
        with open(path, encoding='utf-8', errors='ignore') as f: # Added encoding and error handling
            content = f.read()
            # Make this list dynamic or configurable if possible
            for table in ['old_platform_listings', 'platform_common', 'products', 
                          'ebay_listings', 'reverb_listings', 'vr_listings', 
                          'product_platform_mappings', 'activity_log']: # Added more common tables
                if table in content:
                    references[table].append(str(path))
    return dict(references)


def find_field_usage(project_root_path, table_fields): # Renamed arg
    """
    Scan Python files for specific field references
    table_fields: dict of fields to check, e.g. {'products': ['brand', 'brand_name']}
    """
    field_usage = defaultdict(list)
    for path in Path(project_root_path).rglob('*.py'): # Use renamed arg
        if 'venv' in str(path) or '__pycache__' in str(path):
            continue
        with open(path, encoding='utf-8', errors='ignore') as f: # Added encoding and error handling
            content = f.read()
            # Assuming table_fields is a dict where keys are table names and values are lists of fields
            for table_name_key, fields_to_check in table_fields.items():
                for field in fields_to_check:
                    if field in content: # This is a simple string check, might need regex for precision
                        field_usage[f"{table_name_key}.{field}"].append(str(path))
    return dict(field_usage)

# User's original __main__ block
if __name__ == "__main__":
    # This is user's original way of getting database_url
    db_url_settings = Settings().DATABASE_URL 
    # User's original modification for non-async driver
    db_url_sync = db_url_settings.replace("postgresql+asyncpg://", "postgresql://") 
    
    print(f"Analyzing schema for: {db_url_sync[:db_url_sync.find('@') if '@' in db_url_sync else len(db_url_sync)]}...") # Obfuscate creds

    analysis_results = analyze_schema(db_url_sync) # Pass the modified sync URL
    generated_report = generate_schema_report(analysis_results) # Pass the full results
    
    print("\n--- Schema Report Start ---")
    print(generated_report)
    print("--- Schema Report End ---\n")
    
    save_schema_analysis(analysis_results, generated_report) # Pass the full results
    
    # The rest of the user's __main__ for finding references
    # Ensure project_root is defined correctly as per their original intent
    current_project_root = Path(__file__).parent.parent 
    table_refs_results = find_table_references(current_project_root)
    print("\nTable references in codebase:")
    for table, files in table_refs_results.items():
        print(f"\n{table} referenced in:")
        for f_path in files: # Renamed f to f_path
            print(f"  - {f_path}")

    # Check usage of duplicated fields (User's original)
    duplicate_fields_to_check = {
        'products': ['brand', 'brand_name', 'model', 'product_model', 'category', 'category_name']
    }
    field_refs_results = find_field_usage(current_project_root, duplicate_fields_to_check)
    print("\nField usage in products table:")
    for field, files in field_refs_results.items():
        print(f"\n{field} used in:")
        for f_path in files: # Renamed f to f_path
            print(f"  - {f_path}")