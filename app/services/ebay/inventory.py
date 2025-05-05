# app/services/ebay/inventory.py
import logging
import asyncio
from datetime import datetime, timezone
from sqlalchemy import select, update
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session

from app.core.exceptions import EbayAPIError
from app.models.platform_common import PlatformCommon
from app.models.ebay import EbayListing
from app.schemas.platform.ebay import EbayListingStatusInfo  # Adjust imports based on your schemas
from app.services.ebay.client import EbayClient
from app.services.ebay.trading import EbayTradingAPI


logger = logging.getLogger(__name__)

class EbayInventoryService:
    """
    Service for fetching and managing eBay inventory
    Provides a unified interface that might use either the REST API
    or the older Trading API under the hood as needed
    """
    
    def __init__(self, sandbox: bool = False):
        """
        Initialize eBay inventory service
        
        Args:
            sandbox: Whether to use sandbox environment
        """
        self.sandbox = sandbox
        self.rest_client = EbayClient()  # REST API client
        self.trading_api = EbayTradingAPI(sandbox=sandbox)  # Trading API client
        self.expected_user_id = "londonvintagegts"  # Your expected eBay user ID
    
    async def verify_credentials(self) -> bool:
        """
        Verify eBay credentials and check user ID
        
        Returns:
            bool: True if credentials are valid and user ID matches
        """
        user_info = await self.trading_api.get_user_info()
        
        if not user_info.get('success'):
            logger.error(f"Failed to get eBay user info: {user_info.get('message')}")
            return False
        
        user_id = user_info.get('user_data', {}).get('UserID')
        if user_id != self.expected_user_id:
            logger.error(f"Unexpected eBay user: {user_id}, expected: {self.expected_user_id}")
            return False
        
        logger.info(f"Successfully authenticated as eBay user: {user_id}")
        return True
    
    async def get_all_active_listings(self) -> List[Dict[str, Any]]:
        """
        Get all active eBay listings with pagination
        Uses Trading API for better listing information
        
        Returns:
            List of all active listings
        """
        # First get the first page to determine total pages
        first_page = await self.trading_api.get_active_listings(page_num=1)
        
        # Extract pagination info
        pagination_result = first_page.get('PaginationResult', {})
        total_pages = int(pagination_result.get('TotalNumberOfPages', '1'))
        total_entries = int(pagination_result.get('TotalNumberOfEntries', '0'))
        
        logger.info(f"Found {total_entries} eBay listings across {total_pages} pages")
        
        # Get all items from the first page
        all_items = []
        items = first_page.get('ItemArray', {}).get('Item', [])
        if items and not isinstance(items, list):
            items = [items]
        
        if items:
            all_items.extend(items)
        
        # Get remaining pages in parallel
        if total_pages > 1:
            tasks = [self.trading_api.get_active_listings(page_num=page) for page in range(2, total_pages + 1)]
            results = await asyncio.gather(*tasks)
            
            for result in results:
                items = result.get('ItemArray', {}).get('Item', [])
                if items:
                    if not isinstance(items, list):
                        items = [items]
                    all_items.extend(items)
        
        return all_items
    
    async def get_active_listing_count(self) -> int:
        """
        Get count of active eBay listings
        
        Returns:
            int: Number of active listings
        """
        first_page = await self.trading_api.get_active_listings(page_num=1, items_per_page=1)
        
        # Extract pagination info
        pagination_result = first_page.get('PaginationResult', {})
        total_entries = int(pagination_result.get('TotalNumberOfEntries', '0'))
        
        return total_entries
    
    async def get_listing_details(self, item_id: str) -> Dict[str, Any]:
        """
        Get detailed information for a specific listing
        
        Args:
            item_id: The eBay item ID
            
        Returns:
            Dict: Detailed listing information
        """
        # Implement item details retrieval
        # This could be implemented using Trading API GetItem call
        pass
    
