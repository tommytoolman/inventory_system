# app.services.reverb_service.py
# """
# Purpose: Manages high-level operations and integration logic for Reverb listings via enterprise-grade integration with Reverb marketplace

# Role: Primary service layer for Reverb-specific logic. This service layer integrates the Reverb API with our inventory management system,
# providing high-level business operations and synchronization between platforms.

# Key Functionality:
# 1. Draft Creation - Create listings in draft state
# 2. Publishing - Move drafts to live listings
# 3. Inventory Sync - Keep stock levels in sync across platforms
# 4. Mapping - Convert between our data models and Reverb's API formats
# 5. Error Handling - Robust error handling with proper transaction management

# Usage:
#     reverb_service = ReverbService(db_session, settings)
    
#     # Create a draft listing
#     draft = await reverb_service.create_draft_listing(platform_id, listing_data)
    
#     # Publish a draft
#     success = await reverb_service.publish_listing(listing_id)
    
#     # Update inventory
#     success = await reverb_service.update_inventory(listing_id, new_quantity)
# """

# import logging

# from typing import Optional, Dict, List, Any, Tuple
# from sqlalchemy.ext.asyncio import AsyncSession
# from sqlalchemy import select
# from datetime import datetime, timezone


# from app.models.reverb import ReverbListing
# from app.models.platform_common import PlatformCommon, ListingStatus, SyncStatus
# from app.models.product import Product
# from app.schemas.platform.reverb import ReverbListingCreateDTO
# from app.core.config import Settings
# from app.core.exceptions import ReverbAPIError, ListingNotFoundError, SyncError
# from app.services.reverb.client import ReverbClient

# logger = logging.getLogger(__name__)

