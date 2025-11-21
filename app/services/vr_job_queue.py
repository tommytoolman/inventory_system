"""Helpers for enqueuing and managing V&R listing jobs."""

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vr_job import VRJob, VRJobStatus


async def enqueue_vr_job(
    db: AsyncSession,
    *,
    product_id: int,
    payload: Dict[str, Any],
) -> VRJob:
    """Create a queued job for a given product/payload."""
    job = VRJob(
        product_id=product_id,
        payload=payload,
        status=VRJobStatus.QUEUED.value,
    )
    db.add(job)
    await db.flush()
    await db.refresh(job)
    return job


async def fetch_next_queued_job(db: AsyncSession) -> Optional[VRJob]:
    """Fetch the next queued job (using SKIP LOCKED to avoid contention)."""
    stmt = (
        select(VRJob)
        .where(VRJob.status == VRJobStatus.QUEUED.value)
        .order_by(VRJob.created_at.asc())
        .with_for_update(skip_locked=True)
    )
    result = await db.execute(stmt)
    job = result.scalars().first()
    return job


async def mark_job_in_progress(db: AsyncSession, job: VRJob) -> None:
    job.status = VRJobStatus.IN_PROGRESS.value
    job.last_attempt_at = datetime.now(timezone.utc)
    job.attempts += 1
    await db.flush()


async def mark_job_completed(db: AsyncSession, job: VRJob) -> None:
    job.status = VRJobStatus.COMPLETED.value
    job.error_message = None
    await db.flush()


async def mark_job_failed(db: AsyncSession, job: VRJob, error_message: str) -> None:
    job.status = VRJobStatus.FAILED.value
    job.error_message = error_message[:2000]
    await db.flush()
