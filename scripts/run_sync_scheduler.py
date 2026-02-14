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
from app.services.reverb_service import ReverbService
from app.services.reconciliation_service import process_reconciliation
from app.models.sync_event import SyncEvent
from sqlalchemy import select
from shopify.auto_archive import run_auto_archive

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

    async def _auto_process_ended_sold_events(db, sync_run_id):
        """Auto-process status_change events where a listing went to ended/sold.

        Called after each platform sync to propagate endings across all platforms.
        Works for any source platform (Reverb, eBay, Shopify, VR).
        """
        logger.info(
            "🔍 Auto-process check: looking for pending status_change events in sync_run %s",
            sync_run_id,
        )
        try:
            # First, log ALL pending events for this sync run so we can see what exists
            all_pending_stmt = select(SyncEvent).where(
                SyncEvent.sync_run_id == sync_run_id,
                SyncEvent.status == "pending",
            )
            all_pending_result = await db.execute(all_pending_stmt)
            all_pending = all_pending_result.scalars().all()
            logger.info(
                "🔍 Found %s total pending events for sync_run %s: %s",
                len(all_pending),
                sync_run_id,
                [(e.id, e.change_type, e.platform_name, e.change_data.get("new") if e.change_data else None) for e in all_pending],
            )

            # Now filter to status_change only
            status_change_events = [e for e in all_pending if e.change_type == "status_change"]
            logger.info(
                "🔍 Of those, %s are status_change events",
                len(status_change_events),
            )

            auto_count = 0
            for event in status_change_events:
                new_state = (event.change_data or {}).get("new", "")
                new_state_lower = new_state.lower() if new_state else ""
                logger.info(
                    "🔍 Event %s: platform=%s, product_id=%s, change_data=%s, new_state='%s' (lower='%s')",
                    event.id, event.platform_name, event.product_id,
                    event.change_data, new_state, new_state_lower,
                )

                if new_state_lower not in ("ended", "sold"):
                    logger.info(
                        "🔍 Skipping event %s: new_state '%s' not in (ended, sold)",
                        event.id, new_state_lower,
                    )
                    continue

                try:
                    logger.info(
                        "⚡ Auto-processing %s status_change event %s (%s → %s) for product %s",
                        event.platform_name, event.id,
                        (event.change_data or {}).get("old", "?"), new_state_lower,
                        event.product_id,
                    )
                    report = await process_reconciliation(
                        db=db,
                        event_id=event.id,
                        dry_run=False,
                    )
                    auto_count += 1
                    logger.info(
                        "✅ Auto-processed %s status_change event %s (%s → %s) — summary: %s",
                        event.platform_name, event.id,
                        (event.change_data or {}).get("old", "?"), new_state_lower,
                        report.summary,
                    )
                    if report.summary.get("errors", 0) > 0:
                        logger.warning(
                            "⚠️ Auto-process event %s had errors: %s, actions: %s",
                            event.id, report.summary, report.actions_taken,
                        )
                except Exception as evt_err:
                    logger.error("❌ Failed to auto-process status_change event %s: %s", event.id, evt_err, exc_info=True)

            if auto_count:
                logger.info("✅ Auto-processed %s ended/sold status_change events for sync run %s", auto_count, sync_run_id)
            else:
                logger.info("🔍 No ended/sold status_change events to auto-process for sync run %s", sync_run_id)
        except Exception as e:
            logger.warning("❌ Status change auto-processing failed: %s", e, exc_info=True)

    async def reverb_sync_and_autoprocess(db, settings, sync_run_id):
        """Run Reverb listing sync, then auto-process ended/sold status changes."""
        await run_reverb_sync_background(
            api_key=settings.REVERB_API_KEY,
            db=db,
            settings=settings,
            sync_run_id=sync_run_id,
        )
        await _auto_process_ended_sold_events(db, sync_run_id)

    async def ebay_sync_and_autoprocess(db, settings, sync_run_id):
        """Run eBay listing sync, then auto-process ended/sold status changes."""
        await run_ebay_sync_background(
            db=db,
            settings=settings,
            sync_run_id=sync_run_id,
        )
        await _auto_process_ended_sold_events(db, sync_run_id)

    async def shopify_sync_and_autoprocess(db, settings, sync_run_id):
        """Run Shopify listing sync, then auto-process ended/sold status changes."""
        await run_shopify_sync_background(
            db=db,
            settings=settings,
            sync_run_id=sync_run_id,
        )
        await _auto_process_ended_sold_events(db, sync_run_id)

    async def vr_sync_and_autoprocess(db, settings, sync_run_id):
        """Run VR listing sync, then auto-process ended/sold status changes."""
        await run_vr_sync_background(
            settings.VINTAGE_AND_RARE_USERNAME,
            settings.VINTAGE_AND_RARE_PASSWORD,
            db,
            sync_run_id,
        )
        await _auto_process_ended_sold_events(db, sync_run_id)

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

                # Process orders for inventory management (pass settings for API propagation)
                processor = OrderSaleProcessor(db, settings)
                sale_summary = await processor.process_unprocessed_orders("reverb", dry_run=False)
                logger.info("Reverb sale processing: %s", sale_summary)

                # Create order_sale sync events for stocked items, then auto-process
                # (propagates to eBay/Shopify/VR + sends email notification)
                reverb_service = ReverbService(db, settings)
                event_result = await reverb_service.create_sync_events_for_stocked_orders(sync_run_id)
                events_created = event_result.get("events_created", 0)
                logger.info("Reverb order_sale sync events: %s", event_result)

                if events_created > 0:
                    await db.commit()  # commit events before processing
                    recon_report = await process_reconciliation(
                        db=db,
                        sync_run_id=str(sync_run_id),
                        event_type="order_sale",
                        dry_run=False,
                    )
                    logger.info(
                        "Auto-processed %s order_sale events (errors: %s)",
                        recon_report.summary.get("processed", 0),
                        recon_report.summary.get("errors", 0),
                    )

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
                        "order_sale_events": events_created,
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

                # Process orders for inventory management (pass settings for API propagation)
                processor = OrderSaleProcessor(db, settings)
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

                # Process orders for inventory management (pass settings for API propagation)
                processor = OrderSaleProcessor(db, settings)
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

    async def refresh_ebay_stats(db, settings, sync_run_id):
        """Fetch current eBay listing stats and store historical snapshot."""
        logger.info("Refreshing eBay listing stats...")
        activity_logger = ActivityLogger(db)
        try:
            stats_service = ListingStatsService(db)
            result = await stats_service.refresh_ebay_stats(
                dry_run=False,
                batch_size=10
            )

            if result.get("status") == "success":
                await activity_logger.log_activity(
                    action="stats_refresh",
                    entity_type="listings",
                    entity_id="ebay",
                    platform="ebay",
                    details={
                        "icon": "📊",
                        "status": "success",
                        "message": f"Refreshed eBay stats ({result.get('listings_fetched', 0)} listings)",
                        "listings_fetched": result.get("listings_fetched", 0),
                        "snapshots_inserted": result.get("stats_snapshots_inserted", 0),
                        "errors": result.get("errors", 0),
                    }
                )
                await db.commit()
            logger.info("eBay stats refresh: %s", result)
        except Exception as e:
            logger.warning("eBay stats refresh failed: %s", e)

    async def shopify_auto_archive(db, settings, sync_run_id):
        """Auto-archive Shopify listings for sold/ended products older than 14 days."""
        logger.info("Running Shopify auto-archive...")
        activity_logger = ActivityLogger(db)
        try:
            result = await run_auto_archive(dry_run=False, limit=None, days=14)

            await activity_logger.log_activity(
                action="auto_archive",
                entity_type="listings",
                entity_id="shopify",
                platform="shopify",
                details={
                    "icon": "📦",
                    "status": "success",
                    "message": f"Auto-archived {result.get('archived', 0)} Shopify listings",
                    "archived": result.get("archived", 0),
                    "skipped": result.get("skipped", 0),
                    "errors": result.get("errors", 0),
                }
            )
            await db.commit()
            logger.info("Shopify auto-archive: %s", result)
        except Exception as e:
            logger.warning("Shopify auto-archive failed: %s", e)

    jobs = [
        ScheduledJob(
            "reverb_hourly",
            60,
            reverb_sync_and_autoprocess,
        ),
        ScheduledJob(
            "ebay_hourly",
            60,
            ebay_sync_and_autoprocess,
        ),
        ScheduledJob(
            "shopify_hourly",
            60,
            shopify_sync_and_autoprocess,
        ),
        ScheduledJob(
            "vr_every_3h",
            180,
            vr_sync_and_autoprocess,
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
        ScheduledJob(
            "ebay_stats_daily",
            1440,
            refresh_ebay_stats,
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
        # Weekly auto-archive job - 10080 minutes = 7 days
        ScheduledJob(
            "shopify_auto_archive_weekly",
            10080,
            shopify_auto_archive,
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
