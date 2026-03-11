# scripts/create_test_db.py

"""
This creates a backup of inventory, drops inventory_test_2 and recreates it and adds in sync_events table.
"""

import os
import subprocess
import sys
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError

# --- Configuration ---
# The name of your PRODUCTION database, which is the source of the clone.
PROD_DB_NAME = "inventory"

# The SQL to create the sync_events table and its related objects.
ADD_SYNC_EVENTS_SQL = """
-- Create the sync_events table
CREATE TABLE sync_events (
    id SERIAL PRIMARY KEY,
    sync_run_id UUID NOT NULL,
    platform_name VARCHAR NOT NULL,
    product_id INTEGER,
    platform_common_id INTEGER,
    external_id VARCHAR NOT NULL,
    change_type VARCHAR NOT NULL,
    change_data JSON NOT NULL,
    status VARCHAR NOT NULL DEFAULT 'pending',
    detected_at TIMESTAMP DEFAULT NOW(),
    processed_at TIMESTAMP,
    notes TEXT,
    CONSTRAINT sync_events_product_id_fkey
        FOREIGN KEY (product_id) REFERENCES products(id),
    CONSTRAINT sync_events_platform_common_id_fkey
        FOREIGN KEY (platform_common_id) REFERENCES platform_common(id)
);

-- Create indexes for performance
CREATE INDEX idx_sync_events_sync_run_id ON sync_events(sync_run_id);
CREATE INDEX idx_sync_events_status ON sync_events(status);
CREATE INDEX idx_sync_events_platform_name ON sync_events(platform_name);
CREATE INDEX idx_sync_events_detected_at ON sync_events(detected_at);
CREATE INDEX idx_sync_events_product_id ON sync_events(product_id);
CREATE INDEX idx_sync_events_platform_common_id ON sync_events(platform_common_id);

-- Add performance index for common queries
CREATE INDEX idx_sync_events_platform_external ON sync_events (platform_name, external_id);

-- Add check constraint for status values
ALTER TABLE sync_events ADD CONSTRAINT sync_events_status_check
    CHECK (status IN ('pending', 'processed', 'error'));

-- Add check constraint for change_type values
ALTER TABLE sync_events ADD CONSTRAINT sync_events_change_type_check
    CHECK (change_type IN ('new_listing', 'price', 'status', 'removed_listing', 'title', 'description'));

-- *** CRITICAL: Add unique constraint to prevent duplicates ***
ALTER TABLE sync_events 
ADD CONSTRAINT sync_events_platform_external_change_unique 
UNIQUE (platform_name, external_id, change_type);

"""

def run_command(command):
    """Helper function to run a shell command and exit on error."""
    try:
        subprocess.run(command, shell=True, check=True, text=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        print(f"❌ Error executing command: {e.cmd}")
        print(f"   Return code: {e.returncode}")
        print(f"   Output (stdout):\n{e.stdout}")
        print(f"   Output (stderr):\n{e.stderr}")
        sys.exit(1)

def main():
    """Main function to orchestrate the database setup."""
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("❌ Error: DATABASE_URL environment variable is not set.")
        sys.exit(1)
        
    try:
        url_object = make_url(db_url)
        test_db_name = url_object.database
        if not test_db_name:
            print("❌ Error: Could not find database name in DATABASE_URL.")
            sys.exit(1)
    except Exception as e:
        print(f"❌ Error parsing DATABASE_URL: {e}")
        sys.exit(1)

    # **NEW**: Force a synchronous driver for this script's operations.
    # This prevents errors if the DATABASE_URL is for an async driver (e.g., asyncpg).
    sync_url_object = url_object.set(drivername="postgresql+psycopg2")

    print(f"--- Starting test database setup for '{test_db_name}' ---")
    print(f"Source (Production): '{PROD_DB_NAME}'")

    # Step 1a: Terminate all active connections to the test database
    print(f"➡️ Step 1a: Terminating existing connections to '{test_db_name}'...")
    try:
        # **MODIFIED**: Use the sync URL to connect to the 'postgres' maintenance DB
        maintenance_url = sync_url_object.set(database="postgres")
        engine = create_engine(maintenance_url)
        with engine.connect() as connection:
            with connection.begin():
                terminate_sql = text(f"""
                SELECT pg_terminate_backend(pid)
                FROM pg_stat_activity
                WHERE datname = :db_name AND pid <> pg_backend_pid();
                """)
                connection.execute(terminate_sql, {"db_name": test_db_name})
        print("✅ Active connections terminated.")
    except Exception as e:
        print(f"   ⚠️  Could not terminate connections. This is normal if the DB doesn't exist yet. Error: {e}")

    # Step 1b: Drop the existing test database
    print(f"➡️ Step 1b: Dropping database '{test_db_name}' if it exists...")
    run_command(f"dropdb --if-exists {test_db_name}")
    print("✅ Dropped successfully.")

    # Step 2: Create the new database
    print(f"➡️ Step 2: Creating new database '{test_db_name}'...")
    run_command(f"createdb {test_db_name}")
    print("✅ Created successfully.")

    # Step 3: Dump production and restore to test
    print(f"➡️ Step 3: Cloning data from '{PROD_DB_NAME}' to '{test_db_name}'...")
    clone_command = f"pg_dump {PROD_DB_NAME} | psql {test_db_name}"
    run_command(clone_command)
    print("✅ Cloned successfully.")

    # Step 4: Create the sync_events table with all constraints and indexes
    print(f"➡️ Step 4: Adding 'sync_events' table with unique constraints to '{test_db_name}'...")
    try:
        # **MODIFIED**: Use the sync URL to connect to the new test database
        engine = create_engine(sync_url_object)
        with engine.connect() as connection:
            with connection.begin():
                connection.execute(text(ADD_SYNC_EVENTS_SQL))
        print("✅ 'sync_events' table created successfully with unique constraint!")
    except OperationalError as e:
        print(f"❌ Error connecting to the database or executing SQL: {e}")
        sys.exit(1)

    print(f"\n🎉 --- Test database '{test_db_name}' is ready with duplicate prevention! ---")

if __name__ == "__main__":
    main()