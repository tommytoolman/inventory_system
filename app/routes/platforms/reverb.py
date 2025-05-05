"""
API routes for Reverb platform integration.

This module provides endpoints for managing Reverb listings, including:
- Creating listings
- Publishing listings
- Updating inventory
- Syncing listing status
- Getting category information
"""

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Dict, Any, Optional

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
from app.dependencies import get_db
from app.core.config import get_settings
from app.core.exceptions import ReverbAPIError, ListingNotFoundError

router = APIRouter(prefix="/platforms/reverb", tags=["reverb"])


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