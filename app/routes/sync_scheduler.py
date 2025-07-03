# app/routes/sync_scheduler.py
import logging
from fastapi import APIRouter, Depends, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.core.config import Settings, get_settings

# Import the specific background task functions from your platform route files
# Make sure these functions are defined at the module level in those files so they can be imported.
from app.routes.platforms.ebay import run_ebay_sync_background
from app.routes.platforms.reverb import run_reverb_sync_background
from app.routes.platforms.vr import run_vr_sync_background
# from app.routes.platforms.website import run_website_sync_background # If you have one for the website

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/sync", tags=["Synchronization Actions"]) # Grouping under /api/sync

@router.post("/all") # Will result in endpoint /api/sync/all
async def sync_all_platforms_endpoint( # Renamed to avoid conflict if imported elsewhere
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings)
):
    logger.info("Received API request to sync all platforms.")

    # eBay Sync
    background_tasks.add_task(run_ebay_sync_background, db, settings)
    logger.info("eBay sync (from platform) added to background tasks.")

    # Reverb Sync
    # run_reverb_sync_background requires: api_key: str, db: AsyncSession, settings: Settings
    if settings.REVERB_API_KEY:
        background_tasks.add_task(run_reverb_sync_background, settings.REVERB_API_KEY, db, settings)
        logger.info("Reverb sync (from platform) added to background tasks.")
    else:
        logger.warning("Reverb API key not configured. Skipping Reverb sync.")

    # Vintage & Rare Sync
    # run_vr_sync_background requires: username: str, password: str, db: AsyncSession
    if settings.VINTAGE_AND_RARE_USERNAME and settings.VINTAGE_AND_RARE_PASSWORD:
        background_tasks.add_task(
            run_vr_sync_background,
            settings.VINTAGE_AND_RARE_USERNAME,
            settings.VINTAGE_AND_RARE_PASSWORD,
            db
        )
        logger.info("Vintage & Rare sync (from platform) added to background tasks.")
    else:
        logger.warning("Vintage & Rare credentials not configured. Skipping V&R sync.")

    # Shopify Sync (if applicable)
    # Example:
    # if hasattr(settings, 'WEBSITE_API_KEY'): # Check if website sync is configured
    #     try:
    #         from app.routes.platforms.website import run_website_sync_background # Ensure this exists
    #         background_tasks.add_task(run_website_sync_background, db, settings) # Adjust params
    #         logger.info("Shopify sync (from platform) added to background tasks.")
    #     except ImportError:
    #         logger.warning("run_website_sync_background not found. Skipping Shopify sync.")
    # else:
    #     logger.warning("Shopify sync not configured. Skipping Shopify sync.")

    return {"status": "success", "message": "All configured platform syncs have been initiated."}