# app/repositories/ebay_repository.py
import logging
from typing import List, Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, insert

from app.models.platforms import PlatformCommon, EbayListing
from app.schemas.platform import ListingStatus

logger = logging.getLogger(__name__)

class EbayRepository:
    """Repository for eBay-related database operations"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def create_or_update_from_api_data(self, items: List[Dict[str, Any]]) -> Dict[str, int]:
        """
        Create or update database records from eBay API data
        
        Args:
            items: List of eBay listing items from API
            
        Returns:
            Stats about the operation (created, updated, errors)
        """
        results = {
            "total": len(items),
            "created": 0,
            "updated": 0,
            "errors": 0
        }
        
        for item_data in items:
            try:
                item_id = item_data.get('ItemID')
                
                # Check if this listing already exists
                stmt = select(PlatformCommon).where(
                    PlatformCommon.platform_name == "ebay",
                    PlatformCommon.external_id == item_id
                )
                result = await self.db.execute(stmt)
                platform_common = result.scalars().first()
                
                if platform_common:
                    # Update existing listing
                    await self._update_listing(platform_common, item_data)
                    results["updated"] += 1
                else:
                    # Create new listing
                    await self._create_listing(item_data)
                    results["created"] += 1
                    
            except Exception as e:
                logger.error(f"Error processing eBay item {item_data.get('ItemID')}: {str(e)}")
                results["errors"] += 1
        
        await self.db.commit()
        return results
    
    async def _create_listing(self, item_data: Dict[str, Any]) -> None:
        """Create new eBay listing in database"""
        # First create PlatformCommon entry
        # Note: You'll need logic to associate with a product_id
        # For now using a placeholder product_id = 1
        
        item_id = item_data.get('ItemID')
        title = item_data.get('Title', '')
        selling_status = item_data.get('SellingStatus', {})
        price_data = selling_status.get('CurrentPrice', {})
        price = float(price_data.get('#text', 0))
        currency = price_data.get('@currencyID', 'GBP')
        listing_url = item_data.get('ListingDetails', {}).get('ViewItemURL', '')
        
        # Create platform_common record
        stmt = insert(PlatformCommon).values(
            product_id=1,  # Placeholder - you'll need to determine the correct product_id
            platform_name="ebay",
            external_id=item_id,
            status=ListingStatus.ACTIVE,
            listing_url=listing_url,
            platform_specific_data=item_data
        ).returning(PlatformCommon.id)
        
        result = await self.db.execute(stmt)
        platform_id = result.scalar()
        
        # Create ebay_listing record
        await self.db.execute(
            insert(EbayListing).values(
                platform_id=platform_id,
                price=price,
                quantity=int(item_data.get('QuantityAvailable', 1)),
                format=item_data.get('ListingType', 'FixedPriceItem'),
                # Map other fields as needed
            )
        )
    
    async def _update_listing(self, platform_common: PlatformCommon, item_data: Dict[str, Any]) -> None:
        """Update existing eBay listing in database"""
        selling_status = item_data.get('SellingStatus', {})
        price_data = selling_status.get('CurrentPrice', {})
        price = float(price_data.get('#text', 0))
        listing_url = item_data.get('ListingDetails', {}).get('ViewItemURL', '')
        
        # Update platform_common
        await self.db.execute(
            update(PlatformCommon)
            .where(PlatformCommon.id == platform_common.id)
            .values(
                status=ListingStatus.ACTIVE,
                listing_url=listing_url,
                platform_specific_data=item_data
            )
        )
        
        # Find and update ebay_listing
        stmt = select(EbayListing).where(EbayListing.platform_id == platform_common.id)
        result = await self.db.execute(stmt)
        ebay_listing = result.scalars().first()
        
        if ebay_listing:
            await self.db.execute(
                update(EbayListing)
                .where(EbayListing.id == ebay_listing.id)
                .values(
                    price=price,
                    quantity=int(item_data.get('QuantityAvailable', 1))
                    # Update other fields as needed
                )
            )