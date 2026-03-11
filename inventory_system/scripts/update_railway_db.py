#!/usr/bin/env python3
"""
Interactive script to update or insert records in Railway database

Usage:
    python scripts/update_railway_db_fixed.py

The script will first ask whether you want to UPDATE or INSERT.

Examples:

1. Update a single eBay listing price:
   ```
   Choose operation: update

   Enter table name: ebay_listings

   Enter column name for WHERE clause: ebay_item_id
   Enter value for ebay_item_id: 257054645278

   Enter column name to update: price
   Enter new value for price: 75999
   ```

2. Update product details with multiple conditions:
   ```
   Choose operation: update

   Enter table name: products

   Enter column name for WHERE clause: sku
   Enter value for sku: REV-12345
   Enter column name for WHERE clause: brand
   Enter value for brand: Fender

   Enter column name to update: base_price
   Enter new value for base_price: 1299.99
   Enter column name to update: quantity
   Enter new value for quantity: 0
   ```

3. Fix sync_events status:
   ```
   Choose operation: update

   Enter table name: sync_events

   Enter column name for WHERE clause: id
   Enter value for id: 12615

   Enter column name to update: status
   Enter new value for status: processed
   Enter column name to update: notes
   Enter new value for notes: Manually processed - duplicate listing
   ```

4. Update with NULL values:
   ```
   Choose operation: update

   Enter table name: reverb_listings

   Enter column name for WHERE clause: reverb_id
   Enter value for reverb_id: 89557351

   Enter column name to update: sold_at
   Enter new value for sold_at: null
   ```

5. INSERT new shopify_listings record:
   ```
   Choose operation: insert

   Enter table name: shopify_listings

   Enter column name to insert: shopify_id
   Enter value for shopify_id: gid://shopify/Product/8902345678901
   Enter column name to insert: platform_id
   Enter value for platform_id: 456
   Enter column name to insert: status
   Enter value for status: active
   Enter column name to insert: title
   Enter value for title: Fender Stratocaster
   ```

Special values:
- Type 'null' (lowercase) to set a column to NULL
- Boolean columns accept: true, t, 1, yes (all case-insensitive)
- Timestamps: Use ISO format (2025-09-17 13:45:00) or PostgreSQL functions like now()
- The script automatically updates 'updated_at' if the column exists
"""

import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from dotenv import load_dotenv
import os
from datetime import datetime

# Load environment variables from .env file
load_dotenv()

async def get_table_columns(conn, table_name):
    """
    Get all columns for a table.

    Args:
        conn: Database connection
        table_name: Name of the table

    Returns:
        List of tuples (column_name, data_type)
    """
    result = await conn.execute(
        text("""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_name = :table_name
            ORDER BY ordinal_position
        """),
        {"table_name": table_name}
    )
    return [(row[0], row[1]) for row in result]

