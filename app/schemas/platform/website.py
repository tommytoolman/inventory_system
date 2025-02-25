# File: app/schemas/platform/website.py

from pydantic import BaseModel, ConfigDict
from typing import Optional, List
from datetime import datetime
from decimal import Decimal


class WebsiteListingCreateDTO(BaseModel):
    seo_title: Optional[str]
    seo_description: Optional[str]
    seo_keywords: List[str] = []
    featured: bool = False
    custom_layout: Optional[str]
    price: Decimal
    quantity: int = 1

class WebsiteListingStatusDTO(BaseModel):
    listing_id: int
    status: str
    last_synced_at: Optional[datetime]
    sync_message: Optional[str]
    website_listing_id: Optional[str]