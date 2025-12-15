import asyncio
import logging
import os
import signal
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import async_session
from app.models.product import Product
from app.services.vintageandrare.brand_validator import VRBrandValidator
from app.services.vintageandrare.client import VintageAndRareClient
from app.services.vintageandrare.constants import DEFAULT_VR_BRAND
from app.services.vr_job_queue import (
    count_pending_resolutions,
    fetch_next_queued_job,
    fetch_pending_resolution_jobs,
    increment_resolution_attempts,
    mark_job_completed,
    mark_job_failed,
    mark_job_in_progress,
    mark_job_pending_id,
    peek_queue_count,
)
from app.services.vr_service import VRService

logger = logging.getLogger("vr_worker")
logging.basicConfig(
    level=os.environ.get("VR_WORKER_LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)

POLL_INTERVAL = float(os.environ.get("VR_WORKER_POLL_INTERVAL", "5"))
MAX_BATCH_SIZE = int(os.environ.get("VR_MAX_BATCH_SIZE", "10"))
MAX_RESOLUTION_ATTEMPTS = int(os.environ.get("VR_MAX_RESOLUTION_ATTEMPTS", "3"))

# Graceful shutdown flag
_shutdown_requested = False
_current_job_id: Optional[int] = None


def _handle_signal(*_: Any) -> None:
    global _shutdown_requested
    if _shutdown_requested:
        # Second signal = force exit
        logger.warning("Forced shutdown requested")
        raise SystemExit(1)
    _shutdown_requested = True
    logger.info("Shutdown requested - will exit after current work completes")


for sig in (signal.SIGINT, signal.SIGTERM):
    signal.signal(sig, _handle_signal)


async def _process_job(session: AsyncSession, job, skip_id_resolution: bool = False) -> Dict[str, Any]:
    """
    Process a VR job - create listing via Selenium.

    Args:
        session: Database session
        job: VRJob to process
        skip_id_resolution: If True, skip CSV download (for batched processing)

    Returns:
        Result dict from VRService including match_criteria if skip_id_resolution=True
    """
    payload: Dict[str, Any] = job.payload or {}
    sync_source = payload.get("sync_source", "unknown")
    product = await session.get(
        Product,
        job.product_id,
        options=[selectinload(Product.shipping_profile)],
    )
    if not product:
        raise RuntimeError(f"Product {job.product_id} no longer exists")

    reverb_data = payload.get("enriched_data") or payload.get("reverb_data") or {}
    platform_options: Dict[str, Any] = {}
    if isinstance(payload.get("platform_options"), dict):
        platform_options = payload["platform_options"].copy()

    override_price = payload.get("override_price")
    if override_price is not None:
        platform_options = platform_options.copy()
        platform_options.setdefault("price", override_price)

    use_fallback = bool(payload.get("use_fallback_brand"))
    brand_for_validation = product.brand or DEFAULT_VR_BRAND

    logger.info(
        "Processing V&R job %s for product %s (source=%s, fallback=%s, skip_id=%s)",
        job.id,
        product.sku,
        sync_source,
        use_fallback,
        skip_id_resolution,
    )

    if not use_fallback:
        validation = VRBrandValidator.validate_brand(brand_for_validation)
        error_code = validation.get("error_code")
        if error_code in {"network", "unexpected", "unexpected_response"}:
            raise RuntimeError(
                f"Vintage & Rare brand validation unavailable (error={error_code})"
            )
        if not validation.get("is_valid"):
            raise RuntimeError(
                f"Brand '{product.brand}' is not recognized by Vintage & Rare. "
                "List via inventory detail page with fallback enabled."
            )
    else:
        logger.info(
            "Using fallback brand '%s' for product %s",
            DEFAULT_VR_BRAND,
            product.sku,
        )

    original_brand: Optional[str] = product.brand
    brand_overridden = False
    if use_fallback or not product.brand:
        product.brand = DEFAULT_VR_BRAND
        brand_overridden = True

    vr_service = VRService(session)
    try:
        result = await vr_service.create_listing_from_product(
            product=product,
            reverb_data=reverb_data,
            platform_options=platform_options,
            skip_id_resolution=skip_id_resolution,
        )
    finally:
        if brand_overridden:
            product.brand = original_brand

    if not isinstance(result, dict):
        raise RuntimeError("Unexpected V&R response format")

    if result.get("status") != "success":
        raise RuntimeError(result.get("message", "Vintage & Rare listing failed"))

    logger.info(
        "V&R job %s listing created: skip_id=%s, has_match_criteria=%s",
        job.id,
        skip_id_resolution,
        "match_criteria" in result,
    )

    return result


async def _resolve_pending_batch(session: AsyncSession) -> None:
    """
    Resolve V&R IDs for all pending jobs using a single CSV download.
    """
    pending_jobs = await fetch_pending_resolution_jobs(session)
    if not pending_jobs:
        return

    logger.info(f"🔄 Starting batch resolution for {len(pending_jobs)} pending jobs...")

    # Prepare pending items for batch resolution
    pending_items: List[Dict[str, Any]] = []
    for job in pending_jobs:
        payload = job.payload or {}
        match_criteria = payload.get("match_criteria", {})

        if not match_criteria:
            logger.warning(f"Job {job.id} has no match_criteria, skipping")
            continue

        pending_items.append({
            "job_id": job.id,
            "product_id": job.product_id,
            "match_criteria": match_criteria,
            "submission_payload": payload.get("submission_payload"),
        })

    if not pending_items:
        logger.info("No valid pending items to resolve")
        return

    # Create VR client and resolve batch
    username = os.environ.get("VINTAGE_AND_RARE_USERNAME")
    password = os.environ.get("VINTAGE_AND_RARE_PASSWORD")

    if not username or not password:
        logger.error("Missing V&R credentials - cannot resolve batch")
        return

    client = VintageAndRareClient(username, password)

    try:
        results = await client.resolve_vr_ids_batch(session, pending_items)

        # Update job statuses based on results
        for resolved in results.get("resolved", []):
            job_id = resolved["job_id"]
            vr_id = resolved["vr_id"]

            # Find the job and mark completed
            for job in pending_jobs:
                if job.id == job_id:
                    # Update payload with resolved ID
                    payload = job.payload or {}
                    payload["vr_listing_id"] = vr_id
                    payload["resolution_complete"] = True
                    job.payload = payload

                    await mark_job_completed(session, job)
                    logger.info(f"✅ Job {job_id} resolved with V&R ID {vr_id}")
                    break

        for failed in results.get("failed", []):
            job_id = failed["job_id"]
            error = failed["error"]

            for job in pending_jobs:
                if job.id == job_id:
                    await increment_resolution_attempts(session, job)
                    attempts = (job.payload or {}).get("resolution_attempts", 1)

                    if attempts >= MAX_RESOLUTION_ATTEMPTS:
                        await mark_job_failed(session, job, f"Resolution failed after {attempts} attempts: {error}")
                        logger.error(f"❌ Job {job_id} failed permanently: {error}")
                    else:
                        logger.warning(f"⚠️ Job {job_id} resolution failed (attempt {attempts}): {error}")
                    break

        await session.commit()
        logger.info(f"🏁 Batch resolution complete: {len(results.get('resolved', []))} resolved, {len(results.get('failed', []))} failed")

    except Exception as e:
        logger.error(f"❌ Batch resolution error: {str(e)}")
        await session.rollback()


async def _should_resolve_now(session: AsyncSession) -> bool:
    """
    Determine if we should run batch resolution now.

    Returns True if:
    - Queue is empty (no more jobs to create), OR
    - Pending count >= MAX_BATCH_SIZE
    """
    pending_count = await count_pending_resolutions(session)
    if pending_count == 0:
        return False

    queue_count = await peek_queue_count(session)

    if queue_count == 0:
        logger.info(f"Queue empty with {pending_count} pending - triggering resolution")
        return True

    if pending_count >= MAX_BATCH_SIZE:
        logger.info(f"Max batch size reached ({pending_count} >= {MAX_BATCH_SIZE}) - triggering resolution")
        return True

    logger.debug(f"Not resolving yet: {queue_count} queued, {pending_count} pending")
    return False


async def worker_loop() -> None:
    global _current_job_id

    while not _shutdown_requested:
        job_processed = False
        async with async_session() as session:
            job = await fetch_next_queued_job(session)

            if not job:
                # No jobs queued - check for pending resolutions
                pending_count = await count_pending_resolutions(session)
                if pending_count > 0:
                    logger.info(f"No queued jobs, resolving {pending_count} pending...")
                    await _resolve_pending_batch(session)
                job_processed = False
            else:
                _current_job_id = job.id

                # Mark job in progress
                try:
                    await mark_job_in_progress(session, job)
                    await session.commit()
                except Exception as exc:
                    await session.rollback()
                    logger.error("Failed to mark job %s in progress: %s", job.id, exc, exc_info=True)
                    await asyncio.sleep(1)
                    _current_job_id = None
                    continue

                # Check if more jobs are queued to decide on batching
                queue_count = await peek_queue_count(session)
                skip_id_resolution = queue_count > 0  # Batch if more jobs waiting

                # Process the job
                try:
                    result = await _process_job(session, job, skip_id_resolution=skip_id_resolution)

                    if skip_id_resolution and result.get("match_criteria"):
                        # Mark as pending ID resolution
                        await mark_job_pending_id(session, job, result["match_criteria"])
                        await session.commit()
                        logger.info(f"V&R job {job.id} marked pending_id (batched mode)")
                    else:
                        # Immediate resolution was done, mark fully completed
                        await mark_job_completed(session, job)
                        await session.commit()
                        logger.info(f"V&R job {job.id} marked completed (immediate mode)")

                    job_processed = True

                except Exception as exc:
                    await session.rollback()
                    error_message = str(exc)
                    try:
                        await mark_job_failed(session, job, error_message)
                        await session.commit()
                    except Exception as inner_exc:
                        await session.rollback()
                        logger.exception(
                            "Failed to record failure for job %s (%s): %s",
                            job.id,
                            error_message,
                            inner_exc,
                        )
                    else:
                        logger.error("V&R job %s failed: %s", job.id, error_message)
                    await asyncio.sleep(1)

                _current_job_id = None

                # Check if we should resolve now
                if job_processed:
                    should_resolve = await _should_resolve_now(session)
                    if should_resolve:
                        await _resolve_pending_batch(session)

        if not job_processed:
            await asyncio.sleep(POLL_INTERVAL)


async def main() -> None:
    global _shutdown_requested

    logger.info("Starting V&R worker (poll=%ss, max_batch=%s)", POLL_INTERVAL, MAX_BATCH_SIZE)

    try:
        await worker_loop()
    except SystemExit:
        pass

    # Graceful shutdown - resolve any pending jobs
    if _shutdown_requested:
        logger.info("Performing graceful shutdown...")

        if _current_job_id:
            logger.warning(f"Job {_current_job_id} was in progress during shutdown")

        # Final resolution attempt
        async with async_session() as session:
            pending_count = await count_pending_resolutions(session)
            if pending_count > 0:
                logger.info(f"Resolving {pending_count} pending jobs before shutdown...")
                await _resolve_pending_batch(session)

        logger.info("V&R worker shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
