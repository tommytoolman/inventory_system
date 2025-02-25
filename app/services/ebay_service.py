"""
Key features of the EbayService:

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

Proper exception handling
Transaction management
Status tracking
"""

from typing import Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime

from app.models.ebay import EbayListing, EbayListingStatus, EbayListingFormat
from app.models.platform_common import PlatformCommon, ListingStatus, SyncStatus
from app.schemas.platform.ebay import EbayListingCreate
from app.core.config import Settings
from app.core.exceptions import EbayAPIError, ListingNotFoundError
from app.services.product_service import ProductService

class EbayService:
    def __init__(self, db: AsyncSession, settings: Settings):
        self.db = db
        self.settings = settings
        self._api_key = settings.EBAY_API_KEY
        self._api_secret = settings.EBAY_API_SECRET
        self._sandbox_mode = settings.EBAY_SANDBOX_MODE

    async def create_draft_listing(
        self,
        platform_id: int,
        listing_data: EbayListingCreate
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
            api_listing_data = self._prepare_api_listing_data(ebay_listing, platform_common.product)

            # Create draft on eBay (not published)
            ebay_item_id = await self._create_ebay_draft(api_listing_data)

            # Update listing with eBay ID
            ebay_listing.ebay_item_id = ebay_item_id
            ebay_listing.listing_status = EbayListingStatus.DRAFT
            await self.db.flush()  # Make sure flushes are awaited
            await self.db.commit()

            return ebay_listing

        except Exception as e:
            await self.db.rollback()
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

            # Call eBay API to publish
            success = await self._publish_to_ebay(listing.ebay_item_id)
            
            if success:
                # Update statuses
                listing.listing_status = EbayListingStatus.ACTIVE
                listing.platform_listing.status = ListingStatus.ACTIVE
                listing.platform_listing.sync_status = SyncStatus.SUCCESS
                listing.last_synced_at = datetime.utcnow()
                await self.db.commit()
                return True

            return False

        except Exception as e:
            await self.db.rollback()
            raise EbayAPIError(f"Failed to publish listing: {str(e)}")

    async def update_listing(
        self,
        ebay_listing_id: int,
        update_data: Dict[str, Any]
    ) -> EbayListing:
        """
        Updates an existing eBay listing.
        """
        try:
            listing = await self._get_ebay_listing(ebay_listing_id)
            if not listing:
                raise ListingNotFoundError(f"eBay listing {ebay_listing_id} not found")

            # Update local record
            for key, value in update_data.items():
                if hasattr(listing, key):
                    setattr(listing, key, value)

            # Update on eBay if listing is active
            if listing.listing_status == EbayListingStatus.ACTIVE:
                await self._update_on_ebay(listing.ebay_item_id, update_data)
                listing.last_synced_at = datetime.utcnow()

            await self.db.commit()
            return listing

        except Exception as e:
            await self.db.rollback()
            raise EbayAPIError(f"Failed to update listing: {str(e)}")

    async def sync_listing_status(self, ebay_listing_id: int) -> EbayListingStatus:
        """
        Syncs the listing status with eBay.
        """
        listing = await self._get_ebay_listing(ebay_listing_id)
        if not listing:
            raise ListingNotFoundError(f"eBay listing {ebay_listing_id} not found")

        try:
            # Get status from eBay
            ebay_status = await self._get_ebay_status(listing.ebay_item_id)
            
            # Update local status
            listing.listing_status = ebay_status
            listing.last_synced_at = datetime.utcnow()
            listing.platform_listing.sync_status = SyncStatus.SUCCESS
            
            await self.db.commit()
            return ebay_status

        except Exception as e:
            listing.platform_listing.sync_status = SyncStatus.ERROR
            await self.db.commit()
            raise EbayAPIError(f"Failed to sync status: {str(e)}")

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
        listing_data: EbayListingCreate
    ) -> EbayListing:
        """Creates the local EbayListing record."""
        ebay_listing = EbayListing(
            platform_id=platform_common.id,
            **listing_data.model_dump(exclude={'platform_id'})
        )
        self.db.add(ebay_listing)
        await self.db.flush()
        return ebay_listing

    def _prepare_api_listing_data(self, listing: EbayListing, product: Any) -> Dict[str, Any]:
        """
        Prepares listing data for eBay API.
        This will be expanded based on eBay API requirements.
        """
        return {
            "title": f"{product.brand} {product.model}",
            "description": product.description,
            "categoryId": listing.ebay_category_id,
            "price": str(listing.price),
            "quantity": listing.quantity,
            "listingPolicies": {
                "paymentPolicyId": listing.payment_policy_id,
                "returnPolicyId": listing.return_policy_id,
                "shippingPolicyId": listing.shipping_policy_id
            },
            "itemSpecifics": listing.item_specifics
        }

    async def _create_ebay_draft(self, listing_data: Dict[str, Any]) -> str:
        """
        Creates draft listing via eBay API.
        Returns eBay item ID.
        To be implemented with actual eBay API calls.
        """
        # TODO: Implement actual eBay API call
        return "draft_ebay_item_id_123"

    async def _publish_to_ebay(self, ebay_item_id: str) -> bool:
        """
        Publishes listing via eBay API.
        To be implemented with actual eBay API calls.
        """
        # TODO: Implement actual eBay API call
        return True

    async def _update_on_ebay(self, ebay_item_id: str, update_data: Dict[str, Any]) -> bool:
        """
        Updates listing via eBay API.
        To be implemented with actual eBay API calls.
        """
        # TODO: Implement actual eBay API call
        return True

    async def _get_ebay_status(self, ebay_item_id: str) -> EbayListingStatus:
        """
        Gets listing status from eBay API.
        To be implemented with actual eBay API calls.
        """
        # TODO: Implement actual eBay API call
        return EbayListingStatus.ACTIVE