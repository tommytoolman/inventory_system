# app/routes/sync_scheduler.py
import logging
import asyncio
import uuid
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.core.config import Settings, get_settings
from app.services.sync_services import SyncService

# Import the specific background task functions from your platform route files
# Make sure these functions are defined at the module level in those files so they can be imported.
from app.routes.platforms.ebay import run_ebay_sync_background
from app.routes.platforms.reverb import run_reverb_sync_background
from app.routes.platforms.vr import run_vr_sync_background
# from app.routes.platforms.website import run_website_sync_background # If you have one for the website

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/sync", tags=["Synchronization Actions"]) # Grouping under /api/sync

@router.post("/all") # Will result in endpoint /api/sync/all
async def sync_all_platforms_and_reconcile(
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings)
):
    """
    Phase 1: Run all platform syncs concurrently to detect changes.
    Phase 2: After all syncs are complete, run reconciliation.
    """
    sync_run_id = uuid.uuid4()
    logger.info(f"Initiating full sync run with ID: {sync_run_id}")

    # --- Phase 1: Run all platform syncs concurrently ---
    sync_tasks = []

    # NOTE: The background functions (e.g., run_vr_sync_background) must be updated
    # to accept the `sync_run_id`.

    # Vintage & Rare Sync
    if settings.VINTAGE_AND_RARE_USERNAME and settings.VINTAGE_AND_RARE_PASSWORD:
        # We pass the sync_run_id to the background task
        task = run_vr_sync_background(
            settings.VINTAGE_AND_RARE_USERNAME,
            settings.VINTAGE_AND_RARE_PASSWORD,
            db,
            sync_run_id  # Pass the run ID
        )
        sync_tasks.append(task)
        logger.info("V&R sync added to concurrent tasks.")

    # Reverb Sync
    if settings.REVERB_API_KEY:
        # task = run_reverb_sync_background(settings.REVERB_API_KEY, db, settings, sync_run_id)
        # sync_tasks.append(task)
        logger.info("Reverb sync added to concurrent tasks (placeholder).")
 
    # eBay Sync
    if settings.EBAY_APP_ID: # Check if eBay is configured
        task = run_ebay_sync_background(db=db, settings=settings, sync_run_id=sync_run_id)
        sync_tasks.append(task)
        logger.info("eBay sync added to concurrent tasks.")

    # This will run all tasks in `sync_tasks` concurrently and wait for them all to finish.
    # `return_exceptions=True` ensures that one failed sync doesn't stop the others.
    phase1_results = await asyncio.gather(*sync_tasks, return_exceptions=True)
    logger.info(f"Phase 1 (Detection) complete for sync run {sync_run_id}. Results: {phase1_results}")

    # --- Phase 2: Reconcile all detected changes for this run ---
    # This part runs *after* all the above tasks are complete.
    logger.info(f"Starting Phase 2 (Reconciliation) for sync run {sync_run_id}.")
    sync_service = SyncService(db)
    reconciliation_report = await sync_service.reconcile_sync_run(sync_run_id)

    return {
        "status": "success",
        "message": "Full sync and reconciliation process complete.",
        "sync_run_id": sync_run_id,
        "reconciliation_report": reconciliation_report
    }