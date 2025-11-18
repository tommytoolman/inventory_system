import asyncio
import uuid
import logging

from app.core.config import get_settings
from app.database import async_session
from app.routes.platforms.vr import run_vr_sync_background


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main():
    settings = get_settings()
    sync_run_id = uuid.uuid4()
    logger.info("Starting V&R sync run_id=%s", sync_run_id)
    async with async_session() as db:
        await run_vr_sync_background(
            settings.VINTAGE_AND_RARE_USERNAME,
            settings.VINTAGE_AND_RARE_PASSWORD,
            db,
            sync_run_id,
        )
    logger.info("Completed V&R sync run_id=%s", sync_run_id)


if __name__ == "__main__":
    asyncio.run(main())