async def insert_record(conn):
    """
    Insert a new record into a table.

    This function:
    1. Prompts for table name and validates it exists
    2. Shows available columns with data types and constraints
    3. Builds INSERT statement interactively
    4. Shows preview of INSERT statement
    5. Executes upon confirmation
    6. Shows the inserted record
    """
    # Get table name
    table_name = input("\nEnter table name: ").strip()

    # Check if table exists
    table_check = await conn.execute(
        text("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_name = :table_name
            )
        """),
        {"table_name": table_name}
    )

    if not table_check.scalar():
        print(f"ERROR: Table '{table_name}' does not exist")
        return

    # Show available columns with constraints
    columns_query = """
        SELECT
            c.column_name,
            c.data_type,
            c.is_nullable,
            c.column_default,
            CASE
                WHEN pk.column_name IS NOT NULL THEN 'PRIMARY KEY'
                WHEN fk.column_name IS NOT NULL THEN 'FOREIGN KEY'
                ELSE ''
            END as constraint_type
        FROM information_schema.columns c
        LEFT JOIN (
            SELECT kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_name = kcu.table_name
            WHERE tc.table_name = :table_name
                AND tc.constraint_type = 'PRIMARY KEY'
        ) pk ON c.column_name = pk.column_name
        LEFT JOIN (
            SELECT kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_name = kcu.table_name
            WHERE tc.table_name = :table_name
                AND tc.constraint_type = 'FOREIGN KEY'
        ) fk ON c.column_name = fk.column_name
        WHERE c.table_name = :table_name
        ORDER BY c.ordinal_position
    """

    result = await conn.execute(text(columns_query), {"table_name": table_name})
    columns_info = []

    print(f"\nColumns in {table_name}:")
    for row in result:
        col_name, col_type, is_nullable, default, constraint = row
        nullable_str = "NULL" if is_nullable == 'YES' else "NOT NULL"
        default_str = f" DEFAULT {default}" if default else ""
        constraint_str = f" {constraint}" if constraint else ""

        columns_info.append((col_name, col_type, is_nullable, default))
        print(f"  - {col_name} ({col_type}) {nullable_str}{default_str}{constraint_str}")

    # Get values to insert
    print("\n--- Values to INSERT ---")
    insert_columns = []
    insert_params = {}

    while True:
        col = input("Enter column name to insert (or press Enter to finish): ").strip()
        if not col:
            break

        # Find column info
        col_info = next((c for c in columns_info if c[0] == col), None)
        if not col_info:
            print(f"Warning: Column '{col}' not found in table")
            continue

        col_name, col_type, is_nullable, default = col_info

        # Skip if it has a default and user doesn't want to override
        if default and default not in ["nextval", "now()", "CURRENT_TIMESTAMP"]:
            use_default = input(f"Column has default value: {default}. Use default? (Y/n): ")
            if use_default.lower() != 'n':
                continue

        value = input(f"Enter value for {col} (type: {col_type}): ").strip()

        # Handle different data types
        if value.lower() == 'null':
            if is_nullable == 'NO':
                print(f"ERROR: Column {col} cannot be NULL")
                continue
            insert_columns.append(col)
            insert_params[col] = None
        elif col_type in ['integer', 'bigint', 'numeric', 'double precision', 'real']:
            insert_columns.append(col)
            try:
                insert_params[col] = float(value) if '.' in value else int(value)
            except ValueError:
                print(f"ERROR: Invalid number format for {col}")
                continue
        elif col_type in ['boolean']:
            insert_columns.append(col)
            insert_params[col] = value.lower() in ['true', 't', '1', 'yes']
        elif value.lower() == 'now()':
            # Special handling for timestamps
            insert_columns.append(col)
            insert_params[col] = None  # Will use NOW() in SQL
        else:
            insert_columns.append(col)
            insert_params[col] = value

    if not insert_columns:
        print("ERROR: At least one column value is required")
        return

    # Add automatic timestamps if they exist and not provided
    timestamp_cols = ['created_at', 'updated_at']
    for ts_col in timestamp_cols:
        if any(c[0] == ts_col for c in columns_info) and ts_col not in insert_columns:
            # Check if it has a default
            col_info = next((c for c in columns_info if c[0] == ts_col), None)
            if not col_info[3]:  # No default
                insert_columns.append(ts_col)
                insert_params[ts_col] = None  # Will use NOW()

    # Build INSERT query
    columns_str = ", ".join(insert_columns)
    values_list = []

    for col in insert_columns:
        if insert_params[col] is None and col in timestamp_cols:
            values_list.append("timezone('utc', now())")
        elif insert_params[col] is None:
            values_list.append("NULL")
        else:
            values_list.append(f":{col}")

    values_str = ", ".join(values_list)

    # Show preview
    print("\n--- INSERT preview ---")
    print(f"INSERT INTO {table_name} ({columns_str})")
    print(f"VALUES ({values_str})")
    print("\nValues:")
    for col in insert_columns:
        print(f"  {col}: {insert_params[col] if insert_params[col] is not None else 'NULL/NOW()'}")

    # Confirm
    confirm = input("\nExecute this INSERT? (y/N): ")
    if confirm.lower() != 'y':
        print("Insert cancelled")
        return

    # Execute insert with RETURNING *
    insert_query = f"""
        INSERT INTO {table_name} ({columns_str})
        VALUES ({values_str})
        RETURNING *
    """

    # Remove None values that will use SQL functions
    clean_params = {k: v for k, v in insert_params.items() if v is not None}

    result = await conn.execute(text(insert_query), clean_params)
    inserted_row = result.first()
    await conn.commit()

    print(f"\n✓ Inserted successfully!")

    # Show the inserted record
    if inserted_row:
        print("\nInserted record:")
        col_names = [c[0] for c in columns_info]
        for i, value in enumerate(inserted_row):
            if i < len(col_names):
                print(f"  {col_names[i]}: {value}")

async def update_record(conn):
    """
    Update existing records in a table.

    This function:
    1. Prompts for table name and validates it exists
    2. Shows available columns with data types
    3. Builds WHERE clause interactively (supports multiple conditions)
    4. Builds SET clause interactively (supports multiple columns)
    5. Shows current values before update
    6. Previews the UPDATE SQL statement
    7. Executes upon confirmation
    8. Shows new values after update

    Safety features:
    - Requires at least one WHERE condition (no accidental full table updates)
    - Shows row count that will be affected
    - Requires explicit confirmation
    - Automatically handles data type conversion
    - Adds updated_at timestamp if column exists
    """
    # Get table name
    table_name = input("\nEnter table name: ").strip()

    # Check if table exists
    table_check = await conn.execute(
        text("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_name = :table_name
            )
        """),
        {"table_name": table_name}
    )

    if not table_check.scalar():
        print(f"ERROR: Table '{table_name}' does not exist")
        return

    # Show available columns
    columns = await get_table_columns(conn, table_name)
    print(f"\nColumns in {table_name}:")
    for col_name, col_type in columns:
        print(f"  - {col_name} ({col_type})")

    # Get WHERE clause
    print("\n--- WHERE clause to identify the row(s) ---")
    where_conditions = []
    where_params = {}

    while True:
        col = input("Enter column name for WHERE clause (or press Enter to finish): ").strip()
        if not col:
            break

        if not any(c[0] == col for c in columns):
            print(f"Warning: Column '{col}' not found in table")
            continue

        # Find column type
        col_type = next((c[1] for c in columns if c[0] == col), "unknown")

        value = input(f"Enter value for {col} (type: {col_type}): ").strip()

        # Convert value based on column type
        if value.lower() == 'null':
            where_conditions.append(f"{col} IS NULL")
        else:
            where_conditions.append(f"{col} = :where_{col}")

            # Handle different data types for WHERE clause
            if col_type in ['integer', 'bigint', 'numeric', 'double precision', 'real']:
                try:
                    where_params[f"where_{col}"] = float(value) if '.' in value else int(value)
                except ValueError:
                    print(f"ERROR: Invalid number format for {col}")
                    continue
            elif col_type in ['boolean']:
                where_params[f"where_{col}"] = value.lower() in ['true', 't', '1', 'yes']
            else:
                # Remove surrounding quotes if user added them
                if value.startswith("'") and value.endswith("'"):
                    value = value[1:-1]
                elif value.startswith('"') and value.endswith('"'):
                    value = value[1:-1]
                where_params[f"where_{col}"] = value

    if not where_conditions:
        print("ERROR: At least one WHERE condition is required")
        return

    where_clause = " AND ".join(where_conditions)

    # Get columns to update
    print("\n--- Columns to UPDATE ---")
    update_columns = []
    update_params = {}

    while True:
        col = input("Enter column name to update (or press Enter to finish): ").strip()
        if not col:
            break

        if not any(c[0] == col for c in columns):
            print(f"Warning: Column '{col}' not found in table")
            continue

        # Find column type
        col_type = next((c[1] for c in columns if c[0] == col), "unknown")

        value = input(f"Enter new value for {col} (type: {col_type}): ").strip()

        # Handle different data types
        if value.lower() == 'null':
            update_columns.append(f"{col} = NULL")
        elif col_type in ['integer', 'bigint', 'numeric', 'double precision', 'real']:
            update_columns.append(f"{col} = :update_{col}")
            try:
                update_params[f"update_{col}"] = float(value) if '.' in value else int(value)
            except ValueError:
                print(f"ERROR: Invalid number format for {col}")
                continue
        elif col_type in ['boolean']:
            update_columns.append(f"{col} = :update_{col}")
            update_params[f"update_{col}"] = value.lower() in ['true', 't', '1', 'yes']
        else:
            update_columns.append(f"{col} = :update_{col}")
            # Remove surrounding quotes if user added them
            if value.startswith("'") and value.endswith("'"):
                value = value[1:-1]
            elif value.startswith('"') and value.endswith('"'):
                value = value[1:-1]
            update_params[f"update_{col}"] = value

    if not update_columns:
        print("ERROR: At least one column to update is required")
        return

    # Add automatic updated_at if it exists
    if any(c[0] == 'updated_at' for c in columns) and 'updated_at' not in [col.split(' = ')[0] for col in update_columns]:
        update_columns.append("updated_at = timezone('utc', now())")

    update_clause = ", ".join(update_columns)

    # Show current values
    print("\n--- Current values ---")
    select_columns = list(set([col.split(' = ')[0] for col in update_columns] + [col.split(' = ')[0] for col in where_conditions]))

    current_query = f"""
        SELECT {', '.join(select_columns)}
        FROM {table_name}
        WHERE {where_clause}
    """

    result = await conn.execute(text(current_query), where_params)
    rows = result.fetchall()

    if not rows:
        print("No rows found matching WHERE criteria")
        return

    print(f"Found {len(rows)} row(s):")
    for i, row in enumerate(rows):
        print(f"\nRow {i+1}:")
        for j, col_name in enumerate(select_columns):
            print(f"  {col_name}: {row[j]}")

    # Show what will be updated
    print("\n--- UPDATE preview ---")
    print(f"UPDATE {table_name}")
    print(f"SET {update_clause}")
    print(f"WHERE {where_clause}")
    print(f"\nThis will affect {len(rows)} row(s)")

    # Confirm
    confirm = input("\nExecute this UPDATE? (y/N): ")
    if confirm.lower() != 'y':
        print("Update cancelled")
        return

    # Execute update
    all_params = {**where_params, **update_params}
    update_query = f"""
        UPDATE {table_name}
        SET {update_clause}
        WHERE {where_clause}
    """

    result = await conn.execute(text(update_query), all_params)
    await conn.commit()

    print(f"\n✓ Updated {result.rowcount} row(s) successfully!")

    # Show new values
    print("\n--- New values ---")
    verify_result = await conn.execute(text(current_query), where_params)
    new_rows = verify_result.fetchall()

    for i, row in enumerate(new_rows):
        print(f"\nRow {i+1}:")
        for j, col_name in enumerate(select_columns):
            print(f"  {col_name}: {row[j]}")

async def main():
    """
    Main entry point that lets user choose between UPDATE or INSERT operations.
    """
    db_url = os.getenv('DATABASE_URL')
    if not db_url:
        print("ERROR: DATABASE_URL environment variable not set")
        return

    # Convert to async URL
    if db_url.startswith('postgresql://'):
        db_url = db_url.replace('postgresql://', 'postgresql+asyncpg://', 1)

    # Show which database we're connecting to (masked)
    host_part = db_url.split('@')[1].split('/')[0] if '@' in db_url else 'unknown'
    print(f"Connecting to database at: {host_part}")

    print("\n=== Railway Database Manager ===")
    print("1. UPDATE existing record(s)")
    print("2. INSERT new record")

    choice = input("\nChoose operation (1 or 2): ").strip()

    engine = create_async_engine(db_url)
    async with engine.connect() as conn:
        if choice == '1':
            await update_record(conn)
        elif choice == '2':
            await insert_record(conn)
        else:
            print("Invalid choice. Please run the script again.")
    await engine.dispose()

if __name__ == '__main__':
    asyncio.run(main())