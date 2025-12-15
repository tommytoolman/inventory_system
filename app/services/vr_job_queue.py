"""Helpers for enqueuing and managing V&R listing jobs."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import flag_modified

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


async def mark_job_pending_id(
    db: AsyncSession, job: VRJob, match_criteria: Dict[str, Any]
) -> None:
    """Mark job as listing created but V&R ID not yet resolved."""
    job.status = VRJobStatus.COMPLETED_PENDING_ID.value
    job.error_message = None
    # Store match criteria in payload for later resolution
    # Use dict copy to ensure SQLAlchemy detects the change
    payload = dict(job.payload) if job.payload else {}
    payload["match_criteria"] = match_criteria
    payload["listing_created"] = True
    job.payload = payload
    flag_modified(job, 'payload')  # Explicitly mark JSONB as modified
    await db.flush()


async def fetch_pending_resolution_jobs(db: AsyncSession) -> List[VRJob]:
    """Fetch all jobs that need V&R ID resolution."""
    stmt = (
        select(VRJob)
        .where(VRJob.status == VRJobStatus.COMPLETED_PENDING_ID.value)
        .order_by(VRJob.created_at.asc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def count_pending_resolutions(db: AsyncSession) -> int:
    """Count jobs waiting for V&R ID resolution."""
    stmt = select(func.count(VRJob.id)).where(
        VRJob.status == VRJobStatus.COMPLETED_PENDING_ID.value
    )
    result = await db.execute(stmt)
    return result.scalar() or 0


async def peek_queue_count(db: AsyncSession) -> int:
    """Check how many jobs are still queued (without locking)."""
    stmt = select(func.count(VRJob.id)).where(
        VRJob.status == VRJobStatus.QUEUED.value
    )
    result = await db.execute(stmt)
    return result.scalar() or 0


async def increment_resolution_attempts(db: AsyncSession, job: VRJob) -> None:
    """Increment resolution attempt counter for a pending job."""
    payload = dict(job.payload) if job.payload else {}
    payload["resolution_attempts"] = payload.get("resolution_attempts", 0) + 1
    job.payload = payload
    flag_modified(job, 'payload')  # Explicitly mark JSONB as modified
    await db.flush()
