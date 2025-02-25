from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
from enum import Enum
from datetime import datetime
import asyncio
from pydantic import BaseModel


class SyncStatus(Enum):
    SYNCED = "synced"
    PENDING = "pending"
    ERROR = "error"
    OUT_OF_SYNC = "out_of_sync"


class PlatformInterface(ABC):
    def __init__(self, api_credentials: Dict[str, str]):
        self.api_credentials = api_credentials
        self._last_sync: Optional[datetime] = None
        self._sync_status = SyncStatus.PENDING

    @abstractmethod
    async def update_stock(self, product_id: int, quantity: int) -> bool:
        """Update stock level on the platform"""
        pass

    @abstractmethod
    async def get_current_stock(self, product_id: int) -> Optional[int]:
        """Get current stock level from the platform"""
        pass

    @abstractmethod
    async def sync_status(self, product_id: int) -> SyncStatus:
        """Check sync status with platform"""
        pass