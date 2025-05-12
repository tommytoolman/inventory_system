# app/services/ebay_service.py

import logging
import asyncio
import json
from typing import Optional, Dict, List, Any, Union, Tuple
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from sqlalchemy import select, update, delete

from app.models.ebay import EbayListing
from app.models.product import Product
from app.models.platform_common import PlatformCommon, ListingStatus, SyncStatus
from app.schemas.platform.ebay import EbayListingCreate
from app.core.config import Settings
from app.core.enums import EbayListingStatus
from app.core.exceptions import EbayAPIError, ListingNotFoundError, DatabaseError
from app.services.ebay.client import EbayClient
from app.services.ebay.trading import EbayTradingLegacyAPI

logger = logging.getLogger(__name__)

class EbayService:
    """
    Service for managing eBay listings and synchronization.
    
    Key responsibilities:
    1. Listing lifecycle management (draft, publish, end)
    2. Inventory management and synchronization
    3. Data synchronization between local DB and eBay platform
    4. Error handling and status tracking
    """
    
    def __init__(self, db: AsyncSession, settings: Settings):
        """Initialize the eBay service with database session and settings"""
        self.db = db
        self.settings = settings
        self._api_key = settings.EBAY_API_KEY
        self._api_secret = settings.EBAY_API_SECRET
        self._sandbox_mode = settings.EBAY_SANDBOX_MODE
        
        # Initialize API clients
        self.client = EbayClient(sandbox=self._sandbox_mode)
        self.trading_api = EbayTradingLegacyAPI(sandbox=self._sandbox_mode)
        
        # Default user expected for verification
        self.expected_user_id = "londonvintagegts"
    
    # -------------------------------------------------------------------------
    # Core Database Access Methods
    # -------------------------------------------------------------------------
    
    async def _get_listing(self, listing_id: int, for_update: bool = False) -> Tuple[EbayListing, PlatformCommon]:
        """
        Get an EbayListing and its associated PlatformCommon
        
        Args:
            listing_id: The ID of the EbayListing
            for_update: Whether to lock the records for update
            
        Returns:
            Tuple of (EbayListing, PlatformCommon)
            
        Raises:
            ListingNotFoundError: If listing not found
        """
        try:
            # Query for the eBay listing
            query = select(EbayListing).where(EbayListing.id == listing_id)
            if for_update:
                query = query.with_for_update()
                
            result = await self.db.execute(query)
            listing = result.scalar_one_or_none()
            
            if not listing:
                raise ListingNotFoundError(f"eBay listing with ID {listing_id} not found")
            
            # Get the associated platform_common record
            platform_query = select(PlatformCommon).where(PlatformCommon.id == listing.platform_id)
            if for_update:
                platform_query = platform_query.with_for_update()
                
            platform_result = await self.db.execute(platform_query)
            platform_common = platform_result.scalar_one_or_none()
            
            if not platform_common:
                raise ListingNotFoundError(f"Platform record not found for eBay listing {listing_id}")
            
            return listing, platform_common
            
        except Exception as e:
            if isinstance(e, ListingNotFoundError):
                raise
            logger.error(f"Database error getting eBay listing {listing_id}: {str(e)}")
            raise DatabaseError(f"Error retrieving listing {listing_id}: {str(e)}")
    
    async def _get_product(self, product_id: int) -> Product:
        """Get product by ID"""
        query = select(Product).where(Product.id == product_id)
        result = await self.db.execute(query)
        product = result.scalar_one_or_none()
        
        if not product:
            raise ListingNotFoundError(f"Product with ID {product_id} not found")
        
        return product
    
    async def _update_sync_status(
        self, 
        platform_common: PlatformCommon, 
        status: SyncStatus,
        message: Optional[str] = None,
        commit: bool = True
    ) -> None:
        """Update sync status of a platform_common record"""
        platform_common.sync_status = status.value
        platform_common.sync_message = message
        platform_common.updated_at = datetime.now(timezone.utc)
        
        if commit:
            await self.db.commit()
    
    async def _update_listing_status(
        self, 
        platform_common: PlatformCommon, 
        status: ListingStatus,
        commit: bool = True
    ) -> None:
        """Update listing status of a platform_common record"""
        platform_common.status = status.value
        platform_common.updated_at = datetime.now(timezone.utc)
        
        if commit:
            await self.db.commit()
    
    # -------------------------------------------------------------------------
    # Listing Management Methods
    # -------------------------------------------------------------------------
    
    async def create_draft_listing(self, listing_id: int, listing_data: Dict[str, Any]) -> EbayListing:
        """
        Create a draft listing on eBay
        
        Args:
            listing_id: ID of the existing EbayListing record
            listing_data: Dictionary with listing details (category, condition, format, etc)
            
        Returns:
            Updated EbayListing with eBay item ID
            
        Raises:
            ListingNotFoundError: If listing not found
            EbayAPIError: If API request fails
        """
        listing = None
        platform_common = None
        
        try:
            # Get the listing and lock for update
            listing, platform_common = await self._get_listing(listing_id, for_update=True)
            
            # Get associated product
            product = await self._get_product(platform_common.product_id)
            
            # Prepare inventory item data
            availability = {
                "shipToLocationAvailability": {
                    "quantity": listing.quantity or 1
                }
            }
            
            product_data = {
                "title": product.title,
                "description": product.description,
                "aspects": listing_data.get("item_specifics", {}),
                "brand": product.brand,
                "mpn": product.model
            }
            
            condition = listing_data.get("condition_id", "3000")  # Default to Used
            
            inventory_item = {
                "availability": availability,
                "condition": condition,
                "product": product_data
            }
            
            # Create inventory item on eBay
            sku = f"{product.sku}-{listing.id}"
            await self._update_sync_status(platform_common, SyncStatus.IN_PROGRESS, message="Creating inventory item")
            
            inventory_result = await self.client.create_or_replace_inventory_item(sku, inventory_item)
            
            # Create offer
            offer_data = {
                "sku": sku,
                "marketplaceId": "EBAY_GB",
                "format": listing_data.get("format", "FIXED_PRICE"),
                "categoryId": listing_data.get("category_id"),
                "availableQuantity": listing.quantity or 1,
                "pricingSummary": {
                    "price": {
                        "currency": "GBP",
                        "value": str(listing.price)
                    }
                },
                "listingPolicies": {
                    "fulfillmentPolicyId": self.settings.EBAY_FULFILLMENT_POLICY_ID,
                    "paymentPolicyId": self.settings.EBAY_PAYMENT_POLICY_ID,
                    "returnPolicyId": self.settings.EBAY_RETURN_POLICY_ID
                },
                "listingDescription": product.description
            }
            
            await self._update_sync_status(platform_common, SyncStatus.IN_PROGRESS, message="Creating offer")
            offer_result = await self.client.create_offer(offer_data)
            
            # Update listing with eBay data
            listing.ebay_sku = sku
            listing.ebay_offer_id = offer_result.get("offerId")
            listing.ebay_item_id = sku  # Temporary - will be updated when published
            listing.ebay_category_id = listing_data.get("category_id")
            listing.ebay_condition_id = condition
            listing.listing_status = EbayListingStatus.DRAFT
            listing.format = listing_data.get("format", "FIXED_PRICE")
            listing.updated_at = datetime.now(timezone.utc)
            
            # Update platform_common status
            platform_common.external_id = sku
            platform_common.status = ListingStatus.DRAFT.value
            await self._update_sync_status(platform_common, SyncStatus.SYNCED, commit=False)
            
            # Commit all changes
            await self.db.commit()
            
            return listing
            
        except Exception as e:
            # Roll back changes
            await self.db.rollback()
            
            # Update sync status to error
            if platform_common:
                await self._update_sync_status(
                    platform_common, 
                    SyncStatus.ERROR, 
                    message=str(e)
                )
            
            if isinstance(e, (ListingNotFoundError, EbayAPIError)):
                raise
                
            logger.error(f"Error creating draft listing: {str(e)}")
            raise EbayAPIError(f"Failed to create draft listing: {str(e)}")
    
    async def publish_listing(self, listing_id: int) -> bool:
        """
        Publish a draft listing to make it active on eBay
        
        Args:
            listing_id: ID of the EbayListing record
            
        Returns:
            bool: Success status
            
        Raises:
            ListingNotFoundError: If listing not found
            EbayAPIError: If API request fails
        """
        listing = None
        platform_common = None
        
        try:
            # Get the listing and lock for update
            listing, platform_common = await self._get_listing(listing_id, for_update=True)
            
            # Ensure listing is in draft status
            if listing.listing_status != EbayListingStatus.DRAFT:
                raise EbayAPIError(f"Cannot publish listing that is not in DRAFT status (current: {listing.listing_status})")
            
            # Update sync status to indicate work in progress
            await self._update_sync_status(
                platform_common, 
                SyncStatus.IN_PROGRESS, 
                message="Publishing listing to eBay"
            )
            
            # Call eBay API to publish the offer
            offer_id = listing.ebay_offer_id
            if not offer_id:
                raise EbayAPIError("Cannot publish listing: missing offer ID")
            
            publish_result = await self.client.publish_offer(offer_id)
            
            # Update listing details
            listing.listing_status = EbayListingStatus.ACTIVE
            listing.ebay_listing_id = publish_result.get("listingId")
            listing.published_at = datetime.now(timezone.utc)
            listing.updated_at = datetime.now(timezone.utc)
            
            # Update platform_common status
            platform_common.status = ListingStatus.ACTIVE.value
            await self._update_sync_status(
                platform_common, 
                SyncStatus.SYNCED, 
                message="Successfully published to eBay",
                commit=False
            )
            
            # Commit all changes
            await self.db.commit()
            
            return True
            
        except Exception as e:
            # Roll back changes
            await self.db.rollback()
            
            # Update sync status to error
            if platform_common:
                await self._update_sync_status(
                    platform_common, 
                    SyncStatus.ERROR, 
                    message=f"Failed to publish: {str(e)}"
                )
            
            if isinstance(e, (ListingNotFoundError, EbayAPIError)):
                raise
                
            logger.error(f"Error publishing listing: {str(e)}")
            raise EbayAPIError(f"Failed to publish listing: {str(e)}")
    
    async def end_listing(self, listing_id: int, reason: str = "NotAvailable") -> bool:
        """
        End an active eBay listing
        
        Args:
            listing_id: ID of the EbayListing record
            reason: Reason code for ending the listing
            
        Returns:
            bool: Success status
            
        Raises:
            ListingNotFoundError: If listing not found
            EbayAPIError: If API request fails
        """
        listing = None
        platform_common = None
        
        try:
            # Get the listing and lock for update
            listing, platform_common = await self._get_listing(listing_id, for_update=True)
            
            # Ensure listing is in active status
            if listing.listing_status != EbayListingStatus.ACTIVE:
                raise EbayAPIError(f"Cannot end listing that is not ACTIVE (current: {listing.listing_status})")
            
            # Update sync status
            await self._update_sync_status(
                platform_common, 
                SyncStatus.IN_PROGRESS, 
                message="Ending listing on eBay"
            )
            
            # Call eBay API to end the listing
            item_id = listing.ebay_listing_id or listing.ebay_item_id
            if not item_id:
                raise EbayAPIError("Cannot end listing: missing item/listing ID")
            
            # Use Trading API for ending listings
            result = await self.trading_api.end_listing(item_id, reason_code=reason)
            
            # Update listing status
            listing.listing_status = EbayListingStatus.ENDED
            listing.ended_at = datetime.now(timezone.utc)
            listing.updated_at = datetime.now(timezone.utc)
            
            # Update platform_common status
            platform_common.status = ListingStatus.ENDED.value
            await self._update_sync_status(
                platform_common, 
                SyncStatus.SYNCED, 
                message="Successfully ended listing on eBay",
                commit=False
            )
            
            # Commit all changes
            await self.db.commit()
            
            return True
            
        except Exception as e:
            # Roll back changes
            await self.db.rollback()
            
            # Update sync status to error
            if platform_common:
                await self._update_sync_status(
                    platform_common, 
                    SyncStatus.ERROR, 
                    message=f"Failed to end listing: {str(e)}"
                )
            
            if isinstance(e, (ListingNotFoundError, EbayAPIError)):
                raise
                
            logger.error(f"Error ending listing: {str(e)}")
            raise EbayAPIError(f"Failed to end listing: {str(e)}")
    
    async def update_inventory(self, listing_id: int, quantity: int) -> bool:
        """
        Update the quantity of an eBay listing
        
        Args:
            listing_id: ID of the EbayListing record
            quantity: New quantity value
            
        Returns:
            bool: Success status
            
        Raises:
            ListingNotFoundError: If listing not found
            EbayAPIError: If API request fails
        """
        listing = None
        platform_common = None
        
        try:
            # Get the listing and lock for update
            listing, platform_common = await self._get_listing(listing_id, for_update=True)
            
            # Update sync status
            await self._update_sync_status(
                platform_common, 
                SyncStatus.IN_PROGRESS, 
                message=f"Updating inventory quantity to {quantity}"
            )
            
            # Call eBay API to update inventory
            sku = listing.ebay_sku
            if not sku:
                raise EbayAPIError("Cannot update inventory: missing SKU")
            
            await self.client.update_inventory_item_quantity(sku, quantity)
            
            # Update listing quantity
            listing.quantity = quantity
            listing.updated_at = datetime.now(timezone.utc)
            
            await self._update_sync_status(
                platform_common, 
                SyncStatus.SYNCED, 
                message="Successfully updated inventory",
                commit=False
            )
            
            # Commit all changes
            await self.db.commit()
            
            return True
            
        except Exception as e:
            # Roll back changes
            await self.db.rollback()
            
            # Update sync status to error
            if platform_common:
                await self._update_sync_status(
                    platform_common, 
                    SyncStatus.ERROR, 
                    message=f"Failed to update inventory: {str(e)}"
                )
            
            if isinstance(e, (ListingNotFoundError, EbayAPIError)):
                raise
                
            logger.error(f"Error updating inventory: {str(e)}")
            raise EbayAPIError(f"Failed to update inventory: {str(e)}")
    
    async def get_listing_details(self, listing_id: int) -> Dict[str, Any]:
        """
        Get detailed information about an eBay listing
        
        Args:
            listing_id: ID of the EbayListing record
            
        Returns:
            Dict with listing details from eBay
            
        Raises:
            ListingNotFoundError: If listing not found
            EbayAPIError: If API request fails
        """
        try:
            # Get the listing
            listing, platform_common = await self._get_listing(listing_id)
            
            # Use appropriate identifier to get details
            if listing.ebay_sku:
                # Use Inventory API for listings with SKU
                details = await self.client.get_inventory_item(listing.ebay_sku)
                
                # Add offer information if available
                if listing.ebay_offer_id:
                    try:
                        offer_details = await self.client.get_offer(listing.ebay_offer_id)
                        details["offer"] = offer_details
                    except Exception as e:
                        logger.warning(f"Could not get offer details: {str(e)}")
                
                return details
                
            elif listing.ebay_listing_id or listing.ebay_item_id:
                # Use Trading API for listings with item ID
                item_id = listing.ebay_listing_id or listing.ebay_item_id
                details = await self.trading_api.get_item_details(item_id)
                return details
            else:
                raise EbayAPIError("Cannot get details: listing has no identifiers")
                
        except Exception as e:
            if isinstance(e, (ListingNotFoundError, EbayAPIError)):
                raise
                
            logger.error(f"Error getting listing details: {str(e)}")
            raise EbayAPIError(f"Failed to get listing details: {str(e)}")
    
    # -------------------------------------------------------------------------
    # API Wrapper Methods (from EbayInventoryService)
    # -------------------------------------------------------------------------
    
    async def verify_credentials(self) -> bool:
        """
        Verify eBay credentials and check user ID
        
        Returns:
            bool: True if credentials are valid and user ID matches expected
        """
        try:
            user_info = await self.trading_api.get_user_info()
            
            if not user_info.get('success'):
                logger.error(f"Failed to get eBay user info: {user_info.get('message')}")
                return False
            
            user_id = user_info.get('user_data', {}).get('UserID')
            if user_id != self.expected_user_id:
                logger.error(f"Unexpected eBay user: {user_id}")
                return False
            
            logger.info(f"Successfully authenticated as eBay user: {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error verifying eBay credentials: {str(e)}")
            return False
    
    async def get_all_active_listings(self, include_details: bool = False) -> List[Dict[str, Any]]:
        """
        Get all active eBay listings
        
        Args:
            include_details: Whether to include full item details
            
        Returns:
            List of active listings data
        """
        return await self.trading_api.get_all_active_listings(include_details=include_details)
    
    async def get_active_listing_count(self) -> int:
        """
        Get count of active eBay listings
        
        Returns:
            int: Count of active listings
        """
        return await self.trading_api.get_total_active_listings_count()
    
    # -------------------------------------------------------------------------
    # Synchronization Methods (from EbayInventorySync)
    # -------------------------------------------------------------------------
    
    async def sync_inventory_from_ebay(self) -> Dict[str, int]:
        """
        Synchronize all eBay inventory to database
        
        Returns:
            Dict with statistics about the sync operation
        """
        # Initialize result stats
        results = {
            "total": 0,
            "created": 0,
            "updated": 0,
            "errors": 0
        }
        
        try:
            # Verify eBay user
            if not await self.verify_credentials():
                logger.error("Failed to verify eBay user, canceling sync")
                return results
            
            # Get all active listings from eBay
            logger.info("Fetching all active eBay listings")
            listings = await self.get_all_active_listings(include_details=True)
            results["total"] = len(listings)
            
            logger.info(f"Processing {len(listings)} eBay listings")
            
            # Process each listing
            created_count = 0
            updated_count = 0
            error_count = 0
            
            for listing in listings:
                try:
                    item_id = listing.get('ItemID')
                    if not item_id:
                        logger.warning("Skipping listing with no ItemID")
                        continue
                    
                    # Check if listing exists in database
                    query = select(EbayListing).where(EbayListing.ebay_item_id == item_id)
                    result = await self.db.execute(query)
                    existing_listing = result.scalar_one_or_none()
                    
                    if existing_listing:
                        # Update existing listing
                        await self._update_listing_from_api_data(existing_listing, listing)
                        updated_count += 1
                    else:
                        # Create new listing
                        await self._create_listing_from_api_data(listing)
                        created_count += 1
                        
                except Exception as e:
                    logger.exception(f"Error processing listing {listing.get('ItemID')}: {str(e)}")
                    error_count += 1
            
            # Update result counts
            results["created"] = created_count
            results["updated"] = updated_count
            results["errors"] = error_count
            
            return results
            
        except Exception as e:
            logger.error(f"Error in eBay inventory sync: {str(e)}")
            raise
    
    async def _create_listing_from_api_data(self, listing: Dict[str, Any]) -> EbayListing:
        """
        Create a new EbayListing from API data
        
        Args:
            listing: Listing data from eBay API
            
        Returns:
            Newly created EbayListing
        """
        now = datetime.now(timezone.utc)
        item_id = listing.get('ItemID')
        
        try:
            # Extract basic listing data
            title = listing.get('Title', '')
            price = float(listing.get('SellingStatus', {}).get('CurrentPrice', {}).get('#text', '0'))
            quantity = int(listing.get('Quantity', '1'))
            quantity_sold = int(listing.get('SellingStatus', {}).get('QuantitySold', '0'))
            
            # Get or create product
            sku = listing.get('SKU') or f"EB-{item_id}"
            
            query = select(Product).where(Product.sku == sku)
            result = await self.db.execute(query)
            product = result.scalar_one_or_none()
            
            if not product:
                # Create new product
                product = Product(
                    sku=sku,
                    title=title,
                    description=listing.get('Description', ''),
                    condition='USED',  # Default
                    status='ACTIVE',
                    created_at=now,
                    updated_at=now
                )
                self.db.add(product)
                await self.db.flush()  # Get product ID without committing
            
            # Create platform_common record
            platform_common = PlatformCommon(
                product_id=product.id,
                platform_name='ebay',
                external_id=item_id,
                status='ACTIVE',
                sync_status='SYNCED',
                created_at=now,
                updated_at=now
            )
            self.db.add(platform_common)
            await self.db.flush()  # Get platform_common ID
            
            # Extract category data
            primary_category = listing.get('PrimaryCategory', {})
            ebay_category_id = primary_category.get('CategoryID')
            ebay_category_name = primary_category.get('CategoryName')
            
            secondary_category = listing.get('SecondaryCategory', {})
            ebay_second_category_id = secondary_category.get('CategoryID')
            
            # Extract condition
            condition_id = listing.get('ConditionID')
            condition_display_name = listing.get('ConditionDisplayName')
            
            # Extract listing details
            listing_details = listing.get('ListingDetails', {})
            start_time_str = listing_details.get('StartTime')
            end_time_str = listing_details.get('EndTime')
            
            start_time = datetime.fromisoformat(start_time_str.replace('Z', '+00:00')) if start_time_str else now
            end_time = datetime.fromisoformat(end_time_str.replace('Z', '+00:00')) if end_time_str else None
            
            listing_duration = listing.get('ListingDuration')
            
            # Create eBay listing
            ebay_listing = EbayListing(
                platform_id=platform_common.id,
                ebay_item_id=item_id,
                ebay_sku=sku,
                title=title,
                price=price,
                quantity=quantity,
                quantity_sold=quantity_sold,
                format=listing.get('ListingType', 'UNKNOWN').upper(),
                ebay_category_id=ebay_category_id,
                ebay_category_name=ebay_category_name,
                ebay_second_category_id=ebay_second_category_id,
                ebay_condition_id=condition_id,
                condition_display_name=condition_display_name,
                listing_duration=listing_duration,
                listing_status='ACTIVE',
                start_time=start_time,
                end_time=end_time,
                item_specifics=listing.get('ItemSpecifics', {}),
                created_at=now,
                updated_at=now,
                last_synced_at=now
            )
            self.db.add(ebay_listing)
            
            # Commit all changes
            await self.db.commit()
            
            return ebay_listing
            
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error creating listing from API data: {str(e)}")
            raise
    
    async def _update_listing_from_api_data(self, existing_listing: EbayListing, listing: Dict[str, Any]) -> EbayListing:
        """
        Update an existing EbayListing from API data
        
        Args:
            existing_listing: Existing EbayListing record
            listing: Updated listing data from eBay API
            
        Returns:
            Updated EbayListing
        """
        now = datetime.now(timezone.utc)
        
        try:
            # Extract basic listing data
            price = float(listing.get('SellingStatus', {}).get('CurrentPrice', {}).get('#text', '0'))
            quantity = int(listing.get('Quantity', '1'))
            quantity_sold = int(listing.get('SellingStatus', {}).get('QuantitySold', '0'))
            
            # Extract category data
            primary_category = listing.get('PrimaryCategory', {})
            ebay_category_id = primary_category.get('CategoryID')
            ebay_category_name = primary_category.get('CategoryName')
            
            secondary_category = listing.get('SecondaryCategory', {})
            ebay_second_category_id = secondary_category.get('CategoryID')
            
            # Extract condition
            condition_id = listing.get('ConditionID')
            condition_display_name = listing.get('ConditionDisplayName')
            
            # Extract listing details
            listing_details = listing.get('ListingDetails', {})
            listing_duration = listing.get('ListingDuration')
            
            # Update existing listing
            existing_listing.title = listing.get('Title', existing_listing.title)
            existing_listing.price = price
            existing_listing.quantity = quantity
            existing_listing.quantity_sold = quantity_sold
            existing_listing.ebay_category_name = ebay_category_name
            existing_listing.ebay_category_id = ebay_category_id
            existing_listing.ebay_second_category_id = ebay_second_category_id
            existing_listing.listing_duration = listing_duration
            existing_listing.updated_at = now
            existing_listing.last_synced_at = now
            existing_listing.ebay_condition_id = condition_id
            existing_listing.condition_display_name = condition_display_name
            existing_listing.item_specifics = listing.get('ItemSpecifics', existing_listing.item_specifics or {})
            existing_listing.listing_status = 'ACTIVE'
            
            # Commit changes
            await self.db.commit()
            
            return existing_listing
            
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error updating listing from API data: {str(e)}")
            raise
    
    async def sync_inventory_to_ebay(self) -> Dict[str, int]:
        """
        Synchronize inventory quantities from database to eBay
        
        Returns:
            Dict with statistics about the sync operation
        """
        results = {
            "total": 0,
            "updated": 0,
            "errors": 0
        }
        
        try:
            # Get active listings with inventory changes needed
            query = select(EbayListing).join(
                PlatformCommon, EbayListing.platform_id == PlatformCommon.id
            ).join(
                Product, PlatformCommon.product_id == Product.id
            ).where(
                (PlatformCommon.status == ListingStatus.ACTIVE.value) &
                (EbayListing.listing_status == 'ACTIVE') &
                (EbayListing.quantity != Product.quantity)
            )
            
            result = await self.db.execute(query)
            listings = result.scalars().all()
            
            results["total"] = len(listings)
            logger.info(f"Found {len(listings)} listings needing inventory update")
            
            # Process each listing
            for listing in listings:
                try:
                    # Get current product quantity
                    product_query = select(Product.quantity).where(
                        Product.id == select(PlatformCommon.product_id).where(
                            PlatformCommon.id == listing.platform_id
                        ).scalar_subquery()
                    )
                    product_result = await self.db.execute(product_query)
                    product_quantity = product_result.scalar_one_or_none()
                    
                    if product_quantity is None:
                        logger.warning(f"Could not find product quantity for listing {listing.id}")
                        continue
                    
                    # Update on eBay
                    sku = listing.ebay_sku
                    await self.client.update_inventory_item_quantity(sku, product_quantity)
                    
                    # Update local record
                    listing.quantity = product_quantity
                    listing.updated_at = datetime.now(timezone.utc)
                    listing.last_synced_at = datetime.now(timezone.utc)
                    await self.db.commit()
                    
                    results["updated"] += 1
                    
                except Exception as e:
                    results["errors"] += 1
                    logger.error(f"Error updating inventory for listing {listing.id}: {str(e)}")
            
            return results
            
        except Exception as e:
            logger.error(f"Error in eBay inventory sync to eBay: {str(e)}")
            raise
        
        
# Notes on updated code
"""
Key Improvements in the Refactored Code:

1. Consistent Error Handling: Every method follows the same pattern of try/except with status updates and proper rollbacks

2. Helper Methods: Added common helpers like _get_listing() to reduce code duplication

3. Integrated Functionality: Combined the key features from EbayInventoryService and EbayInventorySync:
    - verify_credentials(), get_all_active_listings(), etc.
    - sync_inventory_from_ebay(), _create_listing_from_api_data(), etc.

4. Fixed Import: Added the missing Session import

5. Improved Method Organization:
- Grouped related methods together
- Added clear section comments
- Consistent documentation

6. Transaction Management: Proper handling of transactions with commit/rollback

Unit Testing Recommendations

With this refactored service, your unit tests should focus on:

1. Core Database Access Methods:
    - Test _get_listing() with both found and not found scenarios
    - Test status update methods

2. Listing Management Methods:
    - Test the full lifecycle (create_draft → publish → update_inventory → end_listing)
    - Test error handling in each stage

3. API Wrapper Methods:
    - Test credential verification
    - Test listing retrieval

4. Synchronization Methods:
    - Test sync from eBay to database
    - Test sync from database to eBay
"""