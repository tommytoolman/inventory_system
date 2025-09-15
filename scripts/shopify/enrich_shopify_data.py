import asyncio
import csv
import logging
from typing import Dict
from dotenv import load_dotenv
from sqlalchemy import select
from sqlalchemy.orm import selectinload
import argparse

# Add project root to path to resolve app imports
import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from app.services.shopify.client import ShopifyGraphQLClient
from app.database import async_session
from app.models.shopify import ShopifyListing
from app.models.platform_common import PlatformCommon

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class ShopifyEnrichmentService:
    """
    Handles the logic for enriching local Shopify data from multiple sources.

    This service is designed to work in two phases and with two data sources:

    --- DATA SOURCES ---
    
    1. API-Only (`--source api`): Uses the live Shopify API as the single source of truth.
    2. CSV + API (`--source csv`): Uses a backup CSV as the primary source for historical
        data, supplemented with live data (like status and price) from the API.

    --- PHASES ---
    Phase 1 (Enrich Locally): Updates the local database records. This is the default.
        
        # First, run a dry-run to see what will change
        python scripts/shopify/enrich_shopify_data.py --source api --dry-run

        # If the dry-run looks good, run it for real
        python scripts/shopify/enrich_shopify_data.py --source api
    
    Phase 2 (Push to Shopify): Pushes enriched data back to the live Shopify store. This
    is enabled with the --push-to-shopify flag and is a future implementation.
    
        # First, run a dry-run
        python scripts/shopify/enrich_shopify_data.py --source csv path/to/your/backup.csv --dry-run

        # If it looks good, run it for real
        python scripts/shopify/enrich_shopify_data.py --source csv path/to/your/backup.csv --push-to-shopify
        

    """

    def __init__(self, db_session, shopify_client):
        self.db = db_session
        self.client = shopify_client

    def load_backup_csv(self, file_path: str) -> Dict[str, Dict]:
        """Loads the backup CSV data into a dictionary keyed by shopify_legacy_id."""
        logging.info(f"Loading backup data from {file_path}...")
        backup_data = {}
        try:
            with open(file_path, mode='r', newline='', encoding='utf-8') as csvfile:
                reader = csv.DictReader(csvfile)
                for row in reader:
                    legacy_id = row.get('shopify_legacy_id')
                    if legacy_id:
                        backup_data[legacy_id.strip()] = row
            logging.info(f"✅ Loaded {len(backup_data)} records from backup CSV.")
            return backup_data
        except FileNotFoundError:
            logging.error(f"❌ ERROR: Backup file not found at '{file_path}'. Aborting.")
            sys.exit(1)

    def fetch_live_api_data(self) -> Dict[str, Dict]:
        """Fetches all products from the Shopify API and returns a lookup dictionary."""
        logging.info("Fetching all product summaries from Shopify API...")
        products_from_api = self.client.get_all_products_summary()
        if not products_from_api:
            logging.error("❌ No products returned from Shopify API.")
            return {}
        
        api_data_map = {
            str(p['legacyResourceId']): p for p in products_from_api if p.get('legacyResourceId')
        }
        logging.info(f"✅ Found {len(api_data_map)} products from API.")
        return api_data_map

    async def fetch_local_db_records(self) -> Dict[str, PlatformCommon]:
        """Fetches all local PlatformCommon records for Shopify and returns a lookup dictionary."""
        logging.info("Fetching all existing Shopify records from the database...")
        stmt = (
            select(PlatformCommon)
            .options(selectinload(PlatformCommon.shopify_listing))
            .where(PlatformCommon.platform_name == 'shopify')
        )
        result = await self.db.execute(stmt)
        platform_common_records = result.scalars().all()
        
        local_map = {
            str(pc.shopify_listing.shopify_legacy_id): pc
            for pc in platform_common_records if pc.shopify_listing
        }
        
        logging.info(f"✅ Found {len(local_map)} local records.")
        return local_map

    async def enrich_local_db(self, local_records: Dict, source_data: Dict, dry_run: bool, source_is_backup: bool):
        """Phase 1: Updates local DB records using the chosen data source."""
        logging.info(f"Phase 1: Enriching local DB using {'BACKUP CSV + API' if source_is_backup else 'API ONLY'} as source...")
        update_count = 0

        # --- FIX: Iterate through the local records that need updating, not the source data. ---
        for legacy_id, local_platform_common in local_records.items():
            
            # Find the corresponding data from our chosen source (API or CSV)
            source_item = source_data.get(legacy_id)

            if not source_item:
                logging.warning(f"No source data found for local item {legacy_id}. Skipping.")
                continue

            # Ensure we have the related shopify_listing to update
            if local_platform_common and local_platform_common.shopify_listing:
                local_listing = local_platform_common.shopify_listing

                # --- Update the shopify_listings table ---
                local_listing.title = source_item.get('title')
                local_listing.handle = source_item.get('handle')
                local_listing.vendor = source_item.get('vendor')
                local_listing.status = source_item.get('status')
                local_listing.category_full_name = source_item.get('category_full_name', source_item.get('productType'))
                local_listing.category_gid = source_item.get('category_gid')
                local_listing.category_name = source_item.get('category_name')

                # Extract price
                price = source_item.get('price', '0')
                variants = source_item.get('variants', {}).get('nodes', [])
                if variants and variants[0]:
                    price = variants[0].get('price')

                try:
                    local_listing.price = float(price)
                except (ValueError, TypeError, AttributeError): pass
                
                # Store the raw source data in extended_attributes
                local_listing.extended_attributes = source_item.get('_raw', source_item)
                
                # --- Update the platform_common table ---
                local_platform_common.listing_url = source_item.get('onlineStoreUrl')
                
                update_count += 1
                if dry_run:
                    logging.info(f"[DRY RUN] Would update record for Shopify ID {legacy_id}")
            else:
                logging.warning(f"Shopify product ID {legacy_id} found in source but has no local DB record. Skipping enrichment.")
                
        if not dry_run and update_count > 0:
            logging.info(f"Committing updates for {update_count} records...")
            await self.db.commit()
            logging.info("✅ Phase 1 complete: Database enrichment successful.")
        elif dry_run:
            logging.info(f"✅ [DRY RUN] Finished. {update_count} records would be updated.")
        else:
            logging.info("No records found to update.")

    async def push_updates_to_shopify(self, local_records: Dict, dry_run: bool = True):
        """Phase 2: Pushes enriched data from local DB back to Shopify. (Future)"""
        logging.info("Phase 2: Pushing enriched data from local DB to Shopify API...")
        if dry_run:
            logging.info("[DRY RUN] Phase 2 is not executed in dry-run mode.")
            return
        
        logging.warning("Phase 2 (push to Shopify) is not yet implemented.")

