"""
Scheduler management endpoints
"""

import logging
from fastapi import APIRouter, Depends, HTTPException
from typing import Dict, Any

from app.core.security import get_current_username
from app.scheduler import (
    trigger_sync_manually,
    get_scheduler_status,
    scheduler as global_scheduler
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/scheduler", tags=["scheduler"])


@router.get("/status", response_model=Dict[str, Any])
async def scheduler_status(
    current_user: str = Depends(get_current_username)
):
    """Get current scheduler status and configured jobs"""
    try:
        status = await get_scheduler_status()
        return status
    except Exception as e:
        logger.error(f"Error getting scheduler status: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/trigger-sync")
async def trigger_sync(
    current_user: str = Depends(get_current_username)
):
    """Manually trigger a sync (for testing)"""
    try:
        logger.info(f"User {current_user} manually triggered sync")
        await trigger_sync_manually()
        return {"status": "success", "message": "Sync triggered successfully"}
    except Exception as e:
        logger.error(f"Error triggering sync: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/pause")
async def pause_scheduler(
    current_user: str = Depends(get_current_username)
):
    """Pause all scheduled jobs"""
    try:
        if global_scheduler and global_scheduler.running:
            global_scheduler.pause()
            logger.info(f"Scheduler paused by {current_user}")
            return {"status": "success", "message": "Scheduler paused"}
        else:
            return {"status": "warning", "message": "Scheduler not running"}
    except Exception as e:
        logger.error(f"Error pausing scheduler: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/resume")
async def resume_scheduler(
    current_user: str = Depends(get_current_username)
):
    """Resume all scheduled jobs"""
    try:
        if global_scheduler:
            global_scheduler.resume()
            logger.info(f"Scheduler resumed by {current_user}")
            return {"status": "success", "message": "Scheduler resumed"}
        else:
            return {"status": "warning", "message": "Scheduler not initialized"}
    except Exception as e:
        logger.error(f"Error resuming scheduler: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))