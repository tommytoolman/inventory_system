# app/routes/platforms/vr.py
import logging
import uuid

from fastapi import APIRouter, Request, Depends, BackgroundTasks, HTTPException
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
    sync_run_id = uuid.uuid4()
    logger.info(f"Initiating standalone V&R sync with run_id: {sync_run_id}")
    background_tasks.add_task(
        run_vr_sync_background,
        settings.VINTAGE_AND_RARE_USERNAME,     # Pass username
        settings.VINTAGE_AND_RARE_PASSWORD,     # Pass password  
        db,                                     # Pass db session
        sync_run_id                             # Pass the newly generated sync_run_id
    )
    return {"status": "success", "message": "V&R sync started", "sync_run_id": sync_run_id}

                
async def run_vr_sync_background(username: str, password: str, db: AsyncSession, sync_run_id: uuid.UUID):
    """
    Background task to run the full V&R import and sync process.
    This is designed to be called by the central sync scheduler."""
    logger.info("Starting V&R import process through background task")
    
    # Add activity logger
    activity_logger = ActivityLogger(db)
    
    try:
        # Log sync start - wrap in try/catch
        try:
            await activity_logger.log_activity(
                action="sync_start",
                entity_type="platform",
                entity_id="vr",
                platform="vr",
                details={"status": "started"}
            )
    
        except Exception as log_error:
            logger.warning(f"Failed to log activity start: {log_error}")
            # Don't fail the sync due to logging issues
    
        # Send start notification
        await manager.broadcast({
            "type": "sync_started",
            "platform": "vr",
            "timestamp": datetime.now().isoformat()
        })
        
        vr_service = VintageAndRareService(db)
        result = await vr_service.run_import_process(username, password, sync_run_id, save_only=False)
        
        if result.get('status') == 'success':
            # ADD THIS: Update last_sync timestamp for V&R platform entries
            update_query = text("""
                UPDATE platform_common 
                SET last_sync = timezone('utc', now()),
                    sync_status = 'SYNCED'
                WHERE platform_name = 'vr'
            """)
            await db.execute(update_query)
            
            # Log successful sync with error handling
            try:
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
            except Exception as log_error:
                logger.warning(f"Failed to log activity success: {log_error}")
            
            
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
            # Log failed sync with error handling
            try:
                await activity_logger.log_activity(
                    action="sync_error",
                    entity_type="platform",
                    entity_id="vr", 
                    platform="vr",
                    details={"error": result.get('message', 'Unknown error')}
                )
            except Exception as log_error:
                logger.warning(f"Failed to log activity error: {log_error}")
            
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
        
        # Log exception with error handling
        try:
            await activity_logger.log_activity(
                action="sync_error",
                entity_type="platform",
                entity_id="vr",
                platform="vr", 
                details={"error": error_message}
            )
            await db.commit()
        except Exception as log_error:
            logger.warning(f"Failed to log exception: {log_error}")
            await db.rollback()
        
        # Send error notification
        await manager.broadcast({
            "type": "sync_completed",
            "platform": "vr",
            "status": "error",
            "message": error_message,
            "timestamp": datetime.now().isoformat()
        })