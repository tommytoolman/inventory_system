# app/services/sync_service.py
"""
Central service for synchronizing products across multiple platforms.

This service coordinates:
1. Stock level synchronization across platforms
2. Platform-specific listing creation/updates
3. Status tracking and error handling
"""

import logging
from typing import Dict, List, Any, Optional
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product import Product
from app.models.platform_common import PlatformCommon
from app.core.enums import SyncStatus, ListingStatus
from app.integrations.events import StockUpdateEvent

logger = logging.getLogger(__name__)

class SyncService:
    """
    Coordinates synchronization between inventory system and external platforms.
    
    This service:
    1. Acts as a facade over the StockManager
    2. Maintains platform sync status data
    3. Handles platform-specific synchronization logic
    """
    
    def __init__(self, db: AsyncSession, stock_manager=None):
        """
        Initialize the sync service with database session and optional stock manager.
        
        Args:
            db: AsyncSession for database operations
            stock_manager: StockManager instance from app state
        """
        self.db = db
        self.stock_manager = stock_manager
    
    async def sync_product_to_platforms(
        self, 
        product_id: int, 
        platforms: List[str],
        db: Optional[AsyncSession] = None
    ) -> Dict[str, Any]:
        """
        Synchronize a product to specified platforms.
        
        Args:
            product_id: ID of the product to sync
            platforms: List of platform names to sync to (e.g., ["ebay", "reverb", "vr"])
            db: Optional database session override
            
        Returns:
            Dict with sync results per platform
        """
        if db is None:
            db = self.db
            
        # Find the product
        query = select(Product).where(Product.id == product_id)
        result = await db.execute(query)
        product = result.scalar_one_or_none()
        
        if not product:
            return {"status": "error", "message": "Product not found"}
            
        results = {}
        
        # Process each requested platform
        for platform in platforms:
            try:
                if platform == "ebay":
                    # Handle eBay synchronization
                    from app.services.ebay_service import EbayService
                    ebay_service = EbayService(db)
                    ebay_result = await ebay_service.sync_product(product)
                    results["ebay"] = ebay_result
                    
                elif platform == "reverb":
                    # Handle Reverb synchronization  
                    from app.services.reverb_service import ReverbService
                    reverb_service = ReverbService(db)
                    reverb_result = await reverb_service.sync_product(product)
                    results["reverb"] = reverb_result
                    
                elif platform == "vr":
                    # Handle VintageAndRare synchronization
                    from app.services.vintageandrare.client import VintageAndRareClient
                    vr_client = VintageAndRareClient()
                    
                    # Convert product to the format expected by VR client
                    product_data = {
                        "id": product.id,
                        "brand": product.brand,
                        "model": product.model,
                        "description": product.description,
                        "category": product.category,
                        "price": product.base_price,
                        "condition": product.condition.value,
                        "year": product.year,
                        "finish": product.finish,
                        "primary_image": product.primary_image,
                        "additional_images": product.additional_images
                    }
                    
                    # Create listing in VintageAndRare
                    vr_result = await vr_client.create_listing(product_data, test_mode=False)
                    results["vr"] = {
                        "status": "success" if vr_result.get("external_id") else "error",
                        "id": vr_result.get("external_id"),
                        "message": vr_result.get("message", "")
                    }
                    
                    # Update platform_common record
                    if vr_result.get("external_id"):
                        await self._update_platform_common(
                            db, product.id, "vr", vr_result["external_id"], 
                            ListingStatus.ACTIVE, SyncStatus.SYNCED
                        )
                        
                else:
                    results[platform] = {
                        "status": "error", 
                        "message": f"Unknown platform: {platform}"
                    }
                    
            except Exception as e:
                logger.exception(f"Error syncing to {platform}: {str(e)}")
                results[platform] = {
                    "status": "error",
                    "message": str(e)
                }
                
                # Update platform_common with error status
                await self._update_platform_common(
                    db, product.id, platform, None,
                    ListingStatus.DRAFT, SyncStatus.ERROR
                )
                
        return results
    
    async def propagate_stock_update(
        self, 
        product_id: int, 
        new_quantity: int,
        source_platform: str = "local"
    ) -> bool:
        """
        Propagate a stock update to all platforms through StockManager.
        
        Args:
            product_id: ID of the product with changed stock
            new_quantity: New stock quantity
            source_platform: Platform that originated the update
            
        Returns:
            True if queued successfully, False otherwise
        """
        if self.stock_manager is None:
            logger.error("Stock manager not available")
            return False
            
        try:
            # Create stock update event
            event = StockUpdateEvent(
                product_id=product_id,
                platform=source_platform,
                new_quantity=new_quantity,
                timestamp=datetime.now(timezone.utc)
            )
            
            # Process the update directly - useful for API calls
            await self.stock_manager.process_stock_update(event)
            return True
            
        except Exception as e:
            logger.exception(f"Error propagating stock update: {str(e)}")
            return False
    
    async def _update_platform_common(
        self, 
        db: AsyncSession,
        product_id: int,
        platform_name: str,
        external_id: Optional[str],
        status: ListingStatus,
        sync_status: SyncStatus
    ) -> Optional[PlatformCommon]:
        """
        Update or create platform_common record for a product/platform.
        
        Args:
            db: Database session
            product_id: Product ID
            platform_name: Platform name (e.g., "ebay")
            external_id: External platform ID (or None)
            status: Listing status enum value
            sync_status: Sync status enum value
            
        Returns:
            Updated or created PlatformCommon record (or None on error)
        """
        try:
            # Find existing record
            query = select(PlatformCommon).where(
                (PlatformCommon.product_id == product_id) & 
                (PlatformCommon.platform_name == platform_name)
            )
            result = await db.execute(query)
            platform_common = result.scalar_one_or_none()
            
            now = datetime.now(timezone.utc)
            
            if platform_common:
                # Update existing record
                platform_common.external_id = external_id or platform_common.external_id
                platform_common.status = status.value
                platform_common.sync_status = sync_status.value
                platform_common.last_sync = now
                platform_common.updated_at = now
            else:
                # Create new record
                platform_common = PlatformCommon(
                    product_id=product_id,
                    platform_name=platform_name,
                    external_id=external_id,
                    status=status.value,
                    sync_status=sync_status.value,
                    last_sync=now,
                    created_at=now,
                    updated_at=now
                )
                db.add(platform_common)
                
            await db.commit()
            return platform_common
            
        except Exception as e:
            await db.rollback()
            logger.exception(f"Error updating platform_common: {str(e)}")
            return None


# Helper function for fastAPI dependency injection
async def get_sync_service(
    db: AsyncSession,
    request = None
) -> SyncService:
    """
    Create a SyncService with database session and stock manager from app state.
    
    Args:
        db: Database session from dependency
        request: Optional FastAPI request object
        
    Returns:
        Configured SyncService instance
    """
    stock_manager = None
    if request and hasattr(request.app.state, 'stock_manager'):
        stock_manager = request.app.state.stock_manager
    
    return SyncService(db, stock_manager)