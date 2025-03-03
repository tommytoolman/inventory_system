# app/services/reverb/importer.py
import os
import logging
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
        try:
            logger.info("Starting import of all Reverb listings")
            
            # Get all listings from Reverb
            listings = await self.client.get_all_listings()           
            
            stats = {
                "total": len(listings),
                "created": 0,
                "errors": 0
            }
            
            for listing_data in listings:
                try:
                    # Get detailed listing info
                    listing_id = listing_data.get('id')
                    if not listing_id:
                        continue
                        
                    details = await self.client.get_listing_details(listing_id)
                    
                    # Create database records
                    await self._create_database_records(details)
                    stats["created"] += 1
                    
                except Exception as e:
                    import traceback
                    logger.error(f"Error importing listing: {str(e)}")
                    traceback.print_exc()  # Prints the full traceback
                    # print(listings)
                    stats["errors"] += 1
            
            await self.db.commit()
            logger.info(f"Import complete: {stats}")
            return stats
            
        except Exception as e:
            import traceback
            await self.db.rollback()
            logger.error(f"Error in import operation: {str(e)}")
            traceback.print_exc()  # Prints the full traceback
            raise
    
    async def _create_database_records(self, listing_data: Dict[str, Any]) -> None:
        """Create database records from validated Reverb listing data"""
        try:
            # Validate and convert all inputs first
            listing_id = listing_data.get('id', '')
            
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
            
            # Log validation results for debugging
            logger.debug(f"Validated data for listing {validated_data['sku']}: {validated_data}")
            
            # Create product with validated data
            product = Product(**validated_data, status=ProductStatus.ACTIVE)
            self.db.add(product)
            await self.db.flush()  # Get the product ID

            # Create platform_common with validated data
            platform_common = PlatformCommon(
                product_id=str(product.id),
                platform_name="reverb",
                external_id=str(listing_id),
                status=ListingStatus.ACTIVE,
                sync_status=SyncStatus.SUCCESS,
                last_sync=datetime.utcnow(),
                listing_url=listing_data.get('_links', {}).get('web', {}).get('href')
            )
            self.db.add(platform_common)
            await self.db.flush()

            # Create reverb_listing with the new reverb_listing_id field
            reverb_listing = ReverbListing(
                platform_id=platform_common.id,
                reverb_listing_id=listing_id,  # Add the Reverb ID
                reverb_category_uuid=self._safe_get(listing_data, 'categories', 0, 'uuid'),
                condition_rating=self._extract_condition_rating(listing_data),
                shipping_profile_id=listing_data.get('shipping_profile_id'),
                shop_policies_id=listing_data.get('shop_policies_id'),
                handmade=listing_data.get('handmade', False),
                offers_enabled=listing_data.get('offers_enabled', False),
                last_synced_at=datetime.utcnow()
            )
            self.db.add(reverb_listing)
            
            logger.info(f"Created records for Reverb listing {listing_id}")
            
        except Exception as e:
            logger.error(f"Error creating database records for listing {listing_id}: {str(e)}")
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
