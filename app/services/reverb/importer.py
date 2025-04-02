# app/services/reverb/importer.py
import os
import json
import glob
import logging
import asyncio
import math
import iso8601
from typing import Dict, List, Any, Optional
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timezone
from dotenv import load_dotenv

from app.models.product import Product, ProductStatus, ProductCondition
from app.models.platform_common import PlatformCommon, ListingStatus, SyncStatus
from app.models.reverb import ReverbListing
from app.services.reverb.client import ReverbClient
from app.core.exceptions import ReverbAPIError

logger = logging.getLogger(__name__)

load_dotenv()

class ReverbImporter:
    """Service for importing Reverb listings into the local database"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.api_key = os.environ.get("REVERB_API_KEY")
        self.client = ReverbClient(self.api_key)
  
    async def import_all_listings(self) -> Dict[str, int]:
        """
        Import all listings from Reverb and create corresponding database records
        
        Returns:
            Dict[str, int]: Statistics about the import operation
        """
        stats = {
            "total": 0,
            "created": 0,
            "errors": 0,
            "skipped": 0
        }
        
        try:
            logger.info("Starting import of all Reverb listings")
            
            # Get all listings from Reverb
            listings = await self.client.get_all_listings()
            if not isinstance(listings, list):
                if isinstance(listings, dict) and 'listings' in listings:
                    # If the API returns a dictionary with 'listings' key, use that
                    listings = listings.get('listings', [])
                else:
                    logger.error(f"Unexpected response format from Reverb API: {type(listings)}")
                    listings = []
            
            stats["total"] = len(listings)
            logger.info(f"Retrieved {stats['total']} listings from Reverb API")
            
            # Process in batches of 50
            BATCH_SIZE = 50
            total_listings = len(listings)
            
            for i in range(0, total_listings, BATCH_SIZE):
                batch = listings[i:i+BATCH_SIZE]
                logger.info(f"Processing batch {i//BATCH_SIZE + 1}/{math.ceil(total_listings/BATCH_SIZE)}")
                
                detail_tasks = []
                valid_listings = []
                
                for listing in batch:
                    # Ensure each listing is a dictionary and has an id
                    if not isinstance(listing, dict):
                        logger.warning(f"Skipping invalid listing format: {listing}")
                        stats["skipped"] += 1
                        continue
                    
                    listing_id = listing.get('id')
                    if not listing_id:
                        logger.warning("Skipping listing with no ID")
                        stats["skipped"] += 1
                        continue
                    
                    # Convert ID to string for consistent handling
                    listing_id = str(listing_id)
                    valid_listings.append(listing_id)
                    
                    # Create task for each listing in batch
                    detail_tasks.append(self.client.get_listing_details(listing_id))
                
                # Get all details concurrently
                if not detail_tasks:
                    logger.warning("No valid listings in batch, skipping")
                    continue
                    
                details_results = await asyncio.gather(*detail_tasks, return_exceptions=True)
                
                # Process batch with a single transaction
                async with self.db.begin():
                    # Filter out exceptions and invalid responses
                    valid_details = []
                    for j, detail_result in enumerate(details_results):
                        if isinstance(detail_result, Exception):
                            stats["errors"] += 1
                            listing_id = valid_listings[j] if j < len(valid_listings) else "unknown"
                            logger.error(f"Error fetching details for listing {listing_id}: {str(detail_result)}")
                            continue
                            
                        if not isinstance(detail_result, dict):
                            stats["errors"] += 1
                            listing_id = valid_listings[j] if j < len(valid_listings) else "unknown"
                            logger.error(f"Invalid response format for listing {listing_id}: {type(detail_result)}")
                            continue
                            
                        valid_details.append(detail_result)
                    
                    if valid_details:
                        try:
                            # Process all valid listings in one batch
                            await self._create_database_records_batch(valid_details)
                            stats["created"] += len(valid_details)
                        except Exception as e:
                            stats["errors"] += len(valid_details)
                            logger.error(f"Error in batch processing: {str(e)}")
                    else:
                        logger.warning("No valid listing details to process in batch")
                            
                # Commit after each batch
                await self.db.commit()
                
                # Report progress
                logger.info(f"Completed batch: {stats['created']}/{total_listings} imported")
            
            logger.info(f"Import complete: Created {stats['created']} listings, "
                    f"skipped {stats['skipped']}, errors {stats['errors']}")
            return stats
            
        except Exception as e:
            # Handle unexpected errors in the overall process
            await self.db.rollback()
            logger.error(f"Critical error in import operation: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            # Re-raise to caller
            raise ImportError(f"Failed to import Reverb listings: {str(e)}") from e

    async def _create_database_records_batch(self, listings_data: List[Dict[str, Any]]) -> None:
        """Create multiple records in a single database operation"""
        if not listings_data:
            logger.warning("No listings data provided for batch creation")
            return

        products = []
        platform_commons = []
        reverb_listings = []
        listing_ids = []  # Track successful IDs for logging
        
        # First collect all SKUs we're about to create
        skus_to_create = []
        for listing_data in listings_data:
            if isinstance(listing_data, dict) and 'id' in listing_data:
                sku = f"REV-{listing_data['id']}"
                skus_to_create.append(sku)
        
        # Check which SKUs already exist
        existing_skus = set()
        if skus_to_create:
            # Use IN query to efficiently check all SKUs at once
            # Modified SQL syntax with proper parameter mapping
            skus_list = list(skus_to_create)  # Convert to list if it's not already
            stmt = text("SELECT sku FROM products WHERE sku = ANY(:skus)")
            result = await self.db.execute(stmt, {"skus": skus_list})
            existing_skus = {row[0] for row in result.fetchall()}
            
            if existing_skus:
                logger.info(f"Found {len(existing_skus)} existing SKUs that will be skipped")
        
        try:
            # First pass: prepare all product objects
            for listing_data in listings_data:
                try:
                    # Ensure listing_data is a dictionary
                    if not isinstance(listing_data, dict):
                        logger.warning(f"Skipping non-dictionary listing data: {type(listing_data)}")
                        continue
                    
                    # Extract listing_id and ensure it's a string
                    listing_id = str(listing_data.get('id', ''))
                    if not listing_id:
                        logger.warning("Skipping listing with missing ID")
                        continue
                    
                    # Create SKU and check if it already exists
                    sku = f"REV-{listing_id}"
                    if sku in existing_skus:
                        logger.info(f"Skipping duplicate SKU: {sku}")
                        continue
                    
                    # Extract and validate all required data with proper type conversion
                    validated_data = {
                        'brand': self._extract_brand(listing_data),
                        'model': self._extract_model(listing_data),
                        'sku': f"REV-{listing_id}",
                        'year': self._safe_int(self._extract_year(listing_data)),
                        'description': listing_data.get('description', ''),
                        'condition': self._map_condition(listing_data),
                        'category': self._extract_category(listing_data),
                        'base_price': self._safe_float(self._extract_price(listing_data)),
                        'primary_image': self._get_primary_image(listing_data),
                        'additional_images': self._get_additional_images(listing_data)
                    }
                    
                    # Create product with validated data
                    product = Product(**validated_data, status=ProductStatus.ACTIVE)
                    products.append(product)
                    listing_ids.append((listing_id, listing_data))  # Store tuple of (id, data)
                    
                except Exception as e:
                    logger.error(f"Error preparing product for listing {listing_data.get('id', 'unknown') if isinstance(listing_data, dict) else 'invalid'}: {str(e)}")
                    # Skip this listing but continue with others
                    continue
            
            if not products:
                logger.warning("No valid products to create after validation")
                return
                
            # Add all products in a single operation
            self.db.add_all(products)
            await self.db.flush()
            
            # Now create platform_common objects for each product
            for i, (listing_id, listing_data) in enumerate(listing_ids):
                try:
                    product = products[i]
                    
                    # When creating PlatformCommon objects
                    now = datetime.now(timezone.utc)
                    now_naive = self._convert_to_naive_datetime(now)  # Convert to naive datetime
                    
                    platform_common = PlatformCommon(
                        product_id=product.id,
                        platform_name="reverb",
                        external_id=listing_id,
                        status=ListingStatus.ACTIVE,
                        sync_status=SyncStatus.SUCCESS,
                        last_sync=self._convert_to_naive_datetime(datetime.now(timezone.utc)),
                        listing_url=self._safe_get(listing_data, '_links', 'web', 'href', default=''),
                        created_at=now_naive,
                        updated_at=now_naive,
                    )
                    platform_commons.append(platform_common)
                    
                except Exception as e:
                    logger.error(f"Error creating platform_common for listing {listing_id}: {str(e)}")
                    # Skip this one but continue with others
            
            if not platform_commons:
                logger.warning("No valid platform_common records to create")
                return
                
            self.db.add_all(platform_commons)
            await self.db.flush()
            
            # Create reverb listings for each platform_common
            for i, (listing_id, listing_data) in enumerate(listing_ids):
                try:
                    if i >= len(platform_commons):
                        continue  # Skip if no corresponding platform_common
                        
                    platform_common = platform_commons[i]
                    
                    # Parse timestamps
                    reverb_created_at = None
                    if listing_data.get('created_at'):
                        try:
                            dt = iso8601.parse_date(listing_data['created_at'])
                            reverb_created_at = self._convert_to_naive_datetime(dt)
                        except Exception as e:
                            logger.warning(f"Could not parse created_at timestamp: {e}")

                    reverb_published_at = None
                    if listing_data.get('published_at'):
                        try:
                            dt = iso8601.parse_date(listing_data['published_at'])
                            reverb_published_at = self._convert_to_naive_datetime(dt)
                        except Exception as e:
                            logger.warning(f"Could not parse published_at timestamp: {e}")

                    # Use naive datetimes for all datetime fields
                    created_at = self._convert_to_naive_datetime(datetime.now(timezone.utc))
                    updated_at = self._convert_to_naive_datetime(datetime.now(timezone.utc))
                    last_synced_at = self._convert_to_naive_datetime(datetime.now(timezone.utc))

                    # Parse state
                    state = ""
                    state_data = listing_data.get('state', {})
                    if isinstance(state_data, dict) and 'slug' in state_data:
                        state = state_data['slug']
                    
                    # Extract statistics
                    view_count = 0
                    watch_count = 0
                    stats = listing_data.get('stats', {})
                    if isinstance(stats, dict):
                        view_count = self._safe_int(stats.get('views'), 0)
                        watch_count = self._safe_int(stats.get('watches'), 0)                   

                    # Create enhanced reverb_listing with new fields
                    reverb_listing = ReverbListing(
                        platform_id=platform_common.id,
                        reverb_listing_id=listing_id,
                        reverb_slug=listing_data.get('slug', ''),
                        reverb_category_uuid=self._safe_get(listing_data, 'categories', 0, 'uuid', default=''),
                        condition_rating=self._safe_float(self._extract_condition_rating(listing_data)),
                        inventory_quantity=self._safe_int(listing_data.get('inventory'), 1),
                        has_inventory=listing_data.get('has_inventory', True),
                        offers_enabled=listing_data.get('offers_enabled', True),
                        is_auction=listing_data.get('auction', False),
                        list_price=self._safe_float(self._extract_price(listing_data)),
                        listing_currency=listing_data.get('listing_currency', 'USD'),
                        shipping_profile_id=listing_data.get('shipping_profile_id'),
                        shop_policies_id=listing_data.get('shop_policies_id'),
                        reverb_state=state,
                        view_count=view_count,
                        watch_count=watch_count,
                        reverb_created_at=reverb_created_at,
                        reverb_published_at=reverb_published_at,
                        created_at=created_at,
                        updated_at=updated_at,
                        last_synced_at=last_synced_at,
                        handmade=listing_data.get('handmade', False),
                        # Store all other fields in extended_attributes
                        extended_attributes=self._prepare_extended_attributes(listing_data)
                    )
                    reverb_listings.append(reverb_listing)
                    
                except Exception as e:
                    logger.error(f"Error creating reverb_listing for listing {listing_id}: {str(e)}")
                    # Skip this one but continue with others
            
            if reverb_listings:
                self.db.add_all(reverb_listings)
                logger.info(f"Created batch of {len(reverb_listings)} reverb listings")
            else:
                logger.warning("No valid reverb_listing records to create")
                
        except Exception as e:
            logger.error(f"Error in batch creation: {str(e)}")
            raise

        
    def _extract_brand(self, listing_data: Dict[str, Any]) -> str:
        """Extract the brand from listing data"""
        # First check for explicit brand field
        if listing_data.get('brand'):
            return listing_data.get('brand')
        
        # Try to extract from title
        title = listing_data.get('title', '')
        parts = title.split(' ', 1)
        return parts[0] if parts else ""


    def _extract_model(self, listing_data: Dict[str, Any]) -> str:
        """Extract the model from listing data"""
        # Try to extract from title
        title = listing_data.get('title', '')
        parts = title.split(' ', 1)
        return parts[1] if len(parts) > 1 else ""


    def _extract_price(self, listing_data: Dict[str, Any]) -> Optional[float]:
        """Extract price from listing data"""
        price_data = listing_data.get('price', {})
        if isinstance(price_data, dict):
            return price_data.get('amount')
        return price_data


    def _safe_float(self, value, default=0.0) -> float:
        """Safely convert a value to float"""
        if value is None:
            return default
        try:
            return float(value)
        except (ValueError, TypeError):
            logger.warning(f"Failed to convert '{value}' to float, using default {default}")
            return default


    def _safe_int(self, value, default=None) -> Optional[int]:
        """Safely convert a value to int"""
        if value is None:
            return default
        try:
            return int(value)
        except (ValueError, TypeError):
            logger.warning(f"Failed to convert '{value}' to int, using default {default}")
            return default

            
    def _safe_get(self, data, *keys, default=None):
        """Safely navigate nested dictionaries and lists"""
        current = data
        try:
            for key in keys:
                if isinstance(current, dict):
                    current = current.get(key, {})
                elif isinstance(current, list) and isinstance(key, int) and 0 <= key < len(current):
                    current = current[key]
                else:
                    return default
            return current if current != {} else default
        except Exception:
            return default

    
    def _extract_brand_model(self, title: str) -> tuple:
        """
        Extract brand and model from listing title
        """
        parts = title.split(' ', 1)
        if len(parts) > 1:
            return parts[0], parts[1]
        return parts[0], ""

    
    def _extract_year(self, listing_data: Dict[str, Any]) -> Optional[int]:
        """
        Extract year from listing data
        """
        # Check if year is in specs
        specs = listing_data.get('specs', {})
        if 'year' in specs:
            try:
                return int(specs['year'])
            except (ValueError, TypeError):
                pass
        
        # Try to extract from title
        title = listing_data.get('title', '')
        import re
        year_match = re.search(r'\b(19|20)\d{2}\b', title)
        if year_match:
            return int(year_match.group())
        
        return None

    
    def _map_condition(self, listing_data: Dict[str, Any]) -> str:
        """
        Map Reverb condition to our condition enum
        """
        # Extract condition name from the listing data
        condition = listing_data.get('condition', {})
        
        # Check if condition is a dict and extract the display name
        if isinstance(condition, dict):
            condition_name = condition.get('display_name', '')
        else:
            condition_name = str(condition)
        
        # If no valid condition name, return default
        if not condition_name:
            return ProductCondition.GOOD.value
        
        # Now we have a string, so we can safely use .lower()
        condition_name = condition_name.lower()
        
        # Map Reverb condition names to our enum values
        condition_map = {
            "mint": ProductCondition.EXCELLENT.value,
            "excellent": ProductCondition.EXCELLENT.value,
            "very good": ProductCondition.VERY_GOOD.value,
            "good": ProductCondition.GOOD.value,
            "fair": ProductCondition.FAIR.value,
            "poor": ProductCondition.POOR.value,
            "non functioning": ProductCondition.POOR.value
        }
        
        for reverb_condition, our_condition in condition_map.items():
            if reverb_condition in condition_name:
                return our_condition
        
        return ProductCondition.GOOD.value  # Default

  
    def _extract_condition_rating(self, listing_data: Dict[str, Any]) -> float:
        """Extract condition rating as a float"""
        try:
            # If it's already a number
            if isinstance(listing_data.get('condition_rating'), (int, float)):
                return float(listing_data.get('condition_rating'))
                
            # If it's a string, convert it
            rating_str = listing_data.get('condition_rating')
            if rating_str is not None:
                return float(rating_str)
        except (ValueError, TypeError):
            pass
            
        # Apply fallback logic - map condition descriptions to ratings
        condition = listing_data.get('condition', {})
        display_name = condition.get('display_name', '').lower()
        
        rating_map = {
            "mint": 5.0,
            "excellent": 4.5,
            # ...other mappings
        }
        
        for key, rating in rating_map.items():
            if key in display_name:
                return rating
        
        return 3.5  # Default to "Good"

    
    def _extract_category(self, listing_data: Dict[str, Any]) -> str:
        """
        Extract category name from listing data
        """
        categories = listing_data.get('categories', [])
        if categories:
            return categories[0].get('full_name', '')
        return ""

    
    def _get_primary_image(self, listing_data: Dict[str, Any]) -> Optional[str]:
        """
        Get primary image URL from listing data
        """
        photos = listing_data.get('photos', [])
        if photos:
            # Get the first photo's full URL
            return photos[0].get('_links', {}).get('full', {}).get('href')
        return None


    def _get_additional_images(self, listing_data: Dict[str, Any]) -> List[str]:
        """
        Get additional image URLs from listing data
        """
        photos = listing_data.get('photos', [])
        if len(photos) <= 1:
            return []
            
        # Skip the first photo (primary) and get the rest
        additional_urls = []
        for photo in photos[1:]:
            url = photo.get('_links', {}).get('full', {}).get('href')
            if url:
                additional_urls.append(url)
        
        return additional_urls


    def _prepare_extended_attributes(self, listing_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Prepare the extended_attributes JSONB field by:
        1. Starting with a copy of the full listing data
        2. Removing fields that are already stored in specific columns
        """
        # Make a shallow copy of the listing data
        attributes = listing_data.copy()
        
        # List of keys that are stored in specific columns (not needed in extended_attributes)
        excluded_keys = [
            'id', 'slug', 'categories', 'condition', 'inventory', 'has_inventory',
            'offers_enabled', 'auction', 'price', 'listing_currency', 'shipping_profile_id',
            'shop_policies_id', 'state', 'stats', 'created_at', 'published_at', 'handmade',
            # Also exclude these common fields
            'brand', 'model', 'year', 'description', 'photos'
        ]
        
        # Remove excluded keys if they exist
        for key in excluded_keys:
            if key in attributes:
                del attributes[key]
        
        return attributes

    def _convert_to_naive_datetime(self, dt):
        """Convert a timezone-aware datetime to a naive datetime for PostgreSQL"""
        if dt is None:
            return None
        
        # If datetime has timezone info, convert to UTC and remove timezone
        if dt.tzinfo is not None:
            return dt.replace(tzinfo=None)
        return dt

    # Add these methods to your ReverbImporter class in app/services/reverb/importer.py
    # async def import_sold_listings(self) -> Dict[str, int]:
    #     """
    #     Import all sold listings from Reverb orders API
        
    #     Returns:
    #         Dict[str, int]: Statistics about the import operation
    #     """
    #     stats = {
    #         "total": 0,
    #         "created": 0,
    #         "errors": 0,
    #         "skipped": 0,
    #         "sold_imported": 0
    #     }
        
    #     try:
    #         logger.info("Starting import of sold Reverb listings from orders API")
            
    #         # Get all sold orders from Reverb
    #         orders = await self.client.get_all_sold_orders()
            
    #         stats["total"] = len(orders)
    #         logger.info(f"Retrieved {stats['total']} sold orders from Reverb API")
            
    #         # Process in batches of 50
    #         BATCH_SIZE = 50
    #         total_orders = len(orders)
            
    #         for i in range(0, total_orders, BATCH_SIZE):
    #             batch = orders[i:i+BATCH_SIZE]
    #             logger.info(f"Processing batch {i//BATCH_SIZE + 1}/{math.ceil(total_orders/BATCH_SIZE)}")
                
    #             # Process order items as listings
    #             listings_data = []
    #             for order in batch:
    #                 try:
    #                     # Extract the listing data from the order
    #                     listing_data = self._extract_listing_from_order(order)
    #                     if listing_data:
    #                         listings_data.append(listing_data)
    #                 except Exception as e:
    #                     logger.error(f"Error extracting listing from order: {str(e)}")
    #                     stats["errors"] += 1
                
    #             # Process the extracted listings
    #             if listings_data:
    #                 try:
    #                     # Create database records for these sold listings
    #                     created = await self._create_sold_records_batch(listings_data)
    #                     stats["created"] += created
    #                     stats["sold_imported"] += created
    #                 except Exception as e:
    #                     stats["errors"] += len(listings_data)
    #                     logger.error(f"Error in sold batch processing: {str(e)}")
                
    #             # Commit after each batch
    #             await self.db.commit()
                
    #             # Report progress
    #             logger.info(f"Completed sold batch: {stats['created']}/{total_orders} imported")
            
    #         logger.info(f"Sold import complete: Created {stats['created']} listings, "
    #                 f"skipped {stats['skipped']}, errors {stats['errors']}")
    #         return stats
            
    #     except Exception as e:
    #         # Handle unexpected errors
    #         await self.db.rollback()
    #         logger.error(f"Critical error in sold import operation: {str(e)}")
    #         import traceback
    #         logger.error(traceback.format_exc())
    #         # Re-raise to caller
    #         raise ImportError(f"Failed to import sold Reverb listings: {str(e)}") from e

    # def _extract_listing_from_order(self, order: Dict[str, Any]) -> Dict[str, Any]:
    #     """
    #     Extract listing data from an order object
        
    #     Args:
    #         order: Order object from Reverb API
            
    #     Returns:
    #         Dict[str, Any]: Listing data in a format similar to listings API
    #     """
    #     # Extract the listing info from the order
    #     listing = order.get('listing_info', {})
        
    #     # Build a listing object similar to what we'd get from the listings API
    #     listing_data = {
    #         'id': listing.get('id'),
    #         'title': listing.get('title', ''),
    #         'description': listing.get('description', ''),
    #         'price': {
    #             'amount': order.get('amount', {}).get('amount', 0)
    #         },
    #         'condition': {
    #             'display_name': listing.get('condition', {}).get('display_name', '')
    #         },
    #         'photos': [], # Try to extract photos if available
    #         'categories': [{'full_name': listing.get('category', '')}],
    #         'make': listing.get('make', ''),
    #         'model': listing.get('model', ''),
    #         'year': listing.get('year'),
    #         'created_at': listing.get('created_at'),
    #         'published_at': listing.get('published_at'),
    #         'state': {'slug': 'sold'},  # Mark as sold
    #         'slug': listing.get('slug', ''),
    #         # Add any other fields that might be in the order data
    #         # Add order-specific fields
    #         'order_id': order.get('id'),
    #         'order_number': order.get('order_number'),
    #         'buyer_id': order.get('buyer', {}).get('id'),
    #         'buyer_name': order.get('buyer', {}).get('name'),
    #         'sold_at': order.get('created_at'),
    #         'sold': True  # Explicitly mark as sold
    #     }
        
    #     # Add additional order fields to extended attributes
    #     listing_data['order_data'] = {
    #         'shipping_address': order.get('shipping_address'),
    #         'shipping_price': order.get('shipping_amount', {}).get('amount'),
    #         'tax_amount': order.get('tax_amount', {}).get('amount'),
    #         'total_price': order.get('total_amount', {}).get('amount'),
    #         'payment_method': order.get('payment_method'),
    #         'payment_status': order.get('status')
    #     }
        
    #     return listing_data

    async def _create_sold_records_batch(self, listings_data: List[Dict[str, Any]]) -> int:
        """Create database records for sold listings"""
        created_count = 0
        skipped_count = 0  # Add a local counter for skipped items
        
        # First collect all SKUs we're about to create
        skus_to_create = []
        for listing_data in listings_data:
            if isinstance(listing_data, dict) and 'id' in listing_data:
                listing_id = str(listing_data['id'])
                sku = f"REV-{listing_id}"
                skus_to_create.append(sku)
        
        # Check which SKUs already exist
        existing_skus = set()
        if skus_to_create:
            skus_list = list(skus_to_create)
            stmt = text("SELECT sku FROM products WHERE sku = ANY(:skus)")
            result = await self.db.execute(stmt, {"skus": skus_list})
            existing_skus = {row[0] for row in result.fetchall()}
        
        # Also check which listing_ids already exist in reverb_listings
        existing_listing_ids = set()
        if listings_data:
            listing_ids = [str(ld['id']) for ld in listings_data if 'id' in ld]
            if listing_ids:
                stmt = text("SELECT reverb_listing_id FROM reverb_listings WHERE reverb_listing_id = ANY(:ids)")
                result = await self.db.execute(stmt, {"ids": listing_ids})
                existing_listing_ids = {row[0] for row in result.fetchall()}
        
        # Process each listing
        for listing_data in listings_data:
            try:
                # Ensure we have a valid listing ID
                listing_id = str(listing_data.get('id', ''))
                if not listing_id:
                    logger.warning("Skipping listing with missing ID")
                    continue
                    
                sku = f"REV-{listing_id}"
                
                # Skip if product already exists
                if sku in existing_skus:
                    skipped_count += 1  # Use the local counter
                    logger.debug(f"Skipping existing SKU: {sku}")
                    
                    # Check if listing exists but needs to be marked as sold
                    if listing_id not in existing_listing_ids:
                        # Create just the listing with sold status
                        await self._create_sold_listing_only(listing_id, listing_data)
                        created_count += 1
                    else:
                        # Update existing listing to sold status
                        await self._update_listing_to_sold(listing_id, listing_data)
                    continue
                
                # Create a descriptive title for products without listings
                title = listing_data.get('title', '')
                if listing_id.startswith('NOLIST') and not title:
                    # Try to create a descriptive title from available info
                    order_id = listing_data.get('order_id', 'Unknown Order')
                    price = listing_data.get('price', {}).get('amount', 0)
                    title = f"Sold Order #{order_id} (${price})"
                    listing_data['title'] = title
                
                # Create Product with more fields for no-listing items
                product = Product(
                    brand=self._extract_brand(listing_data),
                    model=self._extract_model(listing_data),
                    sku=sku,
                    year=self._safe_int(self._extract_year(listing_data)),
                    description=listing_data.get('description', ''),
                    condition=self._map_condition(listing_data),
                    category=self._extract_category(listing_data),
                    base_price=self._safe_float(self._extract_price(listing_data)),
                    primary_image=self._get_primary_image(listing_data),
                    additional_images=self._get_additional_images(listing_data),
                    status=ProductStatus.SOLD  # Mark as SOLD
                )
                
                self.db.add(product)
                await self.db.flush()
                
                # Create PlatformCommon
                now_naive = self._convert_to_naive_datetime(datetime.now(timezone.utc))
                
                platform_common = PlatformCommon(
                    product_id=product.id,
                    platform_name="reverb",
                    external_id=listing_id,
                    status=ListingStatus.SOLD,  # Mark as SOLD
                    sync_status=SyncStatus.SUCCESS,
                    last_sync=now_naive,
                    listing_url=self._safe_get(listing_data, '_links', 'web', 'href', default=''),
                    created_at=now_naive,
                    updated_at=now_naive
                )
                
                self.db.add(platform_common)
                await self.db.flush()
                
                # Create ReverbListing
                # Parse timestamps and handle potential None values
                reverb_created_at = self._parse_timestamp(listing_data.get('created_at'))
                reverb_published_at = self._parse_timestamp(listing_data.get('published_at'))
                reverb_sold_at = self._parse_timestamp(listing_data.get('sold_at'))
                
                # Prepare extended attributes with order data
                extended_attributes = self._prepare_extended_attributes(listing_data)
                
                # Add order-specific data
                if 'order_data' in listing_data:
                    extended_attributes['order_data'] = listing_data['order_data']
                
                # Add sold flag and no-listing indicator if applicable
                extended_attributes['sold'] = True
                if listing_id.startswith('NOLIST'):
                    extended_attributes['no_listing'] = True
                    extended_attributes['order_id'] = listing_data.get('order_id')
                
                reverb_listing = ReverbListing(
                    platform_id=platform_common.id,
                    reverb_listing_id=listing_id,
                    reverb_slug=listing_data.get('slug', ''),
                    reverb_category_uuid=self._safe_get(listing_data, 'categories', 0, 'uuid', default=''),
                    condition_rating=self._safe_float(self._extract_condition_rating(listing_data)),
                    inventory_quantity=0,  # Sold items have 0 inventory
                    has_inventory=False,   # No inventory
                    offers_enabled=False,  # No offers for sold items
                    is_auction=listing_data.get('auction', False),
                    list_price=self._safe_float(self._extract_price(listing_data)),
                    listing_currency=listing_data.get('listing_currency', 'USD'),
                    shipping_profile_id=listing_data.get('shipping_profile_id'),
                    shop_policies_id=listing_data.get('shop_policies_id'),
                    reverb_state='sold',  # Mark as sold
                    view_count=0,  # No view data for sold items
                    watch_count=0,  # No watch data for sold items
                    reverb_created_at=reverb_created_at,
                    reverb_published_at=reverb_published_at,
                    created_at=now_naive,
                    updated_at=now_naive,
                    last_synced_at=now_naive,
                    handmade=listing_data.get('handmade', False),
                    extended_attributes=extended_attributes
                )
                
                self.db.add(reverb_listing)
                created_count += 1
                
            except Exception as e:
                logger.error(f"Error creating sold record for listing {listing_data.get('id', 'unknown')}: {str(e)}")
                # Continue with next record
        
        # At the end of the _create_sold_records_batch method:
        logger.info(f"Created {created_count} listings, skipped {skipped_count}")
        return created_count, skipped_count  # Return both values

    def _parse_timestamp(self, timestamp_str):
        """Parse an ISO timestamp and convert to naive datetime"""
        if not timestamp_str:
            return None
        
        try:
            dt = iso8601.parse_date(timestamp_str)
            return self._convert_to_naive_datetime(dt)
        except Exception as e:
            logger.warning(f"Could not parse timestamp {timestamp_str}: {e}")
            return None

    async def _create_sold_listing_only(self, listing_id, listing_data):
        """Create just a reverb_listing record for an existing product"""
        # Find the platform_common record
        stmt = text("""
            SELECT pc.id
            FROM platform_common pc
            JOIN products p ON pc.product_id = p.id
            WHERE pc.external_id = :listing_id AND pc.platform_name = 'reverb'
        """)
        result = await self.db.execute(stmt, {"listing_id": listing_id})
        platform_id = result.scalar()
        
        if not platform_id:
            logger.warning(f"Could not find platform_common for listing {listing_id}")
            return
        
        # Create ReverbListing with sold status
        now_naive = self._convert_to_naive_datetime(datetime.now(timezone.utc))
        
        # Save the order data in extended_attributes
        extended_attributes = self._prepare_extended_attributes(listing_data)
        
        # Add order-specific data
        if 'order_data' in listing_data:
            extended_attributes['order_data'] = listing_data['order_data']
        
        # Add sold flag
        extended_attributes['sold'] = True
        
        reverb_listing = ReverbListing(
            platform_id=platform_id,
            reverb_listing_id=listing_id,
            reverb_slug=listing_data.get('slug', ''),
            reverb_state='sold',  # Mark as sold
            inventory_quantity=0, # Sold items have 0 inventory
            has_inventory=False,  # No inventory
            created_at=now_naive,
            updated_at=now_naive,
            last_synced_at=now_naive,
            extended_attributes=extended_attributes
        )
        
        self.db.add(reverb_listing)
        await self.db.flush()

    async def _update_listing_to_sold(self, listing_id, listing_data):
        """Update an existing listing to sold status"""
        # Find the listing
        stmt = text("""
            SELECT id FROM reverb_listings
            WHERE reverb_listing_id = :listing_id
        """)
        result = await self.db.execute(stmt, {"listing_id": listing_id})
        listing_id_db = result.scalar()
        
        if not listing_id_db:
            logger.warning(f"Could not find reverb_listing for {listing_id}")
            return
        
        # Update the listing status
        stmt = text("""
            UPDATE reverb_listings
            SET reverb_state = 'sold',
                has_inventory = FALSE,
                inventory_quantity = 0,
                updated_at = NOW(),
                last_synced_at = NOW(),
                extended_attributes = extended_attributes || :order_data::jsonb
            WHERE id = :id
        """)
        
        # Prepare order data as JSON
        order_data = {}
        if 'order_data' in listing_data:
            order_data['order_data'] = listing_data['order_data']
        order_data['sold'] = True
        
        await self.db.execute(stmt, {
            "id": listing_id_db,
            "order_data": json.dumps(order_data)
        })
        
        # Also update the platform_common status
        stmt = text("""
            UPDATE platform_common
            SET status = 'SOLD',
                updated_at = NOW()
            FROM reverb_listings
            WHERE reverb_listings.id = :listing_id
            AND platform_common.id = reverb_listings.platform_id
        """)
        await self.db.execute(stmt, {"listing_id": listing_id_db})
        
    async def import_sold_listings(self, use_cache=False) -> Dict[str, int]:
        """
        Import all sold listings from Reverb orders API, with caching to file
        
        Args:
            use_cache: Whether to try using cached data if available
        
        Returns:
            Dict[str, int]: Statistics about the import operation
        """
        stats = {
            "total": 0,
            "created": 0,
            "errors": 0,
            "skipped": 0,
            "sold_imported": 0,
            "cache_used": False
        }
        
        # Define cache file path pattern
        cache_dir = os.path.join("data", "reverb_orders")
        os.makedirs(cache_dir, exist_ok=True)
        cache_pattern = os.path.join(cache_dir, "reverb_orders_*.json")
        cache_file_used = None
        
        try:
            # 1. Get the orders data, either from cache or API
            orders = None
            cache_files = sorted(glob.glob(cache_pattern))
            
            # Try to use cache if requested and available
            if use_cache and cache_files:
                latest_cache = cache_files[-1]
                logger.info(f"Found cached orders data: {latest_cache}")
                
                try:
                    with open(latest_cache, 'r') as f:
                        orders = json.load(f)
                    stats["cache_used"] = True
                    cache_file_used = latest_cache
                    logger.info(f"Loaded {len(orders)} orders from cache")
                except Exception as e:
                    logger.error(f"Error loading cache file: {str(e)}")
                    orders = None
                    
            # If no cache or cache failed, fetch from API
            if orders is None:
                logger.info("Fetching sold listings from Reverb API")
                try:
                    # Get all sold orders from Reverb
                    orders = await self.client.get_all_sold_orders()
                    
                    # Save to cache file for future use
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    new_cache_file = os.path.join(cache_dir, f"reverb_orders_{timestamp}.json")
                    
                    with open(new_cache_file, 'w') as f:
                        json.dump(orders, f)
                    
                    logger.info(f"Saved {len(orders)} orders to cache file: {new_cache_file}")
                    cache_file_used = new_cache_file
                    
                except Exception as e:
                    logger.error(f"Error fetching orders from API: {str(e)}")
                    raise ImportError(f"Failed to fetch sold orders: {str(e)}")
            
            # 2. Initialize counter and stats
            stats["total"] = len(orders)
            logger.info(f"Processing {stats['total']} sold orders")
            
            # Get the next counter value for no-listing items
            no_listing_counter = await self._get_next_no_listing_counter()
            logger.info(f"Starting no-listing counter at: {no_listing_counter}")
            
            # 3. Pre-check existing SKUs to avoid duplicate key errors
            all_skus_to_check = set()
            counter_for_precheck = no_listing_counter  # Use a copy to avoid modifying the original
            
            for order in orders:
                try:
                    listing_id = None
                    # Try to get listing info
                    listing = order.get('listing_info') or order.get('listing') or {}
                    if isinstance(listing, dict):
                        listing_id = listing.get('id')
                    
                    # Generate SKU for checking
                    if not listing_id:
                        listing_id = f"NOLIST{counter_for_precheck:06d}"
                        counter_for_precheck += 1
                    
                    sku = f"REV-{listing_id}"
                    all_skus_to_check.add(sku)
                except Exception as e:
                    logger.warning(f"Error extracting SKU for pre-check: {str(e)}")
            
            # Check existing SKUs in database
            existing_skus = set()
            if all_skus_to_check:
                try:
                    stmt = text("SELECT sku FROM products WHERE sku = ANY(:skus)")
                    result = await self.db.execute(stmt, {"skus": list(all_skus_to_check)})
                    existing_skus = {row[0] for row in result.fetchall()}
                    if existing_skus:
                        logger.info(f"Found {len(existing_skus)} existing SKUs that will be skipped")
                except Exception as e:
                    logger.warning(f"Error checking existing SKUs: {str(e)}")
            
            # 4. Process orders to extract listings data
            all_listings_data = []
            
            for order in orders:
                try:
                    # Extract listing data with unique ID
                    listing_data = self._extract_listing_from_order(order, no_listing_counter)
                    
                    # If we generated a placeholder ID, increment counter
                    if listing_data and listing_data.get('id', '').startswith('NOLIST'):
                        no_listing_counter += 1
                    
                    if listing_data:
                        all_listings_data.append(listing_data)
                except Exception as e:
                    logger.error(f"Error extracting listing from order {order.get('id') or order.get('order_number') or 'unknown'}: {str(e)}")
                    stats["errors"] += 1
            
            # 5. Process listings in batches
            BATCH_SIZE = 50
            
            for i in range(0, len(all_listings_data), BATCH_SIZE):
                batch = all_listings_data[i:i+BATCH_SIZE]
                batch_num = i // BATCH_SIZE + 1
                total_batches = (len(all_listings_data) + BATCH_SIZE - 1) // BATCH_SIZE
                logger.info(f"Processing batch {batch_num}/{total_batches}")
                
                try:
                    # Process the batch and get stats
                    created_count, skipped_count = await self._create_sold_records_batch(batch)
                    stats["created"] += created_count
                    stats["skipped"] += skipped_count
                    stats["sold_imported"] += created_count
                    
                    # Commit after each successful batch
                    await self.db.commit()
                    logger.info(f"Batch {batch_num} committed: {created_count} created, {skipped_count} skipped")
                    
                except Exception as e:
                    # Rollback on error
                    await self.db.rollback()
                    stats["errors"] += len(batch)
                    logger.error(f"Error in batch {batch_num} processing: {str(e)}")
            
            # 6. Cleanup and final steps
            # If import was successful, save the counter and maybe delete cache
            if stats["created"] > 0:
                # Save the latest counter value
                self._save_no_listing_counter(no_listing_counter)
                
                # Delete cache file if completely successful
                if stats["cache_used"] and stats["errors"] == 0 and cache_file_used:
                    try:
                        os.unlink(cache_file_used)
                        logger.info(f"Deleted cache file after successful import: {cache_file_used}")
                    except Exception as e:
                        logger.warning(f"Could not delete cache file: {str(e)}")
            
            logger.info(f"Sold import complete: Created {stats['created']} listings, "
                    f"skipped {stats['skipped']}, errors {stats['errors']}")
            return stats
            
        except Exception as e:
            # Handle unexpected errors
            await self.db.rollback()
            logger.error(f"Critical error in sold import operation: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            raise ImportError(f"Failed to import sold Reverb listings: {str(e)}") from e
    
    async def _get_next_no_listing_counter(self) -> int:
        """Get the next counter value for 'no listing' SKU generation"""
        # First check if there are existing NOLIST SKUs in the database
        try:
            stmt = text("""
                SELECT MAX(CAST(SUBSTRING(sku FROM 11) AS INTEGER))
                FROM products
                WHERE sku LIKE 'REV-NOLIST%'
            """)
            result = await self.db.execute(stmt)
            highest_number = result.scalar()
            
            if highest_number:
                # Start from the next available number
                logger.info(f"Found existing NOLIST SKUs, starting counter at {highest_number + 1}")
                return highest_number + 1
        except Exception as e:
            logger.warning(f"Error checking for existing NOLIST SKUs: {str(e)}")
        
        # Check counter file as fallback
        counter_file = os.path.join("data", "reverb_orders", "no_listing_counter.txt")
        
        try:
            if os.path.exists(counter_file):
                with open(counter_file, 'r') as f:
                    return int(f.read().strip())
        except Exception as e:
            logger.warning(f"Error reading counter file: {str(e)}")
        
        # Default starting point
        return 1

    def _save_no_listing_counter(self, counter: int) -> None:
        """Save the current 'no listing' counter value"""
        counter_file = os.path.join("data", "reverb_orders", "no_listing_counter.txt")
        
        try:
            with open(counter_file, 'w') as f:
                f.write(str(counter))
        except Exception as e:
            logger.error(f"Error saving counter value: {str(e)}")

    def _extract_listing_from_order(self, order: Dict[str, Any], no_listing_counter: int = 0) -> Dict[str, Any]:
        """
        Extract listing data from an order object
        
        Args:
            order: Order object from Reverb API
            no_listing_counter: Counter for generating IDs for orders without listings
            
        Returns:
            Dict[str, Any]: Listing data for the order
        """
        # Make sure we have a valid order
        if not isinstance(order, dict):
            logger.warning(f"Converting invalid order object to dict: {type(order)}")
            order = {"invalid_order": True, "order_type": str(type(order))}
        
        # Extract the basic order info first
        order_id = order.get('id') or order.get('order_id')
        order_number = order.get('order_number')
        
        # Generate a reference ID for logs and tracking
        ref_id = order_id or order_number or f"unknown_order_{no_listing_counter}"
        
        # Extract the listing info - may be under different keys in different API responses
        listing = None
        listing_id = None
        
        # Try different paths to get listing info
        if 'listing_info' in order:
            listing = order.get('listing_info', {})
        elif 'listing' in order:
            listing = order.get('listing', {})
        
        # If we have a listing object, try to get the ID
        if listing and isinstance(listing, dict):
            listing_id = listing.get('id')
        
        # If we still don't have a listing ID, check if it's directly in the order
        if not listing_id and 'listing_id' in order:
            listing_id = order.get('listing_id')
        
        # Always generate a placeholder ID if needed
        if not listing_id:
            listing_id = f"NOLIST{no_listing_counter:06d}"
            logger.info(f"Generated placeholder ID {listing_id} for order {ref_id}")
        
        # Extract order amount - could be in different locations depending on API response
        amount = 0
        if 'amount' in order:
            if isinstance(order['amount'], dict) and 'amount' in order['amount']:
                amount = order['amount']['amount']
            elif isinstance(order['amount'], (int, float)):
                amount = order['amount']
        elif 'total_amount' in order:
            if isinstance(order['total_amount'], dict) and 'amount' in order['total_amount']:
                amount = order['total_amount']['amount']
        
        # Extract buyer info
        buyer = order.get('buyer', {})
        buyer_id = buyer.get('id') if isinstance(buyer, dict) else None
        buyer_name = buyer.get('name') if isinstance(buyer, dict) else None
        
        # Extract order shipping info
        shipping = {}
        for field in ['shipping_address', 'shipping_amount', 'tax_amount', 'total_amount']:
            if field in order:
                shipping[field] = order[field]
        
        # Extract other listing details from the listing object if available
        title = ''
        description = ''
        condition = {}
        make = ''
        model = ''
        year = None
        created_at = None
        published_at = None
        slug = ''
        
        if listing and isinstance(listing, dict):
            title = listing.get('title', '')
            description = listing.get('description', '')
            condition = listing.get('condition', {})
            make = listing.get('make', '')
            model = listing.get('model', '')
            year = listing.get('year')
            created_at = listing.get('created_at')
            published_at = listing.get('published_at')
            slug = listing.get('slug', '')
        
        # If title is missing but we have order details, create a descriptive title
        if not title:
            title = f"Reverb Order {ref_id}"
            if amount:
                title += f" (${amount})"
        
        # If no make/model, try to extract from title
        if not make and not model and title:
            parts = title.split(' ', 1)
            make = parts[0] if parts else "Unknown"
            model = parts[1] if len(parts) > 1 else "Model"
        
        # Build a listing object with all the data we've collected
        listing_data = {
            'id': listing_id,
            'title': title,
            'description': description or f"Order {ref_id} from Reverb",
            'price': {
                'amount': amount
            },
            'condition': condition or {'display_name': 'Good'},
            'photos': listing.get('photos', []) if isinstance(listing, dict) else [],
            'categories': [{'full_name': listing.get('category', '')}] if isinstance(listing, dict) and listing.get('category') else [],
            'make': make or "Unknown",
            'model': model or "Model",
            'year': year,
            'created_at': created_at or order.get('created_at'),
            'published_at': published_at,
            'state': {'slug': 'sold'},  # Mark as sold
            'slug': slug,
            # Add order-specific fields
            'order_id': order_id,
            'order_number': order_number,
            'buyer_id': buyer_id,
            'buyer_name': buyer_name,
            'sold_at': order.get('created_at'),
            'sold': True,  # Explicitly mark as sold
            'is_no_listing': not bool(listing),  # Flag for orders without listings
            'is_placeholder': listing_id.startswith('NOLIST')  # Flag for placeholder IDs
        }
        
        # Add additional order fields to extended attributes
        order_data = {
            'raw_order_id': ref_id,
            'payment_method': order.get('payment_method'),
            'payment_status': order.get('status')
        }
        
        # Safely extract nested values
        if 'shipping_address' in order and isinstance(order['shipping_address'], dict):
            order_data['shipping_address'] = order['shipping_address']
        
        for field in ['shipping_amount', 'tax_amount', 'total_amount']:
            if field in order:
                if isinstance(order[field], dict) and 'amount' in order[field]:
                    order_data[field.replace('_amount', '_price')] = order[field]['amount']
                elif isinstance(order[field], (int, float)):
                    order_data[field.replace('_amount', '_price')] = order[field]
        
        listing_data['order_data'] = order_data
        
        return listing_data