from typing import Optional, Dict, Any
from pydantic import BaseModel, ConfigDict
from datetime import datetime

from app.models.platform_common import ListingStatus, SyncStatus

class PlatformListingBase(BaseModel):
    """Base schema for all platform listings"""
    product_id: int
    platform_name: str
    external_id: Optional[str] = None
    status: str = ListingStatus.DRAFT.value
    sync_status: str = SyncStatus.PENDING.value
    listing_url: Optional[str] = None
    platform_specific_data: Dict[str, Any] = {}

    model_config = ConfigDict(from_attributes=True)

class PlatformListingCreate(PlatformListingBase):
    pass

class PlatformListingUpdate(PlatformListingBase):
    pass

class PlatformListingRead(PlatformListingBase):
    id: int
    created_at: datetime
    updated_at: datetime
    last_sync: Optional[datetime]