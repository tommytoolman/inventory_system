# File: app/schemas/platform/shopify.py

from pydantic import BaseModel, ConfigDict
from typing import Optional, List
from datetime import datetime, timezone
from decimal import Decimal


class ShopifyListingCreateDTO(BaseModel):
    seo_title: Optional[str]
    seo_description: Optional[str]
    seo_keywords: List[str] = []
    featured: bool = False
    custom_layout: Optional[str]
    price: Decimal
    quantity: int = 1

class ShopifyListingStatusDTO(BaseModel):
    listing_id: int
    status: str
    last_synced_at: Optional[datetime]
    sync_message: Optional[str]
    shopify_listing_id: Optional[str]