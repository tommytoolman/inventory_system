#!/usr/bin/env python3
"""
Update eBay listings that are missing images.
"""
import asyncio
import logging
from typing import List, Optional
from sqlalchemy import text
from app.database import async_session
# These will be imported inside the function to match ebay_service.py pattern

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def get_listings_with_missing_images(limit: int = 10) -> List[dict]:
    """Get eBay listings that have fewer images than their products."""
    async with async_session() as session:
        result = await session.execute(text('''
            SELECT 
                el.ebay_item_id,
                p.sku,
                el.title,
                el.picture_urls,
                p.primary_image,
                p.additional_images,
                el.id as listing_id
            FROM ebay_listings el
            JOIN platform_common pc ON el.platform_id = pc.id
            JOIN products p ON pc.product_id = p.id
            WHERE el.ebay_item_id IS NOT NULL
            AND pc.status = 'active'
            ORDER BY el.created_at DESC
            LIMIT :limit
        '''), {"limit": limit})
        
        listings = []
        for row in result.fetchall():
            # Count images
            ebay_count = len(row.picture_urls) if row.picture_urls else 0
            product_count = (1 if row.primary_image else 0) + (len(row.additional_images) if row.additional_images else 0)
            
            if ebay_count < product_count:
                # Build full image list
                all_images = []
                if row.primary_image:
                    all_images.append(row.primary_image)
                if row.additional_images:
                    all_images.extend(row.additional_images)
                    
                listings.append({
                    'ebay_item_id': row.ebay_item_id,
                    'sku': row.sku,
                    'title': row.title,
                    'current_images': ebay_count,
                    'should_have': product_count,
                    'all_images': all_images,
                    'listing_id': row.listing_id
                })
                
        return listings


async def update_ebay_listing_images(ebay_item_id: str, images: List[str]) -> bool:
    """Update images for an eBay listing using ReviseFixedPriceItem."""
    try:
        # Import and initialize exactly like in ebay_service.py
        from app.services.ebay.auth import EbayAuthManager
        from app.services.ebay.trading import EbayTradingLegacyAPI
        from app.core.config import get_settings
        
        settings = get_settings()
        auth_manager = EbayAuthManager(settings)
        trading_api = EbayTradingLegacyAPI(sandbox=False)  # Production
        
        # Call ReviseFixedPriceItem with images
        response = await trading_api.revise_listing_images(ebay_item_id, images)
        
        if response.get('Ack') == 'Success':
            logger.info(f"✅ Successfully updated images for {ebay_item_id}")
            return True
        else:
            errors = response.get('Errors', response)
            logger.error(f"❌ Failed to update {ebay_item_id}: {errors}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Error updating {ebay_item_id}: {str(e)}")
        return False


async def update_database_images(listing_id: int, images: List[str]):
    """Update the picture_urls in the database."""
    async with async_session() as session:
        await session.execute(
            text('''
                UPDATE ebay_listings 
                SET picture_urls = :images,
                    updated_at = NOW()
                WHERE id = :listing_id
            '''),
            {"images": images, "listing_id": listing_id}
        )
        await session.commit()


async def main():
    """Main function to update missing images."""
    logger.info("🔍 Finding eBay listings with missing images...")
    
    # Get listings that need updating
    listings = await get_listings_with_missing_images(limit=10)
    
    if not listings:
        logger.info("✅ All listings have the correct number of images!")
        return
        
    logger.info(f"Found {len(listings)} listings with missing images")
    
    # Show what we'll update
    for listing in listings:
        logger.info(f"\n{listing['ebay_item_id']} ({listing['sku']})")
        logger.info(f"  Title: {listing['title'][:60]}...")
        logger.info(f"  Current images: {listing['current_images']}")
        logger.info(f"  Should have: {listing['should_have']}")
    
    # Skip confirmation for now - auto-proceed
    logger.info("\n🚀 Proceeding with updates...")
        
    # Update each listing
    success_count = 0
    for listing in listings:
        logger.info(f"\n🔄 Updating {listing['ebay_item_id']}...")
        
        # Update on eBay
        if await update_ebay_listing_images(listing['ebay_item_id'], listing['all_images']):
            # Update in database
            await update_database_images(listing['listing_id'], listing['all_images'])
            success_count += 1
        
        # Small delay to avoid rate limits
        await asyncio.sleep(1)
    
    logger.info(f"\n✅ Complete! Successfully updated {success_count}/{len(listings)} listings")


if __name__ == "__main__":
    asyncio.run(main())