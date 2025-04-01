"""
Enhanced ReverbListing Model

This model represents a listing on the Reverb platform with improved mapping
to Reverb's API data structure.
"""
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any

from sqlalchemy import Column, Integer, String, Float, Boolean, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import JSONB

from app.database import Base

class ReverbListing(Base):
    """
    Model for Reverb platform listings with enhanced API mapping.
    
    This table stores Reverb-specific attributes for listings, linked to the
    platform_common table for shared attributes across platforms.
    """
    __tablename__ = "reverb_listings"

    # Primary key and relationship
    id = Column(Integer, primary_key=True)
    platform_id = Column(Integer, ForeignKey("platform_common.id"))
    
    # Core Reverb identifiers
    reverb_listing_id = Column(String)  # ID assigned by Reverb
    reverb_slug = Column(String)  # URL-friendly identifier
    
    # Category and condition
    reverb_category_uuid = Column(String)  # UUID of category in Reverb's system
    condition_rating = Column(Float)  # Condition rating as float (1-5)
    
    # Business-critical fields
    inventory_quantity = Column(Integer, default=1)  # Current stock
    has_inventory = Column(Boolean, default=True)  # Uses inventory tracking
    offers_enabled = Column(Boolean, default=True)  # Are offers accepted
    is_auction = Column(Boolean, default=False)  # Auction vs. fixed price
    
    # Pricing
    list_price = Column(Float)  # Original listing price
    listing_currency = Column(String)  # Currency code (USD, GBP, etc.)
    
    # Shipping
    shipping_profile_id = Column(String)  # ID of shipping profile in Reverb
    shop_policies_id = Column(String)  # ID of shop policies in Reverb
    
    # Status
    reverb_state = Column(String)  # live, draft, ended, etc.
    
    # Statistics (useful for business intelligence)
    view_count = Column(Integer, default=0)  # Number of views
    watch_count = Column(Integer, default=0)  # Number of watches/favorites
    
    # Tracking fields
    reverb_created_at = Column(DateTime)  # When created on Reverb
    reverb_published_at = Column(DateTime)  # When published on Reverb
    created_at = Column(DateTime, default=datetime.utcnow)  # When created in our system
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_synced_at = Column(DateTime)  # Last time this was synced with Reverb
    
    # Flexible storage for all other Reverb fields
    extended_attributes = Column(JSONB, default={})
    
    # Optional: Specific attributes that might be useful
    handmade = Column(Boolean, default=False)  # Is this a handmade item?
    
    # Relationships
    platform_listing = relationship("PlatformCommon", back_populates="reverb_listing")
    