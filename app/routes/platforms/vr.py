from fastapi import APIRouter, Request, BackgroundTasks
from app.services.vintageandrare_service import VintageAndRareService
from app.services.activity_logger import ActivityLogger
from app.database import async_session
from app.core.config import get_settings

router = APIRouter(prefix="/api", tags=["vr"])

@router.post("/sync/vr")
async def sync_vr(request: Request, background_tasks: BackgroundTasks):
    """Run V&R read sync - download latest inventory and update local database"""
    # Create a simple response
    response = {"status": "success", "message": "V&R sync process started"}
    
    # Run the sync task in the background
    background_tasks.add_task(
        run_vr_sync_background,
        request.app  # Pass the app object for state management
    )
    
    return response

async def run_vr_sync_background(app):
    """Background task for V&R sync process"""
    settings = get_settings()
    
    # Create our own database session
    async with async_session() as db:
        # Initialize VintageAndRare service
        vr_service = VintageAndRareService(db)
        
        # Initialize activity logger
        activity_logger = ActivityLogger(db)
        
        try:
            # Log start
            await activity_logger.log_activity(
                action="sync_start",
                entity_type="platform",
                entity_id="vr",
                platform="vr",
                details={"message": "Starting V&R inventory sync"}
            )
            await db.commit()
            
            print("Starting V&R import process through background task")
            # Run the import process
            result = await vr_service.run_import_process(
                settings.VINTAGE_AND_RARE_USERNAME,
                settings.VINTAGE_AND_RARE_PASSWORD
            )
            
            print(f"V&R import process result: {result}")
            
            # Update app state
            app.state.vr_last_sync = result.get("timestamp", None)
            
            # Log result
            if result and result.get("status") == "success":
                app.state.vr_sync_status = "SUCCESS"
                await activity_logger.log_activity(
                    action="sync",
                    entity_type="platform",
                    entity_id="vr", 
                    platform="vr",
                    details={
                        "processed": result.get("processed", 0),
                        "created": result.get("new_products", 0),
                        "updated": result.get("updated_products", 0),
                        "status_changes": result.get("status_changes", 0)
                    }
                )
            else:
                app.state.vr_sync_status = "FAILED"
                error_message = result.get("message", "Unknown error")
                print(f"V&R sync error in result: {error_message}")
                await activity_logger.log_activity(
                    action="sync_error",
                    entity_type="platform",
                    entity_id="vr",
                    platform="vr",
                    details={"error": error_message}
                )
            
            # Commit the transaction
            await db.commit()
            
        except Exception as e:
            import traceback
            error_traceback = traceback.format_exc()
            print(f"V&R sync exception: {str(e)}")
            print(f"Traceback: {error_traceback}")
            
            app.state.vr_sync_status = "FAILED"
            app.state.vr_last_error = str(e)
            
            # Try to log the error
            try:
                await activity_logger.log_activity(
                    action="sync_error",
                    entity_type="platform",
                    entity_id="vr",
                    platform="vr",
                    details={"error": str(e), "traceback": error_traceback[:500]}
                )
                await db.commit()
            except Exception:
                print("Failed to log error to activity log")