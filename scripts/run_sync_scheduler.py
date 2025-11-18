import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone

from app.core.config import get_settings
from app.database import async_session
from app.routes.platforms.ebay import run_ebay_sync_background
from app.routes.platforms.reverb import run_reverb_sync_background
from app.routes.platforms.shopify import run_shopify_sync_background
from app.routes.platforms.vr import run_vr_sync_background

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ScheduledJob:
    def __init__(self, name: str, interval_minutes: int, coro):
        self.name = name
        self.interval = timedelta(minutes=interval_minutes)
        self.coro = coro
        self.next_run = datetime.now(timezone.utc)

    def update_next_run(self):
        self.next_run = datetime.utcnow() + self.interval


async def run_job(job: ScheduledJob, settings):
    sync_run_id = uuid.uuid4()
    logger.info("Starting job=%s sync_run_id=%s", job.name, sync_run_id)
    try:
        async with async_session() as db:
            await job.coro(db=db, settings=settings, sync_run_id=sync_run_id)
        logger.info("Completed job=%s sync_run_id=%s", job.name, sync_run_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Job %s failed: %s", job.name, exc, exc_info=True)
    finally:
        job.update_next_run()


async def main():
    settings = get_settings()

    jobs = [
        ScheduledJob(
            "reverb_hourly",
            60,
            lambda db, settings, sync_run_id: run_reverb_sync_background(
                api_key=settings.REVERB_API_KEY,
                db=db,
                settings=settings,
                sync_run_id=sync_run_id,
            ),
        ),
        ScheduledJob(
            "ebay_hourly",
            60,
            lambda db, settings, sync_run_id: run_ebay_sync_background(
                db=db,
                settings=settings,
                sync_run_id=sync_run_id,
            ),
        ),
        ScheduledJob(
            "shopify_hourly",
            60,
            lambda db, settings, sync_run_id: run_shopify_sync_background(
                db=db,
                settings=settings,
                sync_run_id=sync_run_id,
            ),
        ),
        ScheduledJob(
            "vr_every_3h",
            180,
            lambda db, settings, sync_run_id: run_vr_sync_background(
                settings.VINTAGE_AND_RARE_USERNAME,
                settings.VINTAGE_AND_RARE_PASSWORD,
                db,
                sync_run_id,
            ),
        ),
    ]

    heartbeat_interval = timedelta(minutes=10)
    next_heartbeat = datetime.now(timezone.utc) + heartbeat_interval

    while True:
        now = datetime.now(timezone.utc)
        due_jobs = [job for job in jobs if job.next_run <= now]

        for job in due_jobs:
            await run_job(job, settings)

        if datetime.utcnow() >= next_heartbeat:
            schedule = {job.name: job.next_run.isoformat() for job in jobs}
            logger.info("Scheduler heartbeat; next runs: %s", schedule)
            next_heartbeat = datetime.utcnow() + heartbeat_interval

        await asyncio.sleep(60)  # check every minute


if __name__ == "__main__":
    asyncio.run(main())
