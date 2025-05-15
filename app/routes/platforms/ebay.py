import logging
import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict, Any

from app.dependencies import get_db
from app.core.config import Settings, get_settings
from app.services.websockets.manager import manager
from app.schemas.product import ProductCreate
from app.schemas.platform.ebay import EbayListingCreate
from app.services.product_service import ProductService
from app.services.ebay_service import EbayService

router = APIRouter(prefix="/api", tags=["ebay"])

logger = logging.getLogger(__name__)

@router.post("/sync/ebay")
async def sync_ebay_inventory(db: AsyncSession = Depends(get_db)):
    """Synchronize eBay inventory with the database"""
    print("*** EBAY ROUTE CALLED - PRINT STATEMENT ***")
    logger.info("=== EBAY SYNC ROUTE CALLED ===")
    logger.info("Starting eBay inventory sync")
    
    # Initialize the eBay service
    ebay_service = EbayService(db, settings=get_settings())  # Add settings if needed
    
    print("*** EBAY SERVICE CREATED SUCCESSFULLY ***")
    
    # Create progress callback function
    async def send_progress(progress_data: Dict[str, Any]):
        """Send progress updates via websocket"""
        try:
            notification = {
                "category": "ebay",
                "type": "sync",
                "data": progress_data
            }
            await manager.broadcast(json.dumps(notification))
        except Exception as e:
            logger.error(f"Error sending progress update: {str(e)}")
    
    print("*** ABOUT TO CALL sync_inventory_from_ebay ***")
    
    try:
        # Run the import process with progress callback
        result = await ebay_service.sync_inventory_from_ebay(progress_callback=send_progress)
        
        # Send completion notification regardless of errors within
        completion_data = {
            "category": "ebay",
            "type": "sync_complete",
            "data": {
                "message": f"eBay sync completed. Created: {result['created']}, Updated: {result['updated']}, Errors: {result['errors']}",
                "stats": result
            }
        }
        await manager.broadcast(json.dumps(completion_data))
        
        logger.info(f"eBay sync completed: {result}")
        return {"status": "success", "message": "eBay sync completed", "stats": result}
            
            
    except Exception as e:
        logger.exception(f"eBay sync error: {str(e)}")
        
        # Send error notification
        error_data = {
            "category": "ebay",
            "type": "sync_error", 
            "data": {
                "message": "eBay sync failed",
                "error": str(e)
            }
        }
        await manager.broadcast(json.dumps(error_data))
        
        raise HTTPException(status_code=500, detail=f"eBay sync error: {str(e)}")



async def create_product_with_ebay(
    product_data: ProductCreate,
    ebay_data: EbayListingCreate,
    db: AsyncSession = Depends(get_db)
):
    # Initialize services
    product_service = ProductService(db)
    ebay_service = EbayService(db)

    # Create product and get platform_common ID
    product = await product_service.create_product(product_data)
    
    # Create eBay listing
    ebay_listing = await ebay_service.create_draft_listing(
        product.platform_listings[0].id,  # First platform listing is eBay
        ebay_data
    )

    return {
        "product": product,
        "ebay_listing": ebay_listing
    }   
