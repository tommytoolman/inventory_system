import asyncio
import uuid
import logging

from app.core.config import get_settings
from app.database import async_session
from app.services.ebay_service import EbayService
from app.services.shopify_service import ShopifyService
from app.services.vr_service import VRService
from app.services.reverb_service import ReverbService
from app.services.sync_services import SyncServices

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def run_all_syncs():
    settings = get_settings()
    sync_run_id = uuid.uuid4()
    logger.info("Starting sync run %s", sync_run_id)

    async with async_session() as db:
        # 1) Platform imports
        try:
            ebay_service = EbayService(db, settings)
            await ebay_service.run_import_process(sync_run_id)
        except Exception as exc:
            logger.error("eBay import failed: %s", exc, exc_info=True)

        try:
            shopify_service = ShopifyService(db, settings)
            await shopify_service.run_import_process(sync_run_id)
        except Exception as exc:
            logger.error("Shopify import failed: %s", exc, exc_info=True)

        try:
            vr_service = VRService(db, settings)
            await vr_service.run_import_process(
                username=settings.VINTAGE_AND_RARE_USERNAME,
                password=settings.VINTAGE_AND_RARE_PASSWORD,
                sync_run_id=sync_run_id,
                save_only=False,
            )
        except Exception as exc:
            logger.error("V&R import failed: %s", exc, exc_info=True)

        try:
            reverb_service = ReverbService(db, settings)
            await reverb_service.run_import_process(sync_run_id)
        except Exception as exc:
            logger.error("Reverb import failed: %s", exc, exc_info=True)

        # 2) Reconciliation
        try:
            sync_service = SyncServices(db)
            await sync_service.reconcile_sync_run(str(sync_run_id), dry_run=False)
        except Exception as exc:
            logger.error("Reconciliation failed: %s", exc, exc_info=True)

    logger.info("Sync run %s completed", sync_run_id)


if __name__ == "__main__":
    asyncio.run(run_all_syncs())
