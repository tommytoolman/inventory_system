# app/routes/platforms/sync_all.py
"""
Parallel synchronization endpoint for all platforms.

This module provides a single endpoint to run all platform syncs concurrently,
focusing purely on change detection (Phase 1). Reconciliation logic is handled
separately in sync_scheduler.py.
"""

import logging
import asyncio
import uuid
import multiprocessing
from typing import Dict, Any, List, Optional, Callable
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime
import httpx
import httpcore

from app.dependencies import get_db
from app.core.config import Settings, get_settings
from app.database import async_session
from app.services.websockets.manager import manager

# Import the background task functions from platform route files
from app.routes.platforms.ebay import run_ebay_sync_background
from app.routes.platforms.reverb import run_reverb_sync_background
from app.routes.platforms.shopify import run_shopify_sync_background
from app.routes.platforms.vr import run_vr_sync_background

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["sync"])

@router.post("/sync/all")
async def sync_all_platforms(
    max_concurrent: int = 2,
    platforms: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings)
):
    """
    Run configured platform syncs with configurable concurrency for change detection only.
    
    This endpoint initiates sync operations across specified platforms with
    configurable concurrency level. Each sync performs change detection and
    logs differences to the sync_events table without making immediate DB updates.
    
    Args:
        max_concurrent: Maximum number of platforms to sync concurrently (default: 4)
        platforms: Comma-separated list of platforms to sync (default: all configured)
                  Options: ebay,reverb,shopify,vr
    
    Examples:
        POST /api/sync/all?max_concurrent=2&platforms=reverb,ebay
        POST /api/sync/all?platforms=reverb,vr
        POST /api/sync/all (syncs all platforms with max concurrency 4)
    
    Returns:
        Dict containing overall status and individual platform results
    """
    sync_run_id = uuid.uuid4()
    platforms_attempted = []
    
    try:
        logger.info(f"Initiating parallel sync with run_id: {sync_run_id}, max_concurrent: {max_concurrent}, platforms: {platforms}")
        
        # Parse platforms filter if provided
        target_platforms = set()
        if platforms:
            target_platforms = {p.strip().lower() for p in platforms.split(',') if p.strip()}
            logger.info(f"Filtering to specific platforms: {target_platforms}")
        
        # Check system resources
        cpu_cores = multiprocessing.cpu_count()
        logger.info(f"System has {cpu_cores} CPU cores available")
        
        # Validate max_concurrent parameter
        if max_concurrent < 1 or max_concurrent > 10:
            logger.warning(f"Invalid max_concurrent value {max_concurrent}, using default of 4")
            max_concurrent = 4
        
        # Warn if running on low-spec system
        if cpu_cores < max_concurrent:
            logger.warning(f"Requested concurrency ({max_concurrent}) exceeds available cores ({cpu_cores}). Consider reducing concurrency.")
        
        # Build list of available platform configurations
        available_platforms = []
        
        # eBay
        if hasattr(settings, 'EBAY_DEV_ID') and settings.EBAY_DEV_ID:
            if not target_platforms or 'ebay' in target_platforms:
                available_platforms.append(('ebay', _create_ebay_sync_task))
        
        # Reverb  
        if hasattr(settings, 'REVERB_API_KEY') and settings.REVERB_API_KEY:
            if not target_platforms or 'reverb' in target_platforms:
                available_platforms.append(('reverb', _create_reverb_sync_task))
        
        # Shopify
        if hasattr(settings, 'SHOPIFY_API_KEY') and settings.SHOPIFY_API_KEY:
            if not target_platforms or 'shopify' in target_platforms:
                available_platforms.append(('shopify', _create_shopify_sync_task))
        
        # V&R
        if (hasattr(settings, 'VINTAGE_AND_RARE_USERNAME') and settings.VINTAGE_AND_RARE_USERNAME and
            hasattr(settings, 'VINTAGE_AND_RARE_PASSWORD') and settings.VINTAGE_AND_RARE_PASSWORD):
            if not target_platforms or 'vr' in target_platforms:
                available_platforms.append(('vr', _create_vr_sync_task))
        
        if not available_platforms:
            error_msg = "No platforms available for sync"
            if target_platforms:
                error_msg += f" (requested: {target_platforms})"
            logger.warning(error_msg)
            return {
                "status": "warning",
                "message": error_msg,
                "sync_run_id": str(sync_run_id),
                "platforms_attempted": [],
                "results": {}
            }
        
        platforms_attempted = [p[0] for p in available_platforms]
        logger.info(f"Found {len(available_platforms)} available platforms: {platforms_attempted}")
        
        # Execute platforms in batches based on max_concurrent
        all_results = {}
        all_successful = []
        all_failed = []
        
        # Process platforms in batches
        for i in range(0, len(available_platforms), max_concurrent):
            batch = available_platforms[i:i + max_concurrent]
            batch_names = [p[0] for p in batch]
            
            logger.info(f"Starting batch {i//max_concurrent + 1}: {batch_names} (max_concurrent: {max_concurrent})")
            
            # Create tasks for this batch
            batch_tasks = []
            for platform_name, task_creator in batch:
                task = task_creator(settings, sync_run_id)
                batch_tasks.append(task)
                logger.info(f"{platform_name} sync added to current batch")
            
            # Execute this batch concurrently
            try:
                batch_results = await asyncio.gather(*batch_tasks, return_exceptions=True)
                
                # Process batch results
                for j, result in enumerate(batch_results):
                    platform_name = batch_names[j]
                    
                    if isinstance(result, Exception):
                        error_msg = str(result)
                        all_results[platform_name] = {
                            "status": "error",
                            "message": error_msg
                        }
                        all_failed.append(platform_name)
                        logger.error(f"{platform_name} sync failed with exception: {error_msg}")
                    else:
                        all_results[platform_name] = {
                            "status": "success", 
                            "message": f"{platform_name} sync completed successfully"
                        }
                        all_successful.append(platform_name)
                        logger.info(f"{platform_name} sync completed successfully")
                
                # Small delay between batches if there are more batches
                if i + max_concurrent < len(available_platforms):
                    logger.info("Waiting 1 second before starting next batch...")
                    await asyncio.sleep(1)
                    
            except Exception as e:
                # Unexpected error in the gather operation for this batch
                error_msg = f"Critical error during batch {i//max_concurrent + 1} execution: {str(e)}"
                logger.exception(error_msg)
                
                # Mark all platforms in this batch as failed
                for platform_name, _ in batch:
                    all_results[platform_name] = {
                        "status": "error",
                        "message": error_msg
                    }
                    all_failed.append(platform_name)
        
        # Determine overall status
        if len(all_failed) == 0:
            overall_status = "success"
            overall_message = f"All {len(all_successful)} platform syncs completed successfully"
        elif len(all_successful) == 0:
            overall_status = "error"
            overall_message = f"All {len(all_failed)} platform syncs failed"
        else:
            overall_status = "partial_success"
            overall_message = f"{len(all_successful)} syncs succeeded, {len(all_failed)} failed"
        
        if max_concurrent < len(platforms_attempted):
            overall_message += f" (batched with max_concurrent={max_concurrent})"
        
        logger.info(f"Parallel sync complete. {overall_message}")
        
        # Send final WebSocket notification to trigger dashboard refresh
        await manager.broadcast({
            "type": "sync_all_completed",
            "status": overall_status,
            "message": overall_message,
            "sync_run_id": str(sync_run_id),
            "successful_platforms": all_successful,
            "failed_platforms": all_failed,
            "max_concurrent": max_concurrent,
            "total_platforms": len(platforms_attempted),
            "timestamp": datetime.now().isoformat()
        })
        
        return {
            "status": overall_status,
            "message": overall_message,
            "sync_run_id": str(sync_run_id),
            "platforms_attempted": platforms_attempted,
            "successful_platforms": all_successful,
            "failed_platforms": all_failed,
            "max_concurrent": max_concurrent,
            "batched_execution": max_concurrent < len(platforms_attempted),
            "results": all_results
        }

    except Exception as e:
        # Unexpected error in the overall sync process
        error_msg = f"Critical error during sync execution: {str(e)}"
        logger.exception(error_msg)
        
        return {
            "status": "error",
            "message": error_msg,
            "sync_run_id": str(sync_run_id),
            "platforms_attempted": platforms_attempted,
            "max_concurrent": max_concurrent,
            "results": {}
        }


