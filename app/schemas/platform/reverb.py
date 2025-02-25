from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import datetime
from decimal import Decimal


# File: app/schemas/platform/reverb.py
class ReverbListingCreateDTO(BaseModel):
    reverb_category_uuid: str
    condition_rating: float
    shipping_profile_id: Optional[str]
    shop_policies_id: Optional[str]
    handmade: bool = False
    offers_enabled: bool = True
    price: Decimal
    quantity: int = 1

class ReverbListingStatusDTO(BaseModel):
    listing_id: int
    status: str
    last_synced_at: Optional[datetime]
    sync_message: Optional[str]
    reverb_listing_id: Optional[str]