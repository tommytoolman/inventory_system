# app.schemas.platform.reverb
"""
Data Transfer Objects (DTOs) for Reverb integration.

This module contains Pydantic models for validating and transferring data
related to Reverb listings between the API and the database.
"""

from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
from decimal import Decimal


class ReverbListingBase(BaseModel):
    """Base model with common fields for Reverb listings"""
    platform_id: int
    reverb_category_uuid: str
    condition_rating: Optional[float] = None
    shipping_profile_id: Optional[str] = None
    shop_policies_id: Optional[str] = None
    handmade: bool = False
    offers_enabled: bool = True
    
    model_config = ConfigDict(
        from_attributes = True  # For ORM compatibility
    )


class ReverbListingCreateDTO(ReverbListingBase):
    """DTO for creating a new Reverb listing"""
    price: Decimal
    quantity: int = 1


class ReverbListingUpdateDTO(BaseModel):
    """DTO for updating a Reverb listing"""
    reverb_category_uuid: Optional[str] = None
    condition_rating: Optional[float] = None
    shipping_profile_id: Optional[str] = None
    shop_policies_id: Optional[str] = None
    handmade: Optional[bool] = None
    offers_enabled: Optional[bool] = None
    price: Optional[Decimal] = None
    quantity: Optional[int] = None


class ReverbListingReadDTO(ReverbListingBase):
    """DTO for reading a Reverb listing"""
    id: int
    reverb_listing_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    last_synced_at: Optional[datetime] = None


class ReverbListingStatusDTO(BaseModel):
    """DTO for Reverb listing status"""
    listing_id: int
    status: str
    last_synced_at: Optional[datetime] = None
    sync_message: Optional[str] = None
    reverb_listing_id: Optional[str] = None


class ReverbCategoryDTO(BaseModel):
    """DTO for Reverb category"""
    uuid: str
    name: str
    full_name: Optional[str] = None
    product_type_uuid: Optional[str] = None


class ReverbConditionDTO(BaseModel):
    """DTO for Reverb condition"""
    uuid: str
    display_name: str
    description: Optional[str] = None
