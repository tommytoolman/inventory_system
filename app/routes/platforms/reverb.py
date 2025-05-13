"""
API routes for Reverb platform integration.

This module provides endpoints for managing Reverb listings, including:
- Creating listings
- Publishing listings
- Updating inventory
- Syncing listing status
- Getting category information
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Dict, Any, Optional
from datetime import datetime

from app.schemas.platform.reverb import (
    ReverbListingCreateDTO,
    ReverbListingReadDTO,
    # Not sure if the following are needed at all. Might want to delete import and delete from platform file too.
    ReverbListingUpdateDTO,
    ReverbListingStatusDTO,
    ReverbCategoryDTO,
    ReverbConditionDTO
)
from app.services.reverb_service import ReverbService
from app.services.websockets.manager import manager
from app.services.activity_logger import ActivityLogger
from app.dependencies import get_db
from app.core.config import Settings, get_settings
from app.core.exceptions import ReverbAPIError, ListingNotFoundError

router = APIRouter(prefix="/api", tags=["reverb"])

logger = logging.getLogger(__name__)

@router.post("/sync/reverb")
async def sync_reverb(
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings)
):
    """Run Reverb read sync - download latest inventory and update local database"""
    background_tasks.add_task(
        run_reverb_sync_background,
        settings.REVERB_API_KEY,  # Assuming you have this in settings
        db,
        settings
    )
    return {"status": "success", "message": "Reverb sync started"}

# Add this background task function
async def run_reverb_sync_background(api_key: str, db: AsyncSession, settings: Settings):
    """Run Reverb sync in background with WebSocket updates"""
    logger.info("Starting Reverb import process through background task")
    
    # Add activity logger
    activity_logger = ActivityLogger(db)
    
    try:
        # Log sync start
        await activity_logger.log_activity(
            action="sync_start",
            entity_type="platform",
            entity_id="reverb",
            platform="reverb",
            details={"status": "started"}
        )
        
        # Send start notification
        await manager.broadcast({
            "type": "sync_started",
            "platform": "reverb",
            "timestamp": datetime.now().isoformat()
        })
        
        # Initialize Reverb service
        reverb_service = ReverbService(db, settings)
        # You'll need to implement a sync method in ReverbService similar to V&R
        result = await reverb_service.run_import_process(api_key)
        
        if result.get('status') == 'success':
            # Update last_sync timestamp for Reverb platform entries
            update_query = text("""
                UPDATE platform_common 
                SET last_sync = timezone('utc', now()),
                    sync_status = 'SYNCED'
                WHERE platform_name = 'reverb'
            """)
            await db.execute(update_query)
            
            # Log successful sync
            await activity_logger.log_activity(
                action="sync",
                entity_type="platform", 
                entity_id="reverb",
                platform="reverb",
                details={
                    "status": "success",
                    "processed": result.get('processed', 0),
                    "created": result.get('created', 0),
                    "updated": result.get('updated', 0),
                    "errors": result.get('errors', 0),
                    "icon": "✅",
                    "message": f"Synced Reverb ({result.get('processed', 0)} items)"
                }
            )
            
            # Send success notification
            await manager.broadcast({
                "type": "sync_completed",
                "platform": "reverb",
                "status": "success",
                "data": result,
                "timestamp": datetime.now().isoformat()
            })
            logger.info(f"Reverb import process result: {result}")
        else:
            # Log failed sync
            await activity_logger.log_activity(
                action="sync_error",
                entity_type="platform",
                entity_id="reverb", 
                platform="reverb",
                details={"error": result.get('message', 'Unknown error')}
            )
            
            # Send error notification
            await manager.broadcast({
                "type": "sync_completed",
                "platform": "reverb",
                "status": "error",
                "message": result.get('message', 'Unknown error'),
                "timestamp": datetime.now().isoformat()
            })
            logger.error(f"Reverb sync error in result: {result.get('message', 'Unknown error')}")
        
        # Commit the activity logging
        await db.commit()
            
    except Exception as e:
        await db.rollback()
        error_message = str(e)
        logger.exception(f"Reverb sync background task failed: {error_message}")
        
        # Log exception
        await activity_logger.log_activity(
            action="sync_error",
            entity_type="platform",
            entity_id="reverb",
            platform="reverb", 
            details={"error": error_message}
        )
        await db.commit()
        
        # Send error notification
        await manager.broadcast({
            "type": "sync_completed",
            "platform": "reverb",
            "status": "error",
            "message": error_message,
            "timestamp": datetime.now().isoformat()
        })

@router.post("/listings", response_model=ReverbListingReadDTO)
async def create_reverb_listing(
    listing_data: ReverbListingCreateDTO,
    db: AsyncSession = Depends(get_db),
    settings = Depends(get_settings)
):
    """
    Create a new listing on Reverb (draft mode).
    
    This endpoint creates a draft listing on Reverb. The listing will not be
    visible to buyers until it is published.
    
    Args:
        listing_data: Data for the listing
        
    Returns:
        The created listing data
    """
    try:
        service = ReverbService(db, settings)
        listing = await service.create_draft_listing(
            listing_data.platform_id,
            listing_data.model_dump(exclude_unset=True)
        )
        return listing
    except ListingNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ReverbAPIError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@router.post("/listings/{listing_id}/publish", response_model=bool)
async def publish_reverb_listing(
    listing_id: int,
    db: AsyncSession = Depends(get_db),
    settings = Depends(get_settings)
):
    """
    Publish a draft listing on Reverb.
    
    This endpoint publishes a draft listing, making it visible to buyers.
    
    Args:
        listing_id: ID of the listing to publish
        
    Returns:
        Boolean indicating success
    """
    try:
        service = ReverbService(db, settings)
        success = await service.publish_listing(listing_id)
        return success
    except ListingNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ReverbAPIError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@router.post("/listings/{listing_id}/end", response_model=bool)
async def end_reverb_listing(
    listing_id: int,
    reason: str = "not_sold",
    db: AsyncSession = Depends(get_db),
    settings = Depends(get_settings)
):
    """
    End a listing on Reverb.
    
    This endpoint ends a live listing.
    
    Args:
        listing_id: ID of the listing to end
        reason: Reason for ending (not_sold or reverb_sale)
        
    Returns:
        Boolean indicating success
    """
    if reason not in ["not_sold", "reverb_sale"]:
        raise HTTPException(status_code=400, detail="Invalid reason. Must be 'not_sold' or 'reverb_sale'")
    
    try:
        service = ReverbService(db, settings)
        success = await service.end_listing(listing_id, reason)
        return success
    except ListingNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ReverbAPIError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@router.put("/listings/{listing_id}/inventory", response_model=bool)
async def update_reverb_inventory(
    listing_id: int,
    quantity: int,
    db: AsyncSession = Depends(get_db),
    settings = Depends(get_settings)
):
    """
    Update inventory for a listing on Reverb.
    
    This endpoint updates the quantity available for a listing.
    
    Args:
        listing_id: ID of the listing to update
        quantity: New quantity value
        
    Returns:
        Boolean indicating success
    """
    if quantity < 0:
        raise HTTPException(status_code=400, detail="Quantity cannot be negative")
    
    try:
        service = ReverbService(db, settings)
        success = await service.update_inventory(listing_id, quantity)
        return success
    except ListingNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ReverbAPIError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@router.get("/listings/{listing_id}/sync", response_model=bool)
async def sync_reverb_listing(
    listing_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    settings = Depends(get_settings)
):
    """
    Sync a listing from Reverb.
    
    This endpoint fetches the current state of a listing from Reverb
    and updates our local record.
    
    Args:
        listing_id: ID of the listing to sync
        
    Returns:
        Boolean indicating success
    """
    try:
        service = ReverbService(db, settings)
        
        # Add sync task to background tasks
        # This prevents timeout issues with long-running syncs
        background_tasks.add_task(service.sync_listing_from_reverb, listing_id)
        
        return True
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@router.get("/categories", response_model=Dict[str, str])
async def get_reverb_categories(
    db: AsyncSession = Depends(get_db),
    settings = Depends(get_settings)
):
    """
    Get all categories from Reverb.
    
    This endpoint fetches the current categories from Reverb and
    returns a mapping of category names to UUIDs.
    
    Returns:
        Dict mapping category names to UUIDs
    """
    try:
        service = ReverbService(db, settings)
        categories = await service.fetch_and_store_category_mapping()
        return categories
    except ReverbAPIError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@router.get("/conditions", response_model=Dict[str, str])
async def get_reverb_conditions(
    db: AsyncSession = Depends(get_db),
    settings = Depends(get_settings)
):
    """
    Get all listing conditions from Reverb.
    
    This endpoint fetches the current listing conditions from Reverb and
    returns a mapping of condition display names to UUIDs.
    
    Returns:
        Dict mapping condition display names to UUIDs
    """
    try:
        service = ReverbService(db, settings)
        conditions = await service.fetch_and_store_condition_mapping()
        return conditions
    except ReverbAPIError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@router.get("/listings/find", response_model=Optional[Dict[str, Any]])
async def find_reverb_listing_by_sku(
    sku: str,
    db: AsyncSession = Depends(get_db),
    settings = Depends(get_settings)
):
    """
    Find a listing on Reverb by SKU.
    
    This endpoint searches for a listing on Reverb using the product SKU.
    
    Args:
        sku: Product SKU to search for
        
    Returns:
        Listing data if found, null otherwise
    """
    try:
        service = ReverbService(db, settings)
        listing = await service.find_listing_by_sku(sku)
        return listing
    except ReverbAPIError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")