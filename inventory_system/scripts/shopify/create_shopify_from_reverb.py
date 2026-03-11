"""
Create Shopify listings from existing Reverb products
Based on the working V&R → Shopify script but using Reverb as source

This script:
1. Queries products that exist in Reverb but NOT in Shopify
2. Creates the database linkage (platform_common + shopify_listings)
3. Creates actual Shopify products via API
4. Mirrors Reverb status exactly

python scripts/shopify/create_shopify_from_reverb.py --limit 5

python scripts/shopify/create_shopify_from_reverb.py --id 91172256

# Create the first 3 live listings in Shopify
python scripts/shopify/create_shopify_from_reverb.py --limit 3 --live-run

# Create ALL live listings in Shopify (use with caution)
python scripts/shopify/create_shopify_from_reverb.py --live-run

"""

import asyncio
import aiohttp
import os
import sys
import csv
import time
import json
import logging
import argparse
import pandas as pd
from pathlib import Path
from dotenv import load_dotenv
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any

# Add the parent directory to the path so we can import app modules
sys.path.append(str(Path(__file__).parent.parent))

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text

from app.core.utils import ImageTransformer, ImageQuality
from app.database import async_session
from app.core.enums import ProductStatus
from app.models.product import Product, ProductCondition
from app.models.platform_common import PlatformCommon, ListingStatus, SyncStatus
from app.models.shopify import ShopifyListing
from app.models.reverb import ReverbListing
from app.services.reverb.client import ReverbClient
from app.services.shopify.client import ShopifyGraphQLClient

from scripts.reverb.get_reverb_listings import get_reverb_listings

load_dotenv()
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