# Helper functions to create sync tasks with retry logic
async def _retry_with_backoff(
    func: Callable,
    platform_name: str,
    max_attempts: int = 3,
    base_delay: float = 1.0
) -> Any:
    """
    Retry a function with exponential backoff for network errors only.
    
    Args:
        func: Async function to retry
        platform_name: Name of platform for logging
        max_attempts: Maximum number of retry attempts
        base_delay: Base delay in seconds (will be doubled each retry)
        
    Returns:
        Result of the function call
        
    Raises:
        The last exception if all retries fail
    """
    last_exception = None
    
    for attempt in range(max_attempts):
        try:
            return await func()
        except (
            httpx.ConnectTimeout,
            httpx.ReadTimeout, 
            httpx.NetworkError,
            httpcore.ConnectTimeout,
            httpcore.ReadTimeout,
            httpcore.NetworkError,
            ConnectionError
        ) as e:
            last_exception = e
            if attempt < max_attempts - 1:  # Don't sleep on the last attempt
                delay = base_delay * (2 ** attempt)  # Exponential backoff: 1s, 2s, 4s
                logger.warning(
                    f"{platform_name} sync failed on attempt {attempt + 1}/{max_attempts} "
                    f"due to network error: {str(e)}. Retrying in {delay}s..."
                )
                await asyncio.sleep(delay)
            else:
                logger.error(
                    f"{platform_name} sync failed on all {max_attempts} attempts "
                    f"due to network errors. Final error: {str(e)}"
                )
        except Exception as e:
            # For non-network errors, don't retry - fail immediately
            logger.error(f"{platform_name} sync failed with non-retryable error: {str(e)}")
            raise e
    
    # If we get here, all retries failed with network errors
    raise last_exception

