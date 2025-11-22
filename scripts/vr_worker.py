import asyncio
import logging
import os
import signal
from typing import Any, Dict, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import async_session
from app.models.product import Product
from app.services.vintageandrare.brand_validator import VRBrandValidator
from app.services.vintageandrare.constants import DEFAULT_VR_BRAND
from app.services.vr_job_queue import (
    fetch_next_queued_job,
    mark_job_completed,
    mark_job_failed,
    mark_job_in_progress,
)
from app.services.vr_service import VRService

logger = logging.getLogger("vr_worker")
logging.basicConfig(
    level=os.environ.get("VR_WORKER_LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)

POLL_INTERVAL = float(os.environ.get("VR_WORKER_POLL_INTERVAL", "5"))


class GracefulExit(SystemExit):
    pass


def _handle_signal(*_: Any) -> None:
    raise GracefulExit()


for sig in (signal.SIGINT, signal.SIGTERM):
    signal.signal(sig, _handle_signal)


async def _process_job(session: AsyncSession, job) -> None:
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
        "Processing V&R job %s for product %s (source=%s, fallback=%s)",
        job.id,
        product.sku,
        sync_source,
        use_fallback,
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
        )
    finally:
        if brand_overridden:
            product.brand = original_brand

    if not isinstance(result, dict):
        raise RuntimeError("Unexpected V&R response format")

    if result.get("status") != "success":
        raise RuntimeError(result.get("message", "Vintage & Rare listing failed"))

    logger.info(
        "V&R job %s completed: listing_id=%s payload_keys=%s",
        job.id,
        result.get("vr_listing_id"),
        list(result.keys()),
    )


async def worker_loop() -> None:
    while True:
        job_processed = False
        async with async_session() as session:
            job = await fetch_next_queued_job(session)
            if not job:
                job_processed = False
            else:
                try:
                    await mark_job_in_progress(session, job)
                    await session.commit()
                except Exception as exc:  # pragma: no cover - defensive logging
                    await session.rollback()
                    logger.error("Failed to mark job %s in progress: %s", job.id, exc, exc_info=True)
                    await asyncio.sleep(1)
                    continue

                try:
                    await _process_job(session, job)
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
                    continue

                try:
                    await mark_job_completed(session, job)
                    await session.commit()
                except Exception as exc:  # pragma: no cover - defensive logging
                    await session.rollback()
                    logger.exception("Failed to mark job %s completed: %s", job.id, exc)
                else:
                    logger.info("V&R job %s marked completed", job.id)
                    job_processed = True

        if not job_processed:
            await asyncio.sleep(POLL_INTERVAL)


async def main() -> None:
    logger.info("Starting V&R worker (poll interval %ss)", POLL_INTERVAL)
    try:
        await worker_loop()
    except GracefulExit:
        logger.info("Received shutdown signal. Exiting worker.")


if __name__ == "__main__":
    asyncio.run(main())
