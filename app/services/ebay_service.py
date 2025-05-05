"""
Key features of the EbayService:

Purpose: Manages the lifecycle and high-level operations for eBay listings within your application.

Role: Acts as the primary service layer for eBay-specific business logic, bridging your local database state with the eBay platform state via its client.

Functionality:

1. Draft Creation:
    - Creates local database records
    - Prepares data for eBay API
    - Creates draft on eBay but doesn't publish

2. Publishing:
    - Handles transition from draft to active
    - Updates sync status
    - Manages platform_common status

3. Status Management:
    - Syncs status with eBay
    - Updates local records
    - Handles errors and rollbacks


Error Handling:
- Proper exception handling
- Transaction management
- Status tracking

It interacts with local models (EbayListing, PlatformCommon, Product) and orchestrates calls to an EbayClient (presumably defined elsewhere, 
likely app/services/ebay/client.py) to interact with the actual eBay API. It handles preparing data in the format eBay expects.

"""

# app/services/ebay_service.py - Updated

from typing import Optional, Dict, List, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timezone

from app.models.ebay import EbayListing
from app.models.platform_common import PlatformCommon, ListingStatus, SyncStatus
from app.schemas.platform.ebay import EbayListingCreate
from app.core.config import Settings
from app.core.enums import EbayListingStatus
from app.core.exceptions import EbayAPIError, ListingNotFoundError
from app.services.ebay.client import EbayClient

