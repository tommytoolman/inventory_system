"""
Scheduled tasks for the inventory system.
This module sets up scheduled tasks that run within the FastAPI application.
Works on Railway and other hosting platforms.
"""

import logging
from datetime import datetime
from typing import Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR
import httpx
import os

from app.database import async_session

logger = logging.getLogger(__name__)

# Global scheduler instance
scheduler: Optional[AsyncIOScheduler] = None


async def sync_all_platforms_task():
    """Task to sync all platforms"""
    try:
        logger.info("=== SCHEDULED SYNC STARTING ===")

        # Get the base URL - in Railway this will be the internal URL
        if os.getenv("RAILWAY_ENVIRONMENT"):
            # On Railway, use the internal domain
            base_url = f"http://0.0.0.0:{os.getenv('PORT', '8080')}"
        else:
            # Local development
            base_url = "http://localhost:8080"

        # Get auth credentials
        auth_user = os.getenv("BASIC_AUTH_USERNAME", "admin")
        auth_pass = os.getenv("BASIC_AUTH_PASSWORD", "admin")

        # Make the API call to trigger sync
        async with httpx.AsyncClient(timeout=300.0) as client:  # 5 minute timeout
            response = await client.post(
                f"{base_url}/api/sync/all",
                auth=(auth_user, auth_pass),
                params={"max_concurrent": 2}
            )

            if response.status_code == 200:
                result = response.json()
                logger.info(f"Scheduled sync completed successfully: {result.get('message')}")
                logger.info(f"Sync run ID: {result.get('sync_run_id')}")

                # Log to database for tracking
                async with async_session() as db:
                    from sqlalchemy import text
                    await db.execute(
                        text("""
                        INSERT INTO activity_log (action, entity_type, entity_id, platform, details, user_id, created_at)
                        VALUES ('scheduled_sync', 'system', 'scheduler', 'all', :details, NULL, NOW())
                        """),
                        {"details": result}
                    )
                    await db.commit()
            else:
                logger.error(f"Scheduled sync failed with status {response.status_code}: {response.text}")

    except Exception as e:
        logger.exception(f"Error in scheduled sync task: {str(e)}")


async def cleanup_old_logs_task():
    """Task to cleanup old sync events and logs"""
    try:
        logger.info("Starting cleanup of old sync events")

        async with async_session() as db:
            from sqlalchemy import text

            # Delete sync events older than 30 days
            result = await db.execute(
                text("""
                DELETE FROM sync_events
                WHERE created_at < NOW() - INTERVAL '30 days'
                AND status IN ('processed', 'error')
                """)
            )
            deleted_count = result.rowcount

            # Delete old activity logs
            result2 = await db.execute(
                text("""
                DELETE FROM activity_log
                WHERE created_at < NOW() - INTERVAL '60 days'
                """)
            )
            deleted_logs = result2.rowcount

            await db.commit()

            logger.info(f"Cleanup completed: {deleted_count} sync events, {deleted_logs} activity logs deleted")

    except Exception as e:
        logger.exception(f"Error in cleanup task: {str(e)}")


def job_listener(event):
    """Listen to job events for logging"""
    if event.exception:
        logger.error(f"Job {event.job_id} crashed: {event.exception}")
    else:
        logger.info(f"Job {event.job_id} executed successfully at {datetime.now()}")


def create_scheduler() -> AsyncIOScheduler:
    """Create and configure the scheduler"""
    global scheduler

    if scheduler is not None:
        return scheduler

    scheduler = AsyncIOScheduler()

    # Add job event listeners
    scheduler.add_listener(job_listener, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)

    # Get schedule configuration from environment
    sync_schedule = os.getenv("SYNC_SCHEDULE", "0 */4 * * *")  # Default: every 4 hours
    sync_enabled = os.getenv("SYNC_SCHEDULE_ENABLED", "false").lower() == "true"

    if sync_enabled:
        # Add sync all platforms job
        scheduler.add_job(
            sync_all_platforms_task,
            CronTrigger.from_crontab(sync_schedule),
            id="sync_all_platforms",
            name="Sync All Platforms",
            replace_existing=True,
            max_instances=1,  # Only one sync at a time
            misfire_grace_time=3600  # 1 hour grace time
        )
        logger.info(f"Scheduled sync job added with schedule: {sync_schedule}")

        # Add cleanup job - runs daily at 2 AM
        scheduler.add_job(
            cleanup_old_logs_task,
            CronTrigger(hour=2, minute=0),
            id="cleanup_logs",
            name="Cleanup Old Logs",
            replace_existing=True,
            max_instances=1
        )
        logger.info("Scheduled cleanup job added for 2:00 AM daily")
    else:
        logger.info("Scheduled sync is disabled. Set SYNC_SCHEDULE_ENABLED=true to enable")

    return scheduler


async def start_scheduler():
    """Start the scheduler"""
    global scheduler

    if scheduler is None:
        scheduler = create_scheduler()

    if not scheduler.running:
        scheduler.start()
        logger.info("Scheduler started successfully")

        # Log all scheduled jobs
        jobs = scheduler.get_jobs()
        if jobs:
            logger.info(f"Active scheduled jobs: {len(jobs)}")
            for job in jobs:
                logger.info(f"  - {job.name}: {job.trigger}")
        else:
            logger.info("No scheduled jobs configured")


async def stop_scheduler():
    """Stop the scheduler gracefully"""
    global scheduler

    if scheduler and scheduler.running:
        scheduler.shutdown(wait=True)
        logger.info("Scheduler stopped successfully")


# Manual trigger functions for testing
async def trigger_sync_manually():
    """Manually trigger a sync (for testing)"""
    logger.info("Manually triggering sync...")
    await sync_all_platforms_task()


async def get_scheduler_status():
    """Get current scheduler status and job information"""
    global scheduler

    if scheduler is None:
        return {"status": "not_initialized", "jobs": []}

    jobs_info = []
    for job in scheduler.get_jobs():
        jobs_info.append({
            "id": job.id,
            "name": job.name,
            "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
            "trigger": str(job.trigger)
        })

    return {
        "status": "running" if scheduler.running else "stopped",
        "jobs": jobs_info
    }