from typing import Optional, Dict, Any
from decimal import Decimal
from pydantic import BaseModel, ConfigDict
from datetime import datetime

from app.models.ebay import EbayListingFormat, EbayListingStatus
from app.schemas.platform.common import PlatformListingBase

class EbayListingBase(BaseModel):
    platform_id: int
    ebay_category_id: Optional[str] = None
    ebay_second_category_id: Optional[str] = None
    format: str = EbayListingFormat.BUY_IT_NOW
    price: Decimal
    quantity: int = 1
    payment_policy_id: Optional[str] = None
    return_policy_id: Optional[str] = None
    shipping_policy_id: Optional[str] = None
    item_specifics: Dict[str, Any] = {}
    package_weight: Optional[float] = None
    package_dimensions: Optional[Dict[str, Any]] = None
    listing_duration: Optional[str] = None
    allow_offers: bool = False
    min_offer_amount: Optional[Decimal] = None

    model_config = ConfigDict(from_attributes=True)

class EbayListingCreate(EbayListingBase):
    pass

class EbayListingUpdate(EbayListingBase):
    pass

class EbayListingRead(EbayListingBase):
    id: int
    ebay_item_id: Optional[str]
    listing_status: str = EbayListingStatus.DRAFT
    created_at: datetime
    updated_at: datetime
    last_synced_at: Optional[datetime]

class EbayListingStatus(BaseModel):
    listing_id: int
    status: str
    last_synced_at: Optional[datetime]
    sync_message: Optional[str]
    ebay_item_id: Optional[str]