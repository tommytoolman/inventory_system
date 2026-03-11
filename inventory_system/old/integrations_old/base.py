"""
Purpose: Defines the core abstractions for platform integrations related to stock management.
Contents:
SyncStatus Enum: Defines possible states for synchronization (SYNCED, PENDING, ERROR, OUT_OF_SYNC).
PlatformInterface (Abstract Base Class): This is a crucial part of the design. 
It defines a contract that any specific platform integration must adhere to. 
Any class implementing this interface must provide concrete implementations for update_stock, get_current_stock, and sync_status methods. 
This promotes consistency across different platform integrations.
"""

import asyncio

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
from enum import Enum
from datetime import datetime, timezone
from pydantic import BaseModel

from app.core.enums import SyncStatus


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