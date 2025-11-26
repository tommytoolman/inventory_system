# app/routes/platforms/vr.py
import logging
import uuid
import json
import base64
import os

from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException
from app.services.vr_service import VRService
from app.services.activity_logger import ActivityLogger
from app.services.websockets.manager import manager
from app.services.vintageandrare.brand_validator import VRBrandValidator
from app.core.config import Settings, get_settings
from app.dependencies import get_db
from datetime import datetime
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# In-memory cookie cache for Railway (refreshed via harvest endpoint)
_vr_cookies_cache: list = []

router = APIRouter(prefix="/api", tags=["vr"])

@router.get("/vr/validate-brand")
async def validate_brand(brand: str):
    """
    Validate a brand name against V&R's accepted brand list.
    Returns whether the brand is valid and will be accepted by V&R.
    If invalid, the brand will default to 'Justin' when creating V&R listings.
    """
    if not brand or not brand.strip():
        return {"valid": False, "message": "Brand name is required"}
    
    # Use the V&R brand validator
    result = VRBrandValidator.validate_brand(brand.strip())
    
    return {
        "valid": result["is_valid"],
        "brand_id": result.get("brand_id"),
        "message": result.get("message", ""),
        "fallback_brand": "Justin" if not result["is_valid"] else None
    }

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
        
        vr_service = VRService(db)
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

