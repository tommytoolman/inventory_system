import asyncio
import uuid
import logging

from app.core.config import get_settings
from app.database import async_session
from app.routes.platforms.reverb import run_reverb_sync_background


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main():
    settings = get_settings()
    sync_run_id = uuid.uuid4()
    logger.info("Starting Reverb sync run_id=%s", sync_run_id)
    async with async_session() as db:
        await run_reverb_sync_background(
            api_key=settings.REVERB_API_KEY,
            db=db,
            settings=settings,
            sync_run_id=sync_run_id,
        )
    logger.info("Completed Reverb sync run_id=%s", sync_run_id)


if __name__ == "__main__":
    asyncio.run(main())
