# File: app/schemas/platform/vr.py

from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import datetime
from decimal import Decimal


class VRListingCreateDTO(BaseModel):
    in_collective: bool = False
    in_inventory: bool = True
    in_reseller: bool = False
    collective_discount: Optional[float]
    price_notax: Optional[float]
    show_vat: bool = True
    processing_time: Optional[int]
    price: Decimal
    quantity: int = 1

class VRListingStatusDTO(BaseModel):
    listing_id: int
    status: str
    last_synced_at: Optional[datetime]
    sync_message: Optional[str]
    vr_listing_id: Optional[str]