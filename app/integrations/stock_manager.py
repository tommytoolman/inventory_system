import asyncio
import logging
from typing import Dict
from datetime import datetime
from app.integrations.base import PlatformInterface, SyncStatus
from app.integrations.events import StockUpdateEvent
from app.integrations.metrics import MetricsCollector, MetricsContext  # New import


class StockManager:
    def __init__(self):
        self.platforms: Dict[str, PlatformInterface] = {}
        self.update_queue = asyncio.Queue()
        self.metrics = MetricsCollector()  # New: initialize metrics collector

    def register_platform(self, name: str, platform: PlatformInterface):
        self.platforms[name] = platform

    def get_metrics(self) -> dict:
        """Get current metrics for all platforms and queue status"""
        return {
            "queue": self.metrics.get_queue_stats(),
            "platforms": {
                platform_name: self.metrics.get_platform_stats(platform_name)
                for platform_name in self.platforms
            }
        }

    async def _process_update(self, event: StockUpdateEvent):
        """Internal method to process updates to other platforms"""
        update_tasks = []

        for platform_name, platform in self.platforms.items():
            if platform_name != event.platform:  # Don't update source platform
                # Use MetricsContext to track the update operation
                async with MetricsContext(self.metrics, platform_name) as _:
                    task = platform.update_stock(event.product_id, event.new_quantity)
                    update_tasks.append(task)

        # Wait for all updates to complete
        if update_tasks:
            results = await asyncio.gather(*update_tasks, return_exceptions=True)

            # Handle any failed updates
            for platform_name, result in zip(self.platforms.keys(), results):
                if isinstance(result, Exception):
                    # Log error and mark platform as out of sync
                    self.platforms[platform_name]._sync_status = SyncStatus.ERROR

    async def process_stock_update(self, event: StockUpdateEvent):
        """Process a stock update event directly (not through queue)"""
        await self._process_update(event)

    async def queue_product(self, product_id: int):
        """
        Add a product to the sync queue for all platforms
        Added later on 24-02-25 to fix greenlet_spawn  error.
        Might be superfluous.
        """
        try:
            # Create a stock update event with default quantity=1
            event = StockUpdateEvent(
                product_id=product_id,
                platform="local",  # Source is local system
                new_quantity=1,    # Default quantity
                timestamp=datetime.now()
            )

            # Add to queue
            await self.update_queue.put(event)

            # Record metrics
            await self.metrics.record_queue_length(self.update_queue.qsize())

            return True
        except Exception as e:
            print(f"Error queueing product {product_id}: {str(e)}")
            return False

    async def start_sync_monitor(self):
        """Monitor and process the update queue"""
        while True:
            try:
                # NEW: Record queue length before processing
                await self.metrics.record_queue_length(self.update_queue.qsize())

                event = await self.update_queue.get()
                await self._process_update(event)
                self.update_queue.task_done()  # Only call task_done() after getting from queue

            except asyncio.CancelledError:
                # Clean shutdown when task is cancelled
                break
            except Exception as e:
                # Log error but continue processing
                print(f"Error processing event: {e}")
                self.update_queue.task_done()  # Don't forget to mark task as done even on error