async def _create_ebay_sync_task(settings: Settings, sync_run_id: uuid.UUID):
    """Create eBay sync task with fresh database session and retry logic"""
    async def ebay_sync():
        async with async_session() as db:
            return await run_ebay_sync_background(db=db, settings=settings, sync_run_id=sync_run_id)
    
    return await _retry_with_backoff(ebay_sync, "eBay")

async def _create_reverb_sync_task(settings: Settings, sync_run_id: uuid.UUID):
    """Create Reverb sync task with fresh database session and retry logic"""
    async def reverb_sync():
        async with async_session() as db:
            return await run_reverb_sync_background(
                api_key=settings.REVERB_API_KEY,
                db=db,
                settings=settings,
                sync_run_id=sync_run_id
            )
    
    return await _retry_with_backoff(reverb_sync, "Reverb")

async def _create_shopify_sync_task(settings: Settings, sync_run_id: uuid.UUID):
    """Create Shopify sync task with fresh database session and retry logic"""
    async def shopify_sync():
        async with async_session() as db:
            return await run_shopify_sync_background(db=db, settings=settings, sync_run_id=sync_run_id)
    
    return await _retry_with_backoff(shopify_sync, "Shopify")

async def _create_vr_sync_task(settings: Settings, sync_run_id: uuid.UUID):
    """Create V&R sync task with fresh database session and retry logic"""
    async def vr_sync():
        async with async_session() as db:
            return await run_vr_sync_background(
                username=settings.VINTAGE_AND_RARE_USERNAME,
                password=settings.VINTAGE_AND_RARE_PASSWORD,
                db=db,
                sync_run_id=sync_run_id
            )
    
    return await _retry_with_backoff(vr_sync, "V&R")