@router.post("/vr/listings/{listing_id}/end")
async def end_vr_listing(
    listing_id: str,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings)
):
    """End (mark as sold) a V&R listing"""
    global _vr_cookies_cache

    try:
        # Initialize V&R client with cached cookies
        from app.services.vintageandrare.client import VintageAndRareClient

        vr_client = VintageAndRareClient(
            username=settings.VINTAGE_AND_RARE_USERNAME,
            password=settings.VINTAGE_AND_RARE_PASSWORD,
            db_session=db
        )

        # Load cached cookies if available (harvested from Railway's IP)
        if _vr_cookies_cache:
            logger.info(f"Loading {len(_vr_cookies_cache)} cached cookies for end_listing")
            vr_client.reload_cookies_from_list(_vr_cookies_cache)

        # Authenticate
        auth_result = await vr_client.authenticate()
        if not auth_result:
            raise HTTPException(status_code=401, detail="Failed to authenticate with V&R")

        # Mark item as sold
        result = await vr_client.mark_item_as_sold(listing_id)

        logger.info(f"V&R mark_as_sold result for listing {listing_id}: {result}")

        if result.get("success"):
            await db.execute(
                text("""
                    UPDATE platform_common pc
                    SET status = 'ended',
                        sync_status = 'SYNCED',
                        last_sync = CURRENT_TIMESTAMP
                    WHERE pc.platform_name = 'vr'
                    AND pc.external_id = :listing_id
                """),
                {"listing_id": listing_id},
            )

            await db.execute(
                text("""
                    UPDATE vr_listings
                    SET vr_state = 'ended',
                        last_synced_at = CURRENT_TIMESTAMP
                    WHERE vr_listing_id = :listing_id
                """),
                {"listing_id": listing_id},
            )

            # Log activity
            activity_logger = ActivityLogger(db)
            await activity_logger.log_activity(
                action="end_listing",
                entity_type="listing",
                entity_id=listing_id,
                platform="vr",
                details={"status": "ended", "method": "manual_ui"}
            )

            await db.commit()

            return {"success": True, "message": f"V&R listing {listing_id} marked as sold"}
        else:
            # Log the failure
            logger.warning(f"V&R mark_as_sold failed for listing {listing_id}: {result}")

            # Rollback any pending database changes
            await db.rollback()

            # Return proper error response
            error_msg = result.get("error", f"V&R returned: {result.get('response', 'Unknown error')}")
            raise HTTPException(status_code=400, detail=f"Failed to end listing: {error_msg}")

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error ending V&R listing {listing_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/vr/listings/{listing_id}/delete")
async def delete_vr_listing(
    listing_id: str,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings)
):
    """Delete a V&R listing permanently"""
    try:
        # Initialize V&R client
        from app.services.vintageandrare.client import VintageAndRareClient

        vr_client = VintageAndRareClient(
            username=settings.VINTAGE_AND_RARE_USERNAME,
            password=settings.VINTAGE_AND_RARE_PASSWORD,
            db_session=db
        )

        # Authenticate
        auth_result = await vr_client.authenticate()
        if not auth_result:
            raise HTTPException(status_code=401, detail="Failed to authenticate with V&R")

        # Delete item
        result = await vr_client.delete_item(listing_id)

        if result.get("success"):
            await db.execute(
                text("""
                    UPDATE platform_common pc
                    SET status = 'archived',
                        sync_status = 'SYNCED',
                        last_sync = CURRENT_TIMESTAMP
                    WHERE pc.platform_name = 'vr'
                    AND pc.external_id = :listing_id
                """),
                {"listing_id": listing_id},
            )

            await db.execute(
                text("""
                    UPDATE vr_listings
                    SET vr_state = 'deleted',
                        last_synced_at = CURRENT_TIMESTAMP
                    WHERE vr_listing_id = :listing_id
                """),
                {"listing_id": listing_id},
            )

            # Log activity
            activity_logger = ActivityLogger(db)
            await activity_logger.log_activity(
                action="delete_listing",
                entity_type="listing",
                entity_id=listing_id,
                platform="vr",
                details={"status": "deleted", "method": "manual_ui"}
            )

            await db.commit()

            return {"success": True, "message": f"V&R listing {listing_id} deleted"}
        else:
            error_msg = result.get("error", "Unknown error")
            raise HTTPException(status_code=400, detail=f"Failed to delete listing: {error_msg}")

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error deleting V&R listing {listing_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/vr/cookies/harvest")
async def harvest_vr_cookies(
    settings: Settings = Depends(get_settings)
):
    """
    Harvest fresh V&R cookies from Selenium Grid.

    This endpoint uses the Selenium Grid running on Railway to:
    1. Navigate to V&R
    2. Pass Cloudflare challenge (from Railway's IP)
    3. Login and get authenticated session
    4. Return cookies for use by other V&R operations

    The harvested cookies are cached in memory and used for subsequent requests.
    Call this endpoint when V&R operations start failing with 403 errors.
    """
    global _vr_cookies_cache

    try:
        from app.services.vintageandrare.client import VintageAndRareClient

        logger.info("Starting V&R cookie harvest from Selenium Grid...")

        vr_client = VintageAndRareClient(
            username=settings.VINTAGE_AND_RARE_USERNAME,
            password=settings.VINTAGE_AND_RARE_PASSWORD
        )

        # Harvest cookies via Selenium Grid
        result = await vr_client.harvest_cookies_from_grid()

        if result.get("status") == "success":
            cookies = result.get("cookies", [])

            # Cache the cookies in memory
            _vr_cookies_cache = cookies
            logger.info(f"Cached {len(cookies)} cookies in memory")

            # Also encode as base64 for display/manual backup
            cookies_json = json.dumps(cookies)
            cookies_base64 = base64.b64encode(cookies_json.encode()).decode()

            return {
                "status": "success",
                "message": f"Harvested {len(cookies)} cookies from Railway's IP",
                "cf_clearance_found": result.get("cf_clearance") is not None,
                "logged_in": result.get("logged_in", False),
                "cookie_count": len(cookies),
                "cookies_base64": cookies_base64,  # For manual backup if needed
                "hint": "Cookies are now cached. V&R operations should work."
            }
        else:
            error_msg = result.get("message", "Unknown error")
            logger.error(f"Cookie harvest failed: {error_msg}")

            return {
                "status": "error",
                "message": error_msg,
                "screenshot": result.get("screenshot"),  # Base64 screenshot if available
                "hint": "Check if Selenium Grid is running and accessible"
            }

    except Exception as e:
        logger.error(f"Cookie harvest endpoint error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/vr/cookies/status")
async def get_vr_cookies_status():
    """
    Check the status of cached V&R cookies.
    """
    global _vr_cookies_cache

    # Check env var cookies
    env_cookies_b64 = os.environ.get("VR_COOKIES_BASE64", "")
    env_cookie_count = 0
    env_cf_clearance = False

    if env_cookies_b64:
        try:
            env_cookies = json.loads(base64.b64decode(env_cookies_b64).decode())
            env_cookie_count = len(env_cookies)
            env_cf_clearance = any(c.get("name") == "cf_clearance" for c in env_cookies)
        except Exception:
            pass

    # Check memory cache
    cache_cf_clearance = any(c.get("name") == "cf_clearance" for c in _vr_cookies_cache)

    return {
        "env_cookies": {
            "count": env_cookie_count,
            "has_cf_clearance": env_cf_clearance,
            "source": "VR_COOKIES_BASE64 env var"
        },
        "cached_cookies": {
            "count": len(_vr_cookies_cache),
            "has_cf_clearance": cache_cf_clearance,
            "source": "In-memory cache (from /harvest endpoint)"
        },
        "recommendation": (
            "Call POST /api/vr/cookies/harvest to refresh cookies from Railway's IP"
            if not cache_cf_clearance
            else "Cookies are cached and ready"
        )
    }


def get_vr_client_with_cached_cookies(settings: Settings) -> "VintageAndRareClient":
    """
    Helper to create a V&R client with cached cookies loaded.
    Use this instead of creating VintageAndRareClient directly.
    """
    global _vr_cookies_cache

    from app.services.vintageandrare.client import VintageAndRareClient

    client = VintageAndRareClient(
        username=settings.VINTAGE_AND_RARE_USERNAME,
        password=settings.VINTAGE_AND_RARE_PASSWORD
    )

    # Load cached cookies if available
    if _vr_cookies_cache:
        logger.info(f"Loading {len(_vr_cookies_cache)} cached cookies into V&R client")
        client.reload_cookies_from_list(_vr_cookies_cache)

    return client