# app/routes/platforms/sync_all.py
"""
Background orchestration for running platform sync detection.

Previously this endpoint executed syncs inline, blocking FastAPI requests while
platform imports ran. The new implementation queues work in the background so
callers receive an immediate response and can poll for status while the sync
runs inside the event loop.
"""

from __future__ import annotations

import asyncio
import logging
import multiprocessing
import uuid
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Set

import httpcore
import httpx
from fastapi import APIRouter, Depends, HTTPException

from app.core.config import Settings, get_settings
from app.database import async_session
from app.routes.platforms.ebay import run_ebay_sync_background
from app.routes.platforms.reverb import run_reverb_sync_background
from app.routes.platforms.shopify import run_shopify_sync_background
from app.routes.platforms.vr import run_vr_sync_background
from app.services.websockets.manager import manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["sync"])

_active_sync_tasks: Dict[str, asyncio.Task] = {}
_sync_history: Dict[str, Dict[str, Any]] = {}


@router.post("/sync/all")
async def sync_all_platforms(
    max_concurrent: int = 2,
    platforms: Optional[str] = None,
    settings: Settings = Depends(get_settings),
):
    """Queue a platform detection run without blocking the request."""

    if not 1 <= max_concurrent <= 10:
        raise HTTPException(status_code=400, detail="max_concurrent must be between 1 and 10")

    target_platforms: Set[str] = set()
    if platforms:
        target_platforms = {p.strip().lower() for p in platforms.split(',') if p.strip()}

    run_uuid = uuid.uuid4()
    run_id = str(run_uuid)

    logger.info(
        "Queueing sync run %s (max_concurrent=%s, platforms=%s)",
        run_id,
        max_concurrent,
        target_platforms or "all",
    )

    loop = asyncio.get_running_loop()
    task = loop.create_task(
        _run_sync_all_background(
            run_uuid=run_uuid,
            run_id=run_id,
            settings=settings,
            max_concurrent=max_concurrent,
            target_platforms=target_platforms,
        )
    )

    _active_sync_tasks[run_id] = task

    def _finalize(t: asyncio.Task, sync_id: str) -> None:
        _active_sync_tasks.pop(sync_id, None)
        try:
            result = t.result()
        except Exception as exc:  # noqa: BLE001
            logger.exception("Sync run %s failed", sync_id, exc_info=exc)
            _sync_history[sync_id] = {
                "status": "error",
                "message": str(exc),
                "sync_run_id": sync_id,
                "completed_at": datetime.utcnow().isoformat(),
            }
        else:
            _sync_history[sync_id] = result

        # Keep the history bounded (retain the most recent 25 runs)
        if len(_sync_history) > 25:
            for stale_id in list(_sync_history.keys())[:-25]:
                _sync_history.pop(stale_id, None)

    task.add_done_callback(lambda t, sync_id=run_id: _finalize(t, sync_id))

    return {
        "status": "queued",
        "message": "Sync run scheduled in the background",
        "sync_run_id": run_id,
        "platform_filters": sorted(target_platforms) if target_platforms else None,
    }


@router.get("/sync/status/{sync_run_id}")
async def get_sync_status(sync_run_id: str) -> Dict[str, Any]:
    if sync_run_id in _active_sync_tasks:
        return {
            "status": "running",
            "sync_run_id": sync_run_id,
        }

    result = _sync_history.get(sync_run_id)
    if result is not None:
        return result

    raise HTTPException(status_code=404, detail="Unknown sync run id")


