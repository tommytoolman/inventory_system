from app.integrations.base import PlatformInterface
from app.integrations.events import StockUpdateEvent
from app.integrations.stock_manager import SyncStatus

from typing import Optional, Dict
from datetime import datetime


class MockPlatform(PlatformInterface):
    def __init__(self, api_credentials: Dict[str, str] = None):
        super().__init__(api_credentials or {})
        self.stock_levels: Dict[int, int] = {}  # product_id -> quantity
        self.update_calls: list = []  # Track calls for testing
        self.should_fail = False  # Toggle to test error scenarios

    async def update_stock(self, product_id: int, quantity: int) -> bool:
        if self.should_fail:
            self._sync_status = SyncStatus.ERROR
            return False

        self.update_calls.append({
            'product_id': product_id,
            'quantity': quantity,
            'timestamp': datetime.now()
        })
        self.stock_levels[product_id] = quantity
        self._last_sync = datetime.now()
        self._sync_status = SyncStatus.SYNCED
        return True

    async def get_current_stock(self, product_id: int) -> Optional[int]:
        return self.stock_levels.get(product_id)

    async def sync_status(self, product_id: int) -> SyncStatus:
        return self._sync_status

    def clear_history(self):
        """Clear test history"""
        self.update_calls = []
        self.stock_levels = {}