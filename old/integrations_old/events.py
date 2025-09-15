"""
Purpose: Defines the data structure for events that trigger stock updates.
Contents:
StockUpdateEvent (Pydantic Model): Represents a notification that a product's stock level has changed on a specific platform (or locally). 
It carries the essential information needed to propagate this change (product_id, platform where the change originated, new_quantity, timestamp, etc.). 
This suggests an event-driven approach to synchronization.
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel

class StockUpdateEvent(BaseModel):
    product_id: int
    platform: str
    new_quantity: int
    timestamp: datetime
    transaction_id: Optional[str] = None
    external_order_id: Optional[str] = None
