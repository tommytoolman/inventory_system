import logging
import json
import asyncio
import uuid

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
    settings: Settings = Depends(get_settings) # Resolve settings here
):
    """Endpoint to trigger a standalone eBay sync, which generates its own run ID."""
    sync_run_id = uuid.uuid4()
    logger.info(f"Initiating standalone eBay sync with run_id: {sync_run_id}")
    background_tasks.add_task(
        run_ebay_sync_background,
        db=db,
        settings=settings, # Pass the concrete settings object
        sync_run_id=sync_run_id,
    )
    return {"status": "success", "message": "eBay sync started", "sync_run_id": sync_run_id}

# Add this background task function
async def run_ebay_sync_background(db: AsyncSession, settings: Settings, sync_run_id: uuid.UUID):
    """Run eBay sync in background with WebSocket updates"""
    logger.info(f"Background eBay sync started for run_id: {sync_run_id}.")
    
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
        
        # Run the new import process, passing the sync_run_id
        # The progress callback is no longer part of this simplified flow.
        # We can add a more robust progress system later if needed.
        result = await ebay_service.run_import_process(sync_run_id=sync_run_id)
        
        if result.get('api_errors', 0) == 0: # Primary check for API-level success
            # Update last_sync timestamp for eBay platform entries
            update_query = text("""
                UPDATE platform_common 
                SET last_sync = timezone('utc', now()),
                    sync_status = 'SYNCED'
                WHERE platform_name = 'ebay'
            """)
            await db.execute(update_query)
            
            # Log successful sync (or sync with details if there were partial errors)
            total_api_items = result.get('total_api_items', 0)
            processed_db_items = result.get('processed_db_items', 0)
            created_db = result.get('created_db', 0)
            updated_db = result.get('updated_db', 0)
            marked_sold_db = result.get('marked_sold_db', 0)
            db_errors = result.get('db_errors', 0)
            api_errors = result.get('api_errors', 0) # Already checked above, but good to have for logging

            # Determine overall status message based on errors
            log_status_message = "success"
            icon = "✅"
            if db_errors > 0 or api_errors > 0: # If there were any errors at all
                log_status_message = f"completed with {db_errors + api_errors} errors"
                icon = "⚠️" # Use a warning icon if there were errors but we are still in this "success" block of the route

            activity_log_message_str = (
                f"Synced eBay. API Items: {total_api_items}, "
                f"DB Processed: {processed_db_items} (Created: {created_db}, Updated: {updated_db}, Sold: {marked_sold_db}). "
                f"DB Errors: {db_errors}, API Errors: {api_errors}"
            )

            await activity_logger.log_activity(
                action="sync", # Consider changing action if errors occurred, e.g., "sync_completed_with_issues"
                entity_type="platform", 
                entity_id="ebay",
                platform="ebay",
                details={
                    "status": log_status_message,
                    "total_api_items": total_api_items,
                    "processed_db_items": processed_db_items,
                    "created_db": created_db,
                    "updated_db": updated_db,
                    "marked_sold_db": marked_sold_db,
                    "db_errors": db_errors,
                    "api_errors": api_errors,
                    "icon": icon,
                    "message": activity_log_message_str
                }
            )
            
            # Send success notification (status reflects if there were any DB errors)
            websocket_status = "success"
            if result.get('db_errors', 0) > 0 or result.get('api_errors', 0) > 0: # Check both from the service result
                websocket_status = "error" # Or "success_with_issues" if your frontend can handle it

            await manager.broadcast({
                "type": "sync_completed",
                "platform": "ebay",
                "status": websocket_status, # More accurate status
                "data": result, # This is the detailed dict from ebay_service.py
                "message": activity_log_message_str, # Send the detailed message too
                "timestamp": datetime.now().isoformat()
            })
            
            logger.info(f"eBay import process result: {result}")
        
        else: # This 'else' corresponds to your 'if result.get('api_errors', 0) == 0:' condition
            # This block now means there were API errors or other critical failures identified by the service
            # which prevented the main "success" path.
            
            # Try to get a specific message if the service provided one,
            # otherwise create a generic one.
            error_message_from_service = "eBay sync failed with API errors or other critical issues."
            if result and isinstance(result, dict): # Ensure result is a dict
                if result.get('message'): # If service explicitly provides a top-level error message
                    error_message_from_service = result.get('message')
                else: # Construct from error counts
                    api_errors = result.get('api_errors', 0)
                    db_errors = result.get('db_errors', 0)
                    if api_errors > 0 or db_errors > 0:
                        error_message_from_service = f"eBay sync failed. API Errors: {api_errors}, DB Errors: {db_errors}."
                    # else: result might be an empty dict or unexpected structure if service failed badly
            
            logger.error(f"eBay sync failed or completed with significant errors: {error_message_from_service}. Full result: {result}")

            await activity_logger.log_activity(
                action="sync_error",
                entity_type="platform",
                entity_id="ebay",
                platform="ebay",
                details={"error": error_message_from_service, "full_result_summary": str(result)[:500]} # Log summary of result
            )
            
            await manager.broadcast({
                "type": "sync_completed",
                "platform": "ebay",
                "status": "error",
                "message": error_message_from_service,
                "data": result, # Send the result from service for debugging on client if needed
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

@router.post("/ebay/listings/{listing_id}/end")
async def end_ebay_listing(
    listing_id: str,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings)
):
    """End an eBay listing"""
    try:
        # Initialize eBay service
        ebay_service = EbayService(db, settings)

        # End the listing on eBay
        success = await ebay_service.mark_item_as_sold(listing_id)

        if success:
            # Update local database status
            query = text("""
                UPDATE platform_common pc
                SET status = 'ENDED',
                    last_sync = CURRENT_TIMESTAMP
                WHERE pc.platform_name = 'ebay'
                AND pc.external_id = :listing_id
            """)
            await db.execute(query, {"listing_id": listing_id})

            # Log activity
            activity_logger = ActivityLogger(db)
            await activity_logger.log_activity(
                action="end_listing",
                entity_type="listing",
                entity_id=listing_id,
                platform="ebay",
                details={"status": "ended", "reason": "NotAvailable", "method": "manual_ui"}
            )

            await db.commit()

            return {"success": True, "message": f"eBay listing {listing_id} ended successfully"}
        else:
            raise HTTPException(status_code=400, detail="Failed to end listing on eBay")

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error ending eBay listing {listing_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