async def _run_sync_all_background(
    *,
    run_uuid: uuid.UUID,
    run_id: str,
    settings: Settings,
    max_concurrent: int,
    target_platforms: Set[str],
) -> Dict[str, Any]:
    logger.info(
        "Starting background sync run %s (max_concurrent=%s, platforms=%s)",
        run_id,
        max_concurrent,
        target_platforms or "all",
    )

    cpu_cores = multiprocessing.cpu_count()
    if cpu_cores < max_concurrent:
        logger.warning(
            "Concurrency %s greater than available cores %s for run %s",
            max_concurrent,
            cpu_cores,
            run_id,
        )

    available_platforms: List[tuple[str, Callable[..., Any]]] = []

    if getattr(settings, "EBAY_DEV_ID", None):
        if not target_platforms or "ebay" in target_platforms:
            available_platforms.append(("ebay", _create_ebay_sync_task))

    if getattr(settings, "REVERB_API_KEY", None):
        if not target_platforms or "reverb" in target_platforms:
            available_platforms.append(("reverb", _create_reverb_sync_task))

    if getattr(settings, "SHOPIFY_API_KEY", None):
        if not target_platforms or "shopify" in target_platforms:
            available_platforms.append(("shopify", _create_shopify_sync_task))

    if getattr(settings, "VINTAGE_AND_RARE_USERNAME", None) and getattr(settings, "VINTAGE_AND_RARE_PASSWORD", None):
        if not target_platforms or "vr" in target_platforms:
            available_platforms.append(("vr", _create_vr_sync_task))

    if not available_platforms:
        message = "No platforms available for sync"
        if target_platforms:
            message += f" (requested: {sorted(target_platforms)})"
        logger.warning("Sync run %s aborted: %s", run_id, message)
        return {
            "status": "warning",
            "message": message,
            "sync_run_id": run_id,
            "platforms_attempted": [],
            "results": {},
            "completed_at": datetime.utcnow().isoformat(),
        }

    platforms_attempted = [name for name, _ in available_platforms]
    all_results: Dict[str, Dict[str, Any]] = {}
    all_successful: List[str] = []
    all_failed: List[str] = []

    try:
        await manager.broadcast(
            {
                "type": "sync_started",
                "platform": "all",
                "sync_run_id": run_id,
                "timestamp": datetime.utcnow().isoformat(),
            }
        )

        for offset in range(0, len(available_platforms), max_concurrent):
            batch = available_platforms[offset : offset + max_concurrent]
            batch_names = [name for name, _ in batch]

            logger.info(
                "Sync run %s processing batch %s: %s",
                run_id,
                offset // max_concurrent + 1,
                batch_names,
            )

            batch_tasks = [creator(settings, run_uuid) for _, creator in batch]

            try:
                batch_results = await asyncio.gather(*batch_tasks, return_exceptions=True)
            except Exception as batch_exc:  # noqa: BLE001
                logger.exception("Batch failure in sync run %s", run_id, exc_info=batch_exc)
                for platform_name, _ in batch:
                    all_results[platform_name] = {
                        "status": "error",
                        "message": str(batch_exc),
                    }
                    all_failed.append(platform_name)
                continue

            for platform_name, result in zip(batch_names, batch_results):
                if isinstance(result, Exception):
                    logger.error(
                        "Sync run %s: %s failed with %s",
                        run_id,
                        platform_name,
                        result,
                    )
                    all_results[platform_name] = {
                        "status": "error",
                        "message": str(result),
                    }
                    all_failed.append(platform_name)
                else:
                    all_results[platform_name] = {
                        "status": "success",
                        "message": f"{platform_name} sync completed successfully",
                    }
                    all_successful.append(platform_name)

            if offset + max_concurrent < len(available_platforms):
                await asyncio.sleep(1)

        if not all_failed:
            overall_status = "success"
            overall_message = f"All {len(all_successful)} platform syncs completed successfully"
        elif not all_successful:
            overall_status = "error"
            overall_message = f"All {len(all_failed)} platform syncs failed"
        else:
            overall_status = "partial_success"
            overall_message = f"{len(all_successful)} syncs succeeded, {len(all_failed)} failed"

        if max_concurrent < len(platforms_attempted):
            overall_message += f" (batched with max_concurrent={max_concurrent})"

        payload = {
            "status": overall_status,
            "message": overall_message,
            "sync_run_id": run_id,
            "platforms_attempted": platforms_attempted,
            "results": all_results,
            "completed_at": datetime.utcnow().isoformat(),
        }

        await manager.broadcast(
            {
                "type": "sync_completed",
                "platform": "all",
                "status": overall_status,
                "sync_run_id": run_id,
                "message": overall_message,
                "timestamp": datetime.utcnow().isoformat(),
            }
        )

        logger.info("Sync run %s finished with status %s", run_id, overall_status)
        return payload

    except Exception as exc:  # noqa: BLE001
        logger.exception("Sync run %s failed", run_id, exc_info=exc)
        return {
            "status": "error",
            "message": str(exc),
            "sync_run_id": run_id,
            "platforms_attempted": platforms_attempted,
            "results": all_results,
            "completed_at": datetime.utcnow().isoformat(),
        }


async def _retry_with_backoff(
    func: Callable[[], Any],
    platform_name: str,
    max_attempts: int = 3,
    base_delay: float = 1.0,
) -> Any:
    """Retry helper for network failures with exponential backoff."""
    last_exception: Optional[Exception] = None

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
            ConnectionError,
        ) as exc:
            last_exception = exc
            if attempt < max_attempts - 1:
                delay = base_delay * (2 ** attempt)
                logger.warning(
                    "%s sync attempt %s/%s failed (%s). Retrying in %.2fs",
                    platform_name,
                    attempt + 1,
                    max_attempts,
                    exc,
                    delay,
                )
                await asyncio.sleep(delay)
            else:
                logger.error(
                    "%s sync failed after %s attempts: %s",
                    platform_name,
                    max_attempts,
                    exc,
                )
        except Exception:
            raise

    raise last_exception


async def _create_ebay_sync_task(settings: Settings, sync_run_id: uuid.UUID):
    async def ebay_sync():
        async with async_session() as db:
            return await run_ebay_sync_background(db=db, settings=settings, sync_run_id=sync_run_id)

    return await _retry_with_backoff(ebay_sync, "eBay")


async def _create_reverb_sync_task(settings: Settings, sync_run_id: uuid.UUID):
    async def reverb_sync():
        async with async_session() as db:
            return await run_reverb_sync_background(
                api_key=settings.REVERB_API_KEY,
                db=db,
                settings=settings,
                sync_run_id=sync_run_id,
            )

    return await _retry_with_backoff(reverb_sync, "Reverb")


async def _create_shopify_sync_task(settings: Settings, sync_run_id: uuid.UUID):
    async def shopify_sync():
        async with async_session() as db:
            return await run_shopify_sync_background(db=db, settings=settings, sync_run_id=sync_run_id)

    return await _retry_with_backoff(shopify_sync, "Shopify")


async def _create_vr_sync_task(settings: Settings, sync_run_id: uuid.UUID):
    async def vr_sync():
        async with async_session() as db:
            return await run_vr_sync_background(
                username=settings.VINTAGE_AND_RARE_USERNAME,
                password=settings.VINTAGE_AND_RARE_PASSWORD,
                db=db,
                sync_run_id=sync_run_id,
            )

    return await _retry_with_backoff(vr_sync, "V&R")