async def run_enrichment_process(source: str, csv_file: str, dry_run: bool, push_to_shopify: bool):
    """Main function to orchestrate the enrichment process based on the chosen source."""
    client = ShopifyGraphQLClient()
    async with async_session() as db:
        service = ShopifyEnrichmentService(db, client)
        
        source_data = {}
        source_is_backup = False

        if source == 'api':
            source_data = service.fetch_live_api_data()
        elif source == 'csv':
            if not csv_file:
                logging.error("❌ --source csv requires a file path.")
                return
            source_data = service.load_backup_csv(csv_file)
            source_is_backup = True
        
        local_records = await service.fetch_local_db_records()

        # --- FIX: Swapped the arguments to the correct order. ---
        await service.enrich_local_db(local_records, source_data, dry_run, source_is_backup)

        if push_to_shopify:
            await service.push_updates_to_shopify(local_records, dry_run)


if __name__ == "__main__":
    # --- FIX: Cleaned up the docstring to be more accurate. ---
    parser = argparse.ArgumentParser(
        description="Enrich local Shopify database records from a chosen source (live API or backup CSV)."
    )
    parser.add_argument(
        "--source", 
        choices=['api', 'csv'], 
        required=True, 
        help="The data source for enrichment."
    )
    parser.add_argument(
        "csv_file", 
        nargs='?', 
        default=None, 
        help="Path to the backup CSV file (required if --source is 'csv')."
    )
    parser.add_argument(
        "--dry-run", 
        action="store_true", 
        help="Simulate the process without writing to the database."
    )
    parser.add_argument(
        "--push-to-shopify", 
        action="store_true", 
        help="Enable Phase 2: Push enriched data from the local DB back to the Shopify API."
    )
    args = parser.parse_args()

    asyncio.run(run_enrichment_process(source=args.source, csv_file=args.csv_file, dry_run=args.dry_run, push_to_shopify=args.push_to_shopify))