import json
import os
import sys
import dotenv

from pathlib import Path
from sqlalchemy import create_engine, Column, Integer, String, UniqueConstraint
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.ext.declarative import declarative_base

from app.core.config import get_settings
from app.models.vr import VRAcceptedBrand # If your model is here


# --- Add Project Root to Python Path ---
# This allows the script to find other modules like app.core.config if needed,
# and ensures consistent behavior when run from different locations.
# Assumes this script might be in app/cli/populate_vr_brands.py
# Adjust if your script is located elsewhere or if your project root is different.
try:
    # Calculate project root (assuming this script is in app/cli or similar)
    SCRIPT_DIR = Path(__file__).resolve().parent
    PROJECT_ROOT = SCRIPT_DIR.parent.parent 
    if PROJECT_ROOT not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    print(f"Script running with project root: {PROJECT_ROOT}")
except NameError:
    # __file__ is not defined if running in some interactive environments directly
    # In that case, ensure your PYTHONPATH or current dir is the project root.
    print("Warning: __file__ not defined. Ensure project root is in PYTHONPATH.")
    PROJECT_ROOT = Path.cwd() # Fallback, adjust if necessary


# --- Database Configuration ---
settings = get_settings()
DATABASE_URL = settings.DATABASE_URL

if "+asyncpg" in DATABASE_URL:
    SYNC_DATABASE_URL = DATABASE_URL.replace("+asyncpg", "") # Use psycopg2 (default)
    print(f"Original DATABASE_URL (async): {DATABASE_URL}")
    print(f"Using synchronous DATABASE_URL for this script: {SYNC_DATABASE_URL}")
else:
    SYNC_DATABASE_URL = DATABASE_URL
    print(f"Using DATABASE_URL for this script: {SYNC_DATABASE_URL}")

