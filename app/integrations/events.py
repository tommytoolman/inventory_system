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
