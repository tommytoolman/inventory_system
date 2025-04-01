# ebay.py
from sqlalchemy import Column, Integer, String, Float, Boolean, ForeignKey, DateTime, Numeric, JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from datetime import datetime
from enum import Enum
from .platform_common import ListingStatus
from typing import Optional, Dict, Any
from pydantic import BaseModel

from ..database import Base

class EbayListingFormat(str, Enum):
    BUY_IT_NOW = "Buy it Now"
    AUCTION = "Auction"
    AUCTION_BIN = "Auction with Buy it Now"

class EbayListingStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    ENDED = "ended"
    SCHEDULED = "scheduled"
    PENDING = "pending"

class EbayListing(Base):
    __tablename__ = "ebay_listings"
    
    # Primary keys and identifiers
    id = Column(Integer, primary_key=True, index=True)
    ebay_item_id = Column(String, unique=True, index=True)
    listing_status = Column(String, index=True)  # "ACTIVE", "SOLD", "UNSOLD"
    
    # Basic listing information
    title = Column(String)
    format = Column(String)  # "AUCTION", "BUY_IT_NOW"
    price = Column(Float)
    quantity = Column(Integer)
    quantity_available = Column(Integer)
    quantity_sold = Column(Integer, default=0)
    
    # Category information
    ebay_category_id = Column(String, index=True)
    ebay_category_name = Column(String)
    ebay_second_category_id = Column(String)
    
    # Listing details
    start_time = Column(DateTime)
    end_time = Column(DateTime, nullable=True)
    listing_url = Column(String)
    
    # Condition
    ebay_condition_id = Column(String)
    condition_display_name = Column(String)
    
    # Images
    gallery_url = Column(String)
    picture_urls = Column(JSONB)  # Array of image URLs
    
    # Item specifics
    item_specifics = Column(JSONB)  # Structured metadata about the item
    
    # Business policies
    payment_policy_id = Column(String)
    return_policy_id = Column(String)
    shipping_policy_id = Column(String)
    
    # Transaction details (for sold items)
    transaction_id = Column(String, nullable=True)
    order_line_item_id = Column(String, nullable=True)
    buyer_user_id = Column(String, nullable=True)
    paid_time = Column(DateTime, nullable=True)
    payment_status = Column(String, nullable=True)
    shipping_status = Column(String, nullable=True)
    
    # Timestamps for our system
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_synced_at = Column(DateTime, default=datetime.utcnow)
    
    platform_id = Column(Integer, ForeignKey("platform_common.id"), nullable=True)
    platform_listing = relationship("PlatformCommon", back_populates="ebay_listing")
    
    # Complete data storage
    listing_data = Column(JSONB)  # Store the complete listing data for reference

# class EbayListingOld(Base):
#     __tablename__ = "ebay_listings_old"

#     id = Column(Integer, primary_key=True)
#     platform_id = Column(Integer, ForeignKey("platform_common.id"))
#     ebay_item_id = Column(String)
#     ebay_category_id = Column(String)
#     ebay_second_category_id = Column(String)
#     format = Column(String, default=EbayListingFormat.BUY_IT_NOW)
#     price = Column(Numeric, nullable=False)
#     quantity = Column(Integer, default=1)
#     payment_policy_id = Column(String)
#     return_policy_id = Column(String)
#     shipping_policy_id = Column(String)
#     item_specifics = Column(JSONB, default={})
#     package_weight = Column(Numeric)
#     package_dimensions = Column(JSONB)
#     listing_duration = Column(String)
#     allow_offers = Column(Boolean, default=False)
#     min_offer_amount = Column(Numeric)
#     listing_status = Column(String, default=EbayListingStatus.DRAFT)
#     created_at = Column(DateTime, default=datetime.utcnow)
#     updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
#     last_synced_at = Column(DateTime)
#     ebay_condition_id = Column(String)

#     # Relationships
#     platform_listing = relationship("PlatformCommon", back_populates="ebay_listing")

# Pydantic models for validation
class PlatformCommonCreate(BaseModel):
    product_id: int
    platform_name: str
    external_id: Optional[str] = None
    status: Optional[str] = ListingStatus.DRAFT
    listing_url: Optional[str] = None
    platform_specific_data: Dict[str, Any] = {}

class EbayListingCreate(BaseModel):
    platform_id: int
    ebay_category_id: Optional[str] = None
    ebay_second_category_id: Optional[str] = None
    format: str = EbayListingFormat.BUY_IT_NOW
    price: float
    quantity: int = 1
    payment_policy_id: Optional[str] = None
    return_policy_id: Optional[str] = None
    shipping_policy_id: Optional[str] = None
    item_specifics: Dict[str, Any] = {}
    package_weight: Optional[float] = None
    package_dimensions: Optional[Dict[str, Any]] = None
    listing_duration: Optional[str] = None
    allow_offers: bool = False
    min_offer_amount: Optional[float] = None