# app/routes/platforms/vr.py
import logging

from fastapi import APIRouter, Request, Depends, BackgroundTasks
from app.services.vintageandrare_service import VintageAndRareService
from app.services.activity_logger import ActivityLogger
from app.services.websockets.manager import manager
from app.database import async_session
from app.core.config import Settings, get_settings
from app.dependencies import get_db
from datetime import datetime
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["vr"])

@router.post("/sync/vr")
async def sync_vr(
    background_tasks: BackgroundTasks,  # Add this import and parameter
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings)
):
    """Run V&R read sync - download latest inventory and update local database"""
    background_tasks.add_task(
        run_vr_sync_background,
        settings.VINTAGE_AND_RARE_USERNAME,  # Pass username
        settings.VINTAGE_AND_RARE_PASSWORD,  # Pass password  
        db                                   # Pass db session
    )
    return {"status": "success", "message": "V&R sync started"}

# Old method pre-websocket
# async def run_vr_sync_background(app):
#     """Background task for V&R sync process"""
#     settings = get_settings()
    
#     # Create our own database session
#     async with async_session() as db:
#         # Initialize VintageAndRare service
#         vr_service = VintageAndRareService(db)
        
#         # Initialize activity logger
#         activity_logger = ActivityLogger(db)
        
#         try:
#             # Log start
#             await activity_logger.log_activity(
#                 action="sync_start",
#                 entity_type="platform",
#                 entity_id="vr",
#                 platform="vr",
#                 details={"message": "Starting V&R inventory sync"}
#             )
#             await db.commit()
            
#             print("Starting V&R import process through background task")
#             # Run the import process
#             result = await vr_service.run_import_process(
#                 settings.VINTAGE_AND_RARE_USERNAME,
#                 settings.VINTAGE_AND_RARE_PASSWORD
#             )
            
#             print(f"V&R import process result: {result}")
            
#             # Update app state
#             app.state.vr_last_sync = result.get("timestamp", None)
            
#             # Log result
#             if result and result.get("status") == "success":
#                 app.state.vr_sync_status = "SUCCESS"
#                 await activity_logger.log_activity(
#                     action="sync",
#                     entity_type="platform",
#                     entity_id="vr", 
#                     platform="vr",
#                     details={
#                         "processed": result.get("processed", 0),
#                         "created": result.get("new_products", 0),
#                         "updated": result.get("updated_products", 0),
#                         "status_changes": result.get("status_changes", 0)
#                     }
#                 )
#             else:
#                 app.state.vr_sync_status = "FAILED"
#                 error_message = result.get("message", "Unknown error")
#                 print(f"V&R sync error in result: {error_message}")
#                 await activity_logger.log_activity(
#                     action="sync_error",
#                     entity_type="platform",
#                     entity_id="vr",
#                     platform="vr",
#                     details={"error": error_message}
#                 )
            
#             # Commit the transaction
#             await db.commit()
            
#         except Exception as e:
#             import traceback
#             error_traceback = traceback.format_exc()
#             print(f"V&R sync exception: {str(e)}")
#             print(f"Traceback: {error_traceback}")
            
#             app.state.vr_sync_status = "FAILED"
#             app.state.vr_last_error = str(e)
            
#             # Try to log the error
#             try:
#                 await activity_logger.log_activity(
#                     action="sync_error",
#                     entity_type="platform",
#                     entity_id="vr",
#                     platform="vr",
#                     details={"error": str(e), "traceback": error_traceback[:500]}
#                 )
#                 await db.commit()
#             except Exception:
#                 print("Failed to log error to activity log")
                
async def run_vr_sync_background(username: str, password: str, db: AsyncSession):
    """Run V&R sync in background with WebSocket updates"""
    logger.info("Starting V&R import process through background task")
    
    # Add activity logger
    from app.services.activity_logger import ActivityLogger
    activity_logger = ActivityLogger(db)
    
    try:
        # Log sync start
        await activity_logger.log_activity(
            action="sync_start",
            entity_type="platform",
            entity_id="vr",
            platform="vr",
            details={"status": "started"}
        )
        
        # Send start notification
        await manager.broadcast({
            "type": "sync_started",
            "platform": "vr",
            "timestamp": datetime.now().isoformat()
        })
        
        vr_service = VintageAndRareService(db)
        result = await vr_service.run_import_process(username, password, save_only=False)
        
        if result.get('status') == 'success':
            # ADD THIS: Update last_sync timestamp for V&R platform entries
            update_query = text("""
                UPDATE platform_common 
                SET last_sync = timezone('utc', now()),
                    sync_status = 'SYNCED'
                WHERE platform_name = 'vr'
            """)
            await db.execute(update_query)
            
            # Log successful sync
            await activity_logger.log_activity(
                action="sync",
                entity_type="platform", 
                entity_id="vr",
                platform="vr",
                details={
                    "status": "success",
                    "processed": result.get('processed', 0),
                    "updated": result.get('updated_products', 0),
                    "errors": result.get('errors', 0),
                    "icon": "✅",  # Add icon to details
                    "message": f"Synced VR ({result.get('processed', 0)} items)"
                }
            )
            
            # Send success notification
            await manager.broadcast({
                "type": "sync_completed",
                "platform": "vr",
                "status": "success",
                "data": result,
                "timestamp": datetime.now().isoformat()
            })
            logger.info(f"V&R import process result: {result}")
        else:
            # Log failed sync
            await activity_logger.log_activity(
                action="sync_error",
                entity_type="platform",
                entity_id="vr", 
                platform="vr",
                details={"error": result.get('message', 'Unknown error')}
            )
            
            # Send error notification
            await manager.broadcast({
                "type": "sync_completed",
                "platform": "vr",
                "status": "error",
                "message": result.get('message', 'Unknown error'),
                "timestamp": datetime.now().isoformat()
            })
            logger.error(f"V&R sync error in result: {result.get('message', 'Unknown error')}")

        # Commit the activity logging
        await db.commit()
            
    except Exception as e:
        await db.rollback()
        error_message = str(e)
        logger.exception(f"V&R sync background task failed: {error_message}")
        
        # Log exception
        await activity_logger.log_activity(
            action="sync_error",
            entity_type="platform",
            entity_id="vr",
            platform="vr", 
            details={"error": error_message}
        )
        await db.commit()
        
        # Send error notification
        await manager.broadcast({
            "type": "sync_completed",
            "platform": "vr",
            "status": "error",
            "message": error_message,
            "timestamp": datetime.now().isoformat()
        })