# class ReverbService:
    # """
    # Service for interacting with Reverb marketplace.
    
    # This class manages the integration between our inventory system and
    # the Reverb platform, handling data transformation, error handling,
    # and synchronization.
    # """
    
    # # Mapping between our condition values and Reverb's UUIDs
    # # These UUIDs should be fetched dynamically, but we provide defaults
    # CONDITION_MAPPING = {
    #     "NEW": "7c3f45de-2ae0-4c81-8400-fdb6b1d74890",       # Brand New
    #     "EXCELLENT": "df268ad1-c462-4ba6-b6db-e007e23922ea", # Excellent
    #     "VERYGOOD": "ae4d9114-1bd7-4ec5-a4ba-6653af5ac84d",  # Very Good
    #     "GOOD": "f7a3f48c-972a-44c6-b01a-0cd27488d3f6",      # Good
    #     "FAIR": "98777886-76d0-44c8-865e-bb40e669e934",      # Fair
    #     "POOR": "6a9dfcad-600b-46c8-9e08-ce6e5057921e"       # Poor
    # }
    
    # def __init__(self, db: AsyncSession, settings: Settings):
    #     """
    #     Initialize the Reverb service
        
    #     Args:
    #         db: Database session
    #         settings: Application settings
    #     """
    #     self.db = db
    #     self.settings = settings
        
    #     # Check if sandbox API key is available and use it if specified
    #     if hasattr(settings, 'REVERB_SANDBOX_MODE') and settings.REVERB_SANDBOX_MODE:
    #         # Use sandbox environment with sandbox API key
    #         api_key = getattr(settings, 'REVERB_SANDBOX_API_KEY', settings.REVERB_API_KEY)
    #         self.client = ReverbClient(api_key=api_key, use_sandbox=True)
    #         logger.info("Using Reverb sandbox environment")
    #     else:
    #         # Use production environment
    #         self.client = ReverbClient(api_key=settings.REVERB_API_KEY, use_sandbox=False)
    #         logger.info("Using Reverb production environment")
        
    # async def create_draft_listing(
    #     self,
    #     platform_id: int,
    #     listing_data: Dict[str, Any]
    # ) -> ReverbListing:
    #     """
    #     Creates a draft listing on Reverb.
    #     Does not publish - just prepares the listing data.
        
    #     Args:
    #         platform_id: ID of the platform_common record
    #         listing_data: Data for the listing
            
    #     Returns:
    #         ReverbListing: The created listing record
            
    #     Raises:
    #         ListingNotFoundError: If platform listing not found
    #         ReverbAPIError: If the API request fails
    #     """
    #     try:
    #         # Get platform common record and associated product
    #         platform_common = await self._get_platform_common(platform_id)
    #         if not platform_common:
    #             raise ListingNotFoundError(f"Platform listing {platform_id} not found")
            
    #         product = platform_common.product
            
    #         # Create local Reverb listing record
    #         reverb_listing = await self._create_listing_record(platform_common, listing_data)
            
    #         # Prepare listing data for Reverb API
    #         api_listing_data = self._prepare_listing_data(reverb_listing, product)
            
    #         # Create listing on Reverb (as draft by default)
    #         response = await self.client.create_listing(api_listing_data)
            
    #         # Update local record with Reverb ID and metadata
    #         if 'id' in response:
    #             # Extract Reverb's listing ID
    #             reverb_listing.reverb_listing_id = str(response['id'])
                
    #             # Update status
    #             platform_common.sync_status = SyncStatus.SYNCED.value
    #             platform_common.last_sync = datetime.now(timezone.utc)
                
    #             await self.db.commit()
    #         else:
    #             logger.error(f"Unexpected response from Reverb API: {response}")
    #             raise ReverbAPIError("Failed to extract listing ID from Reverb response")
            
    #         return reverb_listing
            
    #     except Exception as e:
    #         await self.db.rollback()
    #         if isinstance(e, (ListingNotFoundError, ReverbAPIError)):
    #             raise
    #         logger.error(f"Error creating Reverb draft: {str(e)}")
    #         raise ReverbAPIError(f"Failed to create Reverb draft: {str(e)}")
    
    # async def publish_listing(self, reverb_listing_id: int) -> bool:
    #     """
    #     Publish a draft listing to make it live on Reverb
        
    #     Args:
    #         reverb_listing_id: Database ID of the ReverbListing
            
    #     Returns:
    #         bool: True if successful
            
    #     Raises:
    #         ListingNotFoundError: If listing not found
    #         ReverbAPIError: If the API request fails
    #     """
    #     try:
    #         # Get the listing record
    #         listing = await self._get_reverb_listing(reverb_listing_id)
    #         if not listing:
    #             raise ListingNotFoundError(f"Reverb listing {reverb_listing_id} not found")
            
    #         # Check if we have a Reverb ID
    #         if not listing.reverb_listing_id:
    #             raise ReverbAPIError("Cannot publish listing: missing Reverb listing ID")
            
    #         # Publish on Reverb
    #         response = await self.client.publish_listing(listing.reverb_listing_id)
            
    #         # Update local status
    #         if response:
    #             listing.platform_listing.status = ListingStatus.ACTIVE.value
    #             listing.platform_listing.sync_status = SyncStatus.SYNCED.value
    #             listing.platform_listing.last_sync = datetime.now(timezone.utc)
                
    #             await self.db.commit()
    #             return True
            
    #         return False
            
    #     except Exception as e:
    #         await self.db.rollback()
    #         if isinstance(e, (ListingNotFoundError, ReverbAPIError)):
    #             raise
    #         logger.error(f"Error publishing listing: {str(e)}")
    #         raise ReverbAPIError(f"Failed to publish listing: {str(e)}")
    
    # async def update_inventory(self, reverb_listing_id: int, quantity: int) -> bool:
    #     """
    #     Update inventory quantity for a specific listing
        
    #     Args:
    #         reverb_listing_id: Database ID of the ReverbListing
    #         quantity: New quantity value
            
    #     Returns:
    #         bool: True if successful
            
    #     Raises:
    #         ListingNotFoundError: If listing not found
    #         ReverbAPIError: If the API request fails
    #     """
    #     try:
    #         # Get the listing record
    #         listing = await self._get_reverb_listing(reverb_listing_id)
    #         if not listing:
    #             raise ListingNotFoundError(f"Reverb listing {reverb_listing_id} not found")
            
    #         # Check if we have a Reverb ID
    #         if not listing.reverb_listing_id:
    #             raise ReverbAPIError("Cannot update inventory: missing Reverb listing ID")
            
    #         # Update inventory on Reverb
    #         update_data = {
    #             "has_inventory": True,
    #             "inventory": quantity
    #         }
            
    #         response = await self.client.update_listing(listing.reverb_listing_id, update_data)
            
    #         # Update local status
    #         if response:
    #             listing.platform_listing.sync_status = SyncStatus.SYNCED.value
    #             listing.platform_listing.last_sync = datetime.now(timezone.utc)
                
    #             await self.db.commit()
    #             return True
            
    #         return False
            
    #     except Exception as e:
    #         await self.db.rollback()
    #         if isinstance(e, (ListingNotFoundError, ReverbAPIError)):
    #             raise
    #         logger.error(f"Error updating inventory: {str(e)}")
    #         raise ReverbAPIError(f"Failed to update inventory: {str(e)}")
    
    # async def sync_listing_from_reverb(self, reverb_listing_id: int) -> bool:
    #     """
    #     Sync a listing's data from Reverb to update our local copy
        
    #     Args:
    #         reverb_listing_id: Database ID of the ReverbListing
            
    #     Returns:
    #         bool: True if successful
            
    #     Raises:
    #         ListingNotFoundError: If listing not found
    #         ReverbAPIError: If the API request fails
    #     """
    #     try:
    #         # Get the listing record
    #         listing = await self._get_reverb_listing(reverb_listing_id)
    #         if not listing:
    #             raise ListingNotFoundError(f"Reverb listing {reverb_listing_id} not found")
            
    #         # Check if we have a Reverb ID
    #         if not listing.reverb_listing_id:
    #             raise ReverbAPIError("Cannot sync listing: missing Reverb listing ID")
            
    #         # Get current data from Reverb
    #         response = await self.client.get_listing(listing.reverb_listing_id)
            
    #         # Update local record
    #         if 'state' in response:
    #             # Map Reverb state to our status enum
    #             state_mapping = {
    #                 'draft': ListingStatus.DRAFT,
    #                 'published': ListingStatus.ACTIVE,
    #                 'ended': ListingStatus.ENDED
    #             }
                
    #             reverb_state = response.get('state', 'draft')
    #             our_status = state_mapping.get(reverb_state, ListingStatus.DRAFT).value
                
    #             listing.platform_listing.status = our_status
    #             listing.platform_listing.sync_status = SyncStatus.SYNCED.value
    #             listing.platform_listing.last_sync = datetime.now(timezone.utc)
                
    #             # Update offers enabled
    #             listing.offers_enabled = response.get('offers_enabled', True)
                
    #             # Update condition
    #             if 'condition' in response and 'uuid' in response['condition']:
    #                 # Reverse lookup in our condition mapping
    #                 condition_uuid = response['condition']['uuid']
    #                 for our_condition, reverb_uuid in self.CONDITION_MAPPING.items():
    #                     if reverb_uuid == condition_uuid:
    #                         listing.condition_rating = our_condition
    #                         break
                
    #             await self.db.commit()
    #             return True
            
    #         return False
            
    #     except Exception as e:
    #         await self.db.rollback()
    #         if isinstance(e, (ListingNotFoundError, ReverbAPIError)):
    #             raise
    #         logger.error(f"Error syncing listing: {str(e)}")
    #         raise ReverbAPIError(f"Failed to sync listing: {str(e)}")
    
    # async def find_listing_by_sku(self, sku: str) -> Optional[Dict]:
    #     """
    #     Find a listing on Reverb by its SKU
        
    #     Args:
    #         sku: Product SKU
            
    #     Returns:
    #         Optional[Dict]: Listing data if found, None otherwise
            
    #     Raises:
    #         ReverbAPIError: If the API request fails
    #     """
    #     try:
    #         response = await self.client.find_listing_by_sku(sku)
            
    #         # Check if any listings were found
    #         if response and 'listings' in response and response['listings']:
    #             return response['listings'][0]
            
    #         return None
            
    #     except Exception as e:
    #         logger.error(f"Error finding listing by SKU: {str(e)}")
    #         if isinstance(e, ReverbAPIError):
    #             raise
    #         raise ReverbAPIError(f"Failed to find listing by SKU: {str(e)}")
    
    # async def end_listing(self, reverb_listing_id: int, reason: str = "not_sold") -> bool:
    #     """
    #     End a live listing on Reverb
        
    #     Args:
    #         reverb_listing_id: Database ID of the ReverbListing
    #         reason: Reason for ending (not_sold or reverb_sale)
            
    #     Returns:
    #         bool: True if successful
            
    #     Raises:
    #         ListingNotFoundError: If listing not found
    #         ReverbAPIError: If the API request fails
    #     """
    #     try:
    #         # Get the listing record
    #         listing = await self._get_reverb_listing(reverb_listing_id)
    #         if not listing:
    #             raise ListingNotFoundError(f"Reverb listing {reverb_listing_id} not found")
            
    #         # Check if we have a Reverb ID
    #         if not listing.reverb_listing_id:
    #             raise ReverbAPIError("Cannot end listing: missing Reverb listing ID")
            
    #         # End the listing on Reverb
    #         response = await self.client.end_listing(listing.reverb_listing_id, reason)
            
    #         # Update local status
    #         if response:
    #             listing.platform_listing.status = ListingStatus.ENDED.value
    #             listing.platform_listing.sync_status = SyncStatus.SYNCED.value
    #             listing.platform_listing.last_sync = datetime.now(timezone.utc)
                
    #             await self.db.commit()
    #             return True
            
    #         return False
            
    #     except Exception as e:
    #         await self.db.rollback()
    #         if isinstance(e, (ListingNotFoundError, ReverbAPIError)):
    #             raise
    #         logger.error(f"Error ending listing: {str(e)}")
    #         raise ReverbAPIError(f"Failed to end listing: {str(e)}")
    
    # async def fetch_and_store_category_mapping(self) -> Dict[str, str]:
    #     """
    #     Fetch categories from Reverb and store for future use
        
    #     Returns:
    #         Dict[str, str]: Mapping of category names to UUIDs
            
    #     Raises:
    #         ReverbAPIError: If the API request fails
    #     """
    #     try:
    #         response = await self.client.get_categories()
            
    #         # Extract categories and create a mapping of names to UUIDs
    #         category_mapping = {}
            
    #         if 'categories' in response:
    #             for category in response['categories']:
    #                 if 'name' in category and 'uuid' in category:
    #                     category_mapping[category['name']] = category['uuid']
            
    #         return category_mapping
            
    #     except Exception as e:
    #         logger.error(f"Error fetching categories: {str(e)}")
    #         if isinstance(e, ReverbAPIError):
    #             raise
    #         raise ReverbAPIError(f"Failed to fetch categories: {str(e)}")
    
    # async def fetch_and_store_condition_mapping(self) -> Dict[str, str]:
    #     """
    #     Fetch conditions from Reverb and store for future use
        
    #     Returns:
    #         Dict[str, str]: Mapping of condition display names to UUIDs
            
    #     Raises:
    #         ReverbAPIError: If the API request fails
    #     """
    #     try:
    #         response = await self.client.get_listing_conditions()
            
    #         # Extract conditions and create a mapping of display names to UUIDs
    #         condition_mapping = {}
            
    #         if 'conditions' in response:
    #             for condition in response['conditions']:
    #                 if 'display_name' in condition and 'uuid' in condition:
    #                     condition_mapping[condition['display_name']] = condition['uuid']
            
    #         return condition_mapping
            
    #     except Exception as e:
    #         logger.error(f"Error fetching conditions: {str(e)}")
    #         if isinstance(e, ReverbAPIError):
    #             raise
    #         raise ReverbAPIError(f"Failed to fetch conditions: {str(e)}")
    
    # async def get_listing_details(self, reverb_listing_id: int) -> Dict:
    #     """
    #     Get detailed information about a listing from Reverb API
        
    #     Args:
    #         reverb_listing_id: Database ID of the ReverbListing
            
    #     Returns:
    #         Dict: Listing details from Reverb API
            
    #     Raises:
    #         ListingNotFoundError: If listing not found
    #         ReverbAPIError: If the API request fails
    #     """
    #     try:
    #         listing = await self._get_reverb_listing(reverb_listing_id)
    #         if not listing:
    #             raise ListingNotFoundError(f"Reverb listing {reverb_listing_id} not found")
                
    #         if not listing.reverb_listing_id:
    #             raise ReverbAPIError("Cannot get details: missing Reverb listing ID")
                
    #         # Get details from Reverb API
    #         details = await self.client.get_listing_details(listing.reverb_listing_id)
    #         return details
            
    #     except Exception as e:
    #         if isinstance(e, (ListingNotFoundError, ReverbAPIError)):
    #             raise
    #         logger.error(f"Error getting listing details: {str(e)}")
    #         raise ReverbAPIError(f"Failed to get listing details: {str(e)}")
    
    # # Private helper methods
    
    # async def _get_platform_common(self, platform_id: int) -> Optional[PlatformCommon]:
    #     """Get platform_common record by ID with associated product"""
    #     query = select(PlatformCommon).where(PlatformCommon.id == platform_id)
    #     result = await self.db.execute(query)
    #     return result.scalar_one_or_none()
    
    # async def _get_reverb_listing(self, listing_id: int) -> Optional[ReverbListing]:
    #     """Get ReverbListing record by ID with associated platform_common"""
    #     query = select(ReverbListing).where(ReverbListing.id == listing_id)
    #     result = await self.db.execute(query)
    #     return result.scalar_one_or_none()
    
    # async def _create_listing_record(
    #     self,
    #     platform_common: PlatformCommon,
    #     listing_data: Dict[str, Any]
    # ) -> ReverbListing:
    #     """Create the local ReverbListing record"""
    #     reverb_listing = ReverbListing(
    #         platform_id=platform_common.id,
    #         reverb_category_uuid=listing_data.get("category_uuid"),
    #         condition_rating=listing_data.get("condition_rating"),
    #         shipping_profile_id=listing_data.get("shipping_profile_id"),
    #         shop_policies_id=listing_data.get("shop_policies_id"),
    #         handmade=listing_data.get("handmade", False),
    #         offers_enabled=listing_data.get("offers_enabled", True)
    #     )
        
    #     self.db.add(reverb_listing)
    #     await self.db.flush()
    #     return reverb_listing
    
    # def _prepare_listing_data(self, listing: ReverbListing, product: Product) -> Dict[str, Any]:
    #     """
    #     Prepare listing data for Reverb API.
        
    #     Args:
    #         listing: ReverbListing model
    #         product: Product model
            
    #     Returns:
    #         Dict[str, Any]: Data formatted for Reverb API
    #     """
    #     # Get Reverb condition UUID from our condition value
    #     condition_uuid = self.CONDITION_MAPPING.get(
    #         product.condition,
    #         "df268ad1-c462-4ba6-b6db-e007e23922ea"  # Default to "Excellent"
    #     )
        
    #     # Format photos array
    #     photos = []
    #     if product.primary_image:
    #         photos.append(product.primary_image)
        
    #     if product.additional_images:
    #         # additional_images might be a list or a JSON string
    #         if isinstance(product.additional_images, list):
    #             photos.extend(product.additional_images)
    #         else:
    #             # Try to parse as JSON if it's a string
    #             try:
    #                 import json
    #                 additional = json.loads(product.additional_images)
    #                 if isinstance(additional, list):
    #                     photos.extend(additional)
    #             except Exception:
    #                 # If parsing fails, assume it's a single URL
    #                 photos.append(product.additional_images)
        
    #     # Format a video object if we have a video URL
    #     videos = []
    #     if product.video_url:
    #         videos.append({"link": product.video_url})
        
    #     # Prepare the base listing data
    #     listing_data = {
    #         "make": product.brand,
    #         "model": product.model,
    #         "categories": [
    #             {
    #                 "uuid": listing.reverb_category_uuid
    #             }
    #         ],
    #         "condition": {
    #             "uuid": condition_uuid
    #         },
    #         "photos": photos,
    #         "videos": videos,
    #         "description": product.description or f"{product.brand} {product.model}",
    #         "finish": product.finish,
    #         "price": {
    #             "amount": str(product.base_price),
    #             "currency": "USD"  # This could be configurable
    #         },
    #         "title": f"{product.brand} {product.model}",
    #         "year": str(product.year) if product.year else "",
    #         "sku": product.sku,
    #         "has_inventory": True,
    #         "inventory": 1,  # Default inventory
    #         "offers_enabled": listing.offers_enabled,
    #         "handmade": listing.handmade
    #     }
        
    #     # Add shipping profile if available
    #     if listing.shipping_profile_id:
    #         listing_data["shipping_profile_id"] = listing.shipping_profile_id
    #     else:
    #         # Default shipping configuration
    #         listing_data["shipping"] = {
    #             "rates": [
    #                 {
    #                     "rate": {
    #                         "amount": "10.00",
    #                         "currency": "USD"
    #                     },
    #                     "region_code": "US_CON"  # Continental US
    #                 },
    #                 {
    #                     "rate": {
    #                         "amount": "20.00",
    #                         "currency": "USD"
    #                     },
    #                     "region_code": "XX"  # Everywhere Else
    #                 }
    #             ],
    #             "local": True  # Allow local pickup
    #         }
        
    #     return listing_data
    
    
