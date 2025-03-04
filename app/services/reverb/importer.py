# app/services/reverb/importer.py
import os
import logging
import asyncio
import math
import iso8601
from typing import Dict, List, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime
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
                    
                    platform_common = PlatformCommon(
                        product_id=product.id,
                        platform_name="reverb",
                        external_id=listing_id,
                        status=ListingStatus.ACTIVE,
                        sync_status=SyncStatus.SUCCESS,
                        last_sync=datetime.utcnow(),
                        listing_url=self._safe_get(listing_data, '_links', 'web', 'href', default='')
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
                            reverb_created_at = iso8601.parse_date(listing_data['created_at'])
                        except Exception as e:
                            logger.warning(f"Could not parse created_at timestamp: {e}")
                    
                    reverb_published_at = None
                    if listing_data.get('published_at'):
                        try:
                            reverb_published_at = iso8601.parse_date(listing_data['published_at'])
                        except Exception as e:
                            logger.warning(f"Could not parse published_at timestamp: {e}")

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
                        handmade=listing_data.get('handmade', False),
                        last_synced_at=datetime.utcnow(),
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