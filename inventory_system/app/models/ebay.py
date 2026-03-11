# app.models.ebay.py
from sqlalchemy import Column, Integer, String, Float, Boolean, ForeignKey, DateTime, Numeric, JSON, text, TIMESTAMP
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from enum import Enum
from .platform_common import ListingStatus
from typing import Optional, Dict, Any
from pydantic import BaseModel

from app.database import Base

UTC_NOW = text("now() AT TIME ZONE 'utc'")

# Moved class EbayListingFormat(str, Enum): and class EbayListing Status(str, Enum): to app.core.enums

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
    
    # # Timestamps for our system
    # created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), server_default=UTC_NOW)
    # updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=UTC_NOW)
    # last_synced_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=UTC_NOW)

    created_at = Column(
        TIMESTAMP(timezone=False), # Or True if you prefer TIMESTAMP WITH TIME ZONE
        server_default=text("timezone('utc', now())"),
        nullable=False
    )
    updated_at = Column(
        TIMESTAMP(timezone=False),
        server_default=text("timezone('utc', now())"),
        onupdate=text("timezone('utc', now())"),
        nullable=False
    )
    # last_synced_at: Apply the same pattern assuming it should update whenever the record
    # is updated or created. If it has a different meaning (e.g., only set manually
    # after a sync operation), you might adjust nullable or remove onupdate/server_default.
    last_synced_at = Column(
        TIMESTAMP(timezone=False),
        server_default=text("timezone('utc', now())"), # Sets initial value
        onupdate=text("timezone('utc', now())"),     # Updates on modification
        nullable=False # Assuming it should always have a value after creation/update
    )
    

    platform_id = Column(Integer, ForeignKey("platform_common.id"), nullable=False, index=True)

    # Complete data storage
    listing_data = Column(JSONB)  # Store the complete listing data for reference

    platform_listing = relationship("PlatformCommon", back_populates="ebay_listing")