engine = create_engine(SYNC_DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

# --- SQLAlchemy Model Definition ---
# This should match the table created by your Alembic migration 99c07d825b2c
class VRAcceptedBrand(Base):
    __tablename__ = "vr_accepted_brands"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    vr_brand_id = Column(Integer, nullable=True, unique=True, index=True)
    name = Column(String, nullable=False, unique=True, index=True) # Store original name
    name_normalized = Column(String, nullable=False, unique=True, index=True) # For lookups

    def __repr__(self):
        return f"<VRAcceptedBrand(name='{self.name}', vr_brand_id={self.vr_brand_id})>"

# --- Main Population Function ---
def populate_vr_brands(db: Session, json_filepath_str: str):
    json_filepath = Path(json_filepath_str)
    if not json_filepath.is_file():
        print(f"Error: JSON file not found at {json_filepath}")
        return

    print(f"Loading V&R brands from {json_filepath}...")
    try:
        with open(json_filepath, 'r', encoding='utf-8') as f:
            raw_brand_data_list = json.load(f)
    except json.JSONDecodeError as e:
        print(f"Error decoding JSON from {json_filepath}: {e}")
        return
    except Exception as e:
        print(f"Error reading JSON file {json_filepath}: {e}")
        return

    if not isinstance(raw_brand_data_list, list):
        print("Error: JSON file should contain a list of brand objects.")
        return

    print(f"Processing {len(raw_brand_data_list)} raw entries from JSON for de-duplication...")

    # --- De-duplicate and process brands from JSON before DB interaction ---
    # Prioritize entries with IDs if duplicates by normalized name exist
    processed_brands_for_db = {} # Key: normalized_name, Value: brand_entry_to_use

    for brand_entry in raw_brand_data_list:
        if not isinstance(brand_entry, dict):
            print(f"Warning: Skipping raw entry as it's not a dictionary: {brand_entry}")
            continue

        name = brand_entry.get("name")
        vr_id_from_json = brand_entry.get("id")

        if not name or not isinstance(name, str) or not name.strip():
            print(f"Warning: Skipping raw entry due to missing or empty name: {brand_entry}")
            continue
        
        name_stripped = name.strip()
        normalized_name = name_stripped.lower()
        
        current_processed_vr_id = None
        if vr_id_from_json is not None:
            try:
                current_processed_vr_id = int(vr_id_from_json)
            except (ValueError, TypeError):
                pass # Keep as None

        # If this normalized name is already seen, decide if this new entry is "better"
        # (e.g., if the new one has an ID and the old one didn't)
        if normalized_name in processed_brands_for_db:
            existing_entry = processed_brands_for_db[normalized_name]
            if existing_entry.get("id") is None and current_processed_vr_id is not None:
                # Current entry has an ID, previous one didn't; prefer current
                processed_brands_for_db[normalized_name] = {
                    "name": name_stripped, # Use the name from this entry
                    "vr_brand_id": current_processed_vr_id,
                    "name_normalized": normalized_name
                }
            # else: keep the existing entry (it either already had an ID, or both are None)
        else:
            # New normalized name
            processed_brands_for_db[normalized_name] = {
                "name": name_stripped,
                "vr_brand_id": current_processed_vr_id,
                "name_normalized": normalized_name
            }
            
    unique_brand_list_from_json = list(processed_brands_for_db.values())
    print(f"Found {len(unique_brand_list_from_json)} unique brands (by normalized name) in the JSON file.")

    added_to_db_count = 0
    skipped_db_duplicates_count = 0
    updated_in_db_count = 0
    
    print(f"Inserting/updating {len(unique_brand_list_from_json)} unique brands into the database...")

    for idx, brand_to_insert in enumerate(unique_brand_list_from_json):
        # Check against the database
        existing_db_brand = db.query(VRAcceptedBrand).filter(
            VRAcceptedBrand.name_normalized == brand_to_insert["name_normalized"]
        ).first()

        if not existing_db_brand:
            db_brand_object = VRAcceptedBrand(
                name=brand_to_insert["name"],
                name_normalized=brand_to_insert["name_normalized"],
                vr_brand_id=brand_to_insert["vr_brand_id"]
            )
            db.add(db_brand_object)
            added_to_db_count += 1
        else:
            # Brand already exists in DB. Optionally update vr_brand_id if it was NULL.
            if existing_db_brand.vr_brand_id is None and brand_to_insert["vr_brand_id"] is not None:
                print(f"Updating DB entry for '{existing_db_brand.name}' with V&R ID: {brand_to_insert['vr_brand_id']}")
                existing_db_brand.vr_brand_id = brand_to_insert["vr_brand_id"]
                updated_in_db_count +=1
            skipped_db_duplicates_count += 1
            
        if (idx + 1) % 500 == 0: # Commit in batches
            try:
                db.commit()
                print(f"Committed batch {idx + 1}/{len(unique_brand_list_from_json)}...")
            except Exception as e:
                db.rollback()
                print(f"Error committing batch to database: {e}")
                raise # Stop on error

    try:
        db.commit() # Final commit
        print("\n--- Population Summary ---")
        print(f"Brands from JSON after de-duplication: {len(unique_brand_list_from_json)}")
        print(f"Successfully added to DB: {added_to_db_count}")
        if updated_in_db_count > 0:
            print(f"Updated in DB (added missing vr_brand_id): {updated_in_db_count}")
        print(f"Skipped (already in DB by normalized name): {skipped_db_duplicates_count}")
        print(f"Total entries processed from JSON originally: {len(raw_brand_data_list)}")
    except Exception as e:
        db.rollback()
        print(f"Error during final commit to database: {e}")

def main():
    # --- Determine Path to JSON File ---
    default_json_path = PROJECT_ROOT / "app" / "services" / "vintageandrare" / "vintage_and_rare_brands_REFINED.json"
    
    json_file_arg = input(f"Enter path to V&R brands JSON file (default: {default_json_path}): ")
    if not json_file_arg:
        json_filepath_to_load = default_json_path
    else:
        json_filepath_to_load = Path(json_file_arg)

    if not json_filepath_to_load.is_file():
        print(f"FATAL: JSON file not found at specified path: {json_filepath_to_load}")
        print("Please ensure the file exists or correct the path.")
        print(f"If using default, it expected the file at: {default_json_path.resolve()}")
        print(f"Current working directory is: {Path.cwd()}")
        return

    # Get a database session
    db = SessionLocal()
    try:
        populate_vr_brands(db, str(json_filepath_to_load))
    finally:
        db.close()
        print("Database session closed.")

if __name__ == "__main__":
    print("Starting V&R Accepted Brands Population Script...")
    # Make sure your DATABASE_URL at the top is correctly set for your environment!
    if "user:password@host:port/dbname" in DATABASE_URL:
        print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        print("!!! CRITICAL: Update DATABASE_URL in the script before running. !!!")
        print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
    else:
        main()