class ReverbToShopifyCreator:
    """Creates Shopify listings from Reverb products using a clear, sequential process."""

    def __init__(self, db_session: AsyncSession, shopify_client: ShopifyGraphQLClient):
        self.db = db_session
        self.shopify_client = shopify_client
        
        reverb_api_key = os.getenv("REVERB_API_KEY")
        if not reverb_api_key:
            raise ValueError("REVERB_API_KEY not found in environment variables. Please check your .env file.")
        self.reverb_client = ReverbClient(api_key=reverb_api_key)
        
        self.status_mapping = {
            'live': 'ACTIVE',
            'sold': 'ARCHIVED',
            'ended': 'ARCHIVED',
            'draft': 'DRAFT'
        }
        
        self.DEFAULT_LOCATION_GID = None
        self._ensure_location_gid()

    def _ensure_location_gid(self):
        """Ensures the default location GID is set."""
        if not self.DEFAULT_LOCATION_GID:
            self.DEFAULT_LOCATION_GID = "gid://shopify/Location/109766639956" # Replace with your actual GID or a lookup
            print(f"🏢 Using default location GID: {self.DEFAULT_LOCATION_GID}")

    def _extract_max_res_images(self, listing_details: Dict[str, Any]) -> List[Dict[str, str]]:
        """Extracts the highest resolution images, prioritizing the Cloudinary preview_url."""
        images = []
        
        # Prioritize 'cloudinary_photos' as the definitive source, per your instruction.
        if 'cloudinary_photos' in listing_details and listing_details['cloudinary_photos']:
            print("  🖼️ Extracting images from Cloudinary...")
            for photo in listing_details['cloudinary_photos']:
                if photo.get('preview_url'):
                    images.append({'src': photo['preview_url']})
            return images

        # Use the 'photos' array as a fallback if cloudinary_photos is not present.
        if 'photos' in listing_details and listing_details['photos']:
            print("  🖼️ Using fallback 'photos' field for images...")
            for photo in listing_details.get('photos', []):
                full_link = photo.get('_links', {}).get('full', {}).get('href')
                if full_link:
                    images.append({'src': full_link})
            return images
            
        return []

    def prepare_shopify_product_data(self, reverb_listing: Dict[str, Any]) -> Dict[str, Any]:
        """Prepares the complete Shopify product structure from detailed Reverb listing data."""
        print("  🔧 Preparing data for Shopify...")
        
        title_parts = [
            str(reverb_listing['year']) if reverb_listing.get('year') else None,
            reverb_listing.get('make'),
            reverb_listing.get('model')
        ]
        title = ' '.join(part for part in title_parts if part)

        # Use the SKU if it exists, otherwise fall back to the listing ID for a unique handle.
        sku_or_id = reverb_listing.get('sku') or str(reverb_listing.get('id', ''))

        handle = self.generate_shopify_handle(
            reverb_listing.get('make', ''),
            reverb_listing.get('model', ''),
            sku_or_id
        )
        
        reverb_state_obj = reverb_listing.get('state', {})
        reverb_state = reverb_state_obj.get('slug', 'draft').lower() if isinstance(reverb_state_obj, dict) else 'draft'
        
        shopify_status = self.status_mapping.get(reverb_state, 'DRAFT')
        should_publish = shopify_status == 'ACTIVE'

        print(f"    📊 Status Mapping: Reverb '{reverb_state}' -> Shopify '{shopify_status}'")
        
        tags = self.generate_tags(reverb_listing)
        images = self._extract_max_res_images(reverb_listing)
        
        first_category = reverb_listing.get('categories', [{}])[0]
        product_type = first_category.get('full_name', 'Musical Instrument')

        product_input = {
            'title': title,
            'handle': handle,
            'descriptionHtml': reverb_listing.get('description', ''),
            'productType': product_type,
            'vendor': reverb_listing.get('make'),
            'status': shopify_status,
            'tags': tags
        }
        
        variant_data = {
            'price': str(float(reverb_listing.get('price', {}).get('amount', 0))),
            'sku': reverb_listing.get('sku', ''),
            'inventoryQuantities': [{"availableQuantity": int(reverb_listing.get('inventory', 1)), "locationId": self.DEFAULT_LOCATION_GID}],
            'inventoryPolicy': 'DENY',
            'inventoryItem': {'tracked': True}
        }
        
        return {
            'product_input': product_input,
            'variant_updates': variant_data,
            'images': images,
            'should_publish': should_publish,
            'shopify_status': shopify_status
        }
    
    async def create_complete_shopify_product(self, shopify_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Creates a complete product in Shopify using the prepared data."""
        try:
            print("  🚀 STEP 3.1: Creating Shopify product shell...")
            creation_result = self.shopify_client.create_product(shopify_data["product_input"])
            
            if not creation_result or "product" not in creation_result:
                print("    ❌ FAILED: Product shell creation returned no product.")
                return None
            product_id = creation_result["product"]["id"]
            print(f"    ✅ Product shell created with GID: {product_id}")

            print("  🚀 STEP 3.2: Updating variant with price and inventory...")
            variant_gid = creation_result["product"]["variants"]["edges"][0]["node"]["id"]
            self.shopify_client.update_variant_rest(variant_gid, shopify_data["variant_updates"])
            print("    ✅ Variant updated successfully.")

            if shopify_data["images"]:
                print("  🚀 STEP 3.3: Adding {len(shopify_data['images'])} images...")
                self.shopify_client.create_product_images(product_id, shopify_data["images"])
                print("    ✅ Images added successfully.")

            if shopify_data.get("should_publish", False):
                print("  🚀 STEP 3.4: Publishing product...")
                online_store_gid = self.shopify_client.get_online_store_publication_id()
                if online_store_gid:
                    self.shopify_client.publish_product_to_sales_channel(product_id, online_store_gid)
                    print("    ✅ Product published to Online Store.")
            
            return creation_result["product"]
        except Exception as e:
            print(f"  ❌ An error occurred during Shopify product creation: {e}")
            return None

    async def process_single_id(self, reverb_id: str, dry_run: bool = True):
        """Efficiently processes a single Reverb listing by its ID."""
        print("\n" + "="*50)
        print(f"🚀 Processing Single Reverb ID: {reverb_id}")
        print(f"   - Dry Run: {'Yes' if dry_run else 'No'}")
        print("="*50 + "\n")
        
        try:
            print(f"  STEP 1: Fetching full details for Reverb listing {reverb_id}...")
            listing_details = await self.reverb_client.get_listing_details(reverb_id)
            if not listing_details:
                print("  ❌ FAILED: Could not retrieve listing details. Skipping.")
                return
            
            # --- DEBUG LINE ADDED ---
            # Print the full API response object to inspect its structure
            print("\n--- [Reverb API Response] ---")
            print(json.dumps(listing_details, indent=4))
            print("--- [End of Response] ---\n")
            
            print("  ✅ Full details retrieved.")
            
            shopify_data = self.prepare_shopify_product_data(listing_details)
            
            if dry_run:
                print("  ---------- [DRY RUN] ----------")
                print(f"  TITLE: {shopify_data['product_input']['title']}")
                print(f"  STATUS: {shopify_data['shopify_status']}")
                print(f"  IMAGES: {len(shopify_data['images'])} found")
                print("  -----------------------------")
            else:
                print("  STEP 2: Initiating Shopify product creation...")
                shopify_product = await self.create_complete_shopify_product(shopify_data)
                if shopify_product:
                    print(f"  🎉 SUCCESS: Shopify product created with GID: {shopify_product['id']}")
                    
                    # --- ADD THIS BLOCK ---
                    print("  STEP 3: Creating local database records...")
                    await self._create_local_records(listing_details, shopify_product)
                    # --- END ADDED BLOCK ---
                    
                    await self.db.commit()
                else:
                    print("  ❌ FAILED: The Shopify creation process did not complete successfully.")

        except Exception as e:
            print(f"  💥 An unexpected error occurred while processing listing {reverb_id}: {e}")
            if not dry_run: await self.db.rollback()
        
        print("\n🏁 Process Complete!")

    async def run_importer(self, statuses: List[str], limit: Optional[int] = None, dry_run: bool = True):
        """The main processing function for batch importing."""
        print("\n" + "="*50)
        print("🚀 Starting Reverb -> Shopify Batch Importer")
        print(f"   - Statuses: {statuses}")
        print(f"   - Limit: {limit or 'All'}")
        print(f"   - Dry Run: {'Yes' if dry_run else 'No'}")
        print("="*50 + "\n")

        all_listings_to_process = []
        for status in statuses:
            summaries = await get_reverb_listings(state=status.strip(), detailed=False, limit=limit, output_format="none")
            all_listings_to_process.extend(summaries)

        if not all_listings_to_process:
            print("🏁 No listings found for the specified criteria. Process finished.")
            return

        if limit:
            all_listings_to_process = all_listings_to_process[:limit]

        print(f"\n🔥 Total listings to process: {len(all_listings_to_process)}\n")

        for i, listing_summary in enumerate(all_listings_to_process, 1):
            reverb_id = listing_summary.get("id")
            title_guess = f"{listing_summary.get('make', '')} {listing_summary.get('model', '')}"
            print(f"📦 Processing item {i}/{len(all_listings_to_process)}: {title_guess} (ID: {reverb_id})")
            
            await self.process_single_id(reverb_id, dry_run)
            await asyncio.sleep(1) 

    def generate_shopify_handle(self, brand: str, model: str, sku: str) -> str:
        """Generates a URL-friendly handle for a Shopify product."""
        import re
        parts = [str(part) for part in [brand, model, sku] if part and str(part).lower() != 'nan']
        text = '-'.join(parts).lower()
        text = re.sub(r'[^a-z0-9\-]+', '-', text)
        text = re.sub(r'-+', '-', text)
        return text.strip('-')

    def generate_tags(self, product: Dict[str, Any]) -> List[str]:
        """Generates a list of relevant tags for the Shopify product."""
        tags = set()
        if product.get('make'): tags.add(product['make'])
        if product.get('finish'): tags.add(product['finish'])
        if product.get('year'): tags.add(f"Year:{product['year']}")
        if product.get('condition', {}).get('display_name'): tags.add(product['condition']['display_name'])
        
        if product.get('categories'):
            category_name = product['categories'][0].get('full_name')
            if category_name:
                tags.add(category_name)
                
        # Add a specific tag if the item is sold or ended
        reverb_state_obj = product.get('state', {})
        reverb_state = reverb_state_obj.get('slug', '').lower() if isinstance(reverb_state_obj, dict) else ''
        if reverb_state in ['sold', 'ended']:
            tags.add("Sold Archive")
            tags.add("Gallery")
                
        return list(tags)
    
    async def _create_local_records(self, reverb_data: Dict[str, Any], shopify_data: Dict[str, Any]):
        """
        Creates the central Product, PlatformCommon, and ShopifyListing records for a new gallery item.
        """
        sku = reverb_data.get('sku')
        if not sku:
            logger.error("Cannot create local records: SKU is missing from Reverb data.")
            return

        logger.info(f"Creating local database records for gallery item with SKU: {sku}")

        # Step 1: Get or Create the master Product record
        product_stmt = select(Product).where(Product.sku.ilike(sku))
        product = (await self.db.execute(product_stmt)).scalar_one_or_none()

        if not product:
            logger.info(f"Master product for SKU {sku} not found. Creating a new one.")

            # --- DATA CLEANING BLOCK ---
            year_from_api = reverb_data.get('year')
            cleaned_year = None
            if year_from_api:
                try:
                    # Strip whitespace and convert to integer
                    cleaned_year = int(str(year_from_api).strip())
                except (ValueError, TypeError):
                    logger.warning(f"Could not convert year '{year_from_api}' to an integer for SKU {sku}. Setting to NULL.")
                    cleaned_year = None
            # --- END DATA CLEANING BLOCK ---

            # --- CONDITION MAPPING BLOCK ---
            reverb_condition_str = reverb_data.get('condition', {}).get('display_name', 'Good')
            condition_map = {
                "Mint": ProductCondition.EXCELLENT, # Or create a MINT in your enum
                "Excellent": ProductCondition.EXCELLENT,
                "Very Good": ProductCondition.VERYGOOD,
                "Good": ProductCondition.GOOD,
                "Fair": ProductCondition.FAIR,
                "Poor": ProductCondition.POOR
            }
            product_condition = condition_map.get(reverb_condition_str, ProductCondition.GOOD)
            # --- END CONDITION MAPPING BLOCK ---

            product = Product(
                sku=sku,
                brand=reverb_data.get('make'),
                model=reverb_data.get('model'),
                year=cleaned_year, # Use the new cleaned variable
                description=reverb_data.get('description'),
                base_price=float(reverb_data.get('price', {}).get('amount', 0)),
                condition=product_condition,
                status=ProductStatus.ARCHIVED
            )
            self.db.add(product)
            await self.db.flush()
        
        # Step 2: Get or Create the PlatformCommon link
        shopify_legacy_id = shopify_data.get('legacyResourceId')
        pc_stmt = select(PlatformCommon).where(
            PlatformCommon.platform_name == 'shopify',
            PlatformCommon.external_id == shopify_legacy_id
        )
        platform_common = (await self.db.execute(pc_stmt)).scalar_one_or_none()

        if not platform_common:
            logger.info(f"PlatformCommon link for Shopify ID {shopify_legacy_id} not found. Creating a new one.")
            platform_common = PlatformCommon(
                product_id=product.id,
                platform_name='shopify',
                external_id=shopify_legacy_id,
                # --- KEY REQUIREMENT: SET STATUS TO ARCHIVED ---
                status='archived', 
                sync_status=SyncStatus.SYNCED.value
            )
            self.db.add(platform_common)
            await self.db.flush()
        
        # Step 3: Get or Create the ShopifyListing specialist record
        sl_stmt = select(ShopifyListing).where(ShopifyListing.platform_id == platform_common.id)
        shopify_listing = (await self.db.execute(sl_stmt)).scalar_one_or_none()

        if not shopify_listing:
            logger.info(f"ShopifyListing record for PlatformCommon ID {platform_common.id} not found. Creating a new one.")
            shopify_listing = ShopifyListing(
                platform_id=platform_common.id,
                shopify_product_id=shopify_data.get('id'),
                shopify_legacy_id=shopify_legacy_id,
                handle=shopify_data.get('handle'),
                title=shopify_data.get('title'),
                # --- KEY REQUIREMENT: SET STATUS TO ARCHIVED ---
                status='ARCHIVED'
            )
            self.db.add(shopify_listing)
        
        logger.info(f"Successfully created/verified local records for Product #{product.id}.")


async def main():
    """Main function with CLI argument parsing."""
    parser = argparse.ArgumentParser(description="Create Shopify listings from Reverb products.")
    parser.add_argument("--statuses", type=str, default='live', help="Comma-separated Reverb statuses to process. Default: 'live'.")
    parser.add_argument("--limit", type=int, help="Limit the total number of products to process.")
    parser.add_argument("--live-run", action="store_true", help="Execute a live run. Default is 'dry-run'.")
    parser.add_argument("--id", type=str, help="Process a single Reverb listing by its specific ID.")
    args = parser.parse_args()
    
    is_dry_run = not args.live_run

    try:
        shopify_client = ShopifyGraphQLClient(safety_buffer_percentage=0.3)
        print(f"✅ Shopify client initialized (API Version: {shopify_client.api_version})")
        
        async with async_session() as db:
            creator = ReverbToShopifyCreator(db, shopify_client)
            
            # --- FIX for Logic Error ---
            # If a specific ID is provided, use the new, efficient single-process method.
            if args.id:
                await creator.process_single_id(args.id, dry_run=is_dry_run)
            # Otherwise, run the full batch process.
            else:
                statuses = [status.strip() for status in args.statuses.split(",")]
                await creator.run_importer(statuses=statuses, limit=args.limit, dry_run=is_dry_run)

    except Exception as e:
        print(f"\n💥 A critical error occurred: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())




# --------- ARCHIVE ---------------

class ReverbToShopifyCreatorOld:
    """Creates Shopify listings from Reverb products using proven V&R script logic"""
    
    def __init__(self, db_session: AsyncSession, shopify_client: ShopifyGraphQLClient):
        self.db = db_session
        self.shopify_client = shopify_client
        
        from app.services.category_mapping_service import CategoryMappingService
        self.category_service = CategoryMappingService(db_session)
        
        # Status mapping - mirrors your V&R script logic
        self.status_mapping = {
            'live': 'ACTIVE',      # Reverb live → Shopify ACTIVE
            'sold': 'ARCHIVED',    # Reverb sold → Shopify ARCHIVED (since no SOLD status)
            'ended': 'ARCHIVED',   # Reverb ended → Shopify ARCHIVED
            'draft': 'DRAFT'       # Reverb draft → Shopify DRAFT
        }
        
        # Default location GID (you'll need to set this)
        self.DEFAULT_LOCATION_GID = None  # Will be populated from client
    
    async def export_reverb_data_to_csv(self, output_file: str, reverb_status_filter: Optional[str] = None):
        """
        Export Reverb product data to a CSV file.
        """
        print(f"🔍 Exporting Reverb products (status filter: {reverb_status_filter or 'ALL'}) to {output_file}")
        
        # Query Reverb products
        products = await self.get_reverb_products_for_shopify(reverb_status_filter=reverb_status_filter)
        
        if not products:
            print("❌ No products found to export.")
            return
        
        # Write to CSV
        import csv
        with open(output_file, mode='w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=products[0].keys())
            writer.writeheader()
            writer.writerows(products)
        
        print(f"✅ Exported {len(products)} products to {output_file}")    
    
    async def fetch_reverb_listings(self, statuses: List[str]) -> List[Dict[str, Any]]:
        """
        Fetch listings from the Reverb API based on the given statuses.
        """
        print(f"🔍 Fetching Reverb listings with statuses: {statuses}")
        
        # Example API endpoint and parameters
        endpoint = "https://api.reverb.com/api/listings"
        headers = {
            "Authorization": f"Bearer {os.getenv('REVERB_API_TOKEN')}",  # Use your Reverb API token
            "Content-Type": "application/json"
        }
        params = {
            "state": ",".join(statuses),  # Pass statuses as a comma-separated string
            "per_page": 100,  # Adjust as needed
            "page": 1
        }
        
        listings = []
        try:
            while True:
                async with aiohttp.ClientSession() as session:
                    async with session.get(endpoint, headers=headers, params=params) as response:
                        if response.status != 200:
                            print(f"❌ Error fetching listings: {response.status} {await response.text()}")
                            break
                        
                        data = await response.json()
                        listings.extend(data.get("listings", []))
                        
                        # Check if there are more pages
                        if not data.get("next"):
                            break
                        
                        # Update the page parameter for the next request
                        params["page"] += 1
            
            print(f"✅ Fetched {len(listings)} listings from Reverb API")
            return listings
        
        except Exception as e:
            print(f"❌ Error fetching Reverb listings: {str(e)}")
            return []
    
    async def fetch_reverb_listings_via_api(self, state: str, limit: int = None) -> List[Dict[str, Any]]:
        """
        Fetch Reverb listings via the API using the proven get_reverb_listings function.

        Args:
            state (str): The listing state to fetch (e.g., 'live', 'sold', 'ended').
            limit (int, optional): The maximum number of listings to fetch. Defaults to None.

        Returns:
            List[Dict[str, Any]]: A list of Reverb listings.
        """
        print(f"🔄 Fetching Reverb listings with state: {state}")
        listings = await get_reverb_listings(
            state=state,
            detailed=False,  # Use basic mode for faster results
            limit=limit,
            output_format="none"  # We don't need to save the output here
        )
        return listings
    
    async def get_reverb_products_for_shopify(self, 
                                            reverb_status_filter: Optional[List[str]] = None,
                                            limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Get products from the Reverb API based on the given statuses.
        """
        if not reverb_status_filter:
            reverb_status_filter = ["live"]  # Default to live listings if no filter is provided
        
        # Fetch listings from the Reverb API
        products = []
        for status in reverb_status_filter:
            listings = await self.fetch_reverb_listings_via_api(state=status, limit=limit)
            products.extend(listings)
        
        # Transform the API response into the expected format
        transformed_products = []
        for listing in products:
            transformed_products.append({
                "product_id": listing.get("id"),
                "sku": listing.get("sku"),
                "brand": listing.get("make"),
                "model": listing.get("model"),
                "description": listing.get("description"),
                "base_price": listing.get("price", {}).get("amount"),
                "primary_image": listing.get("photos", [{}])[0].get("_links", {}).get("full", {}).get("href") if listing.get("photos") else None,
                "additional_images": [photo["_links"]["full"]["href"] for photo in listing.get("photos", []) if "_links" in photo and "full" in photo["_links"]],
                "category": listing.get("category", {}).get("full_name"),
                "condition": listing.get("condition"),
                "year": listing.get("year"),
                "finish": listing.get("finish"),
                "reverb_state": listing.get("state"),
                "reverb_listing_id": listing.get("id"),
                "reverb_slug": listing.get("slug"),
                "reverb_price": listing.get("price", {}).get("amount"),
                "reverb_currency": listing.get("price", {}).get("currency"),
                "inventory_quantity": listing.get("inventory"),
                "offers_enabled": listing.get("offers_enabled"),
                "reverb_created_at": listing.get("created_at"),
                "reverb_published_at": listing.get("published_at"),
                "extended_attributes": listing.get("extended_attributes"),
            })
        
        print(f"✅ Transformed {len(transformed_products)} listings into product format")
        return transformed_products
    
    async def get_reverb_products_for_shopify_db(self, 
                                            reverb_status_filter: Optional[str] = None,
                                            limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Get products that have Reverb listings but NO Shopify listings
        """
        
        # Fixed query with actual columns from reverb_listings table
        base_query = """
        SELECT 
            p.id as product_id,
            p.sku,
            p.brand,
            p.model,
            p.description,
            p.base_price,
            p.primary_image,
            p.additional_images,
            p.category,
            p.condition,
            p.year,
            p.decade,
            p.finish,
            p.created_at,
            r.reverb_state,
            r.reverb_listing_id,
            r.reverb_slug,
            r.list_price as reverb_price,
            r.listing_currency as reverb_currency,
            r.condition_rating,
            r.inventory_quantity,
            r.offers_enabled,
            r.updated_at as reverb_updated,
            r.reverb_created_at,
            r.reverb_published_at,
            r.extended_attributes,
            pc_r.external_id as reverb_external_id
        FROM products p
        JOIN platform_common pc_r ON p.id = pc_r.product_id AND pc_r.platform_name = 'reverb'
        JOIN reverb_listings r ON pc_r.id = r.platform_id
        LEFT JOIN platform_common pc_s ON p.id = pc_s.product_id AND pc_s.platform_name = 'shopify'
        WHERE pc_s.id IS NULL  -- No existing Shopify listing
        """
        
        # Add status filter if specified
        if reverb_status_filter:
            if isinstance(reverb_status_filter, list):
                status_list = ", ".join(f"'{status}'" for status in reverb_status_filter)
                base_query += f" AND r.reverb_state IN ({status_list})"
            else:
                base_query += f" AND r.reverb_state = '{reverb_status_filter}'"
        
        # Add ordering and limit
        base_query += " ORDER BY p.created_at DESC"
        if limit:
            base_query += f" LIMIT {limit}"
        
        print(f"🔍 Querying Reverb products (status filter: {reverb_status_filter or 'ALL'})")
        print(f"🔍 reverb_status_filter is type: {type(reverb_status_filter)})")
        
        
        print(f"DEBUG: Parsed statuses in method: {reverb_status_filter}")
        print(f"DEBUG: Generated SQL query: {base_query}")
        
        try:
            result = await self.db.execute(text(base_query))
            rows = result.fetchall()
            
            # Convert to list of dicts with correct field mappings
            products = []
            for row in rows:
                products.append({
                    'product_id': row.product_id,
                    'sku': row.sku,
                    'brand': row.brand,
                    'model': row.model,
                    'description': row.description,
                    'base_price': row.base_price,
                    'primary_image': row.primary_image,
                    'additional_images': row.additional_images,
                    'category': row.category,
                    'condition': row.condition,
                    'year': row.year,
                    'decade': row.decade,
                    'finish': row.finish,
                    'created_at': row.created_at,
                    'reverb_state': row.reverb_state,
                    'reverb_listing_id': row.reverb_listing_id,
                    'reverb_slug': row.reverb_slug,
                    'reverb_price': row.reverb_price,  # This is list_price from Reverb
                    'reverb_currency': row.reverb_currency,
                    'condition_rating': row.condition_rating,
                    'inventory_quantity': row.inventory_quantity,
                    'offers_enabled': row.offers_enabled,
                    'reverb_updated': row.reverb_updated,
                    'reverb_created_at': row.reverb_created_at,
                    'reverb_published_at': row.reverb_published_at,
                    'extended_attributes': row.extended_attributes,
                    'reverb_external_id': row.reverb_external_id,
                })
            
            print(f"✅ Found {len(products)} products to create in Shopify")
            return products
            
        except Exception as e:
            print(f"❌ Error querying Reverb products: {str(e)}")
            raise
    
    def prepare_shopify_product_data(self, product: Dict[str, Any]) -> Dict[str, Any]:
        """
        Prepare Shopify product data from Reverb product data
        MIRRORS the VR → Shopify logic from shopify_import_template_from_vr.py
        """
        try:
            # Get category from extended_attributes if available
            extended_attrs = product.get('extended_attributes', {})
            if isinstance(extended_attrs, str):
                import json
                try:
                    extended_attrs = json.loads(extended_attrs)
                except json.JSONDecodeError:
                    extended_attrs = {}

            # Extract category info
            categories = extended_attrs.get('categories', [])
            category_uuid = categories[0].get('uuid', '') if categories else ''
            
            # Map category using the existing mappings
            merchant_type = self.get_merchant_defined_type(category_uuid)
            shopify_category_gid = self.get_shopify_category_gid(category_uuid)
            
            # Build title - handle None values better
            title_parts = []
            if product.get('year') and str(product.get('year')) != 'None':
                title_parts.append(str(product['year']))
            if product.get('brand') and str(product.get('brand')) != 'None':
                title_parts.append(str(product['brand']))
            if product.get('model') and str(product.get('model')) != 'None':
                title_parts.append(str(product['model']))
            
            title = ' '.join(title_parts) if title_parts else f"Product {product.get('sku', 'Unknown')}"
            
            # Generate handle
            handle = self.generate_shopify_handle(
                product.get('brand', ''),
                product.get('model', ''),
                product.get('sku', '')
            )
            
            # Status logic - map Reverb states to correct Shopify status
            reverb_state = product.get('reverb_state', '').lower()

            if reverb_state == 'live':
                shopify_status = 'ACTIVE'
                published_status = 'TRUE'
            elif reverb_state in ['sold', 'ended']:
                shopify_status = 'ARCHIVED'  # Sold/ended items should be archived, not draft
                published_status = 'FALSE'
            elif reverb_state == 'draft':
                shopify_status = 'DRAFT'
                published_status = 'FALSE'
            else:
                # Unknown state - default to draft
                shopify_status = 'DRAFT'
                published_status = 'FALSE'

            print(f"  📊 Reverb '{reverb_state}' → Shopify '{shopify_status}' (Publish: {published_status})")
            
            # Tags - handle None values
            tags_list = []
            if product.get('brand') and str(product.get('brand')) != 'None': 
                tags_list.append(str(product['brand']))
            if merchant_type and merchant_type != "Musical Instrument": 
                tags_list.append(merchant_type)
            if product.get('finish') and str(product.get('finish')) != 'None': 
                tags_list.append(str(product['finish']))
            if product.get('year') and str(product.get('year')) != 'None': 
                tags_list.append(f"Year: {product['year']}")
            tags_list.append(f"Reverb: {product.get('reverb_state', '')}")
            
            # Images from extended_attributes
            images = []
            photos = extended_attrs.get('photos', [])
            for photo in photos:
                full_url = photo.get('_links', {}).get('full', {}).get('href', '')
                if full_url:
                    images.append({'src': full_url})
            
            # Fallback to primary_image
            if not images and product.get('primary_image'):
                images.append({'src': product['primary_image']})
            
            # Shopify structure - DO NOT include productCategory here (causes GraphQL error)
            shopify_data = {
                'title': title,
                'handle': handle,
                'descriptionHtml': product.get('description', ''),
                'productType': merchant_type,
                'vendor': product.get('brand', '') if product.get('brand') and str(product.get('brand')) != 'None' else '',
                'status': shopify_status,
                'tags': tags_list,
                'productOptions': [{'name': 'Title', 'values': [{'name': 'Default Title'}]}]
            }
            
            # Log category info but DON'T add to shopify_data (will be set post-creation)
            if shopify_category_gid and shopify_category_gid != "gid://shopify/TaxonomyCategory/ae-2-8":
                print(f"  🏷️ Category will be set post-creation: {shopify_category_gid}")
            
            # Variant data
            variant_data = {
                'price': str(float(product.get('reverb_price', 0))),
                'sku': product.get('sku', ''),
                'inventory': int(product.get('inventory_quantity', 1)),
                'inventoryPolicy': 'DENY',
                'inventoryItem': {'tracked': True}
            }
            
            return {
                'product_input': shopify_data,
                'variant_updates': variant_data,
                'images': images,
                'should_publish': published_status == 'TRUE',
                'shopify_status': shopify_status,
                'category_info': {
                    'category_uuid': category_uuid,
                    'merchant_type': merchant_type,
                    'shopify_gid': shopify_category_gid  # Store for Step 5 category assignment
                }
            }
            
        except Exception as e:
            print(f"  ❌ Error preparing Shopify data: {str(e)}")
            # Return a basic fallback structure
            return {
                'product_input': {
                    'title': f"{product.get('brand', 'Unknown')} {product.get('model', 'Product')}",
                    'descriptionHtml': product.get('description', ''),
                    'productType': 'Musical Instrument',
                    'vendor': product.get('brand', ''),
                    'status': 'DRAFT',
                    'tags': ['Import Error'],
                    'productOptions': [{'name': 'Title', 'values': [{'name': 'Default Title'}]}]
                },
                'variant_updates': {
                    'price': str(float(product.get('base_price', 0))),
                    'sku': product.get('sku', ''),
                    'inventory': 1,
                    'inventoryPolicy': 'DENY',
                    'inventoryItem': {'tracked': True}
                },
                'images': [],
                'should_publish': False,
                'shopify_status': 'DRAFT'
            }
    
    async def create_complete_shopify_product(self, product_data: Dict[str, Any], shopify_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create complete Shopify product with all data
        Based on your V&R script's create_complete_product function
        """
        
        try:
            product_id = product_data['product_id']
            sku = product_data['sku']
            
            print(f"  Step 1: Creating Shopify product shell...")
            
            # Create the product shell
            created_result = self.shopify_client.create_product(shopify_data["product_input"])
            
            if not created_result or not created_result.get("product"):
                return {"success": False, "error": "Failed to create product shell", "shopify_gid": None}
            
            shopify_product_gid = created_result["product"]["id"]
            shopify_product_title = created_result["product"]["title"]
            shopify_status = shopify_data["shopify_status"]
            
            print(f"  ✅ Shopify product created: {shopify_product_title}")
            print(f"      GID: {shopify_product_gid}")
            print(f"      Status: {shopify_status}")
            
            # Step 2: Update variant with pricing/inventory
            print(f"  Step 2: Updating variant with pricing/inventory...")
            
            # Get the auto-created variant GID
            product_snapshot = self.shopify_client.get_product_snapshot_by_id(shopify_product_gid, num_variants=1)
            if product_snapshot and product_snapshot.get("variants", {}).get("edges"):
                variant_gid = product_snapshot["variants"]["edges"][0]["node"]["id"]
                
                # Prepare variant updates with location
                variant_updates = shopify_data["variant_updates"].copy()
                if self.DEFAULT_LOCATION_GID:
                    variant_updates["inventoryQuantities"] = [{
                        "availableQuantity": variant_updates.get("inventory", 1),
                        "locationId": self.DEFAULT_LOCATION_GID
                    }]
                
                # Update variant
                variant_result = self.shopify_client.update_variant_rest(variant_gid, variant_updates)
                if variant_result:
                    print(f"  ✅ Variant updated with price/SKU/inventory")
                else:
                    print(f"  ⚠️ Variant update failed")
            else:
                print(f"  ⚠️ Could not find variant to update")
            
            # Step 3: Add images
            if shopify_data["images"]:
                print(f"  Step 3: Adding {len(shopify_data['images'])} images...")
                images_result = self.shopify_client.create_product_images(shopify_product_gid, shopify_data["images"])
                if images_result:
                    print(f"  ✅ Images added successfully")
                else:
                    print(f"  ⚠️ Image upload failed")
            
            # Step 4: Publish if needed
            published_status = "Not Published"
            if shopify_data.get("should_publish", False):
                print(f"  Step 4: Publishing to Online Store...")
                
                online_store_gid = self.shopify_client.get_online_store_publication_id()
                if online_store_gid:
                    publish_result = self.shopify_client.publish_product_to_sales_channel(shopify_product_gid, online_store_gid)
                    if publish_result:
                        print(f"  ✅ Product published to Online Store")
                        published_status = "Published"
                    else:
                        print(f"  ⚠️ Publishing failed")
                        published_status = "Publish Failed"
                else:
                    print(f"  ⚠️ Could not find Online Store publication GID")
                    published_status = "No Online Store GID"
            
            # Step 5: Set product category using existing client method
            category_gid = shopify_data.get("category_info", {}).get("shopify_gid")
            if category_gid and category_gid != "gid://shopify/TaxonomyCategory/ae-2-8":
                print(f"  Step 5: Setting product category...")
                category_result = self.shopify_client.set_product_category(shopify_product_gid, category_gid)
                if category_result:
                    print(f"  ✅ Category set successfully")
                else:
                    print(f"  ⚠️ Category setting failed")
            else:
                print(f"  Step 5: Skipping category assignment (using default/fallback)")
            
            return {
                "success": True,
                "shopify_gid": shopify_product_gid,
                "shopify_title": shopify_product_title,
                "shopify_status": shopify_status,
                "published": published_status,
                "message": f"Complete Shopify product created ({published_status})"
            }
            
        except Exception as e:
            print(f"  ❌ Error creating Shopify product: {str(e)}")
            return {"success": False, "error": str(e), "shopify_gid": None}

    async def create_single_listing_by_id(self, reverb_id: str):
        """
        Fetch and process a single Reverb listing by its ID for a dry run.
        
        Args:
            reverb_id (str): The Reverb listing ID to fetch.
        """
        print(f"🔍 Fetching Reverb listing with ID: {reverb_id}")
        
        try:
            # Instantiate ReverbClient and fetch the listing details
            reverb_client = ReverbClient(api_key=os.getenv("REVERB_API_KEY"))
            listing = await reverb_client.get_listing_details(reverb_id)
        except Exception as e:
            print(f"❌ Error fetching listing by ID: {str(e)}")
            return
        
        if not listing:
            print(f"❌ No listing found with ID: {reverb_id}")
            return
        
        print(f"✅ Fetched listing: {listing.get('brand', 'Unknown')} {listing.get('model', 'Unknown')} (SKU: {listing.get('sku', 'Unknown')})")
        
        # Debug raw listing data
        print(f"DEBUG: Raw listing data: {json.dumps(listing, indent=4)}")
        
        # Extract images from cloudinary_photos
        cloudinary_photos = listing.get("cloudinary_photos", [])
        primary_image = cloudinary_photos[0]["preview_url"] if cloudinary_photos else None
        additional_images = [photo["preview_url"] for photo in cloudinary_photos[1:]] if cloudinary_photos else []
        
        # Fallback to photos field if cloudinary_photos is missing
        if not primary_image and "photos" in listing:
            photos = listing["photos"]
            primary_image = photos[0]["_links"]["full"]["href"] if photos else None
            additional_images = [
                photo["_links"]["full"]["href"] for photo in photos[1:] if "_links" in photo and "full" in photo["_links"]
            ]
        
        print(f"🔍 Primary Image: {primary_image}")
        print(f"🔍 Additional Images: {additional_images}")
        
        # Transform the listing into Shopify format
        shopify_data = self.prepare_shopify_product_data(listing)
        
        print(f"✅ Transformed Shopify Data:")
        print(json.dumps(shopify_data, indent=4))
        
        print(f"🧪 Dry run complete. No actual Shopify product was created.")

    async def create_database_entries(self, product_data: Dict[str, Any], shopify_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create the database linkage entries (platform_common + shopify_listings)
        """
        
        try:
            product_id = product_data['product_id']
            reverb_state = product_data['reverb_state']
            shopify_status = self.status_mapping.get(reverb_state, 'DRAFT')
            
            print(f"  Step 5: Creating database linkage...")
            
            # Extract Shopify product ID from GID
            shopify_gid = shopify_result.get('shopify_gid')
            shopify_product_id = shopify_gid.split('/')[-1] if shopify_gid else None
            
            # Generate handle and listing URL
            handle = self.generate_shopify_handle(
                product_data.get('brand', ''),
                product_data.get('model', ''),
                product_data.get('sku', '')
            )
            listing_url = f"https://londonvintageguitars.myshopify.com/products/{handle}" if handle else None
            
            # Build title from product data
            title_parts = []
            if product_data.get('year'):
                title_parts.append(str(product_data['year']))
            if product_data.get('brand'):
                title_parts.append(str(product_data['brand']))
            if product_data.get('model'):
                title_parts.append(str(product_data['model']))
            title = ' '.join(title_parts) if title_parts else f"Product {product_data.get('sku', 'Unknown')}"
            
            # Get category information
            extended_attrs = product_data.get('extended_attributes', {})
            if isinstance(extended_attrs, str):
                import json
                try:
                    extended_attrs = json.loads(extended_attrs)
                except:
                    extended_attrs = {}
                    
            # Add this right after you parse extended_attrs:
            print(f"  🔍 Extended attributes keys: {list(extended_attrs.keys()) if extended_attrs else 'None'}")
            if extended_attrs.get('categories'):
                print(f"  🔍 Categories found: {len(extended_attrs['categories'])}")
                for i, cat in enumerate(extended_attrs['categories']):
                    print(f"    Category {i}: UUID={cat.get('uuid')}, Name={cat.get('full_name')}")
            
            categories = extended_attrs.get('categories', [])
            category_uuid = categories[0].get('uuid', '') if categories else ''
            category_full_name = categories[0].get('full_name', '') if categories else ''
            
            # Map category using your service
            category_gid = None
            category_name = None
            
            if category_uuid:
                print(f"  🏷️ Category UUID found: {category_uuid}")
                print(f"  🏷️ Category name: {category_full_name}")
                
                # Use your existing mapping methods instead of the service
                mappings = self.load_reverb_category_mappings()
                if category_uuid in mappings:
                    category_mapping = mappings[category_uuid]
                    category_gid = category_mapping.get('shopify_gid')
                    category_name = category_mapping.get('merchant_type')
                    print(f"  ✅ Category mapped: {category_name} -> {category_gid}")
                else:
                    print(f"  ⚠️ No mapping found for category UUID: {category_uuid}")
                    # Use fallback
                    category_gid = "gid://shopify/TaxonomyCategory/ae-2-8"
                    category_name = "Musical Instrument"
                    print(f"  🔄 Using fallback: {category_name} -> {category_gid}")
            
            # Use timezone-naive datetime for PostgreSQL
            current_time = datetime.now()
            
            # Create platform_common entry
            platform_common = PlatformCommon(
                product_id=product_id,
                platform_name='shopify',
                status=shopify_status.lower(),
                sync_status=SyncStatus.SYNCED.value,
                external_id=shopify_product_id,
                listing_url=listing_url,
                last_sync=current_time
            )
            
            self.db.add(platform_common)
            await self.db.flush()  # Get the ID
            
            # Fetch the complete Shopify product data to store in extended_attributes
            shopify_product_data = None
            if shopify_gid:
                print(f"  📥 Fetching complete Shopify product data...")
                try:
                    shopify_product_data = self.shopify_client.get_product_snapshot_by_id(shopify_gid)
                    if shopify_product_data:
                        print(f"  ✅ Retrieved Shopify product data with URL: {shopify_product_data.get('onlineStorePreviewUrl', 'N/A')}")
                        # Update listing_url if we got a better one from Shopify
                        if shopify_product_data.get('onlineStorePreviewUrl'):
                            listing_url = shopify_product_data.get('onlineStorePreviewUrl')
                            # Also update platform_common with the correct URL
                            platform_common.listing_url = listing_url
                except Exception as e:
                    print(f"  ⚠️ Could not fetch Shopify product data: {e}")
            
            # Prepare rich extended attributes with both Reverb AND Shopify data
            rich_extended_attrs = {
                # Store the full Shopify API response if available
                **shopify_product_data if shopify_product_data else {},
                
                # Add URL explicitly
                'url': shopify_product_data.get('onlineStorePreviewUrl') if shopify_product_data else None,
                'online_store_url': shopify_product_data.get('onlineStoreUrl') if shopify_product_data else None,
                'online_store_preview_url': shopify_product_data.get('onlineStorePreviewUrl') if shopify_product_data else None,
                
                # Reverb source data (these override any conflicting Shopify fields)
                'reverb_listing_id': product_data.get('reverb_listing_id'),
                'reverb_slug': product_data.get('reverb_slug'),
                'reverb_state': product_data.get('reverb_state'),
                'reverb_price': product_data.get('reverb_price'),
                'reverb_currency': product_data.get('reverb_currency'),
                'condition_rating': product_data.get('condition_rating'),
                'offers_enabled': product_data.get('offers_enabled'),
                'reverb_created_at': product_data.get('reverb_created_at'),
                'reverb_published_at': product_data.get('reverb_published_at'),
                'reverb_external_id': product_data.get('reverb_external_id'),
                
                # Product details from Reverb
                'reverb_brand': product_data.get('brand'),
                'reverb_model': product_data.get('model'),
                'reverb_year': product_data.get('year'),
                'reverb_decade': product_data.get('decade'),
                'reverb_finish': product_data.get('finish'),
                'reverb_condition': product_data.get('condition'),
                'reverb_category': product_data.get('category'),
                
                # Shopify creation details
                'shopify_gid': shopify_gid,
                'shopify_title': shopify_result.get('shopify_title'),
                'published_status': shopify_result.get('published'),
                'sync_source': 'reverb_import',
                'import_date': current_time.isoformat(),
                
                # Category mapping
                'reverb_category_uuid': category_uuid,
                'reverb_category_name': category_full_name,
                'mapped_category_gid': category_gid,
                'mapped_category_name': category_name,
                
                # Images and content from Reverb
                'reverb_primary_image': product_data.get('primary_image'),
                'reverb_additional_images': product_data.get('additional_images'),
                'reverb_description': product_data.get('description')
            }
            
            # Create comprehensive shopify_listings entry
            shopify_listing = ShopifyListing(
                platform_id=platform_common.id,
                
                # Shopify identifiers
                shopify_product_id=shopify_gid,
                shopify_legacy_id=shopify_product_id,  # Numeric ID
                handle=handle,
                title=title,
                vendor=product_data.get('brand'),
                status=shopify_status,
                price=float(product_data.get('reverb_price', 0)) if product_data.get('reverb_price') else None,
                
                # Category fields - use Shopify API response if available, otherwise use mapping
                category_gid=shopify_product_data.get('category', {}).get('id') if shopify_product_data and shopify_product_data.get('category') else category_gid,
                category_name=shopify_product_data.get('category', {}).get('name') if shopify_product_data and shopify_product_data.get('category') else category_name,
                category_full_name=shopify_product_data.get('category', {}).get('fullName') if shopify_product_data and shopify_product_data.get('category') else category_full_name,
                category_assigned_at=current_time if category_gid else None,
                category_assignment_status='ASSIGNED' if category_gid else 'PENDING',
                
                # SEO fields - use Shopify API response if available
                seo_title=shopify_product_data.get('seo', {}).get('title') if shopify_product_data and shopify_product_data.get('seo', {}).get('title') else title[:70] if title else None,
                seo_description=shopify_product_data.get('seo', {}).get('description') if shopify_product_data and shopify_product_data.get('seo', {}).get('description') else product_data.get('description', '')[:320] if product_data.get('description') else None,
                seo_keywords=None,  # Can add keyword extraction later
                
                # Additional fields
                featured=False,  # Default to not featured
                custom_layout=None,
                extended_attributes=rich_extended_attrs,
                last_synced_at=current_time,
                
                # Timestamps
                created_at=current_time,
                updated_at=current_time
            )
            
            self.db.add(shopify_listing)
            await self.db.flush()
            
            print(f"  ✅ Database entries created:")
            print(f"      Platform_common ID: {platform_common.id}")
            print(f"      Shopify_listing ID: {shopify_listing.id}")
            print(f"      External ID: {shopify_product_id}")
            print(f"      Listing URL: {listing_url}")
            print(f"      Title: {title}")
            print(f"      Handle: {handle}")
            print(f"      Vendor: {product_data.get('brand')}")
            print(f"      Price: £{product_data.get('reverb_price', 0)}")
            print(f"      Category: {category_name or 'Not mapped'}")
            
            return {
                "success": True,
                "platform_common_id": platform_common.id,
                "shopify_listing_id": shopify_listing.id,
                "listing_url": listing_url
            }
            
        except Exception as e:
            print(f"  ❌ Error creating database entries: {str(e)}")
            await self.db.rollback()
            return {"success": False, "error": str(e)}

    async def process_products(self, 
        reverb_status_filter: Optional[str] = None,
        limit: Optional[int] = 2,
        dry_run: bool = True) -> Dict[str, Any]:
        """
        Main processing function
        """
        
        print(f"🚀 Starting Reverb → Shopify Creation Process")
        print(f"   🔍 Reverb status filter: {reverb_status_filter or 'ALL'}")
        print(f"   🔢 Limit: {limit or 'No limit'}")
        print(f"   🧪 Dry run: {'Yes' if dry_run else 'No'}")
        
        # Get default location GID
        if not self.DEFAULT_LOCATION_GID:
            # You might need to implement this in your client
            self.DEFAULT_LOCATION_GID = "gid://shopify/Location/109766639956"
        
        # Get products to process
        products = await self.get_reverb_products_for_shopify(reverb_status_filter, limit)
        
        if not products:
            print("❌ No products found to process")
            return {'success': True, 'processed': 0, 'message': 'No products to process'}
        
        results = {
            'success': True,
            'processed': 0,
            'created': 0,
            'errors': 0,
            'products': []
        }
        
        # Process each product
        for i, product in enumerate(products, 1):
            print(f"\n📦 Processing {i}/{len(products)}: {product['brand']} {product['model']} (SKU: {product['sku']})")
            print(f"  🎯 Reverb state: {product['reverb_state']}")
            print(f"  💰 Price: £{product['base_price']}")
            
            try:
                # Prepare Shopify data
                shopify_data = self.prepare_shopify_product_data(product)
                print(f"  📊 Will create as: {shopify_data['shopify_status']}")
                print(f"  🌐 Will publish: {'Yes' if shopify_data['should_publish'] else 'No'}")
                
                if not dry_run:
                    # Create Shopify product
                    shopify_result = await self.create_complete_shopify_product(product, shopify_data)
                    
                    if shopify_result['success']:
                        # Create database entries
                        db_result = await self.create_database_entries(product, shopify_result)
                        
                        if db_result['success']:
                            print(f"  🎉 SUCCESS: Complete creation successful")
                            results['created'] += 1
                        else:
                            print(f"  ⚠️ Shopify created but database linkage failed: {db_result['error']}")
                            results['errors'] += 1
                    else:
                        print(f"  ❌ Shopify creation failed: {shopify_result['error']}")
                        results['errors'] += 1
                else:
                    print(f"  🧪 DRY RUN: Would create Shopify product")
                    results['created'] += 1
                
                # Small delay between products
                if not dry_run:
                    time.sleep(1)
                
            except Exception as e:
                print(f"  💥 Unexpected error: {str(e)}")
                results['errors'] += 1
            
            results['processed'] += 1
            results['products'].append({
                'sku': product['sku'],
                'brand': product['brand'],
                'model': product['model'],
                'reverb_state': product['reverb_state']
            })
        
        # Commit or rollback
        if dry_run:
            print(f"\n🧪 DRY RUN: Rolling back database changes")
            await self.db.rollback()
        else:
            print(f"\n💾 Committing changes to database")
            await self.db.commit()
        
        print(f"\n🏁 Process complete!")
        print(f"   📊 Processed: {results['processed']}")
        print(f"   ✅ Created: {results['created']}")
        print(f"   ❌ Errors: {results['errors']}")
        
        return results

    async def process_products_from_csv(self, input_file: str, dry_run: bool = True) -> Dict[str, Any]:
        """
        Process products from a curated CSV file.
        """
        # Read the curated CSV
        products = self.read_curated_csv(input_file)
        print(f"🚀 Processing {len(products)} products from CSV")
        
        results = {
            'success': True,
            'processed': 0,
            'created': 0,
            'errors': 0,
            'products': []
        }
        
        for i, product in enumerate(products, 1):
            print(f"\n📦 Processing {i}/{len(products)}: {product['title']} (SKU: {product['sku']})")
            
            try:
                # Prepare Shopify data
                shopify_data = self.prepare_shopify_product_data(product)
                print(f"  📊 Will create as: {shopify_data['shopify_status']}")
                print(f"  🌐 Will publish: {'Yes' if shopify_data['should_publish'] else 'No'}")
                
                if not dry_run:
                    # Create Shopify product
                    shopify_result = await self.create_complete_shopify_product(product, shopify_data)
                    
                    if shopify_result['success']:
                        # Create database entries
                        db_result = await self.create_database_entries(product, shopify_result)
                        
                        if db_result['success']:
                            print(f"  🎉 SUCCESS: Complete creation successful")
                            results['created'] += 1
                        else:
                            print(f"  ⚠️ Shopify created but database linkage failed: {db_result['error']}")
                            results['errors'] += 1
                    else:
                        print(f"  ❌ Shopify creation failed: {shopify_result['error']}")
                        results['errors'] += 1
                else:
                    print(f"  🧪 DRY RUN: Would create Shopify product")
                    results['created'] += 1
                
            except Exception as e:
                print(f"  💥 Unexpected error: {str(e)}")
                results['errors'] += 1
            
            results['processed'] += 1
            results['products'].append(product)
        
        print(f"\n🏁 Process complete!")
        print(f"   📊 Processed: {results['processed']}")
        print(f"   ✅ Created: {results['created']}")
        print(f"   ❌ Errors: {results['errors']}")
        
        return results

    def load_reverb_category_mappings(self) -> Dict[str, Dict[str, str]]:
        """
        Load Reverb to Shopify category mappings from JSON file
        """
        config_file = "app/services/category_mappings/reverb_to_shopify.json"
        
        try:
            if os.path.exists(config_file):
                with open(config_file, 'r') as f:
                    config = json.load(f)
                print(f"  📖 Loaded {len(config.get('mappings', {}))} category mappings from JSON")
                return config.get('mappings', {})  # Return the mappings dict
        except Exception as e:
            print(f"  ⚠️ Error loading category mappings: {e}")
        
        print(f"  📖 Using fallback hardcoded mappings")
        # Fallback to hardcoded mappings if file not found
        return self._get_hardcoded_mappings()

    def _get_hardcoded_mappings(self) -> Dict[str, Dict[str, str]]:
        """Fallback hardcoded mappings"""
        return {
            # Your existing mappings
            "10335451-31e5-418a-8ed8-f48cd738f17d": {
                'shopify_category': 'Arts & Entertainment > Hobbies & Creative Arts > Musical Instrument & Orchestra Accessories > Musical Instrument Amplifiers > Guitar Amplifiers',
                'shopify_gid': 'gid://shopify/TaxonomyCategory/ae-2-7-10-3',
                'merchant_type': 'Guitar Combo Amplifier'
            },
            "dfd39027-d134-4353-b9e4-57dc6be791b9": {
                'shopify_category': 'Arts & Entertainment > Hobbies & Creative Arts > Musical Instruments > String Instruments > Electric Guitars',
                'shopify_gid': 'gid://shopify/TaxonomyCategory/ae-2-8-7-2-4',
                'merchant_type': 'Electric Guitar'
            },
            # Add the UUIDs from your SQL results
            "e57deb7a-382b-4e18-a008-67d4fbcb2879": {
                'shopify_category': 'Arts & Entertainment > Hobbies & Creative Arts > Musical Instruments > String Instruments > Electric Guitars',
                'shopify_gid': 'gid://shopify/TaxonomyCategory/ae-2-8-7-2-4',
                'merchant_type': 'Solid Body Electric Guitar'
            },
            "be24976f-ab6e-42e1-a29b-275e5fbca68f": {
                'shopify_category': 'Arts & Entertainment > Hobbies & Creative Arts > Musical Instruments > String Instruments > Acoustic Guitars',
                'shopify_gid': 'gid://shopify/TaxonomyCategory/ae-2-8-7-2-1',
                'merchant_type': 'Archtop Acoustic Guitar'
            },
            "630dc140-45e2-4371-b569-19405de321cc": {
                'shopify_category': 'Arts & Entertainment > Hobbies & Creative Arts > Musical Instruments > String Instruments > Acoustic Guitars',
                'shopify_gid': 'gid://shopify/TaxonomyCategory/ae-2-8-7-2-1',
                'merchant_type': 'Dreadnought Guitar'
            }
        }

    def map_reverb_category_to_shopify_category(self, reverb_category_uuid: str) -> str:
        """
        Map Reverb category UUID to Shopify category string
        """
        mappings = self.load_reverb_category_mappings()
        
        if reverb_category_uuid in mappings:
            return mappings[reverb_category_uuid]['shopify_category']
        
        # Fallback to general Musical Instruments
        return "Arts & Entertainment > Hobbies & Creative Arts > Musical Instruments"

    def get_shopify_category_gid(self, reverb_category_uuid: str) -> str:
        """
        Get Shopify category GID for Reverb category UUID
        """
        mappings = self.load_reverb_category_mappings()
        
        if reverb_category_uuid in mappings:
            return mappings[reverb_category_uuid]['shopify_gid']
        
        # Fallback to general Musical Instruments GID
        return "gid://shopify/TaxonomyCategory/ae-2-8"

    def get_merchant_defined_type(self, reverb_category_uuid: str) -> str:
        """
        Get merchant-defined type from Reverb category UUID
        """
        mappings = self.load_reverb_category_mappings()
        
        if reverb_category_uuid in mappings:
            return mappings[reverb_category_uuid]['merchant_type']
        
        # Fallback
        return "Musical Instrument"
    
    def generate_shopify_handle(self, brand: str, model: str, sku: str) -> str:
        """
        Generate Shopify handle from brand, model, and SKU
        """
        import re
        
        # Combine parts
        parts = [str(brand), str(model), str(sku)]
        text = ' '.join(part for part in parts if part and part != 'nan')
        
        # Convert to lowercase
        text = text.lower()
        
        # Replace spaces and special characters with hyphens
        text = re.sub(r'[^a-z0-9\-]', '-', text)
        
        # Remove multiple consecutive hyphens
        text = re.sub(r'-+', '-', text)
        
        # Remove leading/trailing hyphens
        text = text.strip('-')
        
        # Limit length
        if len(text) > 255:
            text = text[:255].rstrip('-')
        
        # Ensure handle is not empty
        if not text:
            text = 'product'
        
        return text


    def generate_tags(self, product: Dict[str, Any]) -> List[str]:
        """
        Generate tags for Shopify product
        """
        tags = []
        
        # Add brand
        if product.get('brand'):
            tags.append(str(product['brand']))
        # Add merchant type from category

        extended_attrs = product.get('extended_attributes', {})
        categories = extended_attrs.get('categories', [])
        if categories:
            category_uuid = categories[0].get('uuid', '')
            merchant_type = self.get_merchant_defined_type(category_uuid)
            if merchant_type and merchant_type != "Unknown":
              tags.append(merchant_type)
        
        # Add other attributes
        if product.get('finish'):
            tags.append(f"Finish: {product['finish']}")
        
        if product.get('year'):
            tags.append(f"Year: {product['year']}")
        
        if product.get('condition'):
            tags.append(f"Condition: {product['condition']}")
        
        # Add Reverb state
        tags.append(f"Reverb: {product.get('reverb_state', 'unknown')}")
        
        # Remove duplicates and empty tags
        tags = [tag for tag in tags if tag and str(tag).strip()]
        return list(set(tags))

    def read_curated_csv(self, input_file: str) -> List[Dict[str, Any]]:
        """
        Read and validate a curated CSV file.
        """
        print(f"🔍 Reading curated CSV file: {input_file}")
        
        products = []
        with open(input_file, mode='r', newline='', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                # Validate required fields
                if not row.get('sku') or not row.get('title'):
                    print(f"⚠️ Skipping row with missing required fields: {row}")
                    continue
                products.append(row)
        
        print(f"✅ Loaded {len(products)} products from {input_file}")
        return products

async def mainOld():
    """Main function with configuration and CLI argument parsing"""
    
    # Default configuration
    REVERB_STATUS_FILTER = None  # 'live', 'sold', 'ended', 'draft', or None for all
    LIMIT = 2380  # Number of products to process (use None for all)
    DRY_RUN = False  # Set to False to actually create products
    
    # Argument parsing
    parser = argparse.ArgumentParser(description="Create Shopify listings from Reverb products.")
    parser.add_argument(
        "--statuses",
        type=str,
        default=REVERB_STATUS_FILTER,  # Use the default from the config
        help="Comma-separated list of Reverb statuses to filter (e.g., 'live,sold'). Default: None (process all)."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=LIMIT,  # Use the default from the config
        help="Limit the number of products to process. Default: 2380."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=DRY_RUN,  # Use the default from the config
        help="Run in dry-run mode (no actual Shopify product creation)."
    )
    parser.add_argument(
        "--export-csv",
        type=str,
        help="Export Reverb product data to a CSV file for manual curation."
    )
    parser.add_argument(
        "--input-csv",
        type=str,
        help="Specify a curated CSV file to upload products to Shopify."
    )
    parser.add_argument(
        "--dry-run-single", 
        action="store_true", 
        help="Run a dry run for a single listing."
    )
    parser.add_argument(
        "--dry-run-id", 
        type=str, 
        help="Run a dry run for a specific Reverb listing ID."
    )
    args = parser.parse_args()
    
    # Parse statuses into a list
    statuses = [status.strip() for status in args.statuses.split(",")] if args.statuses else None

    print(f"DEBUG: Parsed statuses: {statuses}")

    if args.export_csv:
        async with async_session() as db:
            shopify_client = ShopifyGraphQLClient(safety_buffer_percentage=0.3)
            creator = ReverbToShopifyCreator(db, shopify_client)
            await creator.export_reverb_data_to_csv(args.export_csv, reverb_status_filter=statuses)
        return
    
    if args.input_csv:
        async with async_session() as db:
            shopify_client = ShopifyGraphQLClient(safety_buffer_percentage=0.3)
            creator = ReverbToShopifyCreator(db, shopify_client)
            results = await creator.process_products_from_csv(args.input_csv, dry_run=args.dry_run)
        return
    if args.dry_run_single:
        async with async_session() as db:
            shopify_client = ShopifyGraphQLClient(safety_buffer_percentage=0.3)
            creator = ReverbToShopifyCreator(db, shopify_client)
            await creator.create_single_listing_dry_run(reverb_status=args.statuses)
        return
    if args.dry_run_id:
        async with async_session() as db:
            shopify_client = ShopifyGraphQLClient(safety_buffer_percentage=0.3)
            creator = ReverbToShopifyCreator(db, shopify_client)
            await creator.create_single_listing_by_id(reverb_id=args.dry_run_id)
        return

    print(f"🎸 Reverb to Shopify Creation Tool")
    print(f"=" * 50)
    print(f"🔍 Reverb statuses to filter: {statuses or 'ALL'}")
    print(f"🔢 Limit: {args.limit or 'No limit'}")
    print(f"🧪 Dry run: {'Yes' if args.dry_run else 'No'}")
    
    try:
        # Initialize Shopify client
        shopify_client = ShopifyGraphQLClient(safety_buffer_percentage=0.3)
        print(f"✅ Shopify client initialized (API: {shopify_client.api_version})")
        
        async with async_session() as db:
            creator = ReverbToShopifyCreator(db, shopify_client)
            
            results = await creator.process_products(
                reverb_status_filter=statuses[0] if statuses else None,  # Use the first status if multiple are provided
                limit=args.limit,
                dry_run=args.dry_run
            )
            
            if results['success']:
                print(f"\n✅ Process completed successfully")
            else:
                print(f"\n❌ Process failed")
                
    except Exception as e:
        print(f"\n💥 Process failed with error: {str(e)}")
        import traceback
        traceback.print_exc()
