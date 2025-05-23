from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import datetime, timezone

from .ebay import EbayListingCreate, EbayListingStatusInfo
from .reverb import ReverbListingCreateDTO, ReverbListingStatusDTO
from .vr import VRListingCreateDTO, VRListingStatusDTO
from .website import WebsiteListingCreateDTO, WebsiteListingStatusDTO

# File: app/schemas/platform/combined.py
class MultiPlatformListingCreateDTO(BaseModel):
    ebay: Optional[EbayListingCreate]
    reverb: Optional[ReverbListingCreateDTO]
    vr: Optional[VRListingCreateDTO]
    website: Optional[WebsiteListingCreateDTO]

class PlatformSyncStatusDTO(BaseModel):
    ebay_status: EbayListingStatusInfo
    reverb_status: ReverbListingStatusDTO
    vr_status: VRListingStatusDTO
    website_status: WebsiteListingStatusDTO

    @property
    def all_synced(self) -> bool:
        return all([
            self.ebay_status.status == "success",
            self.reverb_status.status == "success",
            self.vr_status.status == "success",
            self.website_status.status == "success"
        ])