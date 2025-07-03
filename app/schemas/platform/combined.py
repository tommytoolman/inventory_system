from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import datetime, timezone

from .ebay import EbayListingCreate, EbayListingStatusInfo
from .reverb import ReverbListingCreateDTO, ReverbListingStatusDTO
from .vr import VRListingCreateDTO, VRListingStatusDTO
from .shopify import ShopifyListingCreateDTO, ShopifyListingStatusDTO

# File: app/schemas/platform/combined.py
class MultiPlatformListingCreateDTO(BaseModel):
    ebay: Optional[EbayListingCreate]
    reverb: Optional[ReverbListingCreateDTO]
    vr: Optional[VRListingCreateDTO]
    Shopify: Optional[ShopifyListingCreateDTO]

class PlatformSyncStatusDTO(BaseModel):
    ebay_status: EbayListingStatusInfo
    reverb_status: ReverbListingStatusDTO
    vr_status: VRListingStatusDTO
    shopify_status: ShopifyListingStatusDTO

    @property
    def all_synced(self) -> bool:
        return all([
            self.ebay_status.status == "success",
            self.reverb_status.status == "success",
            self.vr_status.status == "success",
            self.shopify_status.status == "success"
        ])