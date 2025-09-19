#!/usr/bin/env python3
"""
Process a sync event for real - creates listings across all platforms.
Uses the centralized event processor service.

Usage:
    python scripts/process_sync_event.py --event-id 12065
    python scripts/process_sync_event.py --event-id 12065 --dry-run
"""

import asyncio
import argparse
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import async_session
from app.models.sync_event import SyncEvent
from sqlalchemy import select
from app.services.event_processor import EventProcessor
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def main(event_id: int, dry_run: bool = False):
    """Process a specific sync event using the centralized event processor."""
    async with async_session() as session:
        try:
            # Get the sync event
            result = await session.execute(
                select(SyncEvent).where(SyncEvent.id == event_id)
            )
            event = result.scalar_one_or_none()

            if not event:
                logger.error(f"Sync event {event_id} not found")
                return 1

            logger.info(f"Processing sync event {event_id}: {event.change_type}")
            logger.info(f"Platform: {event.platform_name}, External ID: {event.external_id}")

            # Process the event using the centralized service
            processor = EventProcessor(session, dry_run=dry_run)
            result = await processor.process_sync_event(event)

            if result.success:
                logger.info(f"✅ Successfully processed sync event {event_id}")
                logger.info(f"Details: {result.details}")
            else:
                logger.error(f"❌ Failed to process sync event {event_id}")
                logger.error(f"Errors: {result.errors}")
                return 1

            # Commit changes if not in dry run mode
            if not dry_run:
                await session.commit()
                logger.info("💾 Changes committed to database")
            else:
                await session.rollback()
                logger.info("🔄 Dry run - changes rolled back")

            return 0

        except Exception as e:
            logger.error(f"Unexpected error processing sync event {event_id}: {e}", exc_info=True)
            await session.rollback()
            return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Process a sync event')
    parser.add_argument('--event-id', type=int, required=True, help='The ID of the sync event to process')
    parser.add_argument('--dry-run', action='store_true', help='Run without making changes')

    args = parser.parse_args()

    # Run the async main function
    exit_code = asyncio.run(main(args.event_id, args.dry_run))
    sys.exit(exit_code)