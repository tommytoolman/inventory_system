import logging
import json
import asyncio

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from datetime import datetime
from typing import Dict, Any

from app.dependencies import get_db
from app.core.config import Settings, get_settings
from app.schemas.product import ProductCreate
from app.schemas.platform.ebay import EbayListingCreate
from app.services.activity_logger import ActivityLogger
from app.services.product_service import ProductService
from app.services.ebay_service import EbayService
from app.services.websockets.manager import manager


sync_in_progress = False

router = APIRouter(prefix="/api", tags=["ebay"])

logger = logging.getLogger(__name__)

# Add an imports dictionary to track active processes
ebay_imports: Dict[str, Dict[str, Any]] = {}

@router.post("/sync/ebay")
async def sync_ebay_inventory(
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings)
):
    """Run eBay sync - download latest inventory and update local database"""
    background_tasks.add_task(
        run_ebay_sync_background,
        db,
        settings
    )
    return {"status": "success", "message": "eBay sync started"}

# Add this background task function
async def run_ebay_sync_background(db: AsyncSession, settings: Settings):
    """Run eBay sync in background with WebSocket updates"""
    logger.info("Starting eBay import process through background task")
    
    # Add activity logger
    activity_logger = ActivityLogger(db)
    
    try:
        # Log sync start
        await activity_logger.log_activity(
            action="sync_start",
            entity_type="platform",
            entity_id="ebay",
            platform="ebay",
            details={"status": "started"}
        )
        
        # Send start notification
        await manager.broadcast({
            "type": "sync_started",
            "platform": "ebay",
            "timestamp": datetime.now().isoformat()
        })
        
        # Initialize eBay service
        ebay_service = EbayService(db, settings)
        
        # Create progress callback function
        async def send_progress(progress_data: Dict[str, Any]):
            """Send progress updates via websocket"""
            try:
                notification = {
                    "category": "ebay",
                    "type": "sync",
                    "data": progress_data
                }
                await manager.broadcast(notification)
            except Exception as e:
                logger.error(f"Error sending progress update: {str(e)}")
        
        # Run the import process
        result = await ebay_service.sync_inventory_from_ebay(progress_callback=send_progress)
        
        if result.get('errors', 0) == 0:
            # Update last_sync timestamp for eBay platform entries
            update_query = text("""
                UPDATE platform_common 
                SET last_sync = timezone('utc', now()),
                    sync_status = 'SYNCED'
                WHERE platform_name = 'ebay'
            """)
            await db.execute(update_query)
            
            # Log successful sync
            await activity_logger.log_activity(
                action="sync",
                entity_type="platform", 
                entity_id="ebay",
                platform="ebay",
                details={
                    "status": "success",
                    "processed": result.get('total', 0),
                    "created": result.get('created', 0),
                    "updated": result.get('updated', 0),
                    "errors": result.get('errors', 0),
                    "icon": "✅",
                    "message": f"Synced eBay ({result.get('total', 0)} items)"
                }
            )
            
            # Send success notification
            await manager.broadcast({
                "type": "sync_completed",
                "platform": "ebay",
                "status": "success",
                "data": result,
                "timestamp": datetime.now().isoformat()
            })
            logger.info(f"eBay import process result: {result}")
        else:
            # Log failed sync
            await activity_logger.log_activity(
                action="sync_error",
                entity_type="platform",
                entity_id="ebay", 
                platform="ebay",
                details={"error": f"Completed with {result.get('errors', 0)} errors"}
            )
            
            # Send error notification
            await manager.broadcast({
                "type": "sync_completed",
                "platform": "ebay",
                "status": "error",
                "message": f"Completed with {result.get('errors', 0)} errors",
                "timestamp": datetime.now().isoformat()
            })
            logger.error(f"eBay sync completed with errors: {result.get('errors', 0)}")
        
        # Commit the activity logging
        await db.commit()
            
    except Exception as e:
        await db.rollback()
        error_message = str(e)
        logger.exception(f"eBay sync background task failed: {error_message}")
        
        # Log exception
        await activity_logger.log_activity(
            action="sync_error",
            entity_type="platform",
            entity_id="ebay",
            platform="ebay", 
            details={"error": error_message}
        )
        await db.commit()
        
        # Send error notification
        await manager.broadcast({
            "type": "sync_completed",
            "platform": "ebay",
            "status": "error",
            "message": error_message,
            "timestamp": datetime.now().isoformat()
        })

@router.get("/sync/ebay/status")
async def get_ebay_sync_status():
    """Get the current status of eBay sync operations"""
    if not ebay_imports:
        return {"status": "idle", "message": "No eBay sync operations running"}
    
    # Return status of the most recent import
    latest_import = max(ebay_imports.values(), key=lambda x: x.get("start_time", 0))
    return {
        "status": latest_import.get("status", "unknown"),
        "message": latest_import.get("message", ""),
        "progress": latest_import.get("progress", 0),
        "stats": latest_import.get("stats", {})
    }

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