class EbayService:
    def __init__(self, db: AsyncSession, settings: Settings):
        self.db = db
        self.settings = settings
        self._api_key = settings.EBAY_API_KEY
        self._api_secret = settings.EBAY_API_SECRET
        self._sandbox_mode = settings.EBAY_SANDBOX_MODE
        self.client = EbayClient()  # Use our new client

    async def create_draft_listing(
        self,
        platform_id: int,
        listing_data: Dict[str, Any]
    ) -> EbayListing:
        """
        Creates a draft listing on eBay.
        Does not publish - just prepares the listing data.
        """
        try:
            # Get platform common record
            platform_common = await self._get_platform_common(platform_id)
            if not platform_common:
                raise ListingNotFoundError(f"Platform listing {platform_id} not found")

            # Create eBay listing record
            ebay_listing = await self._create_listing_record(platform_common, listing_data)

            # Prepare listing data for eBay API
            inventory_item = self._prepare_inventory_item(ebay_listing, platform_common.product)
            
            # Create inventory item on eBay
            success = await self.client.create_or_update_inventory_item(
                sku=platform_common.product.sku,
                item_data=inventory_item
            )

            if success:
                # Create an offer for the inventory item
                offer_data = self._prepare_offer_data(ebay_listing, platform_common.product)
                offer_result = await self.client.create_offer(offer_data)
                
                # Update listing with eBay offer ID
                ebay_listing.ebay_item_id = offer_result.get('offerId')
                ebay_listing.listing_status = EbayListingStatus.DRAFT
                platform_common.sync_status = SyncStatus.SUCCESS
                platform_common.last_sync = datetime.now(timezone.utc)()
                
                await self.db.flush()
                await self.db.commit()
            else:
                raise EbayAPIError("Failed to create inventory item on eBay")

            return ebay_listing

        except Exception as e:
            await self.db.rollback()
            if isinstance(e, EbayAPIError) or isinstance(e, ListingNotFoundError):
                raise
            raise EbayAPIError(f"Failed to create eBay draft: {str(e)}")

    async def publish_listing(self, ebay_listing_id: int) -> bool:
        """
        Publishes a draft listing to eBay.
        Returns True if successful.
        """
        try:
            listing = await self._get_ebay_listing(ebay_listing_id)
            if not listing:
                raise ListingNotFoundError(f"eBay listing {ebay_listing_id} not found")

            # Call eBay API to publish the offer
            result = await self.client.publish_offer(listing.ebay_item_id)
            
            if 'listingId' in result:
                # Update statuses
                listing.listing_status = EbayListingStatus.ACTIVE
                listing.platform_listing.status = ListingStatus.ACTIVE
                listing.platform_listing.sync_status = SyncStatus.SUCCESS
                listing.platform_listing.external_id = result['listingId']
                listing.last_synced_at = datetime.now(timezone.utc)()
                
                await self.db.commit()
                return True

            return False

        except Exception as e:
            await self.db.rollback()
            if isinstance(e, EbayAPIError) or isinstance(e, ListingNotFoundError):
                raise
            raise EbayAPIError(f"Failed to publish listing: {str(e)}")

    async def update_inventory_quantity(self, ebay_listing_id: int, quantity: int) -> bool:
        """
        Updates inventory quantity for an eBay listing
        """
        try:
            listing = await self._get_ebay_listing(ebay_listing_id)
            if not listing:
                raise ListingNotFoundError(f"eBay listing {ebay_listing_id} not found")
                
            product = listing.platform_listing.product
            
            # Update on eBay
            success = await self.client.update_inventory_item_quantity(
                sku=product.sku,
                quantity=quantity
            )
            
            if success:
                # Update record timestamps
                listing.last_synced_at = datetime.now(timezone.utc)()
                listing.platform_listing.last_sync = datetime.now(timezone.utc)()
                listing.platform_listing.sync_status = SyncStatus.SUCCESS
                await self.db.commit()
                
            return success
        
        except Exception as e:
            await self.db.rollback()
            if isinstance(e, EbayAPIError) or isinstance(e, ListingNotFoundError):
                raise
            raise EbayAPIError(f"Failed to update inventory quantity: {str(e)}")

    # Private helper methods
    async def _get_platform_common(self, platform_id: int) -> Optional[PlatformCommon]:
        query = select(PlatformCommon).where(PlatformCommon.id == platform_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def _get_ebay_listing(self, listing_id: int) -> Optional[EbayListing]:
        query = select(EbayListing).where(EbayListing.id == listing_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def _create_listing_record(
        self,
        platform_common: PlatformCommon,
        listing_data: Dict[str, Any]
    ) -> EbayListing:
        """Creates the local EbayListing record."""
        ebay_listing = EbayListing(
            platform_id=platform_common.id,
            ebay_category_id=listing_data.get("category_id"),
            ebay_condition_id=listing_data.get("condition_id"),
            format=listing_data.get("format", "Buy it Now"),
            price=listing_data.get("price", 0),
            listing_duration=listing_data.get("duration", "GTC"),
            item_specifics=listing_data.get("item_specifics", {}),
            listing_status=EbayListingStatus.DRAFT
        )
        self.db.add(ebay_listing)
        await self.db.flush()
        return ebay_listing

    def _prepare_inventory_item(self, listing: EbayListing, product: Any) -> Dict[str, Any]:
        """
        Prepares inventory item data for eBay API.
        """
        return {
            "availability": {
                "shipToLocationAvailability": {
                    "quantity": 1
                }
            },
            "condition": listing.ebay_condition_id,
            "product": {
                "title": f"{product.brand} {product.model}",
                "description": product.description or f"{product.brand} {product.model}",
                "aspects": self._convert_item_specifics(listing.item_specifics),
                "imageUrls": [product.primary_image] + (product.additional_images or [])
            }
        }
    
    def _prepare_offer_data(self, listing: EbayListing, product: Any) -> Dict[str, Any]:
        """
        Prepares offer data for eBay API.
        """
        return {
            "sku": product.sku,
            "marketplaceId": "EBAY_US",  # Could be configurable
            "format": "FIXED_PRICE" if listing.format == "Buy it Now" else "AUCTION",
            "availableQuantity": 1,  # Initial quantity
            "categoryId": listing.ebay_category_id,
            "listingPolicies": {
                "paymentPolicyId": listing.payment_policy_id,
                "returnPolicyId": listing.return_policy_id,
                "shippingPolicyId": listing.shipping_policy_id,
                "fulfillmentPolicyId": listing.shipping_policy_id  # Often the same
            },
            "pricingSummary": {
                "price": {
                    "currency": "USD",  # Could be configurable
                    "value": str(listing.price)
                }
            },
            "listingDescription": product.description or f"{product.brand} {product.model}"
        }
    
    def _convert_item_specifics(self, item_specifics: Dict[str, Any]) -> Dict[str, List[str]]:
        """
        Convert item specifics to eBay's required format
        """
        result = {}
        for key, value in item_specifics.items():
            if isinstance(value, list):
                result[key] = value
            else:
                result[key] = [str(value)]
        return result