class EbayInventorySync:
    """Service for syncing eBay inventory with the database"""
    
    def __init__(self, db: Session, sandbox: bool = False):
        """
        Initialize the inventory sync service
        
        Args:
            db: Database session
            sandbox: Whether to use eBay sandbox
        """
        self.db = db
        self.inventory_service = EbayInventoryService(sandbox=sandbox)
        self.expected_user_id = "londonvintagegts"  # Your eBay seller ID
    
    async def sync_inventory(self) -> Dict[str, int]:
        """
        Sync all eBay inventory to database
        
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
        
        # Verify eBay user
        if not await self.inventory_service.verify_credentials():
            logger.error("Failed to verify eBay user, canceling sync")
            return results
        
        # Get all active listings from eBay
        logger.info("Fetching all active eBay listings")
        listings = await self.inventory_service.get_all_active_listings()
        results["total"] = len(listings)
        
        logger.info(f"Processing {len(listings)} eBay listings")
        
        # Process each listing
        for listing in listings:
            try:
                # Check if listing exists and process it accordingly
                await self._process_listing(listing)
                
                # Update stats based on operation result
                if listing.get("_operation_result") == "created":
                    results["created"] += 1
                elif listing.get("_operation_result") == "updated":
                    results["updated"] += 1
                
            except Exception as e:
                logger.exception(f"Error processing listing {listing.get('ItemID')}: {str(e)}")
                results["errors"] += 1
        
        # Commit changes
        self.db.commit()
        
        return results
    
    async def _process_listing(self, listing: Dict[str, Any]) -> None:
        """
        Process an individual eBay listing
        
        Args:
            listing: eBay listing data
        """
        item_id = listing.get('ItemID')
        
        # Check if this listing already exists
        stmt = select(EbayListing).where(EbayListing.ebay_item_id == item_id)
        result = self.db.execute(stmt)
        existing_listing = result.scalars().first()
        
        if existing_listing:
            # Update existing listing
            await self._update_listing(existing_listing, listing)
            listing["_operation_result"] = "updated"
        else:
            # Create new listing
            await self._create_listing(listing)
            listing["_operation_result"] = "created"
    
    async def _create_listing(self, listing: Dict[str, Any]) -> None:
        """
        Create a new eBay listing in the database
        
        Args:
            listing: eBay listing data
        """
        # Extract necessary data from the listing
        item_id = listing.get('ItemID')
        
        # Extract price
        selling_status = listing.get('SellingStatus', {})
        price_data = selling_status.get('CurrentPrice', {})
        price = float(price_data.get('#text', '0.0'))
        
        # Extract quantity
        quantity = int(listing.get('QuantityAvailable', '1'))
        
        # Extract listing format
        listing_type = listing.get('ListingType', '')
        format_mapping = {
            'Chinese': 'AUCTION',
            'FixedPriceItem': 'BUY_IT_NOW'
        }
        format_value = format_mapping.get(listing_type, 'BUY_IT_NOW')
        
        # Extract policy IDs from SellerProfiles if available
        seller_profiles = listing.get('SellerProfiles', {})
        payment_policy_id = None
        return_policy_id = None
        shipping_policy_id = None
        
        if seller_profiles:
            payment_profile = seller_profiles.get('SellerPaymentProfile', {})
            return_profile = seller_profiles.get('SellerReturnProfile', {})
            shipping_profile = seller_profiles.get('SellerShippingProfile', {})
            
            payment_policy_id = payment_profile.get('PaymentProfileID') if payment_profile else None
            return_policy_id = return_profile.get('ReturnProfileID') if return_profile else None
            shipping_policy_id = shipping_profile.get('ShippingProfileID') if shipping_profile else None
        
        # Extract category information
        primary_category = listing.get('PrimaryCategory', {})
        secondary_category = listing.get('SecondaryCategory', {})
        ebay_category_id = primary_category.get('CategoryID') if primary_category else None
        ebay_second_category_id = secondary_category.get('CategoryID') if secondary_category else None
        
        # Extract listing duration
        listing_duration = listing.get('ListingDuration', '')
        
        # Extract condition ID if available
        condition_id = listing.get('ConditionID')
        
        # Create new ebay_listing record
        now = datetime.now(timezone.utc)()
        new_listing = EbayListing(
            # We're not setting platform_id here - that would be set when
            # integrating with your platform_common table
            ebay_item_id=item_id,
            ebay_category_id=ebay_category_id,
            ebay_second_category_id=ebay_second_category_id,
            format=format_value,
            price=price,
            quantity=quantity,
            payment_policy_id=payment_policy_id,
            return_policy_id=return_policy_id,
            shipping_policy_id=shipping_policy_id,
            item_specifics=listing.get('ItemSpecifics', {}),
            listing_duration=listing_duration,
            listing_status='ACTIVE',
            created_at=now,
            updated_at=now,
            last_synced_at=now,
            ebay_condition_id=condition_id
            # package_weight and package_dimensions would need additional work
            # to extract from the listing
        )
        
        self.db.add(new_listing)
    
    async def _update_listing(self, existing_listing: EbayListing, listing: Dict[str, Any]) -> None:
        """
        Update an existing eBay listing in the database
        
        Args:
            existing_listing: Existing EbayListing object
            listing: Updated eBay listing data
        """
        # Extract necessary data from the listing
        selling_status = listing.get('SellingStatus', {})
        price_data = selling_status.get('CurrentPrice', {})
        price = float(price_data.get('#text', '0.0'))
        
        # Extract quantity
        quantity = int(listing.get('QuantityAvailable', '1'))
        
        # Extract listing format
        listing_type = listing.get('ListingType', '')
        format_mapping = {
            'Chinese': 'AUCTION',
            'FixedPriceItem': 'BUY_IT_NOW'
        }
        format_value = format_mapping.get(listing_type, existing_listing.format or 'BUY_IT_NOW')
        
        # Extract policy IDs from SellerProfiles if available
        seller_profiles = listing.get('SellerProfiles', {})
        payment_policy_id = existing_listing.payment_policy_id
        return_policy_id = existing_listing.return_policy_id
        shipping_policy_id = existing_listing.shipping_policy_id
        
        if seller_profiles:
            payment_profile = seller_profiles.get('SellerPaymentProfile', {})
            return_profile = seller_profiles.get('SellerReturnProfile', {})
            shipping_profile = seller_profiles.get('SellerShippingProfile', {})
            
            if payment_profile and 'PaymentProfileID' in payment_profile:
                payment_policy_id = payment_profile.get('PaymentProfileID')
            if return_profile and 'ReturnProfileID' in return_profile:
                return_policy_id = return_profile.get('ReturnProfileID')
            if shipping_profile and 'ShippingProfileID' in shipping_profile:
                shipping_policy_id = shipping_profile.get('ShippingProfileID')
        
        # Extract category information
        primary_category = listing.get('PrimaryCategory', {})
        secondary_category = listing.get('SecondaryCategory', {})
        ebay_category_id = primary_category.get('CategoryID') if primary_category else existing_listing.ebay_category_id
        ebay_second_category_id = secondary_category.get('CategoryID') if secondary_category else existing_listing.ebay_second_category_id
        
        # Extract listing duration
        listing_duration = listing.get('ListingDuration', existing_listing.listing_duration)
        
        # Extract condition ID if available
        condition_id = listing.get('ConditionID', existing_listing.ebay_condition_id)
        
        # Update the existing listing
        now = datetime.now(timezone.utc)()
        existing_listing.price = price
        existing_listing.quantity = quantity
        existing_listing.format = format_value
        existing_listing.payment_policy_id = payment_policy_id
        existing_listing.return_policy_id = return_policy_id
        existing_listing.shipping_policy_id = shipping_policy_id
        existing_listing.ebay_category_id = ebay_category_id
        existing_listing.ebay_second_category_id = ebay_second_category_id
        existing_listing.listing_duration = listing_duration
        existing_listing.updated_at = now
        existing_listing.last_synced_at = now
        existing_listing.ebay_condition_id = condition_id
        existing_listing.item_specifics = listing.get('ItemSpecifics', existing_listing.item_specifics or {})
        existing_listing.listing_status = 'ACTIVE'
        