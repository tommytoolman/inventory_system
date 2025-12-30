import asyncio
import logging
import math
import uuid
from datetime import datetime, timedelta, timezone

from app.core.config import get_settings
from app.database import async_session
from app.services.ebay_service import EbayService
from app.services.ebay.trading import EbayTradingLegacyAPI
from app.services.reverb.client import ReverbClient
from app.routes.platforms.ebay import run_ebay_sync_background
from app.routes.platforms.reverb import run_reverb_sync_background
from app.routes.platforms.shopify import run_shopify_sync_background
from app.routes.platforms.vr import run_vr_sync_background

# Import order upsert functions from scripts
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from ebay.get_ebay_orders import upsert_orders as upsert_ebay_orders
from reverb.get_reverb_sold_orders import upsert_orders as upsert_reverb_orders
from shopify.get_shopify_orders import upsert_orders as upsert_shopify_orders, fetch_orders_sync as fetch_shopify_orders
from app.services.shopify.client import ShopifyGraphQLClient
from app.services.activity_logger import ActivityLogger
from app.services.order_sale_processor import OrderSaleProcessor
from app.services.listing_stats_service import ListingStatsService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ScheduledJob:
    def __init__(self, name: str, interval_minutes: int, coro):
        self.name = name
        self.interval = timedelta(minutes=interval_minutes)
        self.coro = coro
        self.next_run = self._compute_next_run(datetime.now(timezone.utc))

    def _compute_next_run(self, reference: datetime) -> datetime:
        """
        Align the next run to the next interval boundary after `reference`.
        """
        interval_seconds = self.interval.total_seconds()
        reference_ts = reference.timestamp()
        next_ts = math.ceil(reference_ts / interval_seconds) * interval_seconds
        next_run = datetime.fromtimestamp(next_ts, tz=timezone.utc)
        if next_run <= reference:
            next_run = reference + self.interval
        return next_run

    def update_next_run(self):
        self.next_run = self.next_run + self.interval


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

    async def refresh_ebay_metadata(db, settings, sync_run_id):
        service = EbayService(db, settings)
        await service.refresh_listing_metadata(
            state="active",
            limit=None,
            batch_size=10,
            dry_run=False,
            skus=None,
            item_ids=None,
        )

    async def fetch_reverb_orders(db, settings, sync_run_id):
        """Fetch recent Reverb orders, upsert, and process for inventory."""
        logger.info("Fetching Reverb orders...")
        activity_logger = ActivityLogger(db)
        try:
            client = ReverbClient(api_key=settings.REVERB_API_KEY)
            # Fetch first 2 pages (100 orders) - most recent orders for hourly sync
            orders = await client.get_all_sold_orders(per_page=50, max_pages=2)
            if orders:
                summary = await upsert_reverb_orders(db, orders)
                logger.info("Reverb orders upsert: %s", summary)

                # Process orders for inventory management
                processor = OrderSaleProcessor(db)
                sale_summary = await processor.process_unprocessed_orders("reverb", dry_run=False)
                logger.info("Reverb sale processing: %s", sale_summary)

                await activity_logger.log_activity(
                    action="orders_sync",
                    entity_type="orders",
                    entity_id="reverb",
                    platform="reverb",
                    details={
                        "icon": "📦",
                        "status": "success",
                        "message": f"Synced Reverb orders ({summary.get('total', len(orders))} orders)",
                        "total": summary.get("total", len(orders)),
                        "inserted": summary.get("inserted", 0),
                        "updated": summary.get("updated", 0),
                        "sales_processed": sale_summary.get("sales_detected", 0),
                        "quantity_decrements": sale_summary.get("quantity_decrements", 0),
                    }
                )
                await db.commit()
            else:
                logger.info("No Reverb orders returned")
        except Exception as e:
            logger.warning("Reverb orders fetch failed: %s", e)

    async def fetch_ebay_orders(db, settings, sync_run_id):
        """Fetch recent eBay orders, upsert, and process for inventory."""
        logger.info("Fetching eBay orders...")
        activity_logger = ActivityLogger(db)
        try:
            api = EbayTradingLegacyAPI(sandbox=False)
            # Fetch last 7 days of orders - covers any missed updates
            orders = []
            page = 1
            while True:
                response = await api.get_orders(
                    number_of_days=7,
                    order_status="All",
                    order_role="Seller",
                    entries_per_page=100,
                    page_number=page,
                )
                batch = response.get("orders", [])
                if not batch:
                    break
                orders.extend(batch)
                if not response.get("has_more"):
                    break
                page += 1
            if orders:
                summary = await upsert_ebay_orders(db, orders)
                logger.info("eBay orders upsert: %s", summary)

                # Process orders for inventory management
                processor = OrderSaleProcessor(db)
                sale_summary = await processor.process_unprocessed_orders("ebay", dry_run=False)
                logger.info("eBay sale processing: %s", sale_summary)

                await activity_logger.log_activity(
                    action="orders_sync",
                    entity_type="orders",
                    entity_id="ebay",
                    platform="ebay",
                    details={
                        "icon": "📦",
                        "status": "success",
                        "message": f"Synced eBay orders ({summary.get('total', len(orders))} orders)",
                        "total": summary.get("total", len(orders)),
                        "inserted": summary.get("inserted", 0),
                        "updated": summary.get("updated", 0),
                        "sales_processed": sale_summary.get("sales_detected", 0),
                        "quantity_decrements": sale_summary.get("quantity_decrements", 0),
                    }
                )
                await db.commit()
            else:
                logger.info("No eBay orders returned")
        except Exception as e:
            logger.warning("eBay orders fetch failed: %s", e)

    async def fetch_shopify_orders_job(db, settings, sync_run_id):
        """Fetch recent Shopify orders, upsert, and process for inventory."""
        logger.info("Fetching Shopify orders...")
        activity_logger = ActivityLogger(db)
        try:
            client = ShopifyGraphQLClient()
            # Fetch up to 100 most recent orders
            orders = fetch_shopify_orders(client, max_orders=100)
            if orders:
                summary = await upsert_shopify_orders(db, orders)
                logger.info("Shopify orders upsert: %s", summary)

                # Process orders for inventory management
                processor = OrderSaleProcessor(db)
                sale_summary = await processor.process_unprocessed_orders("shopify", dry_run=False)
                logger.info("Shopify sale processing: %s", sale_summary)

                await activity_logger.log_activity(
                    action="orders_sync",
                    entity_type="orders",
                    entity_id="shopify",
                    platform="shopify",
                    details={
                        "icon": "📦",
                        "status": "success",
                        "message": f"Synced Shopify orders ({summary.get('total', len(orders))} orders)",
                        "total": summary.get("total", len(orders)),
                        "inserted": summary.get("inserted", 0),
                        "updated": summary.get("updated", 0),
                        "sales_processed": sale_summary.get("sales_detected", 0),
                        "quantity_decrements": sale_summary.get("quantity_decrements", 0),
                    }
                )
                await db.commit()
            else:
                logger.info("No Shopify orders returned (store may not have orders yet)")
        except Exception as e:
            logger.warning("Shopify orders fetch failed (expected if no orders): %s", e)

    async def refresh_reverb_stats(db, settings, sync_run_id):
        """Fetch current Reverb listing stats and store historical snapshot."""
        logger.info("Refreshing Reverb listing stats...")
        activity_logger = ActivityLogger(db)
        try:
            stats_service = ListingStatsService(db)
            result = await stats_service.refresh_reverb_stats(
                api_key=settings.REVERB_API_KEY,
                dry_run=False
            )

            if result.get("status") == "success":
                await activity_logger.log_activity(
                    action="stats_refresh",
                    entity_type="listings",
                    entity_id="reverb",
                    platform="reverb",
                    details={
                        "icon": "📊",
                        "status": "success",
                        "message": f"Refreshed Reverb stats ({result.get('listings_fetched', 0)} listings)",
                        "listings_fetched": result.get("listings_fetched", 0),
                        "snapshots_inserted": result.get("stats_snapshots_inserted", 0),
                        "listings_updated": result.get("listings_updated", 0),
                    }
                )
                await db.commit()
            logger.info("Reverb stats refresh: %s", result)
        except Exception as e:
            logger.warning("Reverb stats refresh failed: %s", e)

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
        ScheduledJob(
            "ebay_metadata_12h",
            720,
            refresh_ebay_metadata,
        ),
        # Stats refresh jobs - run daily (1440 minutes = 24 hours)
        ScheduledJob(
            "reverb_stats_daily",
            1440,
            refresh_reverb_stats,
        ),
        # Orders fetch jobs - run hourly after platform syncs
        ScheduledJob(
            "reverb_orders_hourly",
            60,
            fetch_reverb_orders,
        ),
        ScheduledJob(
            "ebay_orders_hourly",
            60,
            fetch_ebay_orders,
        ),
        ScheduledJob(
            "shopify_orders_hourly",
            60,
            fetch_shopify_orders_job,
        ),
    ]

    heartbeat_interval = timedelta(minutes=10)
    next_heartbeat = datetime.now(timezone.utc) + heartbeat_interval

    while True:
        now = datetime.now(timezone.utc)
        due_jobs = [job for job in jobs if job.next_run <= now]

        for job in due_jobs:
            await run_job(job, settings)

        if datetime.now(timezone.utc) >= next_heartbeat:
            schedule = {job.name: job.next_run.isoformat() for job in jobs}
            logger.info("Scheduler heartbeat; next runs: %s", schedule)
            next_heartbeat = datetime.now(timezone.utc) + heartbeat_interval

        await asyncio.sleep(60)  # check every minute


if __name__ == "__main__":
    asyncio.run(main())
