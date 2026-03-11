import asyncio
import uuid
import logging

from app.core.config import get_settings
from app.database import async_session
from app.routes.platforms.shopify import run_shopify_sync_background


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main():
    settings = get_settings()
    sync_run_id = uuid.uuid4()
    logger.info("Starting Shopify sync run_id=%s", sync_run_id)
    async with async_session() as db:
        await run_shopify_sync_background(
            db=db,
            settings=settings,
            sync_run_id=sync_run_id,
        )
    logger.info("Completed Shopify sync run_id=%s", sync_run_id)


if __name__ == "__main__":
    asyncio.run(main())