from typing import Dict, List, Optional, Any, Tuple
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import update

from app.models.platform_common import PlatformCommon, ListingStatus, SyncStatus
from app.models.product import Product
from app.models.reverb import ReverbListing
from app.services.reverb.client import ReverbClient
from app.core.config import Settings
from app.core.exceptions import ListingNotFoundError, ReverbAPIError
import logging

logger = logging.getLogger(__name__)

class ReverbService:
    """
    Service for interacting with Reverb marketplace.
    
    This class manages the integration between our inventory system and
    the Reverb platform, handling data transformation, error handling,
    and synchronization.
    """
    
    def __init__(self, db: AsyncSession, settings: Settings):
        """
        Initialize the Reverb service with database session and settings.
        
        Args:
            db: Database session for data access
            settings: Application settings including API credentials
        """
        self.db = db
        self.settings = settings
        
        # Use sandbox API for testing if enabled in settings
        use_sandbox = self.settings.REVERB_USE_SANDBOX
        api_key = self.settings.REVERB_SANDBOX_API_KEY if use_sandbox else self.settings.REVERB_API_KEY
        
        self.client = ReverbClient(api_key=api_key, use_sandbox=use_sandbox)
    
    async def get_categories(self) -> Dict:
        """
        Get all categories from Reverb.
        
        Returns:
            Dict: Categories data
            
        Raises:
            ReverbAPIError: If the API request fails
        """
        try:
            return await self.client.get_categories()
        except Exception as e:
            logger.error(f"Error fetching categories: {str(e)}")
            if isinstance(e, ReverbAPIError):
                raise
            raise ReverbAPIError(f"Failed to fetch categories: {str(e)}")
    
    async def get_category(self, uuid: str) -> Dict:
        """
        Get a specific category by UUID.
        
        Args:
            uuid: Category UUID
            
        Returns:
            Dict: Category data
            
        Raises:
            ReverbAPIError: If the API request fails
        """
        try:
            return await self.client.get_category(uuid)
        except Exception as e:
            logger.error(f"Error fetching category {uuid}: {str(e)}")
            if isinstance(e, ReverbAPIError):
                raise
            raise ReverbAPIError(f"Failed to fetch category {uuid}: {str(e)}")
    
    async def get_conditions(self) -> Dict:
        """
        Get all listing conditions from Reverb.
        
        Returns:
            Dict: Listing conditions data
            
        Raises:
            ReverbAPIError: If the API request fails
        """
        try:
            return await self.client.get_listing_conditions()
        except Exception as e:
            logger.error(f"Error fetching conditions: {str(e)}")
            if isinstance(e, ReverbAPIError):
                raise
            raise ReverbAPIError(f"Failed to fetch conditions: {str(e)}")
            
    async def fetch_and_store_condition_mapping(self) -> Dict[str, str]:
        """
        Fetch conditions from Reverb and store for future use
        
        Returns:
            Dict[str, str]: Mapping of condition display names to UUIDs
            
        Raises:
            ReverbAPIError: If the API request fails
        """
        try:
            response = await self.client.get_listing_conditions()
            
            # Extract conditions and create a mapping of display names to UUIDs
            condition_mapping = {}
            
            if 'conditions' in response:
                for condition in response['conditions']:
                    if 'display_name' in condition and 'uuid' in condition:
                        condition_mapping[condition['display_name']] = condition['uuid']
            
            return condition_mapping
        except Exception as e:
            logger.error(f"Error fetching conditions: {str(e)}")
            if isinstance(e, ReverbAPIError):
                raise
            raise ReverbAPIError(f"Failed to fetch conditions: {str(e)}")
    
    async def create_draft_listing(self, reverb_listing_id: int, listing_data: Dict[str, Any] = None) -> ReverbListing:
        """
        Create a draft listing on Reverb based on product data.
        
        Args:
            reverb_listing_id: Database ID of the ReverbListing
            listing_data: Optional custom listing data overrides
            
        Returns:
            ReverbListing: Updated database record with Reverb listing ID
            
        Raises:
            ListingNotFoundError: If listing not found
            ReverbAPIError: If the API request fails
        """
        try:
            # Get the ReverbListing and associated PlatformCommon and Product
            listing = await self._get_reverb_listing(reverb_listing_id)
            if not listing:
                raise ListingNotFoundError(f"ReverbListing {reverb_listing_id} not found")
            
            platform_common = await self._get_platform_common(listing.platform_id)
            if not platform_common or not platform_common.product_id:
                raise ListingNotFoundError(f"PlatformCommon {listing.platform_id} or related Product not found")
            
            product = await self._get_product(platform_common.product_id)
            if not product:
                raise ListingNotFoundError(f"Product {platform_common.product_id} not found")
            
            # Prepare the listing data for Reverb API
            api_listing_data = listing_data or self._prepare_listing_data(listing, product)
            
            # Create the listing on Reverb
            response = await self.client.create_listing(api_listing_data)
            
            # Update database with the new Reverb listing ID
            if 'listing' in response and 'id' in response['listing']:
                reverb_id = str(response['listing']['id'])
                
                # Update the ReverbListing record
                listing.reverb_listing_id = reverb_id
                
                # Update platform_common sync status
                platform_common.sync_status = SyncStatus.SYNCED.value
                
                # Save changes to database
                self.db.add(listing)
                self.db.add(platform_common)
                await self.db.flush()
                
                logger.info(f"Created draft listing on Reverb with ID {reverb_id}")
                return listing
            else:
                logger.error(f"Failed to create listing: No listing ID in response: {response}")
                raise ReverbAPIError("Failed to create listing: No listing ID in response")
                
        except Exception as e:
            logger.error(f"Error creating draft listing: {str(e)}")
            if isinstance(e, (ListingNotFoundError, ReverbAPIError)):
                raise
            raise ReverbAPIError(f"Failed to create draft listing: {str(e)}")
    
    async def get_listing_details(self, reverb_listing_id: int) -> Dict:
        """
        Get detailed information about a listing from Reverb API
        
        Args:
            reverb_listing_id: Database ID of the ReverbListing
            
        Returns:
            Dict: Listing details from Reverb API
            
        Raises:
            ListingNotFoundError: If listing not found
            ReverbAPIError: If the API request fails
        """
        try:
            # Get the ReverbListing record
            listing = await self._get_reverb_listing(reverb_listing_id)
            if not listing or not listing.reverb_listing_id:
                raise ListingNotFoundError(f"ReverbListing {reverb_listing_id} not found or has no Reverb ID")
            
            # Fetch the listing details from Reverb API
            return await self.client.get_listing(listing.reverb_listing_id)
        
        except Exception as e:
            logger.error(f"Error getting listing details: {str(e)}")
            if isinstance(e, (ListingNotFoundError, ReverbAPIError)):
                raise
            raise ReverbAPIError(f"Failed to get listing details: {str(e)}")
    
    async def update_inventory(self, reverb_listing_id: int, quantity: int) -> bool:
        """
        Update the inventory quantity of a listing on Reverb
        
        Args:
            reverb_listing_id: Database ID of the ReverbListing
            quantity: New inventory quantity
            
        Returns:
            bool: Success status
            
        Raises:
            ListingNotFoundError: If listing not found
            ReverbAPIError: If the API request fails
        """
        try:
            # Get the ReverbListing record
            listing = await self._get_reverb_listing(reverb_listing_id)
            if not listing or not listing.reverb_listing_id:
                raise ListingNotFoundError(f"ReverbListing {reverb_listing_id} not found or has no Reverb ID")
            
            # Prepare inventory update data
            inventory_data = {
                "inventory": quantity,
                "has_inventory": quantity > 0
            }
            
            # Update the listing on Reverb
            await self.client.update_listing(listing.reverb_listing_id, inventory_data)
            
            # Update local database record
            listing.inventory_quantity = quantity
            listing.has_inventory = quantity > 0
            self.db.add(listing)
            await self.db.flush()
            
            logger.info(f"Updated inventory for listing {listing.reverb_listing_id} to {quantity}")
            return True
            
        except Exception as e:
            logger.error(f"Error updating inventory: {str(e)}")
            if isinstance(e, (ListingNotFoundError, ReverbAPIError)):
                raise
            raise ReverbAPIError(f"Failed to update inventory: {str(e)}")
    
    async def publish_listing(self, reverb_listing_id: int) -> bool:
        """
        Publish a draft listing on Reverb
        
        Args:
            reverb_listing_id: Database ID of the ReverbListing
            
        Returns:
            bool: Success status
            
        Raises:
            ListingNotFoundError: If listing not found
            ReverbAPIError: If the API request fails
        """
        try:
            # Get the ReverbListing and PlatformCommon records
            listing = await self._get_reverb_listing(reverb_listing_id)
            if not listing or not listing.reverb_listing_id:
                raise ListingNotFoundError(f"ReverbListing {reverb_listing_id} not found or has no Reverb ID")
            
            platform_common = await self._get_platform_common(listing.platform_id)
            if not platform_common:
                raise ListingNotFoundError(f"PlatformCommon {listing.platform_id} not found")
            
            # Publish the listing on Reverb
            publish_data = {"publish": True}
            await self.client.update_listing(listing.reverb_listing_id, publish_data)
            
            # Update local database records
            platform_common.status = ListingStatus.ACTIVE.value
            listing.reverb_state = "published"
            
            self.db.add(platform_common)
            self.db.add(listing)
            await self.db.flush()
            
            logger.info(f"Published listing {listing.reverb_listing_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error publishing listing: {str(e)}")
            if isinstance(e, (ListingNotFoundError, ReverbAPIError)):
                raise
            raise ReverbAPIError(f"Failed to publish listing: {str(e)}")
    
    async def end_listing(self, reverb_listing_id: int, reason: str = "not_for_sale") -> bool:
        """
        End a listing on Reverb
        
        Args:
            reverb_listing_id: Database ID of the ReverbListing
            reason: Reason for ending the listing
            
        Returns:
            bool: Success status
            
        Raises:
            ListingNotFoundError: If listing not found
            ReverbAPIError: If the API request fails
        """
        try:
            # Get the ReverbListing and PlatformCommon records
            listing = await self._get_reverb_listing(reverb_listing_id)
            if not listing or not listing.reverb_listing_id:
                raise ListingNotFoundError(f"ReverbListing {reverb_listing_id} not found or has no Reverb ID")
            
            platform_common = await self._get_platform_common(listing.platform_id)
            if not platform_common:
                raise ListingNotFoundError(f"PlatformCommon {listing.platform_id} not found")
            
            # End the listing on Reverb
            end_data = {"state": "ended"}
            await self.client.update_listing(listing.reverb_listing_id, end_data)
            
            # Update local database records
            platform_common.status = ListingStatus.ENDED.value
            listing.reverb_state = "ended"
            
            self.db.add(platform_common)
            self.db.add(listing)
            await self.db.flush()
            
            logger.info(f"Ended listing {listing.reverb_listing_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error ending listing: {str(e)}")
            if isinstance(e, (ListingNotFoundError, ReverbAPIError)):
                raise
            raise ReverbAPIError(f"Failed to end listing: {str(e)}")

    # Private helper methods
    
    async def _get_platform_common(self, platform_id: int) -> Optional[PlatformCommon]:
        """Get platform_common record by ID with associated product"""
        query = select(PlatformCommon).where(PlatformCommon.id == platform_id)
        result = await self.db.execute(query)
        return result.scalars().first()
    
    async def _get_product(self, product_id: int) -> Optional[Product]:
        """Get product record by ID"""
        query = select(Product).where(Product.id == product_id)
        result = await self.db.execute(query)
        return result.scalars().first()
    
    async def _get_reverb_listing(self, listing_id: int) -> Optional[ReverbListing]:
        """Get reverb_listing record by ID"""
        query = select(ReverbListing).where(ReverbListing.id == listing_id)
        result = await self.db.execute(query)
        return result.scalars().first()
    
    # def _prepare_listing_data(self, listing: ReverbListing, product: Product) -> Dict[str, Any]:
    #     """
    #     Prepare listing data for Reverb API
        
    #     This transforms our internal product and listing data into the format
    #     expected by the Reverb API for creating or updating listings.
        
    #     Args:
    #         listing: ReverbListing model
    #         product: Product model
            
    #     Returns:
    #         Dict[str, Any]: Data formatted for Reverb API
    #     """
    #     # Basic listing information
    #     listing_data = {
    #         "title": f"{product.brand} {product.model}",
    #         "description": product.description or f"{product.brand} {product.model}",
    #         "make": product.brand,
    #         "model": product.model,
    #         "price": str(product.base_price),
            
    #         # Use condition name directly instead of UUID
    #         "condition": "excellent"  # Default to excellent condition
    #     }
        
    #     # Map product condition to Reverb condition - using string format instead of UUID
    #     if product.condition:
    #         condition_map = {
    #             "NEW": "brand_new",
    #             "EXCELLENT": "excellent",
    #             "VERYGOOD": "very_good",
    #             "GOOD": "good",
    #             "FAIR": "fair",
    #             "POOR": "poor"
    #         }
    #         if product.condition in condition_map:
    #             listing_data["condition"] = condition_map[product.condition]
        
    #     # Add optional fields if they exist
    #     if product.year:
    #         listing_data["year"] = str(product.year)
        
    #     if product.finish:
    #         listing_data["finish"] = product.finish
        
    #     # Add photos
    #     if product.primary_image:
    #         listing_data["photos"] = [product.primary_image]
        
    #     # Add category if specified
    #     if listing.reverb_category_uuid:
    #         listing_data["categories"] = [
    #             {"uuid": listing.reverb_category_uuid}
    #         ]
            
    #     # Add product type (required for publishing)
    #     listing_data["product_type"] = "electric-guitars"  # Default to electric guitars
            
    #     # Add inventory settings
    #     listing_data["inventory"] = listing.inventory_quantity
    #     listing_data["has_inventory"] = listing.has_inventory
    #     listing_data["offers_enabled"] = listing.offers_enabled
        
    #     # Add shipping details
    #     if listing.shipping_profile_id:
    #         listing_data["shipping_profile_id"] = listing.shipping_profile_id
    #     else:
    #         # Default shipping configuration
    #         # Note: Using the simple format that works with the API
    #         listing_data["shipping"] = {
    #             "local": True,  # Allow local pickup
    #             "us": True,
    #             "us_rate": "25.00"  # Simple US shipping rate
    #         }
        
    #     return listing_data
    

    def _prepare_listing_data(self, listing: ReverbListing, product: Product) -> Dict[str, Any]:
        """
        Prepare listing data for Reverb API
        
        Args:
            listing: ReverbListing record
            product: Associated Product record
            
        Returns:
            Dict: Listing data formatted for Reverb API
        """
        data = {
            "title": product.title or f"{product.brand} {product.model}",
            "description": product.description or "",
            "make": product.brand,
            "model": product.model,
            # Format condition as object with UUID
            "condition": {
                "uuid": self._get_condition_uuid(product.condition)
            },
            # Format price as object with amount and currency
            "price": {
                "amount": str(product.base_price),  # Must be a string
                "currency": "USD" if self.client.use_sandbox else "GBP"  # USD for sandbox, GBP for production
            },
            "shipping": {
                "local": True,
                "us": True,
                "us_rate": "25.00"  # Default shipping rate
            },
            "categories": [
                {"uuid": listing.reverb_category_uuid or "dfd39027-d134-4353-b9e4-57dc6be791b9"}  # Default to Electric Guitars
            ],
            "has_inventory": listing.has_inventory,
            "inventory": listing.inventory_quantity or 1,
            "offers_enabled": listing.offers_enabled
        }
        
        # Add photos if available
        if listing.photos:
            data["photos"] = listing.photos.split(",")
            
        # Add year if available
        if product.year:
            data["year"] = str(product.year)
            
        # Add finish if available
        if product.finish:
            data["finish"] = product.finish
            
        return data

    def _get_condition_uuid(self, condition_name: str) -> str:
        """Map condition name to UUID"""
        condition_map = {
            "Mint": "ec942c5e-fd9d-4a70-af95-ce686ed439e5",
            "Excellent": "df268ad1-c462-4ba6-b6db-e007e23922ea",
            "Very Good": "ae4d9114-1bd7-4ec5-a4ba-6653af5ac84d", 
            "Good": "ddadff2a-188c-42e0-be90-ebed197400a3",
            "Fair": "a2356006-97f9-487c-bd68-6c148a8ffe93",
            "Poor": "41b843b5-af33-4f37-9e9e-eec54aac6ce4",
            "Non Functioning": "196adee9-5415-4b5d-910f-39f2eb72e92f"
        }
        # Default to "Excellent" condition if not found
        return condition_map.get(condition_name, "df268ad1-c462-4ba6-b6db-e007e23922ea")